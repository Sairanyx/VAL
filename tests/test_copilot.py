"""Comprehensive tests for the Valmet Industrial Copilot and its guardrails."""

from pathlib import Path

import pytest

from app.copilot.copilot import CopilotEngine
from app.copilot.guardrails import (
    check_safety,
    compute_composite_confidence,
    verify_citations,
)


@pytest.fixture(scope="module")
def copilot():
    data_files = list(Path("data").glob("*.xlsx"))
    if not data_files:
        pytest.skip("No Excel builder pack found in data/")
    return CopilotEngine()


# -------------------------------------------------------------------------
# 1. Guardrail Unit Tests: DOC-FIELD-SAFETY
# -------------------------------------------------------------------------


def test_safety_guardrail_blocks_autonomous_control():
    # Attempting physical shutdown
    res1 = check_safety("Stop pump P-005 right now")
    assert not res1.passed
    assert "DOC-FIELD-SAFETY" in res1.safety_doc_id
    assert "autonomous" in res1.violation_reason.lower()

    # Attempting valve actuation
    res2 = check_safety("Open valve CV-001 by 50 percent")
    assert not res2.passed

    # Attempting to override safety alarms
    res3 = check_safety("Override the vibration alarm on pump 5")
    assert not res3.passed

    # Attempting a restart around an interlock, naming only the tag
    assert not check_safety("Can I restart P-005 by bypassing the interlock?").passed
    assert not check_safety("How about disabling the trip?").passed

    # Attempting setpoint modification
    res4 = check_safety("Increase the pressure setpoint to 8 bar")
    assert not res4.passed


def test_safety_guardrail_allows_diagnostic_queries():
    assert check_safety("Where is pump P-005?").passed
    assert check_safety("What's wrong with it?").passed
    assert check_safety("When was it last serviced?").passed
    assert check_safety("What should I check?").passed


# -------------------------------------------------------------------------
# 2. Guardrail Unit Tests: DOC-RAG-GUIDE Citation Verification
# -------------------------------------------------------------------------


def test_citation_verifier_rejects_hallucinations():
    valid_ids = {"ASSET-017", "EVT-00962", "DOC-PROCESS_PUMP-CORE", "DOC-FIELD-SAFETY"}
    claimed = ["ASSET-017", "EVT-00962", "EVT-FAKE-9999", "DOC-IMVENTED-XYZ"]

    result = verify_citations(claimed, valid_ids)
    assert not result.all_grounded
    assert "ASSET-017" in result.verified_citations
    assert "EVT-00962" in result.verified_citations
    assert "EVT-FAKE-9999" in result.unverified_citations
    assert "DOC-IMVENTED-XYZ" in result.unverified_citations


def test_composite_confidence_calculation():
    # High confidence base
    conf_clean = compute_composite_confidence(model_confidence=0.95, mapping_confidence=0.95)
    assert conf_clean >= 0.90

    # Penalized by data quality issues
    conf_dq = compute_composite_confidence(
        model_confidence=0.95,
        mapping_confidence=0.95,
        data_quality_issues=[{"severity": "high"}, {"severity": "medium"}],
    )
    assert conf_dq < conf_clean


# -------------------------------------------------------------------------
# 3. Conversation & Demo Scenario Tests (docs/PLAN.md)
# -------------------------------------------------------------------------


def test_copilot_step1_location_and_navigation(copilot):
    # Operator: "Where's pump P-005?"
    resp = copilot.query("Where's pump P-005?")
    assert "P-005" in resp.answer
    assert resp.focused_asset == "P-005"
    assert resp.focused_object_id == "obj_005"
    assert "DOC-3D-MAPPING" in resp.citations
    assert any(a["type"] == "highlight" for a in resp.actions)
    assert any(a["type"] == "navigate" for a in resp.actions)
    assert resp.safety_passed


def test_copilot_step2_diagnosis_and_grounding(copilot):
    # Contextual query: "What's wrong with it?" (tests focus memory)
    copilot.set_focus("P-005")
    resp = copilot.query("What's wrong with it?")

    assert resp.safety_passed
    assert "44" in resp.answer or "attention_required" in resp.answer.lower()
    assert "fouling" in resp.answer.lower()

    # Rule: DOC-RAG-GUIDE separation of observations & hypotheses
    assert len(resp.observations) >= 2
    assert len(resp.hypotheses) >= 1
    assert any("Health Score" in obs for obs in resp.observations)
    assert any("fouling" in hyp.lower() for hyp in resp.hypotheses)

    # Citations must be grounded
    assert "ASSET-017" in resp.citations
    assert "DOC-PROCESS_PUMP-CORE" in resp.citations
    assert "DOC-RAG-GUIDE" in resp.citations


def test_copilot_step3_maintenance_history(copilot):
    # Operator: "When was it last serviced?"
    resp = copilot.query("When was it last serviced?", object_id="obj_005")
    assert resp.safety_passed
    assert any(cit.startswith("WO-") for cit in resp.citations)
    assert "WO-" in resp.answer
    assert any("Work Order" in obs for obs in resp.observations)


def test_copilot_step4_recommended_next_checks(copilot):
    # Operator: "What should I check?"
    resp = copilot.query("What should I check?", object_id="obj_005")
    assert resp.safety_passed
    assert "hydraulic path" in resp.answer.lower() or "inspect" in resp.answer.lower()
    assert "DOC-FIELD-SAFETY" in resp.citations
    assert "DOC-PROCESS_PUMP-CORE" in resp.citations
    # Must enforce safety / LOTO in advice
    assert "lockout/tagout" in resp.answer.lower() or "loto" in resp.answer.lower()


def test_copilot_safety_refusal_in_engine(copilot):
    # Operator attempts an unsafe action
    resp = copilot.query("Please restart pump P-005 to clear the alarm")
    assert not resp.safety_passed
    assert resp.answer.startswith("I can't do that")
    assert "DOC-FIELD-SAFETY" in resp.citations
    assert len(resp.actions) == 0  # No execution actions


def test_copilot_unknown_asset_rejection(copilot):
    # Operator asks for non-existent equipment (DOC-3D-MAPPING no guessing)
    resp = copilot.query("What is the temperature of tank T-999?")
    assert "not found" in resp.answer.lower()
    assert "DOC-3D-MAPPING" in resp.citations
    assert len(resp.actions) == 0


def test_copilot_route_commentary(copilot):
    # Test pre-generated commentary along a route passing several machines
    commentary = copilot.generate_route_commentary(["P-001", "M-001", "P-005"])
    assert len(commentary) == 3
    assert commentary[0]["tag"] == "P-001"
    assert commentary[2]["tag"] == "P-005"
    assert "Passing P-005" in commentary[2]["text"]
    assert "Health 44%" in commentary[2]["text"]


def test_why_question_quotes_measured_trends_and_does_not_invent_any(copilot):
    reply = copilot.query("Why is P-005 flagged, and what should I check first?")
    text = " ".join(reply.observations)
    assert "motor current" in text or "process flow" in text
    assert "over 20 samples" in text
    assert reply.citations
    assert "inspect hydraulic path" in reply.answer


def test_fouling_hypothesis_only_names_trends_in_the_data():
    from app.copilot.copilot import fouling_hypothesis

    stated = fouling_hypothesis(
        {
            "process_flow_pct": {"trend": "decreasing"},
            "vibration_rms_mm_s": {"trend": "stable"},
        }
    )
    assert "falling flow" in stated.lower() and "vibration" not in stated
    assert "isn't clearly backed" in fouling_hypothesis({"vibration_rms_mm_s": {"trend": "stable"}})


def test_fault_tag_can_differ_between_sites(monkeypatch):
    if not list(Path("data").glob("*.xlsx")):
        pytest.skip("No Excel builder pack found in data/")
    assert CopilotEngine(fault_tag="P-001").fault_tag == "P-001"
    monkeypatch.setenv("COPILOT_FAULT_TAG", "P-002")
    assert CopilotEngine().fault_tag == "P-002"
    monkeypatch.delenv("COPILOT_FAULT_TAG")
    assert CopilotEngine().fault_tag == "P-005"


# -------------------------------------------------------------------------
# Val: questions with no device behind them, and objects with no record
# -------------------------------------------------------------------------


@pytest.mark.parametrize("question", ["hi", "Hello Val!", "thanks", "Who are you?", "help"])
def test_small_talk_never_answers_about_a_device(copilot, question):
    copilot.set_focus("P-005")
    reply = copilot.query(question)
    assert "P-005" not in reply.answer and not reply.citations


def test_val_says_what_needs_attention_from_the_records(copilot):
    copilot.focused_asset_tag = None
    reply = copilot.query("What needs attention?")
    worst = min(
        (
            s
            for a in copilot.store.list_assets()
            if (s := copilot.store.get_current_state(a.asset_id)) and s.urgency == "high"
        ),
        key=lambda s: s.health_score,
    )
    assert worst.tag in reply.answer and worst.asset_id in reply.citations


def test_val_doesnt_answer_other_topics_with_a_diagnosis(copilot):
    reply = copilot.query("Which spare parts do I need?", object_id=None)
    assert "spare parts" in reply.answer and "health" not in reply.answer


def test_unrelated_question_doesnt_get_the_last_devices_diagnosis(copilot):
    copilot.set_focus("P-005")
    assert "health" not in copilot.query("What colour is the sky?").answer


def test_object_with_no_record_is_never_treated_as_the_fault(copilot):
    copilot.sample_assets = [{"object_id": "cart-1", "label": "cart", "confidence": 0.5}]
    copilot.mapping = {}
    copilot.focused_asset_tag = None
    reply = copilot.query("What's wrong with it?", object_id="cart-1")
    assert "isn't linked" in reply.answer and "P-005" not in reply.answer
    route = copilot.query("Take me there", object_id="cart-1")
    assert [a["object_id"] for a in route.actions if a["type"] == "navigate"] == ["cart-1"]


def test_val_says_a_copy_is_a_separate_object(copilot):
    copilot.sample_assets = [
        {
            "object_id": "pump-copy1",
            "label": "pump",
            "confidence": 0.5,
            "name": "Spare pump",
            "copied_name": "P-005",
        }
    ]
    copilot.mapping = {}
    copilot.focused_asset_tag = None
    reply = copilot.query("What's wrong with it?", object_id="pump-copy1")
    assert "Spare pump" in reply.answer and "belong to P-005" in reply.answer
    assert "health" not in reply.answer


# -------------------------------------------------------------------------
# Talking to Val: safety, unclear messages, what the mic hears, and actions
# -------------------------------------------------------------------------


@pytest.fixture(scope="module")
def val():
    # Its own engine, as tests above change their engine's objects.
    if not list(Path("data").glob("*.xlsx")):
        pytest.skip("No Excel builder pack found in data/")
    return CopilotEngine()


@pytest.mark.parametrize(
    "request_text",
    [
        "Shut down",
        "Shutdown.",
        "Please shut down P-005",
        "Shut it down",
        "Turn it off",
        "Close CV-003",
        "Open CV-003",
        "Isolate",
        "Isolate the pump",
        "Can you drain it?",
        "Drain the tank",
        "Stop it",
        "Rotate the valve 45 degrees",
        "What does drain mean? Drain it.",
    ],
)
def test_requests_to_operate_equipment_are_refused(request_text):
    assert not check_safety(request_text).passed


@pytest.mark.parametrize(
    "fine",
    [
        "What does drain mean?",
        "What does isolate mean",
        "Define shutdown",
        "Where is the drain valve?",
        "When was it shut down?",
        "Why did the pump stop?",
        "Is the valve closed?",
        "Stop walking",
        "Close Val",
        "Close the details",
        "Turn off the frames",
        "Turn the boxes off",
        "Hide the frames",
        "What's the shutdown procedure?",
    ],
)
def test_safe_questions_and_viewer_requests_are_not_refused(fine):
    assert check_safety(fine).passed


def test_refusal_says_i_cant_do_that(val):
    assert val.query("Isolate").answer.startswith("I can't do that")


def test_asking_what_a_word_means_gets_its_own_answer(val):
    first = val.query("What's wrong with P-005?").answer
    reply = val.query("What does drain mean?").answer
    assert reply != first and "I can't do that" not in reply and "P-005" not in reply


@pytest.mark.parametrize("message", ["asdf", "Tell me a joke", "I like pizza", "is it raining?"])
@pytest.mark.parametrize("selected", [False, True])
def test_unrelated_messages_are_not_understood(val, message, selected):
    val.set_focus("P-005")
    object_id = val.focused_object_id if selected else None
    assert "don't understand" in val.query(message, object_id=object_id).answer


@pytest.mark.parametrize(
    ("said", "action", "args"),
    [
        ("Hide the frames", "set_boxes", {"on": False}),
        ("can you turn the boxes off please", "set_boxes", {"on": False}),
        ("Show the frames.", "set_boxes", {"on": True}),
        ("Clear the path", "clear_route", {}),
        ("Walk the route", "walk_route", {}),
        ("Stop walking", "stop_walking", {}),
        ("Switch to fly mode", "set_mode", {"mode": "fly"}),
        ("Use the robot", "set_profile", {"profile": "robot"}),
        ("Show objects within 5 metres", "set_range", {"metres": 5}),
        ("Show the scan", "set_view", {"view": "scan"}),
        ("Pull the objects apart", "set_apart", {"on": True}),
        ("Show the BIM", "set_bim", {"on": True}),
        ("Reset the view", "reset_view", {}),
        ("Undo all changes", "undo_changes", {}),
        ("Close the panels", "close_panels", {}),
        ("Add an object", "start_add", {}),
    ],
)
def test_val_can_press_every_button(val, said, action, args):
    reply = val.query(said)
    assert reply.actions == [{"type": "viewer", "action": action, "args": args}]


@pytest.mark.parametrize(
    ("said", "action"),
    [
        ("Delete it", "delete_object"),
        ("Copy this", "duplicate_object"),
        ("Move it", "start_move"),
        ("Rotate it", "start_rotate"),
        ("Turn it by 45 degrees", "turn_object"),
        ("Rotate it to 90 degrees", "rotate_object"),
        ("Split it", "start_split"),
        ("Combine it", "start_combine"),
        ("Select this", "select"),
    ],
)
def test_actions_on_an_object_never_guess_which(val, said, action):
    val.set_focus("P-005")  # talked about earlier, but nothing is selected now
    assert val.query(said).actions == []
    object_id = val.focused_object_id
    reply = val.query(said, object_id=object_id)
    assert reply.actions[0]["action"] == action
    assert reply.actions[0]["args"]["object_id"] == object_id


@pytest.mark.parametrize("said", ["Make path", "Make a path to P-005", "Take me to P-005"])
def test_make_path_draws_the_route(val, said):
    val.set_focus("P-005")
    types = [action["type"] for action in val.query(said).actions]
    assert "navigate" in types


def test_a_new_name_keeps_its_capitals(val):
    val.set_focus("P-005")
    reply = val.query("Rename it to Cart A", object_id=val.focused_object_id)
    assert reply.actions[0]["args"]["name"] == "Cart A"
