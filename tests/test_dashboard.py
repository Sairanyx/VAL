import json
from datetime import datetime, timedelta

import pytest

pytest.importorskip("matplotlib")

from app.copilot.store import (  # noqa: E402
    Asset,
    CurrentState,
    DataQualityIssue,
    DataStore,
    Event,
    TelemetryPoint,
    WorkOrder,
)
from app.dashboard import link_note, render_dashboard, trend_note  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n"


def store_with(asset_class="PROCESS_PUMP", tag="P-005", last_service="2025-01-01"):
    store = DataStore()
    asset = Asset(
        asset_id="ASSET-1",
        tag=tag,
        asset_class=asset_class,
        area_id="A",
        area_name="Utility",
        process_context="",
        criticality="A",
        installation_date="2017-10-04",
        last_service_date=last_service,
        service_interval_days=365,
    )
    store.assets_by_id[asset.asset_id] = asset
    store.assets_by_tag[tag] = asset
    store.states_by_id[asset.asset_id] = CurrentState(
        asset_id=asset.asset_id,
        tag=tag,
        asset_class=asset_class,
        area_name="Utility",
        criticality="A",
        health_score=44,
        condition_state="attention_required",
        issue_code="FOULING",
        issue_summary="Efficiency loss",
        urgency="high",
        last_updated="2026-10-08T07:29:00",
    )
    start = datetime(2026, 10, 5)
    store.telemetry_by_id[asset.asset_id] = [
        TelemetryPoint(
            timestamp=(start + timedelta(minutes=30 * i)).isoformat(),
            asset_id=asset.asset_id,
            tag=tag,
            asset_class=asset_class,
            area_id="A",
            metrics={
                "motor_current_a": 40 + i / 16,
                "position_setpoint_pct": 50.0,
                "position_actual_pct": 52.0,
            },
        )
        for i in range(144)
    ]
    store.events_by_id[asset.asset_id] = [
        Event(
            event_id=f"E{i}",
            timestamp=f"2026-10-0{i + 1}T10:00:00",
            asset_id=asset.asset_id,
            tag=tag,
            area_name="Utility",
            event_type="DIAGNOSTIC_ALERT",
            severity="high",
            event_code="X",
            description="",
            source="",
            status="open" if i else "closed",
        )
        for i in range(3)
    ]
    store.maintenance_by_id[asset.asset_id] = [
        WorkOrder(
            work_order_id="W1",
            asset_id=asset.asset_id,
            tag=tag,
            area_name="Utility",
            opened_at="2026-03-01T08:00:00",
            action="",
            maintenance_type="corrective",
            priority="",
            result="",
            duration_h=4,
            downtime_h=1.5,
        )
    ]
    store.data_quality_by_id[asset.asset_id] = [
        DataQualityIssue(
            issue_id="Q1",
            asset_id=asset.asset_id,
            tag=tag,
            issue_type="timestamp_jitter",
            severity="low",
            source_sheet="",
            recommended_handling="",
        )
    ]
    return store


@pytest.mark.parametrize(
    "asset_class", ["PROCESS_PUMP", "CONTROL_VALVE", "PRESSURE_TRANSMITTER", "OTHER"]
)
def test_every_kind_of_equipment_draws(asset_class):
    image = render_dashboard(store_with(asset_class), "P-005")
    assert image.startswith(PNG) and len(image) > 20_000


def test_record_without_readings_still_draws():
    store = store_with()
    store.telemetry_by_id.clear()
    store.events_by_id.clear()
    store.maintenance_by_id.clear()
    store.states_by_id.clear()
    assert render_dashboard(store, "ASSET-1").startswith(PNG)


def test_unknown_record_is_refused():
    with pytest.raises(KeyError):
        render_dashboard(store_with(), "NOPE-1")


def test_links_by_rule_are_never_shown_as_confirmed():
    text, _ = link_note({"object_id": "obj-1", "method": "procedural_class", "confidence": 0.15})
    assert "Not a confirmed identity" in text and "obj-1" in text
    text, _ = link_note({"object_id": "obj-2", "method": "manual_visual_unconfirmed"})
    assert "Not a confirmed identity" in text
    text, _ = link_note({"object_id": "obj-3", "method": "qr_scan", "confidence": 1.0})
    assert "Not a confirmed" not in text


def test_trend_compares_first_and_last_twelve_hours():
    assert (
        trend_note([40.0] * 24 + [45.0] * 96 + [48.0] * 24) == "first 12 h 40 → last 12 h 48 (+20%)"
    )
    assert trend_note([1.0] * 48) == "flat"
    assert trend_note([1.0] * 10) == ""


def test_api_serves_dashboards_only_for_linked_objects(tmp_path):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    pytest.importorskip("psycopg")
    from fastapi.testclient import TestClient

    from app.api.main import create_app

    def box(object_id, mapping):
        return {
            "object_id": object_id,
            "label": "pump",
            "center": [0, 0, 0],
            "bbox_min": [-1] * 3,
            "bbox_max": [1] * 3,
            "mapping": mapping,
            "mobility": "fixed",
        }

    link = {"asset_id": "ASSET-1", "tag": "P-005", "method": "procedural_class", "confidence": 0.15}
    gone = {**link, "asset_id": "ASSET-404"}
    path = tmp_path / "assets.json"
    assets = [box("linked", link), box("plain", None), box("stale", gone)]
    path.write_text(json.dumps({"scene_id": "t", "assets": assets}))

    class Engine:
        store = store_with()

    client = TestClient(create_app(path, engine=Engine()))
    reply = client.get("/api/assets/linked/dashboard.png")
    assert reply.status_code == 200 and reply.headers["content-type"] == "image/png"
    assert reply.content.startswith(PNG)
    assert client.get("/api/assets/plain/dashboard.png").status_code == 404
    assert client.get("/api/assets/stale/dashboard.png").status_code == 404
    assert client.get("/api/assets/missing/dashboard.png").status_code == 404
