"""What Val hears: tidying spoken words, and the speech endpoint."""

from pathlib import Path

import pytest

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
