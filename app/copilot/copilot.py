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
    COMMON_WORDS,
    find_assets,
    get_events_for_asset,
    get_maintenance_history,
    get_status,
    get_telemetry_summary,
    normalize_query_tag,
    search_docs,
    search_service_cases,
)
from app.copilot.viewer_actions import match_action

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
    "wrong with a device, what to check next, when it was last serviced, or to make a path to it. "
    "I can also change the view, like hiding the frames. I answer only from the plant's records, "
    "I say when I'm unsure, and I never operate equipment."
)
GREETING = "Hi, I'm Val. Tap a device and ask me about it, or ask what needs attention."
THANKS = "You're welcome. Ask me if you need anything else."
GREETING_WORDS = r"(hi|hello|hey|moi|hei|good (morning|afternoon|evening))( there)?( val)?"
THANKS_WORDS = (
    r"((ok|okay|great|cool|nice|perfect|got it|good)[ ,]*)?"
    r"(thanks|thank you|thx|kiitos|ok|okay|great|cool|nice|perfect|got it)?"
    r"( so much| a lot)?( val)?"
)
BYE_WORDS = r"(bye|goodbye|see you|see ya)( val)?"
HOW_ARE_YOU = ("how are you", "how's it going", "hows it going")
DIAGNOSIS_WORDS = (
    "wrong", "status", "state", "condition", "health", "issue", "problem", "fault", "flag", "why",
    "explain", "how is", "how's", "fail", "broken", "happening", "diagnos", "tell me more", "okay",
    "working", "running", "fine", "alarm", "signature", "foul", "cause",
)  # fmt: skip
MADE_UP_WORDS = ("ignore your", "ignore all", "ignore previous", "invent", "make up", "pretend",
                 "forget your", "disregard", "guess a", "fake")  # fmt: skip
CONFIDENCE_WORDS = ("how confident", "how sure", "confidence", "could this be wrong",
                    "could it be wrong", "what could make this wrong")  # fmt: skip
HISTORY_WORDS = ("happened before", "seen this before", "similar", "past case", "previous case",
                 "history of this")  # fmt: skip
METRICS = {
    "vibration": ("vibration_rms_mm_s", "Vibration", " mm/s"),
    "temperature": ("temperature_c", "Temperature", " °C"),
    "temp": ("temperature_c", "Temperature", " °C"),
    "pressure": ("process_pressure_bar", "Pressure", " bar"),
    "flow": ("process_flow_pct", "Flow", "%"),
    "current": ("current_a", "Motor current", " A"),
}
MEASUREMENT_WORDS = ("measurement", "reading", "telemetry", "sensor", "getting worse",
                     "getting better", "trend", "changed recently")  # fmt: skip
TRENDS = {"decreasing": "falling", "increasing": "rising", "stable": "steady"}
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
    "anything urgent",
    "everything ok",
    "everything fine",
    "do first",
    "start with",
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
    "the room",
    "the plant",
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
    "parts": "spare parts",
    "who do i call": "contacts",
    "phone number": "contacts",
    "contact": "contacts",
}
NEXT_STEP_WORDS = ("how do i fix", "how to repair", "what do i do", "what should i do")
SAFE_TO_WORK_WORDS = ("dangerous", "is it safe", "safe to", "can i touch", "can i work on")
DOCUMENT_WORDS = ("manual", "document", "procedure", "guidance", "instructions")
EQUIPMENT_WORDS = {
    "pump": "PROCESS_PUMP",
    "valve": "CONTROL_VALVE",
    "motor": "MOTOR",
    "sensor": "SENSOR",
    "transmitter": "SENSOR",
}
PLACE_ANY_WORDS = {
    "there",
    "it",
    "this",
    "that",
    "here",
    "fault",
    "faulty",
    "broken",
    "worst",
    "one",
}
URGENCY_ORDER = {"high": 0, "medium": 1, "low": 2}
NOT_UNDERSTOOD = (
    "Sorry, I don't understand that. You can ask what needs attention, what's wrong with a device, "
    "when it was last serviced, or ask me to make a path to it."
)
DEFINITION_ASKED = re.compile(
    r"^(?:what\s+(?:does|do)\s+(.+?)\s+mean|what\s+is\s+meant\s+by\s+(.+)|"
    r"(?:what\s+is\s+)?the\s+meaning\s+of\s+(.+)|meaning\s+of\s+(.+)|define\s+(.+))[.?!]*$"
)
# Words that show a question is about the device, as "it" alone may not be: "is it raining?"
DEVICE_QUESTION = re.compile(
    r"\b(?:status|condition|health|score|wrong|problems?|faults?|issues?|fail\w*|broken|alarms?|"
    r"events?|urgent|urgency|flagged|cause\w*|confiden\w*|sure|measur\w*|readings?|telemetry|trend\w*|"
    r"flow|pressure|temperature|vibration|current|foul\w*|serv[ei]\w*|maintenance|repair\w*|"
    r"inspect\w*|work orders?|history|check\w*|next steps?|fix|troubleshoot|guidance|happened|"
    r"changed|worse|better|ok|okay|fine|safe|details?|info|information|describe|"
    r"tell me (?:more|about)|about (?:it|this|that)|what(?:'s| is) (?:it|this|that)|"
    r"how(?:'s| is) (?:it|this|that)|explain (?:it|this|that|why)|this one)\b"
)


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
                    "I can't do that. I only read the plant's records and give guidance, and I "
                    f"never operate equipment. {safety_check.recommended_action}"
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
        if any(word in question.lower() for word in MADE_UP_WORDS):
            return CopilotResponse(
                answer=(
                    "I can't make things up. I only tell you what the plant's records show, and "
                    "if they don't cover something, I'll say so."
                ),
                citations=["DOC-RAG-GUIDE"],
                confidence=1.0,
            )

        # Asking what a word means isn't asking about the device that's selected.
        definition = self._define(question)
        if definition:
            return definition

        # A request to change the 3D view, the same as pressing its button.
        action = self._viewer_action(question, object_id)
        if action:
            return action

        # 3. Resolve target asset (from prompt or existing focus)
        target_tag = self._resolve_target_asset(question)
        named_tag = target_tag
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

        if not named_tag and self._is_overview_intent(q_lower, question, object_id):
            return self._handle_overview()
        counted = re.search(r"how many (\w+?)s?\b", q_lower)
        if counted and counted.group(1) in EQUIPMENT_WORDS and not named_tag:
            return self._count(counted.group(1))

        # A selected object with no record must never turn into the fault or the last device.
        if not named_tag and object_id and object_id not in self.mapping:
            if self._is_navigation_intent(q_lower):
                return self._handle_navigation_to_object(object_id)
            if self._asks_about_device(q_lower) or "movable" in q_lower or "move it" in q_lower:
                return self._describe_unlinked(object_id, q_lower)

        unknown_place = self._unknown_place(q_lower) if not named_tag else None
        if unknown_place:
            return CopilotResponse(
                answer=(
                    f"I don't know where {unknown_place} is. I can only take you to equipment in "
                    "this room, so tap a device or give me a tag like P-005."
                ),
                citations=["DOC-3D-MAPPING"],
                confidence=1.0,
            )
        which = self._which_one(q_lower, named_tag, object_id)
        if which:
            return which

        missing = next((name for word, name in NOT_IN_RECORDS.items() if word in q_lower), None)
        if missing:
            return self._not_in_records(missing)

        # Intent A: Navigation / Location ("Where is...", "Take me to...", "Show route")
        if self._is_navigation_intent(q_lower):
            if not target_tag and "fault" in q_lower:
                target_tag = self.fault_tag
            return self._handle_navigation(target_tag or self.focused_asset_tag, question)

        # Intent B: Last service / Maintenance history ("When was it last serviced?")
        if self._is_maintenance_intent(q_lower):
            return self._handle_maintenance(target_tag or self.focused_asset_tag)

        # Intent C: Recommended Checks / Next Steps ("What should I check?", "Next steps")
        # "Why" needs the evidence as well as the check, and the diagnosis gives both.
        wants_reason = any(word in q_lower for word in ("flagged", "what's wrong", "what is wrong"))
        wants_reason = wants_reason or q_lower.strip(" ?!.") == "why"
        about_this = bool(named_tag or object_id or self._references_context(question))
        if self.focused_asset_tag or named_tag:
            if about_this and any(word in q_lower for word in SAFE_TO_WORK_WORDS):
                return self._handle_safe_to_work(target_tag or self.focused_asset_tag)
            if about_this and any(word in q_lower for word in DOCUMENT_WORDS):
                return self._handle_documents(target_tag or self.focused_asset_tag)
        if (
            any(word in q_lower for word in NEXT_STEP_WORDS)
            and about_this
            and self.focused_asset_tag
        ):
            return self._handle_next_steps(target_tag or self.focused_asset_tag)
        if self._is_next_steps_intent(q_lower) and not wants_reason:
            return self._handle_next_steps(target_tag or self.focused_asset_tag)

        # Specific questions get specific answers, not the whole diagnosis.
        device = target_tag or self.focused_asset_tag
        pointed = about_this
        if device and pointed:
            if any(word in q_lower for word in CONFIDENCE_WORDS):
                return self._handle_confidence(device)
            if "urgen" in q_lower or "priority" in q_lower:
                return self._handle_urgency(device)
            if any(word in q_lower for word in HISTORY_WORDS):
                return self._handle_history(device)
            if "what is this" in q_lower or "what is it" in q_lower or "tell me about" in q_lower:
                return self._handle_identity(device)
        asked_metric = re.search(rf"\b({'|'.join(METRICS)})\b", q_lower)
        if device and (asked_metric or any(word in q_lower for word in MEASUREMENT_WORDS)):
            if pointed or asked_metric:
                return self._handle_measurements(device, asked_metric, q_lower)

        # Intent D: Status / Condition / Diagnosis ("What's wrong?", "Condition", "Health")
        # A message that doesn't ask about a device's state mustn't get its diagnosis.
        meaning = re.match(r"(what (is|does|are)|define|what's)\b", q_lower) and not pointed
        meaning = meaning and not wants_reason
        about_device = about_this or wants_reason
        asks = wants_reason or self._asks_about_device(q_lower)
        asks = asks or any(word in q_lower for word in DIAGNOSIS_WORDS)
        if named_tag or (self.focused_asset_tag and about_device and asks and not meaning):
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
        if not clean:
            text = "What would you like to know? Tap a device, or ask me what needs attention."
        elif re.fullmatch(GREETING_WORDS, clean):
            text = GREETING
        elif re.fullmatch(THANKS_WORDS, clean):
            text = THANKS
        elif re.fullmatch(BYE_WORDS, clean):
            text = "See you. Stay safe out there."
        elif any(phrase in clean for phrase in HOW_ARE_YOU):
            text = "All good, thanks. What can I look up for you?"
        elif clean in ("help", "help me") or any(phrase in clean for phrase in ABOUT_VAL):
            text = INTRO
        if text is None:
            return None
        return CopilotResponse(answer=text, confidence=1.0)

    @staticmethod
    def _asks_about_device(q_lower: str) -> bool:
        return bool(DEVICE_QUESTION.search(q_lower))

    def _define(self, question: str) -> CopilotResponse | None:
        """Answer "what does X mean" from the documents, or say the records don't explain it."""
        asked = DEFINITION_ASKED.match(question.strip().lower())
        if not asked:
            return None
        term = next(group for group in asked.groups() if group).strip(" '\"")
        term = re.sub(r"^(?:the|a|an)\s+", "", term)
        docs = self._matching_docs(term)
        if docs:
            return self._quote_doc(docs[0])
        return CopilotResponse(
            answer=f"The plant's records don't explain \"{term}\", so I won't guess what it means.",
            citations=["DOC-RAG-GUIDE"],
            confidence=1.0,
        )

    def _viewer_action(self, question: str, object_id: str | None) -> CopilotResponse | None:
        """Run a request to change the view. An object must be selected or named, never guessed."""
        found = match_action(question)
        if found is None:
            return None
        target = None
        if found.needs_object:
            unknown = self._check_unmapped_or_unknown(question, None)
            if unknown:
                return unknown
            # "Move P-002 next to P-005" moves P-002: look for the device before the other one.
            near = found.args.get("near")
            subject = question[: question.lower().rfind(near)] if near else question
            tag = self._resolve_target_asset(subject)
            if tag:
                matches = find_assets(tag, self.store, self.sample_assets, self.mapping)
                target = matches[0].object_id if matches else None
                if target is None:
                    return CopilotResponse(
                        answer=f"I can't find {tag} in the 3D scene.",
                        citations=["DOC-3D-MAPPING"],
                        confidence=1.0,
                    )
            else:
                target = object_id
            if target is None:
                return CopilotResponse(
                    answer="Which one? Tap it first, or say its name, like P-005.",
                    confidence=1.0,
                )
        args = dict(found.args)
        name = "it"
        if target:
            args["object_id"] = target
            record = self.mapping.get(target, {})
            scene = self._scene_object(target)
            name = record.get("tag") or scene.get("name") or f"this {scene.get('label', 'object')}"
        return CopilotResponse(
            answer=found.say.format(name=name),
            confidence=1.0,
            actions=[{"type": "viewer", "action": found.action, "args": args}],
        )

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
        issue = top.issue_summary[:1].lower() + top.issue_summary[1:]
        answer = (
            f"{len(urgent)} devices are marked high urgency. I'd start with {top.tag}: its health "
            f"is {top.health_score:.0f} out of 100, and the records point to {issue}. The first "
            f"check is: {top.recommended_next_check}."
        )
        others = ", ".join(f"{s.tag} ({s.health_score:.0f})" for s in urgent[1:4])
        if others:
            answer += f" After that, look at {others}."
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

    def _status_or_reply(self, tag: str) -> tuple[dict[str, Any] | None, CopilotResponse | None]:
        status = get_status(tag, self.store, self.mapping)
        if status:
            self.set_focus(tag)
            return status, None
        reply = CopilotResponse(
            answer=f"I don't have any current records for {tag}.",
            citations=["DOC-RAG-GUIDE"],
            confidence=0.5,
        )
        return None, reply

    @staticmethod
    def _state_words(condition: str) -> str:
        return {
            "attention_required": "needs attention",
            "degraded": "is degraded",
            "healthy": "looks healthy",
        }.get(condition, f"is {condition.replace('_', ' ')}")

    def _unknown_place(self, q_lower: str) -> str | None:
        """Return a place the question asks for, if it isn't equipment Val knows of."""
        found = re.search(r"(?:take me to|navigate to|route to|where is|where's)\s+(.+)", q_lower)
        if not found:
            return None
        place = re.sub(r"[?.!]+$", "", found.group(1)).strip()
        words = set(re.findall(r"[a-z]+", place)) - {"the", "a", "an", "my"}
        known = PLACE_ANY_WORDS | set(EQUIPMENT_WORDS)
        known |= {a.get("label", "") for a in self.sample_assets}
        known |= {w for a in self.sample_assets for w in str(a.get("label", "")).split()}
        if not words or words & known or words & {"pumps", "valves", "motors"}:
            return None
        return f"the {place}" if not place.startswith(("the ", "a ", "an ")) else place

    def _mentions_other_equipment(self, q_lower: str) -> bool:
        """Return whether a question names a kind of equipment that the current device isn't."""
        current = self.store.get_asset(self.focused_asset_tag) if self.focused_asset_tag else None
        kind = current.asset_class if current else ""
        return any(word in q_lower and cls not in kind for word, cls in EQUIPMENT_WORDS.items())

    def _which_one(
        self, q_lower: str, named_tag: str | None, object_id: str | None
    ) -> CopilotResponse | None:
        """Ask which device, when a question names a kind of equipment and none is meant yet."""
        if named_tag or object_id or self._is_navigation_intent(q_lower):
            return None
        for word in EQUIPMENT_WORDS:
            if re.search(rf"\b(the|that|this) {word}\b", q_lower):
                if not self.focused_asset_tag or self._mentions_other_equipment(q_lower):
                    return CopilotResponse(
                        answer=f"Which {word} do you mean? Tap it, or give me its tag.",
                        citations=[],
                        confidence=1.0,
                    )
        return None

    def _count(self, word: str) -> CopilotResponse:
        cls = EQUIPMENT_WORDS[word]
        found = [a for a in self.store.list_assets() if cls in a.asset_class]
        tags = ", ".join(a.tag for a in found[:8])
        return CopilotResponse(
            answer=f"The records list {len(found)} {word}s: {tags}.",
            citations=[a.asset_id for a in found[:4]],
            confidence=1.0,
        )

    def _handle_safe_to_work(self, tag: str) -> CopilotResponse:
        """Never declare equipment safe. That's for the site's procedures and qualified staff."""
        status, reply = self._status_or_reply(tag)
        if reply:
            return reply
        return CopilotResponse(
            answer=(
                f"I can't tell you that it's safe. Only the site's procedures and qualified staff "
                f"can. What I can say is that {tag} {self._state_words(status['condition_state'])}"
                ". Get a permit and follow lockout/tagout before any work."
            ),
            citations=["DOC-FIELD-SAFETY", status["asset_id"]],
            confidence=1.0,
            focused_object_id=status.get("object_id"),
        )

    def _handle_documents(self, tag: str) -> CopilotResponse:
        status, reply = self._status_or_reply(tag)
        if reply:
            return reply
        docs = self.store.list_docs(scope=status["asset_class"])
        if not docs:
            return self._not_in_records("documents for this device")
        titles = "; ".join(f"{d.title} ({d.doc_id})" for d in docs[:3])
        return CopilotResponse(
            answer=f"I don't have a manual, but this guidance covers {tag}: {titles}.",
            citations=[d.doc_id for d in docs[:3]],
            confidence=0.9,
            focused_object_id=status.get("object_id"),
        )

    def _handle_confidence(self, tag: str) -> CopilotResponse:
        """Say how sure the records are, and separately how sure the object's link is."""
        status, reply = self._status_or_reply(tag)
        if reply:
            return reply
        link = status.get("mapping_confidence")
        answer = (
            f"The records rate this finding on {tag} at {status['model_confidence']:.0%} "
            "confidence."
        )
        if link is not None and link < 1.0:
            answer += (
                f" The weaker part is knowing this object really is {tag}: that link is only "
                f"{link:.0%} certain, so check the nameplate."
            )
        issues = status.get("data_quality_issues") or []
        if issues:
            answer += f" There are also {len(issues)} data quality notes on its readings."
        return CopilotResponse(
            answer=answer,
            observations=[f"Mapping: {status.get('mapping_method')}."],
            citations=[status["asset_id"]],
            confidence=status["model_confidence"],
            focused_object_id=status.get("object_id"),
        )

    def _handle_urgency(self, tag: str) -> CopilotResponse:
        status, reply = self._status_or_reply(tag)
        if reply:
            return reply
        return CopilotResponse(
            answer=(
                f"{tag} is marked {status['urgency']} urgency, with its health at "
                f"{status['health_score']:.0f} out of 100. Its criticality is listed as "
                f"{status['criticality']}."
            ),
            citations=[status["asset_id"]],
            confidence=status["model_confidence"],
            focused_object_id=status.get("object_id"),
        )

    def _handle_history(self, tag: str) -> CopilotResponse:
        status, reply = self._status_or_reply(tag)
        if reply:
            return reply
        cases = search_service_cases(
            self.store, asset_class=status["asset_class"], issue_code=status["issue_code"]
        )
        if not cases:
            return CopilotResponse(
                answer=f"I can't find a past case like this for {tag}'s type of equipment.",
                citations=[status["asset_id"]],
                confidence=0.8,
                focused_object_id=status.get("object_id"),
            )
        first = cases[0]
        return CopilotResponse(
            answer=(
                f"Yes, the records have {len(cases)} similar cases on this type of equipment. In "
                f"{first['case_id']}, it was read as: {first['historical_interpretation']}. The "
                f"next check then was: {first['recommended_next_check']}."
            ),
            observations=[f"{c['case_id']}: {c['historical_interpretation']}" for c in cases[:5]],
            citations=[c["case_id"] for c in cases[:5]],
            confidence=0.9,
            focused_object_id=status.get("object_id"),
        )

    def _handle_identity(self, tag: str) -> CopilotResponse:
        status, reply = self._status_or_reply(tag)
        if reply:
            return reply
        kind = status["asset_class"].replace("_", " ").lower()
        return CopilotResponse(
            answer=(
                f"This is {tag}, a {kind} in {status['area_name']}. Right now it "
                f"{self._state_words(status['condition_state'])}, with its health at "
                f"{status['health_score']:.0f} out of 100."
            ),
            citations=[status["asset_id"]],
            confidence=status["model_confidence"],
            focused_object_id=status.get("object_id"),
        )

    def _handle_measurements(
        self, tag: str, asked: re.Match[str] | None, q_lower: str
    ) -> CopilotResponse:
        """Answer about what's measured, and say so when something isn't."""
        status, reply = self._status_or_reply(tag)
        if reply:
            return reply
        metrics = get_telemetry_summary(tag, self.store, limit=20).get("metrics", {})

        def describe(key: str, nice: str, unit: str) -> str:
            metric = metrics[key]
            trend = TRENDS.get(metric["trend"], metric["trend"])
            return (
                f"{nice} is {metric['latest']}{unit} and {trend} over the last "
                f"{metric['sample_count']} readings, between {metric['min_val']} and "
                f"{metric['max_val']}."
            )

        known = {key: (nice, unit) for key, nice, unit in METRICS.values() if key in metrics}
        parts = []
        if asked:
            key, nice, unit = METRICS[asked.group(1)]
            if key not in metrics:
                parts.append(f"I don't have {nice.lower()} readings for {tag}.")
            else:
                parts.append(describe(key, nice, unit))
        if not asked or asked and METRICS[asked.group(1)][0] not in metrics:
            moving = [k for k in known if metrics[k]["trend"] != "stable"] or list(known)
            if moving:
                lead = "Here's what is measured: " if asked else ""
                parts.append(lead + " ".join(describe(k, *known[k]) for k in moving))
            else:
                parts.append(f"I don't have recent readings for {tag}.")
        return CopilotResponse(
            answer=" ".join(parts),
            observations=metric_observations(metrics),
            citations=[status["asset_id"]],
            confidence=status["model_confidence"],
            focused_object_id=status.get("object_id"),
        )

    def _scene_object(self, object_id: str) -> dict[str, Any]:
        return next((a for a in self.sample_assets if a.get("object_id") == object_id), {})

    def _handle_navigation_to_object(self, object_id: str) -> CopilotResponse:
        """Route to a selected object that has no record."""
        found = self._scene_object(object_id)
        label = found.get("name") or f"this {found.get('label', 'object')}"
        return CopilotResponse(
            answer=f"I've marked {label} and drawn the path to it.",
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

    def _describe_unlinked(self, object_id: str, q_lower: str = "") -> CopilotResponse:
        """Say what's known about an object with no record, without guessing its identity."""
        found = self._scene_object(object_id)
        label = found.get("label", "object")
        confidence = float(found.get("confidence") or 0.0)
        name = found.get("name")
        copied = found.get("copied_name")
        if "movable" in q_lower or "can i move" in q_lower or "move it" in q_lower:
            mobility = found.get("mobility", "unsure")
            words = {
                "movable": "Yes, it's marked as movable. Press Move in its panel.",
                "fixed": "No, it's marked as fixed.",
            }.get(mobility, "I'm not sure. It isn't marked as movable or fixed.")
            answer = words
        elif copied:
            answer = (
                f"This is {name}, a copy of {copied}, showing a {label}. It's a separate object "
                f"with its own ID, and the records and history belong to {copied}, not this copy."
            )
        else:
            answer = (
                f"The scan shows this as: {name + ', a ' + label if name else label}. It isn't "
                "linked to a plant record, so I have no condition, measurements or service "
                "history for it, and I won't guess which device it is. I can make a path to it so "
                "you can check its nameplate."
            )
        return CopilotResponse(
            answer=answer,
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
                        f"I can't find {code} in the plant's records, so I can't tell you "
                        "anything about it. Could the tag be a different one?"
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
            "show the path",
            "show route",
            "show the route",
            "make path",
            "make a path",
            "make the path",
            "draw a path",
            "draw the path",
            "draw a route",
            "draw the route",
            "path to",
            "go to",
            "go there",
            "head to",
            "walk me",
            "lead me",
            "get me to",
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

        answer = f"I've marked {tag} and drawn the path to it."
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
        state = self._state_words(cond_str)
        issue = status["issue_summary"]
        issue = issue[:1].lower() + issue[1:]
        check = status["recommended_next_check"]
        if cond_str == "healthy":
            answer = (
                f"{tag} looks healthy. Its health is {h_score:.0f} out of 100 and nothing unusual "
                f"stands out. The records just say: {check}."
            )
        else:
            answer = (
                f"{tag} {state}. Its health is {h_score:.0f} out of 100, and the records point to "
                f"{issue}. I'd start with this check: {check}. Follow the site's safety rules "
                "before touching anything."
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
            f"{tag} was last serviced on {opened}, under work order {wo_id}. It was a "
            f"{latest_wo['action']}, and the result was recorded as "
            f"{latest_wo['result'].replace('_', ' ')}."
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
            f"For {tag}, I'd start with this check: {rec_check}. The guidance also says to look "
            "at several readings together and confirm it on site. Get the proper permits and "
            "follow lockout/tagout before opening anything."
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

    def _matching_docs(self, text: str) -> list[dict[str, Any]]:
        """Return documents covering at least half of the words asked about."""
        words = set(re.findall(r"[a-z0-9-]{3,}", text.lower())) - COMMON_WORDS
        if not words:
            return []
        found = []
        for doc in search_docs(self.store, query=text):
            content = set(re.findall(r"[a-z0-9-]+", f"{doc['title']} {doc['content']}".lower()))
            if len(words & content) * 2 >= len(words):
                found.append(doc)
        return found

    def _quote_doc(doc: dict[str, Any]) -> CopilotResponse:
        doc_id = doc["doc_id"]
        return CopilotResponse(
            answer=(
                f"Here's what the guidance on {doc['title'].lower()} says: "
                + " ".join(re.split(r"(?<=[.!?])\s+", doc["content"].strip())[:2])
            ),
            observations=[f"Matched guidance document {doc_id}."],
            hypotheses=[],
            citations=[doc_id, "DOC-RAG-GUIDE"],
            confidence=0.85,
            actions=[{"type": "open_document", "doc_id": doc_id}],
        )

    def _handle_general_query(self, question: str) -> CopilotResponse:
        """Answer from the guidance documents, or say the question wasn't understood."""
        docs = self._matching_docs(question)
        if docs:
            return self._quote_doc(docs[0])
        return CopilotResponse(answer=NOT_UNDERSTOOD, confidence=1.0)

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
