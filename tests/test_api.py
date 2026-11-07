import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.api.main import create_app  # noqa: E402


def box(object_id, center, mobility):
    low = [c - 0.5 for c in center]
    high = [c + 0.5 for c in center]
    return {
        "object_id": object_id,
        "label": "cart",
        "center": center,
        "bbox_min": low,
        "bbox_max": high,
        "mapping": None,
        "mobility": mobility,
    }


@pytest.fixture
def client(tmp_path):
    assets = [box("near", [1, 1, 0], "movable"), box("far", [9, 1, 0], "fixed")]
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "floor_y": 1.25, "assets": assets}))
    return TestClient(create_app(path))


def test_assets_and_missing_object(client):
    assert len(client.get("/api/assets").json()["assets"]) == 2
    assert client.get("/api/assets/near").json()["telemetry"] == []
    assert client.get("/api/assets/nope").status_code == 404


def test_nearby_uses_radius_and_sorts(client):
    found = client.get("/api/nearby", params={"x": 0, "y": 1, "z": 0, "radius": 3}).json()["assets"]
    assert [a["object_id"] for a in found] == ["near"]
    assert found[0]["distance"] == 0.5


def test_route_is_marked_placeholder(client):
    body = client.post("/api/route", json={"start": [0, 1.25, 0], "object_id": "far"}).json()
    assert body["placeholder"] is True
    assert body["path"][0] == [0, 1.25, 0]
    assert body["length"] == 9


def test_move_updates_box_and_is_logged(client):
    moved = {"op": "move", "object_id": "near", "position": [5, 1, 0]}
    assert client.post("/api/changes", json=moved).status_code == 200
    asset = client.get("/api/assets/near").json()
    assert asset["center"] == [5, 1, 0]
    assert asset["bbox_min"] == [4.5, 0.5, -0.5]
    assert len(client.get("/api/changes").json()["changes"]) == 1


def test_fixed_object_cannot_move(client):
    change = {"op": "move", "object_id": "far", "position": [5, 1, 0]}
    assert client.post("/api/changes", json=change).status_code == 409


def test_add_remove_and_reset(client):
    added = client.post("/api/changes", json={"op": "add", "position": [2, 1, 2]}).json()
    assert client.get(f"/api/assets/{added['object_id']}").json()["mapping"] is None
    assert (
        client.post("/api/changes", json={"op": "remove", "object_id": "near"}).status_code == 200
    )
    assert client.get("/api/assets/near").status_code == 404
    client.post("/api/changes/reset")
    ids = {a["object_id"] for a in client.get("/api/assets").json()["assets"]}
    assert ids == {"near", "far"}


def test_real_route_reroutes_when_a_movable_object_is_moved(tmp_path):
    import json

    np = pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    from app.nav.grid import build_nav_grid

    rng = np.random.default_rng(0)
    floor = rng.uniform([0, 0, 0], [6, 0, 6], (120000, 3))
    wall = rng.uniform([2.95, -1.8, 0], [3.05, -0.2, 4.8], (40000, 3))
    points = np.concatenate([floor, wall])
    grid = build_nav_grid(points, np.ones(len(points)), (0, -1, 0), floor_height=0.0)
    box = {"label_confidence": 0.5, "mapping": None}
    assets = [
        {
            **box,
            "object_id": "pump",
            "label": "pump",
            "center": [5.2, -0.5, 1.2],
            "bbox_min": [5.0, 0.0, 1.0],
            "bbox_max": [5.4, -1.0, 1.4],
            "mobility": "fixed",
        },
        {
            **box,
            "object_id": "cart",
            "label": "cart",
            "center": [3.0, -0.5, 5.3],
            "bbox_min": [2.5, 0.0, 4.6],
            "bbox_max": [3.5, -1.0, 6.0],
            "mobility": "movable",
        },
    ]
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "floor_y": 0.0, "assets": assets}))
    client = TestClient(create_app(path, grid=grid))
    request = {"start": [1.0, 0.0, 1.0], "object_id": "pump"}
    blocked = client.post("/api/route", json=request)
    assert blocked.status_code == 409
    assert "closest reachable floor" in blocked.json()["detail"]
    moved = client.post(
        "/api/changes", json={"op": "move", "object_id": "cart", "position": [0.5, -0.5, 5.3]}
    )
    assert moved.status_code == 200
    route = client.post("/api/route", json=request)
    assert route.status_code == 200
    assert route.json()["placeholder"] is False
    assert route.json()["stop_distance"] < 0.8
