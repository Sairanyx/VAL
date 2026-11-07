"""Tests for the copilot Excel data store, fixtures, and asset merging."""

from pathlib import Path

import pytest

from app.copilot.store import (
    DataStore,
    join_asset_detail,
    load_mapping,
    load_sample_assets,
)


@pytest.fixture(scope="module")
def store():
    data_files = list(Path("data").glob("*.xlsx"))
    if not data_files:
        pytest.skip("No Excel builder pack found in data/")
    return DataStore.load()


def test_asset_master_loaded(store):
    assets = store.list_assets()
    assert len(assets) == 30

    pump = store.get_asset("P-005")
    assert pump is not None
    assert pump.asset_id == "ASSET-017"
    assert pump.tag == "P-005"
    assert pump.asset_class == "PROCESS_PUMP"
    assert pump.area_name == "Utility Island"
    assert "critical" in pump.criticality.lower()


def test_target_faulty_pump(store):
    asset, state = store.get_faulty_target()
    assert asset is not None
    assert state is not None
    assert asset.tag == "P-005"
    assert state.tag == "P-005"
    assert state.health_score == 44
    assert state.condition_state == "attention_required"
    assert state.issue_code == "FOULING"
    assert state.urgency == "high"
    assert state.knowledge_doc_id == "DOC-PROCESS_PUMP-CORE"


def test_telemetry_loaded(store):
    telemetry = store.get_telemetry("P-005", limit=20)
    assert len(telemetry) > 0
    first = telemetry[0]
    assert first.asset_id == "ASSET-017"
    assert first.tag == "P-005"


def test_events_and_alarms(store):
    events = store.get_events("P-005", limit=10)
    assert len(events) > 0
    assert any(e.event_code == "FOULING" for e in events)


def test_maintenance_history(store):
    history = store.get_maintenance("P-005")
    assert len(history) > 0
    assert any("WO-" in wo.work_order_id for wo in history)


def test_knowledge_docs_and_guidelines(store):
    # Verify mandatory rules mentioned in docs/CHALLENGE.md
    rag_guide = store.get_doc("DOC-RAG-GUIDE")
    assert rag_guide is not None
    assert "confidence" in rag_guide.content.lower()

    safety = store.get_doc("DOC-FIELD-SAFETY")
    assert safety is not None
    assert "safety" in safety.title.lower()
    assert "verification" in safety.content.lower()

    mapping_doc = store.get_doc("DOC-3D-MAPPING")
    assert mapping_doc is not None
    assert "confidence" in mapping_doc.content.lower()

    pump_doc = store.get_doc("DOC-PROCESS_PUMP-CORE")
    assert pump_doc is not None
    assert "PROCESS_PUMP" in pump_doc.scope


def test_fixtures_and_join():
    sample_assets = load_sample_assets("fixtures/copilot_assets.json")
    mapping = load_mapping("fixtures/mapping.json")

    assert len(sample_assets) >= 15
    assert len(mapping) >= 15

    # Target faulty pump obj_005
    assert "obj_005" in mapping
    assert mapping["obj_005"]["tag"] == "P-005"
    assert mapping["obj_005"]["asset_id"] == "ASSET-017"

    # Unmapped clutter / obstacle obj_015, obj_016
    assert mapping["obj_015"]["asset_id"] is None
    assert mapping["obj_016"]["asset_id"] is None


def test_join_asset_detail_mapped(store):
    sample_assets = load_sample_assets("fixtures/copilot_assets.json")
    mapping = load_mapping("fixtures/mapping.json")

    detail = join_asset_detail("obj_005", sample_assets, mapping, store)
    assert detail is not None
    assert detail["object_id"] == "obj_005"
    assert detail["mapping"]["tag"] == "P-005"
    assert detail["current_state"]["health_score"] == 44
    assert detail["current_state"]["issue_code"] == "FOULING"
    assert len(detail["recent_events"]) > 0
    assert len(detail["documents"]) > 0


def test_join_asset_detail_unmapped(store):
    sample_assets = load_sample_assets("fixtures/copilot_assets.json")
    mapping = load_mapping("fixtures/mapping.json")

    detail = join_asset_detail("obj_015", sample_assets, mapping, store)
    assert detail is not None
    assert detail["object_id"] == "obj_015"
    assert detail["mapping"]["asset_id"] is None
    assert detail["asset_record"] is None
    assert detail["current_state"] is None
