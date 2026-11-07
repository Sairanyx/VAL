"""Valmet Industrial Copilot Service.

Implements the evidence-grounded field service copilot.
Enforces:
- DOC-FIELD-SAFETY: Refuses autonomous physical equipment control.
- DOC-RAG-GUIDE: Separates observations from hypotheses, cites verified evidence IDs,
  and reports calibrated confidence.
- DOC-3D-MAPPING: Exposes spatial mapping provenance and never invents asset IDs.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.copilot.guardrails import (
    check_safety,
    compute_composite_confidence,
    verify_citations,
)
from app.copilot.store import (
    DataStore,
    load_mapping,
    load_sample_assets,
)
from app.copilot.tools import (
    find_assets,
    get_events_for_asset,
    get_maintenance_history,
    get_status,
    get_telemetry_summary,
    normalize_query_tag,
    search_docs,
    search_service_cases,
)

logger = logging.getLogger(__name__)


@dataclass
class CopilotResponse:
    """Standardized response schema aligned with API contract and DOC-RAG-GUIDE."""

    answer: str
    observations: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    confidence: float = 1.0
    actions: list[dict[str, Any]] = field(default_factory=list)
    focused_asset: str | None = None
    focused_object_id: str | None = None
    mapping_status: str | None = None
    safety_passed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def metric_observations(metrics: dict[str, dict[str, Any]]) -> list[str]:
    """Describe each measured value and its trend, with changing values first."""
    ordered = sorted(metrics.values(), key=lambda metric: metric["trend"] == "stable")
    return [
        f"{metric['metric'].replace('_', ' ')}: now {metric['latest']}, "
        f"range {metric['min_val']} to {metric['max_val']}, {metric['trend']} "
        f"over {metric['sample_count']} samples."
        for metric in ordered
    ]


def fouling_hypothesis(metrics: dict[str, dict[str, Any]]) -> str:
    """Explain fouling from the trends that the data actually shows."""
    signs = []
    for name, wanted, text in (
        ("process_flow_pct", "decreasing", "falling flow"),
        ("process_pressure_bar", "decreasing", "falling pressure"),
        ("current_a", "increasing", "rising motor current"),
        ("temperature_c", "increasing", "rising temperature"),
        ("vibration_rms_mm_s", "increasing", "rising vibration"),
    ):
        if metrics.get(name, {}).get("trend") == wanted:
            signs.append(text)
    if not signs:
        return "The fouling flag isn't clearly backed by the recent measured trends."
    return f"{', '.join(signs).capitalize()} may point to fouling in the hydraulic path."


INTRO = (
    "I'm Val, your field-service assistant for this room. Ask me what needs attention, what's "
    "wrong with a device, what to check next, when it was last serviced, or to take you to it. I "
    "answer only from the plant's records, I say when I'm unsure, and I never operate equipment."
)
GREETING = "Hi, I'm Val. Tap a device and ask me about it, or ask what needs attention."
THANKS = "You're welcome. Ask me if you need anything else."
GREETING_WORDS = r"(hi|hello|hey|moi|hei|good (morning|afternoon|evening))( val)?"
THANKS_WORDS = r"(thanks|thank you|thx|kiitos|ok|okay|great|cool)( val)?"
ABOUT_VAL = (
    "who are you",
    "what are you",
    "your name",
    "what can you do",
    "what do you do",
    "how can you help",
    "how do you work",
)
OVERVIEW_PHRASES = (
    "needs attention",
    "need attention",
    "most urgent",
    "what's urgent",
    "what is urgent",
    "priorit",
    "any alarm",
    "any alert",
    "any problem",
    "any fault",
    "any issue",
    "worst",
    "overview",
)
NOT_IN_RECORDS = {
    "spare": "spare parts",
    "part number": "part numbers",
    "stock": "stock",
    "inventory": "stock",
    "price": "prices",
    "cost": "costs",
    "budget": "costs",
    "supplier": "suppliers",
    "warranty": "warranties",
}
URGENCY_ORDER = {"high": 0, "medium": 1, "low": 2}


class CopilotEngine:
    """Val: field-service diagnostics with enforced guardrails and citation checking."""

    def __init__(
        self,
        store: DataStore | None = None,
        sample_assets: list[dict[str, Any]] | None = None,
        mapping: dict[str, dict[str, Any]] | None = None,
        fault_tag: str | None = None,
    ) -> None:
        self.store = store or DataStore.load()
        self.sample_assets = (
            sample_assets
            if sample_assets is not None
            else load_sample_assets("fixtures/copilot_assets.json")
        )
        self.mapping = mapping if mapping is not None else load_mapping("fixtures/mapping.json")
        self.focused_asset_tag: str | None = None
        self.focused_object_id: str | None = None
        # The device to talk about when a question names none. Each site chooses its own.
        self.fault_tag = fault_tag or os.getenv("COPILOT_FAULT_TAG", "P-005")

    def set_focus(self, tag_or_object_id: str) -> None:
        """Set the active equipment focus (e.g. when user taps a 3D box)."""
        clean = tag_or_object_id.strip()
        # Check if it's an object_id
        if clean in self.mapping:
            self.focused_object_id = clean
            self.focused_asset_tag = self.mapping[clean].get("tag")
            return

        # Check by tag or asset_id
        asset = self.store.get_asset(clean)
        if asset:
            self.focused_asset_tag = asset.tag
            map_entry = next(
                (m for m in self.mapping.values() if m.get("asset_id") == asset.asset_id),
                {},
            )
            self.focused_object_id = map_entry.get("object_id")

    def query(
        self,
        question: str,
        object_id: str | None = None,
        position: list[float] | None = None,
    ) -> CopilotResponse:
        """Process an operator query, execute tools, check guardrails, and return evidence."""
        # 1. Update focus if object_id supplied
        if object_id:
            self.set_focus(object_id)

        # 2. Check safety guardrail (DOC-FIELD-SAFETY)
        safety_check = check_safety(question)
        if not safety_check.passed:
            return CopilotResponse(
                answer=(
                    f"Refusal under DOC-FIELD-SAFETY: {safety_check.violation_reason}\n\n"
                    f"Mandatory Procedure: {safety_check.recommended_action}"
                ),
                observations=[
                    "User command attempted autonomous physical control of plant equipment."
                ],
                hypotheses=["Autonomous actuation disallowed by industrial field safety policy."],
                citations=["DOC-FIELD-SAFETY"],
                confidence=1.0,
                actions=[],
                safety_passed=False,
                focused_asset=self.focused_asset_tag,
                focused_object_id=self.focused_object_id,
            )

        # Small talk has no device behind it, so it mustn't answer about the last one discussed.
        casual = self._casual_reply(question)
        if casual:
            return casual

        # 3. Resolve target asset (from prompt or existing focus)
        target_tag = self._resolve_target_asset(question)
        if not target_tag and self.focused_asset_tag:
            # Check if query references "it", "this", "the pump", etc.
            if self._references_context(question):
                target_tag = self.focused_asset_tag

        # If question mentions an unknown or unmapped asset explicitly
        unmapped_check = self._check_unmapped_or_unknown(question, target_tag)
        if unmapped_check:
            return unmapped_check

        # 4. Route intent
        q_lower = question.lower()

        if not target_tag and self._is_overview_intent(q_lower, question, object_id):
            return self._handle_overview()

        # A selected object with no record must never turn into the fault or the last device.
        if not target_tag and object_id and object_id not in self.mapping:
            if self._is_navigation_intent(q_lower):
                return self._handle_navigation_to_object(object_id)
            return self._describe_unlinked(object_id)

        missing = next((name for word, name in NOT_IN_RECORDS.items() if word in q_lower), None)
        if missing:
            return self._not_in_records(missing)

        # Intent A: Navigation / Location ("Where is...", "Take me to...", "Show route")
        if self._is_navigation_intent(q_lower):
            return self._handle_navigation(target_tag or self.focused_asset_tag, question)

        # Intent B: Last service / Maintenance history ("When was it last serviced?")
        if self._is_maintenance_intent(q_lower):
            return self._handle_maintenance(target_tag or self.focused_asset_tag)

        # Intent C: Recommended Checks / Next Steps ("What should I check?", "Next steps")
        # "Why" needs the evidence as well as the check, and the diagnosis gives both.
        wants_reason = any(word in q_lower for word in ("why", "flagged", "what's wrong"))
        if self._is_next_steps_intent(q_lower) and not wants_reason:
            return self._handle_next_steps(target_tag or self.focused_asset_tag)

        # Intent D: Status / Condition / Diagnosis ("What's wrong?", "Condition", "Health")
        # A question that points at no device mustn't get the last device's diagnosis.
        about_device = object_id or self._references_context(question) or wants_reason
        if target_tag or (self.focused_asset_tag and about_device):
            return self._handle_diagnosis(target_tag or self.focused_asset_tag)

        # Intent E: General search or guidance
        return self._handle_general_query(question)

    def _resolve_target_asset(self, question: str) -> str | None:
        """Extract asset tag from question text."""
        norm = normalize_query_tag(question)
        if norm and self.store.resolve_asset_id(norm):
            asset = self.store.get_asset(norm)
            return asset.tag if asset else norm
        return None

    @staticmethod
    def _casual_reply(question: str) -> CopilotResponse | None:
        """Answer greetings, thanks and questions about Val, none of which need records."""
        clean = question.strip().lower().rstrip("!.?, ")
        text = None
        if re.fullmatch(GREETING_WORDS, clean):
            text = GREETING
        elif re.fullmatch(THANKS_WORDS, clean):
            text = THANKS
        elif clean == "help" or any(phrase in clean for phrase in ABOUT_VAL):
            text = INTRO
        if text is None:
            return None
        return CopilotResponse(answer=text, confidence=1.0)

    def _is_overview_intent(self, q_lower: str, question: str, object_id: str | None) -> bool:
        """Check for a question about the whole room rather than one device."""
        if (object_id or self.focused_asset_tag) and self._references_context(question):
            return False
        if any(phrase in q_lower for phrase in OVERVIEW_PHRASES):
            return True
        wrong = "what's wrong" in q_lower or "what is wrong" in q_lower
        return wrong and not self.focused_asset_tag and not object_id

    def _handle_overview(self) -> CopilotResponse:
        """Say which devices the records rank as most urgent, worst health first."""
        states = [self.store.get_current_state(a.asset_id) for a in self.store.list_assets()]
        ranked = sorted(
            (state for state in states if state),
            key=lambda state: (URGENCY_ORDER.get(state.urgency, 3), state.health_score),
        )
        urgent = [state for state in ranked if state.urgency == "high"]
        if not urgent:
            return CopilotResponse(
                answer="The records don't mark any device as high urgency right now.",
                observations=[f"Checked the current state of {len(ranked)} devices."],
                citations=["DOC-RAG-GUIDE"],
                confidence=1.0,
            )
        top = urgent[0]
        self.set_focus(top.tag)
        answer = (
            f"{len(urgent)} devices are marked high urgency. Start with {top.tag}: health "
            f"{top.health_score:.0f}/100, {top.issue_summary}. Recommended check: "
            f"{top.recommended_next_check}."
        )
        others = ", ".join(f"{s.tag} ({s.health_score:.0f}/100)" for s in urgent[1:4])
        if others:
            answer += f" Also high urgency: {others}."
        actions: list[dict[str, Any]] = []
        if self.focused_object_id:
            actions.append({"type": "highlight", "object_id": self.focused_object_id})
        return CopilotResponse(
            answer=answer,
            observations=[
                f"{s.tag}: health {s.health_score:.0f}/100, {s.condition_state}, {s.issue_summary}"
                for s in urgent
            ],
            citations=[s.asset_id for s in urgent[:4]],
            confidence=top.model_confidence,
            actions=actions,
            focused_object_id=self.focused_object_id,
        )

    def _scene_object(self, object_id: str) -> dict[str, Any]:
        return next((a for a in self.sample_assets if a.get("object_id") == object_id), {})

    def _handle_navigation_to_object(self, object_id: str) -> CopilotResponse:
        """Route to a selected object that has no record."""
        label = self._scene_object(object_id).get("label", "object")
        return CopilotResponse(
            answer=f"I've marked this {label} and drawn the route to it.",
            observations=[f"Detected object {object_id}, with no linked plant record."],
            citations=["DOC-3D-MAPPING"],
            confidence=float(self._scene_object(object_id).get("confidence") or 0.0),
            actions=[
                {"type": "highlight", "object_id": object_id},
                {"type": "navigate", "object_id": object_id},
            ],
            focused_object_id=object_id,
            mapping_status="not linked to a record",
        )

    def _describe_unlinked(self, object_id: str) -> CopilotResponse:
        """Say what's known about an object with no record, without guessing its identity."""
        found = self._scene_object(object_id)
        label = found.get("label", "object")
        confidence = float(found.get("confidence") or 0.0)
        return CopilotResponse(
            answer=(
                f"The scan shows this as: {label}. It isn't linked to a plant record, so I have "
                "no condition, measurements or service history for it, and I won't guess which "
                "device it is. I can take you to it so you can check its nameplate."
            ),
            observations=[f"Detected object {object_id}, labelled {label}."],
            citations=["DOC-3D-MAPPING"],
            confidence=confidence,
            actions=[{"type": "highlight", "object_id": object_id}],
            focused_object_id=object_id,
            mapping_status="not linked to a record",
        )

    @staticmethod
    def _not_in_records(topic: str) -> CopilotResponse:
        """Say plainly that a topic isn't in the records, rather than answering something else."""
        return CopilotResponse(
            answer=(
                f"I don't have records on {topic}, so I won't guess. I can see each device's "
                "condition, measurements, events, work orders and guidance documents."
            ),
            citations=["DOC-RAG-GUIDE"],
            confidence=1.0,
        )

    @staticmethod
    def _references_context(question: str) -> bool:
        """Check if query refers to the currently focused asset."""
        q_lower = question.lower()
        context_words = ["it", "this", "that", "the machine", "the pump", "the valve", "the device"]
        return any(re.search(rf"\b{re.escape(w)}\b", q_lower) for w in context_words)

    def _check_unmapped_or_unknown(
        self, question: str, target_tag: str | None
    ) -> CopilotResponse | None:
        """Detect queries asking about equipment not present or unmapped."""
        m = re.search(r"\b([A-Z]{1,3}-[0-9]{3,4})\b", question, re.IGNORECASE)
        if m:
            code = m.group(1).upper()
            if not self.store.resolve_asset_id(code):
                return CopilotResponse(
                    answer=(
                        f"Asset '{code}' was not found in the plant Asset Master. "
                        "Under DOC-3D-MAPPING, I never invent identities or guess data for "
                        "unmapped equipment."
                    ),
                    observations=[f"Query tag '{code}' has no corresponding Asset_Master record."],
                    hypotheses=["Device does not exist or has not been commissioned/mapped."],
                    citations=["DOC-3D-MAPPING"],
                    confidence=1.0,
                    actions=[],
                )
        return None

    @staticmethod
    def _is_navigation_intent(q_lower: str) -> bool:
        nav_triggers = [
            "where is",
            "where's",
            "take me",
            "navigate",
            "route to",
            "locate",
            "find pump",
            "find valve",
            "find motor",
            "show path",
        ]
        return any(t in q_lower for t in nav_triggers)

    @staticmethod
    def _is_maintenance_intent(q_lower: str) -> bool:
        maint_triggers = [
            "last service",
            "last serviced",
            "serviced",
            "maintenance history",
            "work order",
            "repaired",
            "inspected",
        ]
        return any(t in q_lower for t in maint_triggers)

    @staticmethod
    def _is_next_steps_intent(q_lower: str) -> bool:
        step_triggers = [
            "what should i check",
            "check next",
            "next steps",
            "recommended check",
            "how to fix",
            "troubleshoot",
            "guidance",
        ]
        return any(t in q_lower for t in step_triggers)

    def _handle_navigation(self, target_tag: str | None, question: str) -> CopilotResponse:
        """Handle location and pathfinding requests."""
        if not target_tag:
            target_tag = self.fault_tag

        matches = find_assets(target_tag, self.store, self.sample_assets, self.mapping)
        if not matches:
            return CopilotResponse(
                answer=f"Could not locate 3D position for '{target_tag}'.",
                observations=[f"No 3D spatial anchor found for {target_tag}."],
                hypotheses=[],
                citations=["DOC-3D-MAPPING"],
                confidence=0.5,
            )

        match = matches[0]
        self.set_focus(match.object_id)
        tag = match.tag or target_tag

        actions = [
            {"type": "highlight", "object_id": match.object_id, "tag": tag},
            {
                "type": "navigate",
                "object_id": match.object_id,
                "target_coordinates": match.center,
                "tag": tag,
            },
        ]

        citations = ["DOC-3D-MAPPING"]
        if match.asset_id:
            citations.append(match.asset_id)

        prov = (
            f"Mapped procedurally via {match.mapping_method}"
            if match.mapping_method
            else "Spatial match"
        )

        answer = f"I've marked {tag} and drawn the route to it."
        if match.confidence < 1.0:
            answer += (
                f" Its link to this object is only {match.confidence * 100:.0f}% certain, so "
                "check the nameplate when you get there."
            )
        return CopilotResponse(
            answer=answer,
            observations=[
                f"3D bounding box center: {match.center}",
                f"Mapping provenance: {prov} with {match.confidence * 100:.0f}% confidence.",
            ],
            hypotheses=[],
            citations=citations,
            confidence=match.confidence,
            actions=actions,
            focused_asset=tag,
            focused_object_id=match.object_id,
            mapping_status=prov,
        )

    def _handle_diagnosis(self, tag: str | None) -> CopilotResponse:
        """Handle diagnosis and current condition queries (enforcing DOC-RAG-GUIDE)."""
        if not tag:
            tag = self.fault_tag

        status = get_status(tag, self.store, self.mapping)
        if not status:
            return CopilotResponse(
                answer=f"No operational state records available for {tag}.",
                observations=[f"Asset {tag} has no record in Current_State."],
                citations=[],
                confidence=0.3,
            )

        asset_id = status["asset_id"]
        self.set_focus(tag)

        # 1. Fetch deterministic tool evidence
        events = get_events_for_asset(tag, self.store, limit=5)
        telemetry_sum = get_telemetry_summary(tag, self.store, limit=20)
        docs = search_docs(self.store, query=status["issue_code"], scope=status["asset_class"])
        doc_id = status.get("knowledge_doc_id") or (docs[0]["doc_id"] if docs else "DOC-RAG-GUIDE")

        # 2. Gather ground-truth IDs
        evidence_ids = {asset_id, doc_id, "DOC-RAG-GUIDE", "DOC-FIELD-SAFETY"}
        for ev in events:
            evidence_ids.add(ev["event_id"])

        # 3. Compile Observations
        cond_str = status["condition_state"]
        observations = [
            f"Health Score: {status['health_score']:.0f}/100, Condition: {cond_str}.",
            f"Active Issue Code: {status['issue_code']} ({status['issue_summary']}).",
        ]

        top_event = events[0] if events else None
        if top_event:
            observations.append(
                f"Recent event {top_event['event_id']} ({top_event['severity']}): "
                f"{top_event['description']}"
            )

        metrics = telemetry_sum.get("metrics", {})
        observations.extend(metric_observations(metrics))

        # 4. Compile Hypotheses (distinct from observations)
        hypotheses = []
        if status["issue_code"] == "FOULING":
            hypotheses.append(fouling_hypothesis(metrics))
        else:
            issue_clean = status["issue_code"].lower().replace("_", " ")
            hypotheses.append(f"Deviations consistent with {issue_clean} pattern.")

        # 5. Composite confidence calculation
        conf = compute_composite_confidence(
            model_confidence=status["model_confidence"],
            mapping_confidence=status["mapping_confidence"],
            data_quality_issues=status.get("data_quality_issues"),
        )

        # 6. Candidate citations
        claimed_citations = [asset_id, doc_id]
        if top_event:
            claimed_citations.append(top_event["event_id"])
        claimed_citations.extend(["DOC-RAG-GUIDE", "DOC-FIELD-SAFETY"])

        cit_result = verify_citations(claimed_citations, evidence_ids)

        h_score = status["health_score"]
        answer = (
            f"{tag} ({asset_id}): {status['condition_state'].replace('_', ' ')}, health "
            f"{h_score:.0f}/100. Signature: {status['issue_summary']}. "
            f"Recommended safe check: {status['recommended_next_check']} ({doc_id}). "
            "Follow the site's safety rules (DOC-FIELD-SAFETY)."
        )

        actions = [
            {"type": "highlight", "object_id": status.get("object_id"), "tag": tag},
            {"type": "open_document", "doc_id": doc_id},
        ]

        prov = f"Mapped via {status['mapping_method']}"

        return CopilotResponse(
            answer=answer,
            observations=observations,
            hypotheses=hypotheses,
            citations=cit_result.verified_citations,
            confidence=conf,
            actions=actions,
            focused_asset=tag,
            focused_object_id=status.get("object_id"),
            mapping_status=prov,
        )

    def _handle_maintenance(self, tag: str | None) -> CopilotResponse:
        """Handle maintenance history inquiries with work order citations."""
        if not tag:
            tag = self.fault_tag

        history = get_maintenance_history(tag, self.store, limit=5)
        if not history:
            return CopilotResponse(
                answer=f"No maintenance history found for {tag}.",
                observations=[f"No work orders found in Maintenance_History for {tag}."],
                citations=[],
                confidence=0.8,
            )

        latest_wo = history[0]
        wo_id = latest_wo["work_order_id"]
        raw_open = latest_wo["opened_at"]
        opened = raw_open.split("T")[0] if "T" in raw_open else raw_open

        evidence_ids = {wo_id, "DOC-RAG-GUIDE"}
        for wo in history:
            evidence_ids.add(wo["work_order_id"])

        observations = [
            f"Work Order {wo_id} opened on {opened}: Action was '{latest_wo['action']}'.",
            f"Type: {latest_wo['maintenance_type']}, Priority: {latest_wo['priority']}, "
            f"Result: '{latest_wo['result']}'.",
            f"Service duration: {latest_wo['duration_h']} hours.",
        ]

        hypotheses = [
            f"Intervention ({latest_wo['action']}) completed with outcome '{latest_wo['result']}'."
        ]

        claimed_citations = [wo_id, "DOC-RAG-GUIDE"]
        cit_result = verify_citations(claimed_citations, evidence_ids)

        answer = (
            f"{tag} was last serviced on {opened} under work order {wo_id}. "
            f"Action performed: '{latest_wo['action']}' ({latest_wo['maintenance_type']}), "
            f"with result recorded as '{latest_wo['result']}'."
        )

        return CopilotResponse(
            answer=answer,
            observations=observations,
            hypotheses=hypotheses,
            citations=cit_result.verified_citations,
            confidence=0.95,
            actions=[{"type": "highlight_work_order", "work_order_id": wo_id}],
            focused_asset=tag,
        )

    def _handle_next_steps(self, tag: str | None) -> CopilotResponse:
        """Handle check recommendation requests citing Knowledge_Docs and safety."""
        if not tag:
            tag = self.fault_tag

        status = get_status(tag, self.store, self.mapping)
        asset_class = status["asset_class"] if status else None
        doc_id = status.get("knowledge_doc_id") if status else None

        docs = search_docs(self.store, query="inspect check", scope=asset_class)
        primary_doc = self.store.get_doc(doc_id) if doc_id else (docs[0] if docs else None)
        primary_doc_id = primary_doc.doc_id if primary_doc else "DOC-FIELD-SAFETY"

        issue_code = status.get("issue_code") if status else None
        cases = search_service_cases(self.store, asset_class=asset_class, issue_code=issue_code)
        case_id = cases[0]["case_id"] if cases else None

        rec_check = (
            status.get("recommended_next_check", "physical inspection")
            if status
            else "inspect component"
        )

        evidence_ids = {primary_doc_id, "DOC-FIELD-SAFETY", "DOC-RAG-GUIDE"}
        if case_id:
            evidence_ids.add(case_id)

        doc_title = primary_doc.title if primary_doc else ""
        observations = [
            f"Recommended next check from diagnostic state: '{rec_check}'.",
            f"Relevant guidance document: {primary_doc_id} ('{doc_title}').",
        ]
        if case_id:
            observations.append(
                f"Historical case {case_id} recommendation: '{cases[0]['recommended_next_check']}'."
            )

        hypotheses = [
            "Physical inspection of hydraulic path will confirm presence of impeller deposits."
        ]

        claimed_citations = [primary_doc_id, "DOC-FIELD-SAFETY"]
        if case_id:
            claimed_citations.append(case_id)
        cit_result = verify_citations(claimed_citations, evidence_ids)

        answer = (
            f"Recommended check for {tag}: {rec_check}. "
            f"Per {primary_doc_id}, inspect multivariate parameters (vibration, bearing temp) "
            "and verify locally. In accordance with safety guardrail DOC-FIELD-SAFETY, "
            "obtain proper permits and follow Lockout/Tagout (LOTO) protocols "
            "prior to opening inspection ports."
        )

        return CopilotResponse(
            answer=answer,
            observations=observations,
            hypotheses=hypotheses,
            citations=cit_result.verified_citations,
            confidence=0.92,
            actions=[{"type": "open_document", "doc_id": primary_doc_id}],
            focused_asset=tag,
        )

    def _handle_general_query(self, question: str) -> CopilotResponse:
        """Handle general knowledge questions against Knowledge_Docs."""
        docs = search_docs(self.store, query=question)
        if docs:
            top_doc = docs[0]
            doc_id = top_doc["doc_id"]
            preview = top_doc["content"][:200]
            return CopilotResponse(
                answer=f"According to {doc_id} ('{top_doc['title']}'): {preview}...",
                observations=[f"Matched guidance document {doc_id}."],
                hypotheses=[],
                citations=[doc_id, "DOC-RAG-GUIDE"],
                confidence=0.85,
                actions=[{"type": "open_document", "doc_id": doc_id}],
            )

        return CopilotResponse(
            answer=(
                "I couldn't find anything on that in the plant's records, so I won't guess. Try "
                "asking what needs attention, or tap a device and ask what's wrong with it."
            ),
            observations=["No matching documents in Knowledge_Docs corpus."],
            hypotheses=[],
            citations=["DOC-RAG-GUIDE"],
            confidence=0.5,
        )

    def generate_route_commentary(self, asset_ids_or_tags: list[str]) -> list[dict[str, Any]]:
        """Pre-generate fast status commentary for assets passed along avatar walking route.

        Runs instantaneously with zero LLM latency to prevent stalling walking animation.
        """
        commentary = []
        for item in asset_ids_or_tags:
            asset = self.store.get_asset(item)
            if not asset:
                continue
            state = self.store.get_current_state(asset.tag)
            health = state.health_score if state else 100.0
            cond = state.condition_state if state else "healthy"

            commentary.append(
                {
                    "tag": asset.tag,
                    "asset_id": asset.asset_id,
                    "asset_class": asset.asset_class,
                    "health_score": health,
                    "condition_state": cond,
                    "text": (
                        f"Passing {asset.tag} ({asset.asset_class}): "
                        f"{cond.replace('_', ' ').capitalize()} (Health {health:.0f}%)."
                    ),
                }
            )
        return commentary
