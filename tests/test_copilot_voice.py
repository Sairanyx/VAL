"""What Val hears: tidying spoken words, and the speech endpoint."""

from pathlib import Path

import pytest

from app.copilot.guardrails import check_safety
from app.copilot.viewer_actions import match_action
from app.copilot.voice import Transcriber, clean_transcript

TAGS = {"P-005", "CV-003", "M-006", "PT-001"}


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        ("What's wrong with P 005?", "What's wrong with P-005?"),
        ("what's wrong with p5", "What's wrong with P-005"),
        ("Close see v 3", "Close CV-003"),
        ("make a path to c v zero zero three", "Make a path to CV-003"),
        ("Hey Val, what needs attention?", "What needs attention?"),
        ("Val check m 6", "Check M-006"),
        ("p t one status", "PT-001 status"),
    ],
)
def test_spoken_tags_become_real_tags(heard, expected):
    assert clean_transcript(heard, TAGS) == expected


def test_a_device_that_doesnt_exist_is_not_invented():
    assert clean_transcript("what about p 999", TAGS) == "What about p 999"


def test_ordinary_words_stay_as_they_are():
    said = "I want to go to the pump for a look"
    assert clean_transcript(said, TAGS) == said


def test_missing_model_is_reported_not_downloaded(tmp_path: Path):
    assert not Transcriber(str(tmp_path)).installed


@pytest.mark.parametrize(
    ("said", "action", "args"),
    [
        ("Show only pumps", "set_filter", {"types": ["pump"], "conditions": [], "mobility": "any"}),
        (
            "Only show pumps and valves",
            "set_filter",
            {"types": ["pump", "valve"], "conditions": [], "mobility": "any"},
        ),
        (
            "Show me what's urgent",
            "set_filter",
            {"types": [], "conditions": ["attention_required"], "mobility": "any"},
        ),
        (
            "Just the degraded pumps",
            "set_filter",
            {"types": ["pump"], "conditions": ["degraded"], "mobility": "any"},
        ),
        (
            "Show only movable objects",
            "set_filter",
            {"types": [], "conditions": [], "mobility": "movable"},
        ),
        ("Hide the pipes", "hide_types", {"types": ["pipe"]}),
        ("Clear the filters", "clear_filters", {}),
        ("Show everything", "clear_filters", {}),
        ("Turn off alerts", "set_alerts", {"level": "off"}),
        ("Show all alerts", "set_alerts", {"level": "all"}),
        ("Alerts for degraded too", "set_alerts", {"level": "degraded"}),
        ("Open the map", "open_map", {}),
        ("Show the full map", "expand_map", {}),
        ("Hide the map", "close_map", {}),
        ("Open the objects list", "open_list", {}),
        ("Find tanks on the map", "find_on_map", {"text": "tanks"}),
        ("Start the demo", "start_demo", {}),
        ("Go dark", "set_stage", {"stage": "dark"}),
        ("Show the simple BIM", "set_stage", {"stage": "box"}),
        ("Blob BIM", "set_stage", {"stage": "mesh"}),
        ("Show the point cloud", "set_stage", {"stage": "points"}),
        ("Back to the real view", "set_stage", {"stage": "real"}),
        ("Next view", "next_stage", {}),
        ("Stop the demo", "stop_demo", {}),
    ],
)
def test_filters_and_panels_by_voice(said, action, args):
    found = match_action(said)
    assert found is not None and found.action == action and found.args == args


@pytest.mark.parametrize(
    "said",
    ["What pumps are there?", "Show P-005", "Hide the frames", "Show objects", "Where is the map?"],
)
def test_other_sentences_arent_filters(said):
    found = match_action(said)
    assert found is None or found.action not in ("set_filter", "hide_types", "clear_filters")


def test_turning_off_alerts_is_not_refused_as_operating_equipment():
    assert check_safety("Turn off alerts").passed
    assert not check_safety("Turn off the pump").passed


def test_focusing_on_a_device_asks_which_one():
    found = match_action("Focus on P-005")
    assert found is not None and found.action == "focus_object" and found.needs_object
