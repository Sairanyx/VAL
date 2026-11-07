import json

import pytest

from app.copilot.copilot import CopilotResponse  # noqa: E402
from app.copilot.llm import Fact, check_reply, explain, parse_reply  # noqa: E402

FACTS = [
    Fact("ASSET-017", "tag: P-005"),
    Fact("ASSET-017", "process flow pct: now 64.557, range 63.347 to 83.191, decreasing."),
    Fact("EVT-00962", "severity: low; description: fouling-like signature"),
    Fact("DOC-PROCESS_PUMP-CORE", "Inspect the hydraulic path."),
    Fact("DOC-FIELD-SAFETY", "Follow lockout/tagout."),
]


def good_reply(**changes):
    reply = {
        "answer": "Flow fell from 83.2 to 64.557 on P-005, as ASSET-017 shows.",
        "hypotheses": ["The hydraulic path may be fouled."],
        "citations": ["ASSET-017", "DOC-PROCESS_PUMP-CORE"],
    }
    return {**reply, **changes}


class FakeWriter:
    def __init__(self, reply):
        self.reply = reply

    def write(self, prompt):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def template():
    return CopilotResponse(
        answer="Template answer.",
        observations=["Measured."],
        hypotheses=["Template cause."],
        citations=["ASSET-017"],
        confidence=0.4,
        actions=[],
    )


def test_grounded_reply_passes_allowing_for_rounding():
    assert check_reply(good_reply(), FACTS) is None


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"citations": ["ASSET-017", "DOC-MADE-UP"]}, "citations not in the facts"),
        ({"citations": []}, "no citations"),
        ({"answer": "Flow fell by 23 percent."}, "number not in the facts: 23"),
        ({"hypotheses": ["Bearing wear above 90 C."]}, "number not in the facts: 90"),
        ({"answer": "Compare with CASE-099, as flow fell."}, "names an ID not in the facts"),
        ({"answer": "Restart the pump to clear it."}, "mentions operating equipment"),
        ({"answer": ""}, "no answer"),
    ],
)
def test_bad_replies_are_rejected_with_the_reason(changes, reason):
    assert reason in check_reply(good_reply(**changes), FACTS)


def test_reply_parsing_handles_code_fences_and_junk():
    assert parse_reply('```json\n{"answer": "a"}\n```') == {"answer": "a"}
    assert parse_reply("no json here") is None
    assert parse_reply("{broken") is None
    assert check_reply(None, FACTS) == "not valid JSON"


def test_passing_reply_replaces_the_wording_and_keeps_the_safety_note():
    response, note = explain(template(), FACTS, "Why?", FakeWriter(json.dumps(good_reply())))
    assert note["answer_source"] == "model"
    assert response.answer.startswith("Flow fell")
    assert "DOC-FIELD-SAFETY" in response.answer
    assert "DOC-FIELD-SAFETY" in response.citations
    assert response.observations == ["Measured."]  # Measured facts stay from code.


@pytest.mark.parametrize(
    "writer",
    [
        None,
        FakeWriter("not json"),
        FakeWriter(json.dumps(good_reply(answer="Flow fell by 23 percent."))),
        FakeWriter(RuntimeError("out of memory")),
    ],
)
def test_any_failure_keeps_the_template_answer(writer):
    response, note = explain(template(), FACTS, "Why?", writer)
    assert response.answer == "Template answer."
    assert note["answer_source"] == "template"
    assert note["reason"]
