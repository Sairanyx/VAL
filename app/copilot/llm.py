"""Let a local language model explain the copilot's facts in plain language.

The model explains facts and doesn't produce them. Code fetches the facts, and refuses unsafe
requests before the model sees them. Code then checks every citation and number in the reply. Any
failure, or a slow or missing model, leaves the template answer in place, and the reply says which
kind of answer it is.
"""

import base64
import io
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
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
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_SECONDS = 60.0  # a laptop's CPU is much slower than a GPU
OLLAMA_CONTEXT = 4096
OLLAMA_MAX_FACTS = 12  # reading the facts is most of the wait on a CPU
MIN_ANSWER_WORDS = 4
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

    def look(self, image: Any, prompt: str) -> str: ...


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
        return self._reply([{"type": "text", "text": prompt}])

    def look(self, image: Any, prompt: str) -> str:
        """Answer a question about an image."""
        return self._reply([{"type": "image", "image": image}, {"type": "text", "text": prompt}])

    def _reply(self, content: list[dict[str, Any]]) -> str:
        messages = [{"role": "user", "content": content}]
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


class OllamaWriter:
    """Runs a small model through a local Ollama, for laptops with no GPU."""

    max_facts = OLLAMA_MAX_FACTS

    def __init__(self, model: str, url: str = OLLAMA_URL, seconds: float = OLLAMA_SECONDS) -> None:
        self.model = model
        self.url = url
        self.seconds = seconds
        # Answers wait for the model to load unless it's already there, so load it now.
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        """Ask Ollama to load the model. If it's slow or not running, the first answer waits."""
        try:
            self._post({"model": self.model, "keep_alive": -1})
        except OSError:  # timeouts and refused connections
            log.info("The model is still loading, so the first answer may be slower")

    def _post(self, body: dict[str, Any]) -> str:
        request = urllib.request.Request(
            f"{self.url}/api/generate",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.seconds) as reply:
            return json.loads(reply.read()).get("response", "")

    def _generate(self, prompt: str, images: list[str] | None = None) -> str:
        options = {"temperature": 0, "num_predict": MAX_NEW_TOKENS, "num_ctx": OLLAMA_CONTEXT}
        body: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "think": False,
            "keep_alive": -1,
            "options": options,
        }
        if images:
            body["images"] = images
        return self._post(body)

    def write(self, prompt: str) -> str:
        return self._generate(prompt)

    def look(self, image: Any, prompt: str) -> str:
        """Answer a question about an image. Not every small model can see, so this may fail."""
        buffer = io.BytesIO()
        image.save(buffer, "JPEG")
        return self._generate(prompt, [base64.b64encode(buffer.getvalue()).decode()])


def load_writer() -> Writer | None:
    """Return the COPILOT_OLLAMA or COPILOT_MODEL model. Without one, Val uses its templates."""
    small = os.getenv("COPILOT_OLLAMA")
    if small:
        return OllamaWriter(small)
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


def clean_citations(citations: Any) -> Any:
    """Accept citations written as they're shown in the facts, such as "[CASE-025]"."""
    if not isinstance(citations, list):
        return citations
    return [c.strip().strip("[]") if isinstance(c, str) else c for c in citations]


def fewer_facts(facts: list[Fact], limit: int) -> list[Fact]:
    """Keep a share of each kind of fact, so any question still has something to go on.

    The order never depends on the question, so a model can reuse what it has already read.
    """
    if len(facts) <= limit:
        return facts
    kinds: dict[str, list[Fact]] = {}
    for fact in facts:
        kinds.setdefault(fact.id.split("-")[0], []).append(fact)
    kept: set[int] = set()
    while len(kept) < limit:
        for group in kinds.values():
            if group and len(kept) < limit:
                kept.add(id(group.pop(0)))
    return [fact for fact in facts if id(fact) in kept]


def real_words(text: str) -> int:
    """Count an answer's words, leaving out IDs, as a reply can be nothing but a citation."""
    return len(re.findall(r"[A-Za-z]{2,}", ID_PATTERN.sub(" ", re.sub(r"\[[^\]]*\]", " ", text))))


def check_reply(reply: dict[str, Any] | None, facts: list[Fact]) -> str | None:
    """Return why a reply can't be shown, or None if it passes every check."""
    if reply is None:
        return "not valid JSON"
    answer = reply.get("answer")
    if not isinstance(answer, str) or real_words(answer) < MIN_ANSWER_WORDS:
        return "no answer"
    hypotheses = reply.get("hypotheses") or []
    citations = clean_citations(reply.get("citations") or [])
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
    facts = fewer_facts(facts, getattr(writer, "max_facts", len(facts)))
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
    cited = clean_citations(reply["citations"])
    response.citations = list(dict.fromkeys([*cited, "DOC-FIELD-SAFETY"]))
    return response, {"answer_source": "model", "model_seconds": seconds}


def service_date_note(last_service_date: str | None, opened_dates: list[str]) -> str | None:
    """Return a note when the asset record and its work orders disagree on the last service.

    Written by code, because a model asked to report this merged the two into one wrong event.
    """
    if not last_service_date or not opened_dates:
        return None
    recorded, newest = last_service_date[:10], max(opened_dates)[:10]
    if recorded == newest:
        return None
    return (
        f"Records disagree: the asset record says last serviced {recorded}, "
        f"but the newest work order is from {newest}."
    )


def warm_up(engine: CopilotEngine, writer: Writer | None) -> None:
    """Have a slow model read the fault's facts now, as it can reuse them for the first question."""
    if not hasattr(writer, "max_facts"):
        return

    def read() -> None:
        try:
            facts = fewer_facts(gather_facts(engine, engine.fault_tag), writer.max_facts)
            listing = "\n".join(f"[{fact.id}] {fact.text}" for fact in facts)
            writer.write(
                PROMPT.format(facts=listing, question=f"Why is {engine.fault_tag} flagged?")
            )
        except Exception:
            log.warning("Couldn't warm up the model, so its first answer will be slower")

    threading.Thread(target=read, daemon=True).start()


def can_reword(engine: CopilotEngine, reply: dict[str, Any], question: str) -> bool:
    """Return whether a model could put this answer in plain words."""
    return bool(
        reply.get("safety_passed")
        and reply.get("focused_asset")
        and reply.get("citations")
        and not engine._is_navigation_intent(question.lower())
    )


def answer(
    engine: CopilotEngine, question: str, object_id: str | None, writer: Writer | None
) -> dict[str, Any]:
    """Answer through the template engine, then let the model explain it where that's safe."""
    response = engine.query(question, object_id=object_id)
    if writer is None:
        return {**response.to_dict(), "answer_source": "template", "reason": "no model loaded"}
    question_lower = question.lower()
    if not can_reword(engine, response.to_dict(), question):
        reason = "refused or nothing to explain"
        return {**response.to_dict(), "answer_source": "template", "reason": reason}
    if "servic" in question_lower or "maintenance" in question_lower:
        record = engine.store.get_asset(response.focused_asset)
        orders = get_maintenance_history(response.focused_asset, engine.store, limit=100)
        opened = [order["opened_at"] for order in orders if order.get("opened_at")]
        disagreement = service_date_note(record.last_service_date if record else None, opened)
        if disagreement:
            response.observations = [disagreement, *response.observations]
    facts = gather_facts(engine, response.focused_asset)
    explained, note = explain(response, facts, question, writer)
    return {**explained.to_dict(), **note}
