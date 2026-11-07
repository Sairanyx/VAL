"""Let a local language model explain the copilot's facts in plain language.

The model explains facts and doesn't produce them. Code fetches the facts, and refuses unsafe
requests before the model sees them. Code then checks every citation and number in the reply. Any
failure, or a slow or missing model, leaves the template answer in place, and the reply says which
kind of answer it is.
"""

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.copilot.copilot import CopilotEngine, CopilotResponse, metric_observations
from app.copilot.guardrails import check_safety, verify_citations
from app.copilot.tools import (
    get_events_for_asset,
    get_maintenance_history,
    get_status,
    get_telemetry_summary,
    search_docs,
    search_service_cases,
)

log = logging.getLogger(__name__)

MAX_NEW_TOKENS = 300
MAX_SECONDS = 30.0
MAX_ITEMS = 5
MAX_FIELD_LENGTH = 300
ID_PATTERN = re.compile(r"\b[A-Z][A-Z0-9_]*(?:-[A-Z0-9_]+)*-\d+[A-Z0-9_]*\b|\bDOC-[A-Z0-9_-]+\b")
NUMBER_PATTERN = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
SAFETY_NOTE = "Follow site lockout/tagout procedures and permits (DOC-FIELD-SAFETY)."

PROMPT = """You help a field technician in an industrial plant. Answer the question using only the
facts below. Each fact starts with its ID in square brackets.

Rules:
- Use only these facts. If they don't answer the question, say what is missing.
- Copy numbers exactly as written. Don't calculate new numbers.
- In "answer", say only what was measured or recorded.
- In "hypotheses", give possible causes, worded with "may", and only ones these facts suggest. Don't
  say whether past work did or didn't fix anything. If nothing is wrong, leave it empty.
- If two facts disagree, such as on dates, say so instead of choosing one.
- model_confidence is about the diagnosis. mapping_confidence is about which physical object this
  record belongs to. Report them separately.
- Cite the ID of every fact you use.
- Never tell anyone to operate, start, stop, or change equipment. Suggest checks only.
- Use two to four short, plain sentences.

Facts:
{facts}

Question: {question}

Reply with JSON only:
{{"answer": "...", "hypotheses": ["..."], "citations": ["ID"]}}"""


class Writer(Protocol):
    def write(self, prompt: str) -> str: ...


@dataclass
class Fact:
    id: str
    text: str


class QwenWriter:
    """Runs a local Hugging Face chat model, with no network access."""

    def __init__(self, model_path: str) -> None:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self.torch = torch
        self.processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
        self.model = AutoModelForImageTextToText.from_pretrained(
            model_path, dtype="auto", device_map="cuda", local_files_only=True
        ).eval()
        self.lock = threading.Lock()

    def write(self, prompt: str) -> str:
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        inputs = self.processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
            enable_thinking=False,
        ).to(self.model.device)
        with self.lock, self.torch.inference_mode():
            output = self.model.generate(
                **inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=False, max_time=MAX_SECONDS
            )
        return self.processor.batch_decode(
            output[:, inputs["input_ids"].shape[1] :], skip_special_tokens=True
        )[0]


def load_writer() -> Writer | None:
    """Return the model named by COPILOT_MODEL. Without one, the copilot uses its templates."""
    path = os.getenv("COPILOT_MODEL")
    if not path:
        return None
    try:
        return QwenWriter(path)
    except Exception:
        log.exception("Couldn't load the copilot model, so using template answers")
        return None


def describe(record: dict[str, Any]) -> str:
    """Return a record's fields as short text."""
    parts = []
    for key, value in record.items():
        if value in (None, "", [], {}):
            continue
        parts.append(f"{key}: {str(value)[:MAX_FIELD_LENGTH]}")
    return "; ".join(parts)


def gather_facts(engine: CopilotEngine, tag: str) -> list[Fact]:
    """Fetch what's known about an asset, using the same tools as the template answers."""
    store = engine.store
    status = get_status(tag, store, engine.mapping)
    if not status:
        return []
    asset_id = status["asset_id"]
    quality = status.get("data_quality_issues") or []
    summary = {key: value for key, value in status.items() if key != "data_quality_issues"}
    facts = [Fact(asset_id, describe(summary))]
    facts += [Fact(issue["issue_id"], describe(issue)) for issue in quality]
    record = store.get_asset(asset_id)
    if record:
        dates = {
            "asset record, last_service_date": record.last_service_date,
            "service_interval_days": record.service_interval_days,
        }
        facts.append(Fact(asset_id, describe(dates)))
    metrics = get_telemetry_summary(tag, store, limit=20).get("metrics", {})
    facts += [Fact(asset_id, text) for text in metric_observations(metrics)]
    for event in get_events_for_asset(tag, store, limit=MAX_ITEMS):
        facts.append(Fact(event["event_id"], describe(event)))
    for order in get_maintenance_history(tag, store, limit=MAX_ITEMS):
        facts.append(Fact(_record_id(order), describe(order)))
    cases = search_service_cases(
        store, asset_class=status.get("asset_class"), issue_code=status.get("issue_code")
    )
    for case in cases[:MAX_ITEMS]:
        facts.append(Fact(case["case_id"], describe(case)))
    docs = search_docs(store, query=status.get("issue_code") or "", scope=status.get("asset_class"))
    for doc in docs[:MAX_ITEMS]:
        facts.append(Fact(doc["doc_id"], describe(doc)))
    return facts


def _record_id(record: dict[str, Any]) -> str:
    for key, value in record.items():
        if key.endswith("_id") and key != "asset_id" and value:
            return str(value)
    return str(record.get("asset_id", "RECORD"))


def _without_ids(text: str) -> str:
    return ID_PATTERN.sub(" ", text)


def _is_stated(written: str, known: list[float]) -> bool:
    """True if a written number matches a known one, allowing for rounding."""
    decimals = len(written.partition(".")[2])
    value = float(written)
    return any(round(number, decimals) == value for number in known)


def parse_reply(raw: str) -> dict[str, Any] | None:
    """Return the JSON object in a reply, or None."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        reply = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return reply if isinstance(reply, dict) else None


def check_reply(reply: dict[str, Any] | None, facts: list[Fact]) -> str | None:
    """Return why a reply can't be shown, or None if it passes every check."""
    if reply is None:
        return "not valid JSON"
    answer = reply.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return "no answer"
    hypotheses = reply.get("hypotheses") or []
    citations = reply.get("citations") or []
    if not isinstance(hypotheses, list) or not all(isinstance(h, str) for h in hypotheses):
        return "hypotheses aren't a list of text"
    if not isinstance(citations, list) or not all(isinstance(c, str) for c in citations):
        return "citations aren't a list of text"
    if not citations:
        return "no citations"
    known_ids = {fact.id for fact in facts}
    grounded = verify_citations(citations, known_ids)
    if not grounded.all_grounded:
        return f"citations not in the facts: {grounded.unverified_citations}"
    written = " ".join([answer, *hypotheses])
    for found in ID_PATTERN.findall(written):
        if found not in known_ids and found not in " ".join(fact.text for fact in facts):
            return f"names an ID not in the facts: {found}"
    known = [
        float(number)
        for fact in facts
        for number in NUMBER_PATTERN.findall(_without_ids(fact.text))
    ]
    for number in NUMBER_PATTERN.findall(_without_ids(written)):
        if not _is_stated(number, known):
            return f"number not in the facts: {number}"
    if not check_safety(written).passed:
        return "mentions operating equipment"
    return None


def explain(
    response: CopilotResponse, facts: list[Fact], question: str, writer: Writer | None
) -> tuple[CopilotResponse, dict[str, Any]]:
    """Return the response with the model's wording if it passes, and a note of what happened."""
    if writer is None:
        return response, {"answer_source": "template", "reason": "no model loaded"}
    if not facts:
        return response, {"answer_source": "template", "reason": "no facts for this question"}
    listing = "\n".join(f"[{fact.id}] {fact.text}" for fact in facts)
    started = time.perf_counter()
    try:
        raw = writer.write(PROMPT.format(facts=listing, question=question))
    except Exception as error:
        log.exception("The copilot model failed")
        return response, {"answer_source": "template", "reason": f"model failed: {error}"}
    seconds = round(time.perf_counter() - started, 1)
    reply = parse_reply(raw)
    problem = check_reply(reply, facts)
    if problem:
        log.warning("Rejected the model's answer: %s", problem)
        return response, {
            "answer_source": "template",
            "reason": problem,
            "model_seconds": seconds,
            "rejected": raw[:500],
        }
    response.answer = f"{reply['answer'].strip()} {SAFETY_NOTE}"
    response.hypotheses = reply.get("hypotheses") or response.hypotheses
    response.citations = list(dict.fromkeys([*reply["citations"], "DOC-FIELD-SAFETY"]))
    return response, {"answer_source": "model", "model_seconds": seconds}


def answer(
    engine: CopilotEngine, question: str, object_id: str | None, writer: Writer | None
) -> dict[str, Any]:
    """Answer through the template engine, then let the model explain it where that's safe."""
    response = engine.query(question, object_id=object_id)
    if writer is None:
        return {**response.to_dict(), "answer_source": "template", "reason": "no model loaded"}
    question_lower = question.lower()
    template_only = (
        not response.safety_passed
        or not response.focused_asset
        or not response.citations
        or engine._is_navigation_intent(question_lower)
    )
    if template_only:
        reason = "refused or nothing to explain"
        return {**response.to_dict(), "answer_source": "template", "reason": reason}
    facts = gather_facts(engine, response.focused_asset)
    explained, note = explain(response, facts, question, writer)
    return {**explained.to_dict(), **note}
