"""Grounded query tools for the Valmet copilot.

Fetches deterministic facts from DataStore and spatial fixtures. All facts are tagged
with explicit IDs (asset_id, event_id, work_order_id, doc_id) so the response can be
verified against actual evidence.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any

from app.copilot.store import DataStore


@dataclass
class AssetMatch:
    """A matched 3D asset with geometry and mapping."""

    object_id: str
    asset_id: str | None
    tag: str | None
    label: str
    confidence: float
    center: list[float]
    box: dict[str, list[float]]
    mapping_method: str | None = None
    notes: str = ""


@dataclass
class TelemetryMetricSummary:
    """Computed metric summary calculated by code, not LLM."""

    metric: str
    latest: float
    min_val: float
    max_val: float
    avg_val: float
    trend: str  # "increasing", "decreasing", "stable"
    sample_count: int


def normalize_query_tag(text: str) -> str:
    """Normalize user queries like 'pump 5' or 'pump P-005' or 'valve 1' to standard tags."""
    clean = text.strip()

    # Matches "pump 5", "pump 05", "pump 005" -> "P-005"
    m_pump = re.search(r"\bpump\s*#?([0-9]+)\b", clean, re.IGNORECASE)
    if m_pump:
        return f"P-{int(m_pump.group(1)):03d}"

    # Matches "motor 2" -> "M-002"
    m_motor = re.search(r"\bmotor\s*#?([0-9]+)\b", clean, re.IGNORECASE)
    if m_motor:
        return f"M-{int(m_motor.group(1)):03d}"

    # Matches "valve 1" / "control valve 1" -> "CV-001"
    m_valve = re.search(r"\b(?:control\s+)?valve\s*#?([0-9]+)\b", clean, re.IGNORECASE)
    if m_valve:
        return f"CV-{int(m_valve.group(1)):03d}"

    # Matches "pt 1" / "pressure 1" -> "PT-001"
    m_pt = re.search(r"\b(?:pressure\s+transmitter|pt)\s*#?([0-9]+)\b", clean, re.IGNORECASE)
    if m_pt:
        return f"PT-{int(m_pt.group(1)):03d}"

    # Matches "sensor 1" / "vibration 1" -> "VS-001"
    m_vs = re.search(r"\b(?:vibration\s+sensor|vs)\s*#?([0-9]+)\b", clean, re.IGNORECASE)
    if m_vs:
        return f"VS-{int(m_vs.group(1)):03d}"

    # Matches direct tags like P-005, CV-001, M-002, ASSET-017
    m_tag = re.search(r"\b([A-Z]{1,2}-[0-9]{3}|ASSET-[0-9]{3})\b", clean, re.IGNORECASE)
    if m_tag:
        return m_tag.group(1).upper()

    return clean


def find_assets(
    query: str,
    store: DataStore,
    sample_assets: list[dict[str, Any]],
    mapping: dict[str, dict[str, Any]],
    class_filter: str | None = None,
) -> list[AssetMatch]:
    """Find assets matching a natural query or tag, returning 3D info and mapping."""
    target_tag = normalize_query_tag(query)
    q_lower = query.strip().lower()
    matches: list[AssetMatch] = []

    for item in sample_assets:
        obj_id = item.get("object_id", "")
        map_info = mapping.get(obj_id, {})
        tag = map_info.get("tag")
        asset_id = map_info.get("asset_id")
        label = item.get("label", "")
        asset_class = map_info.get("asset_class") or ""

        if class_filter:
            cf = class_filter.strip().upper()
            if cf not in label.upper() and cf not in asset_class.upper():
                continue

        score = 0.0

        # Exact tag or asset_id match
        if tag and (tag.upper() == target_tag or tag.upper() in q_lower.upper()):
            score = 1.0
        elif asset_id and (asset_id.upper() == target_tag or asset_id.upper() in q_lower.upper()):
            score = 1.0
        elif target_tag and tag and target_tag in tag.upper():
            score = 0.9
        elif obj_id.lower() == q_lower:
            score = 1.0
        elif q_lower in label.lower() or (asset_class and q_lower in asset_class.lower()):
            score = 0.7

        if score > 0.0:
            matches.append(
                AssetMatch(
                    object_id=obj_id,
                    asset_id=asset_id,
                    tag=tag,
                    label=label,
                    confidence=float(map_info.get("confidence", item.get("confidence", 0.0))),
                    center=item.get("center", [0.0, 0.0, 0.0]),
                    box=item.get("box", {}),
                    mapping_method=map_info.get("method"),
                    notes=map_info.get("notes", ""),
                )
            )

    matches.sort(key=lambda m: (m.tag == target_tag, m.confidence), reverse=True)
    return matches


def get_status(
    asset_id_or_tag: str, store: DataStore, mapping: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    """Retrieve operational condition, health, mapping provenance, and data quality flags."""
    asset = store.get_asset(asset_id_or_tag)
    state = store.get_current_state(asset_id_or_tag)
    if not asset or not state:
        return None

    # Find 3D mapping metadata
    map_entry = next(
        (m for m in mapping.values() if m.get("asset_id") == asset.asset_id),
        {},
    )
    dq_issues = store.get_data_quality(asset.asset_id)

    return {
        "asset_id": asset.asset_id,
        "tag": asset.tag,
        "asset_class": asset.asset_class,
        "area_name": asset.area_name,
        "criticality": asset.criticality,
        "health_score": state.health_score,
        "condition_state": state.condition_state,
        "issue_code": state.issue_code,
        "issue_summary": state.issue_summary,
        "urgency": state.urgency,
        "recommended_next_check": state.recommended_next_check,
        "model_confidence": state.model_confidence,
        "last_updated": state.last_updated,
        "knowledge_doc_id": state.knowledge_doc_id,
        "mapping_confidence": map_entry.get("confidence", 1.0),
        "mapping_method": map_entry.get("method", "unspecified"),
        "object_id": map_entry.get("object_id"),
        "data_quality_issues": [asdict(dq) for dq in dq_issues],
    }


def get_telemetry_summary(
    asset_id_or_tag: str, store: DataStore, limit: int = 50
) -> dict[str, Any]:
    """Calculate summary statistics and trends deterministically in code."""
    points = store.get_telemetry(asset_id_or_tag, limit=limit)
    if not points:
        return {"asset_id": asset_id_or_tag, "samples": 0, "metrics": {}}

    # Group metrics
    all_metrics: dict[str, list[float]] = {}
    timestamps: list[str] = []
    for pt in points:
        timestamps.append(pt.timestamp)
        for k, v in pt.metrics.items():
            all_metrics.setdefault(k, []).append(v)

    summaries: dict[str, dict[str, Any]] = {}
    for metric_name, vals in all_metrics.items():
        if not vals:
            continue
        min_v = min(vals)
        max_v = max(vals)
        avg_v = sum(vals) / len(vals)
        latest_v = vals[-1]

        # Calculate simple trend over halves
        if len(vals) >= 4:
            first_half = sum(vals[: len(vals) // 2]) / (len(vals) // 2)
            second_half = sum(vals[len(vals) // 2 :]) / (len(vals) - len(vals) // 2)
            delta = second_half - first_half
            threshold = 0.05 * (max_v - min_v) if max_v != min_v else 0.01
            if delta > threshold:
                trend = "increasing"
            elif delta < -threshold:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend = "stable"

        summaries[metric_name] = asdict(
            TelemetryMetricSummary(
                metric=metric_name,
                latest=round(latest_v, 3),
                min_val=round(min_v, 3),
                max_val=round(max_v, 3),
                avg_val=round(avg_v, 3),
                trend=trend,
                sample_count=len(vals),
            )
        )

    return {
        "asset_id": points[0].asset_id,
        "tag": points[0].tag,
        "sample_count": len(points),
        "start_time": timestamps[0] if timestamps else "",
        "end_time": timestamps[-1] if timestamps else "",
        "metrics": summaries,
    }


def get_events_for_asset(
    asset_id_or_tag: str, store: DataStore, limit: int = 10, severity: str | None = None
) -> list[dict[str, Any]]:
    """Retrieve recent alarm and condition events."""
    evts = store.get_events(asset_id_or_tag, limit=limit, severity=severity)
    return [asdict(e) for e in evts]


def get_maintenance_history(
    asset_id_or_tag: str, store: DataStore, limit: int = 10
) -> list[dict[str, Any]]:
    """Retrieve historical work orders."""
    wos = store.get_maintenance(asset_id_or_tag)
    # Sort descending by opened_at
    sorted_wos = sorted(wos, key=lambda w: w.opened_at, reverse=True)
    return [asdict(w) for w in sorted_wos[:limit]]


def search_service_cases(
    store: DataStore, asset_class: str | None = None, issue_code: str | None = None
) -> list[dict[str, Any]]:
    """Search historical troubleshooting cases."""
    cases = store.get_service_cases(asset_class=asset_class, issue_code=issue_code)
    return [asdict(c) for c in cases]


COMMON_WORDS = {
    "the", "and", "for", "are", "was", "were", "you", "your", "what", "when", "where", "which",
    "who", "why", "how", "this", "that", "these", "those", "with", "from", "have", "has", "had",
    "can", "could", "should", "would", "will", "does", "did", "not", "any", "all", "about", "there",
    "here", "its", "it's", "what's", "tell", "show", "give", "need", "want", "please", "thanks",
    "mean", "means", "meaning", "like", "know", "think", "get", "got", "one", "some", "much",
    "many",
}  # fmt: skip


def search_docs(
    store: DataStore, query: str = "", scope: str | None = None, min_share: float = 0.0
) -> list[dict[str, Any]]:
    """Search knowledge and guidance documents. `min_share` of the words must be found."""
    docs = store.list_docs(scope=scope)
    if not query.strip():
        return [asdict(d) for d in docs]
    # Whole words only: "hi" mustn't match "this", and common words would match every document.
    q_words = [w for w in re.findall(r"[a-z0-9-]{3,}", query.lower()) if w not in COMMON_WORDS]

    scored = []
    for d in docs:
        words = set(re.findall(r"[a-z0-9-]+", (d.title + " " + d.content).lower()))
        score = sum(1 for w in q_words if w in words)
        if score > 0 and score >= min_share * len(q_words):
            scored.append((score, d))
    scored.sort(key=lambda s: s[0], reverse=True)
    return [asdict(s[1]) for s in scored]


def get_nearby_assets(
    center: list[float],
    radius: float,
    sample_assets: list[dict[str, Any]],
    mapping: dict[str, dict[str, Any]],
    store: DataStore,
) -> list[dict[str, Any]]:
    """Find assets within radius (meters) of a 3D coordinate."""
    cx, cy, cz = center[0], center[1], center[2]
    results = []

    for item in sample_assets:
        pos = item.get("center", [0.0, 0.0, 0.0])
        dist = math.sqrt((pos[0] - cx) ** 2 + (pos[1] - cy) ** 2 + (pos[2] - cz) ** 2)
        if dist <= radius:
            obj_id = item.get("object_id", "")
            map_info = mapping.get(obj_id, {})
            tag = map_info.get("tag")
            state = store.get_current_state(tag) if tag else None
            results.append(
                {
                    "object_id": obj_id,
                    "tag": tag,
                    "label": item.get("label"),
                    "distance_m": round(dist, 2),
                    "center": pos,
                    "condition_state": state.condition_state if state else "unknown",
                    "health_score": state.health_score if state else None,
                }
            )

    results.sort(key=lambda r: r["distance_m"])
    return results
