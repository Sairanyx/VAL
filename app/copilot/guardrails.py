"""Guardrails and verification logic for the Valmet industrial copilot.

Enforces:
1. DOC-FIELD-SAFETY: Rejects autonomous physical control requests, requiring qualified
   personnel, LOTO, and physical verification.
2. DOC-RAG-GUIDE: Verifies all citations against evidence returned by tools, separates
   observations from hypotheses, and includes confidence scores.
3. DOC-3D-MAPPING: Exposes mapping provenance and refuses to guess unmapped IDs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.copilot.guardrails_patterns import (
    AUTONOMOUS_CONTROL_PATTERNS,
    DEFINITION,
    SENTENCE_END,
)


@dataclass
class SafetyCheckResult:
    """Result of safety verification against DOC-FIELD-SAFETY."""

    passed: bool
    violation_reason: str | None = None
    safety_doc_id: str = "DOC-FIELD-SAFETY"
    recommended_action: str | None = None


@dataclass
class CitationValidationResult:
    """Result of citation cross-referencing against actual tool evidence."""

    verified_citations: list[str]
    unverified_citations: list[str]
    all_grounded: bool


def check_safety(user_prompt: str) -> SafetyCheckResult:
    """Verify whether a user query attempts autonomous physical control.

    Enforces DOC-FIELD-SAFETY:
    The assistant must not replace site procedures, lockout/tagout (LOTO), permits,
    OEM instructions, or qualified personnel. Recommend verification and escalation
    rather than autonomous physical action.
    """
    # Sentence by sentence, so asking what a word means can't excuse a request made next to it.
    for sentence in re.split(SENTENCE_END, user_prompt.lower()):
        sentence = sentence.strip(" ,")
        if not sentence or re.fullmatch(DEFINITION, sentence):
            continue
        for pattern in AUTONOMOUS_CONTROL_PATTERNS:
            match = re.search(pattern, sentence)
            if match:
                return SafetyCheckResult(
                    passed=False,
                    violation_reason=(
                        f"Autonomous physical control action requested ('{match.group(0)}'). "
                        "Val is restricted to read-only diagnosis and guidance."
                    ),
                    recommended_action=(
                        "Follow the site's lockout/tagout procedures, get the approved work "
                        "permits, and ask qualified maintenance staff to do it."
                    ),
                )

    return SafetyCheckResult(passed=True)


def extract_potential_citations(text: str) -> list[str]:
    """Find all potential evidence IDs mentioned in text (EVT-, WO-, DOC-, ASSET-, CASE-, DQ-)."""
    pattern = r"\b((?:EVT|WO|DOC|ASSET|CASE|DQ)-[A-Z0-9_\-]+)\b"
    found = re.findall(pattern, text)
    # Deduplicate while preserving order
    seen: set[str] = set()
    result = []
    for f in found:
        if f not in seen:
            seen.add(f)
            result.append(f)
    return result


def verify_citations(
    claimed_citations: list[str], valid_evidence_ids: set[str]
) -> CitationValidationResult:
    """Verify claimed citations against the set of IDs actually fetched by tools.

    Enforces DOC-RAG-GUIDE: rejects or flags IDs that were not returned by tools.
    """
    verified: list[str] = []
    unverified: list[str] = []

    for cit in claimed_citations:
        clean_cit = cit.strip()
        if clean_cit in valid_evidence_ids:
            verified.append(clean_cit)
        else:
            unverified.append(clean_cit)

    return CitationValidationResult(
        verified_citations=verified,
        unverified_citations=unverified,
        all_grounded=len(unverified) == 0,
    )


def compute_composite_confidence(
    model_confidence: float = 1.0,
    mapping_confidence: float = 1.0,
    data_quality_issues: list[dict[str, Any]] | None = None,
) -> float:
    """Calculate composite confidence taking into account model, mapping, and data quality.

    Enforces DOC-3D-MAPPING and DOC-RAG-GUIDE.
    """
    conf = model_confidence * mapping_confidence
    if data_quality_issues:
        for issue in data_quality_issues:
            sev = issue.get("severity", "low").lower()
            if sev == "high":
                conf *= 0.85
            elif sev == "medium":
                conf *= 0.93
            elif sev == "low":
                conf *= 0.98

    return round(max(0.1, min(1.0, conf)), 2)
