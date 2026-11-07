"""Speech to text for Val, on this machine, so it works with no internet. Audio is never saved.

Faster-whisper is imported only when needed, and the model comes from `make voice-model`. It never
downloads anything while running.
"""

import io
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MODEL = "data/models/whisper-small.en"
MAX_AUDIO_BYTES = 10_000_000
UNSURE_LOGPROB = -0.8  # below this, ask the person to check the words before Val acts on them
MAX_NO_SPEECH = 0.75

# Sounds a recogniser may write for the start of a tag.
TAG_SOUNDS = {
    "p": "P",
    "pee": "P",
    "pea": "P",
    "m": "M",
    "em": "M",
    "cv": "CV",
    "c v": "CV",
    "c-v": "CV",
    "see v": "CV",
    "pt": "PT",
    "p t": "PT",
    "vs": "VS",
    "v s": "VS",
}
DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "o": "0",
    "one": "1",
    "two": "2",
    "to": "2",
    "too": "2",
    "three": "3",
    "four": "4",
    "for": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}
_SOUNDS = "|".join(sorted((re.escape(s) for s in TAG_SOUNDS), key=len, reverse=True))
_DIGITS = "|".join(sorted(DIGIT_WORDS, key=len, reverse=True))
SPOKEN_TAG = re.compile(
    rf"\b({_SOUNDS})[\s.\-]*((?:\d+|{_DIGITS})(?:[\s\-]+(?:\d+|{_DIGITS}))*)\b", re.IGNORECASE
)
WAKE = re.compile(r"^(?:hey\s+|hi\s+|ok\s+|okay\s+)?val\b[\s,.:!-]*", re.IGNORECASE)


def clean_transcript(text: str, tags: set[str]) -> str:
    """Tidy what was heard: "see v 3" becomes CV-003, if that device exists. Never invents a tag."""

    def fix(match: re.Match) -> str:
        prefix = TAG_SOUNDS[match.group(1).lower()]
        pieces = re.split(r"[\s\-]+", match.group(2).lower())
        number = "".join(DIGIT_WORDS.get(piece, piece) for piece in pieces)
        tag = f"{prefix}-{int(number):03d}"
        return tag if tag in tags else match.group(0)

    clean = WAKE.sub("", text.strip())
    clean = SPOKEN_TAG.sub(fix, clean)
    return clean[:1].upper() + clean[1:]


def _speech_prompt(tags: set[str]) -> str:
    """Tell the recogniser which words to expect, so device names come out right."""
    names = ", ".join(sorted(tags)[:40])
    return (
        f"Hey Val. Val is the assistant's name. Field service in a plant equipment room. Devices: "
        f"{names}. Hey Val, what needs attention? What's "
        "wrong with it? When was it last serviced? Make a path to it. Hide the frames. Pump, "
        "valve, motor, drain, flush, isolate, shut down, fouling, vibration, pressure."
    )


class Transcriber:
    """Loads the model once and turns recorded audio into text."""

    def __init__(self, model_dir: str | None = None) -> None:
        self.model_dir = model_dir or os.getenv("STT_MODEL", DEFAULT_MODEL)
        self.model: Any = None
        self.lock = threading.Lock()

    @property
    def installed(self) -> bool:
        return (Path(self.model_dir) / "model.bin").exists()

    def load(self) -> Any:
        with self.lock:
            if self.model is None:
                from faster_whisper import WhisperModel

                # CPU by default: it's quick enough, and leaves the GPU to the viewer and the model.
                self.model = WhisperModel(
                    self.model_dir,
                    device=os.getenv("STT_DEVICE", "cpu"),
                    compute_type=os.getenv("STT_COMPUTE", "int8"),
                    local_files_only=True,
                )
            return self.model

    def warm_up(self) -> None:
        """Load in the background, so the first thing said isn't slow."""
        if self.installed:
            threading.Thread(target=self._try_load, daemon=True).start()

    def _try_load(self) -> None:
        try:
            self.load()
        except Exception:
            log.exception("Couldn't load the speech model")

    def transcribe(self, audio: bytes, tags: set[str]) -> dict[str, Any]:
        """Return the words heard, and whether to check them with the person first."""
        model = self.load()
        with self.lock:
            segments, _ = model.transcribe(
                io.BytesIO(audio),
                language="en",
                beam_size=5,
                vad_filter=True,  # ignores silence, where the model tends to imagine words
                vad_parameters={"min_silence_duration_ms": 400},
                condition_on_previous_text=False,
                initial_prompt=_speech_prompt(tags),
            )
            heard = [s for s in segments if s.no_speech_prob < MAX_NO_SPEECH]
        raw = " ".join(segment.text.strip() for segment in heard).strip()
        unsure = any(segment.avg_logprob < UNSURE_LOGPROB for segment in heard)
        return {"text": clean_transcript(raw, tags), "raw": raw, "unsure": unsure}


TRANSCRIBER = Transcriber()  # one model, however many apps start
