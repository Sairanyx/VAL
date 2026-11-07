"""Connect the API's scene objects to Hannu's copilot and Excel data store."""

from dataclasses import asdict
from typing import Any

from app.copilot.copilot import CopilotEngine
from app.copilot.llm import Writer, answer
from app.copilot.store import DataStore

RECENT = 20


def load_engine() -> CopilotEngine | None:
    """Return the copilot, or None if the Excel pack isn't in data/."""
    try:
        store = DataStore.load()
    except FileNotFoundError:
        return None
    return CopilotEngine(store=store, sample_assets=[], mapping={})


def copilot_assets(assets: list[dict]) -> list[dict[str, Any]]:
    """Convert scene objects to the shape the copilot reads."""
    return [
        {
            "object_id": asset["object_id"],
            "label": asset.get("label", "object"),
            "name": asset.get("name"),
            "copied_name": asset.get("copied_name"),
            "mobility": asset.get("mobility"),
            "confidence": asset.get("label_confidence", 0.0),
            "center": asset["center"],
            "box": {"min": asset["bbox_min"], "max": asset["bbox_max"]},
        }
        for asset in assets
    ]


def copilot_mapping(assets: list[dict], store: DataStore) -> dict[str, dict[str, Any]]:
    """Return the copilot's mapping, indexed by object, from each object's `mapping`."""
    mapping = {}
    for asset in assets:
        link = asset.get("mapping")
        if not link:
            continue
        record = store.get_asset(link.get("asset_id") or link.get("tag") or "")
        mapping[asset["object_id"]] = {
            **link,
            "object_id": asset["object_id"],
            "asset_class": record.asset_class if record else None,
            "notes": link.get("note", ""),
        }
    return mapping


def ask(
    engine: CopilotEngine,
    assets: list[dict],
    question: str,
    object_id: str | None,
    writer: Writer | None = None,
) -> dict:
    """Answer from the current scene, so moved objects and new links are always included."""
    engine.sample_assets = copilot_assets(assets)
    engine.mapping = copilot_mapping(assets, engine.store)
    if object_id and object_id not in engine.mapping:
        # A detected object with no record mustn't inherit the previous machine's identity.
        engine.focused_asset_tag = None
        engine.focused_object_id = object_id
    return answer(engine, question, object_id, writer)


def condition(asset: dict, store: DataStore) -> dict[str, Any] | None:
    """Return an object's current state from the Excel pack, if it has a record."""
    link = asset.get("mapping")
    state = store.get_current_state(link.get("asset_id") or "") if link else None
    return asdict(state) if state else None


def details(asset: dict, store: DataStore) -> dict[str, Any]:
    """Return an object's record and evidence from the Excel pack, empty if it has none."""
    link = asset.get("mapping") or {}
    record = store.get_asset(link.get("asset_id") or "") if link else None
    if record is None:
        return {
            "record": None,
            "telemetry": [],
            "events": [],
            "maintenance": [],
            "documents": [],
        }
    return {
        "record": asdict(record),
        "telemetry": [asdict(p) for p in store.get_telemetry(record.asset_id, limit=RECENT)],
        "events": [asdict(e) for e in store.get_events(record.asset_id, limit=RECENT)],
        "maintenance": [asdict(w) for w in store.get_maintenance(record.asset_id)],
        "documents": [asdict(d) for d in store.list_docs(scope=record.asset_class)],
    }
