import json
import math

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("psycopg")

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


def test_route_uses_floor_map_when_present(tmp_path):
    np = pytest.importorskip("numpy")
    floor = tmp_path / "nav_grid.npz"
    open_floor = np.full((200, 200), 2.0, dtype=np.float32)
    np.savez(
        floor,
        origin=np.array([-1.0, -5.0]),
        cell=0.05,
        floor_height=-1.25,
        up=np.array([0.0, -1.0, 0.0]),
        axes=np.array([0, 2]),
        free=open_floor > 0,
        clearance=open_floor,
        clearance_low=open_floor,
    )
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "assets": [box("far", [7, 1, 0], "fixed")]}))
    client = TestClient(create_app(path, floor))
    body = client.post("/api/route", json={"start": [0, 1.25, 0], "object_id": "far"}).json()
    assert body["placeholder"] is False
    assert body["path"][0][1] == 1.25


def test_move_updates_box_and_is_logged(client):
    moved = {"op": "move", "object_id": "near", "position": [5, 1, 0]}
    assert client.post("/api/changes", json=moved).status_code == 200
    asset = client.get("/api/assets/near").json()
    assert asset["center"] == [5, 1, 0]
    assert asset["bbox_min"] == [4.5, 0.5, -0.5]
    assert len(client.get("/api/changes").json()["changes"]) == 1


def test_rotate_updates_yaw_and_bounds(client):
    rotated = {"op": "rotate", "object_id": "near", "yaw": math.pi / 2}
    assert client.post("/api/changes", json=rotated).status_code == 200
    asset = client.get("/api/assets/near").json()
    assert asset["yaw"] == round(math.pi / 2, 4)
    assert asset["bbox_min"] == [0.5, 0.5, -0.5]
    assert asset["bbox_max"] == [1.5, 1.5, 0.5]


def test_move_and_rotate_together(client):
    change = {"op": "move", "object_id": "near", "position": [3, 1, 2], "yaw": math.pi / 4}
    assert client.post("/api/changes", json=change).status_code == 200
    asset = client.get("/api/assets/near").json()
    assert asset["center"] == [3, 1, 2]
    assert asset["yaw"] == round(math.pi / 4, 4)
    expected_hw = round(0.5 * math.cos(math.pi / 4) + 0.5 * math.sin(math.pi / 4), 3)
    assert asset["bbox_min"] == [round(3 - expected_hw, 3), 0.5, round(2 - expected_hw, 3)]
    assert asset["bbox_max"] == [round(3 + expected_hw, 3), 1.5, round(2 + expected_hw, 3)]


def test_fixed_object_cannot_move(client):
    change = {"op": "move", "object_id": "far", "position": [5, 1, 0]}
    assert client.post("/api/changes", json=change).status_code == 409


def test_fixed_object_cannot_rotate(client):
    change = {"op": "rotate", "object_id": "far", "yaw": 1.0}
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


class FakeResponse:
    def __init__(self, question):
        self.question = question

    def to_dict(self):
        return {"answer": self.question, "citations": ["DOC-1"], "confidence": 0.5}


class FakeStore:
    def get_asset(self, _):
        return None

    def get_current_state(self, _):
        return None


class FakeEngine:
    def __init__(self):
        self.store = FakeStore()
        self.focused_asset_tag = "P-005"
        self.focused_object_id = "old"
        self.sample_assets = []
        self.mapping = {}

    def query(self, question, object_id=None):
        return FakeResponse(question)


def test_copilot_uses_scene_and_clears_old_focus(tmp_path):
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "assets": [box("near", [1, 1, 0], "fixed")]}))
    engine = FakeEngine()
    client = TestClient(create_app(path, engine=engine))
    body = client.post(
        "/api/copilot/query", json={"question": "What is this?", "object_id": "near"}
    ).json()
    assert body["placeholder"] is False
    assert body["citations"] == ["DOC-1"]
    assert engine.sample_assets[0]["box"]["min"] == [0.5, 0.5, -0.5]
    assert engine.focused_asset_tag is None


def test_home_redirects_to_docs(client):
    assert client.get("/", follow_redirects=False).headers["location"] == "/docs"


class FakeDatabase:
    """Stands in for TimescaleDB, keeping changes between app starts."""

    def __init__(self):
        self.changes = []
        self.down = False

    def save_change(self, scene_id, change):
        if self.down:
            return False
        self.changes.append(change)
        return True

    def ping(self):
        return not self.down

    def load_changes(self, scene_id):
        return list(self.changes)

    def clear_changes(self, scene_id):
        self.changes = []

    def telemetry(self, asset_id, limit=20):
        return []


def test_changes_survive_restart_and_reset_clears_them(tmp_path):
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "assets": [box("near", [1, 1, 0], "movable")]}))
    database = FakeDatabase()
    client = TestClient(create_app(path, database=database))
    change = {"op": "move", "object_id": "near", "position": [5, 1, 0], "yaw": 1.57}
    assert client.post("/api/changes", json=change).status_code == 200
    restarted = TestClient(create_app(path, database=database))
    assert restarted.get("/api/assets/near").json()["center"] == [5, 1, 0]
    assert restarted.get("/api/assets/near").json()["yaw"] == 1.57
    assert restarted.post("/api/changes/reset").status_code == 200
    again = TestClient(create_app(path, database=database))
    assert again.get("/api/assets/near").json()["center"] == [1, 1, 0]
    assert again.get("/api/assets/near").json()["yaw"] == 0.0


def test_health_says_what_is_connected(client):
    assert client.get("/api/health").json()["objects"] == 2


def test_changes_made_while_database_is_down_save_later(tmp_path):
    path = tmp_path / "assets.json"
    assets = [box("a", [1, 1, 0], "movable"), box("b", [3, 1, 0], "movable")]
    path.write_text(json.dumps({"scene_id": "t", "assets": assets}))
    database = FakeDatabase()
    client = TestClient(create_app(path, database=database))
    database.down = True
    first = {"op": "move", "object_id": "a", "position": [5, 1, 0]}
    reply = client.post("/api/changes", json=first)
    assert reply.status_code == 200
    assert reply.json()["saved"] is False
    assert client.get("/api/assets/a").json()["center"] == [5, 1, 0]
    health = client.get("/api/health").json()
    assert health["database"] is False
    assert health["unsaved_changes"] == 1
    database.down = False
    second = {"op": "move", "object_id": "b", "position": [6, 1, 0]}
    assert client.post("/api/changes", json=second).json()["saved"] is True
    assert [c["object_id"] for c in database.changes] == ["a", "b"]


def open_floor(tmp_path):
    np = pytest.importorskip("numpy")
    pytest.importorskip("scipy")
    path = tmp_path / "nav_grid.npz"
    free = np.ones((120, 40), dtype=bool)
    free[[0, -1], :] = free[:, [0, -1]] = False
    clearance = (
        np.minimum.reduce(
            [
                np.arange(120)[:, None] * np.ones(40),
                (119 - np.arange(120))[:, None] * np.ones(40),
                np.arange(40)[None, :] * np.ones((120, 1)),
                (39 - np.arange(40))[None, :] * np.ones((120, 1)),
            ]
        )
        * 0.05
    )
    np.savez(
        path,
        origin=np.array([0.0, 0.0]),
        cell=0.05,
        floor_height=0.0,
        up=np.array([0.0, -1.0, 0.0]),
        axes=np.array([0, 2]),
        free=free,
        clearance=clearance,
        clearance_low=clearance,
    )
    return path


def test_route_preview_blocks_without_saving_the_move(tmp_path):
    assets = [box("target", [5.5, -0.5, 1.0], "fixed"), box("cart", [0.6, -0.5, 1.0], "movable")]
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "assets": assets}))
    client = TestClient(create_app(path, open_floor(tmp_path), database=FakeDatabase()))
    request = {"start": [2.0, 0.0, 1.0], "object_id": "target"}
    clear = client.post("/api/route", json=request).json()["length"]
    wall = {"object_id": "cart", "position": [3.0, -0.5, 1.0]}
    blocked = client.post("/api/route", json={**request, "preview": wall})
    assert blocked.status_code == 409 or blocked.json()["length"] > clear
    assert client.get("/api/assets/cart").json()["center"] == [0.6, -0.5, 1.0]
    assert client.get("/api/changes").json()["changes"] == []
    assert client.post("/api/route", json=request).json()["length"] == clear


def test_route_says_how_many_changes_the_backend_holds(tmp_path):
    """The viewer compares this with what it sent, to notice a backend that has lost its moves."""
    assets = [box("target", [5.5, -0.5, 1.0], "fixed"), box("cart", [0.6, -0.5, 1.0], "movable")]
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "assets": assets}))
    client = TestClient(create_app(path, open_floor(tmp_path), database=FakeDatabase()))
    request = {"start": [2.0, 0.0, 1.0], "object_id": "target"}
    assert client.post("/api/route", json=request).json()["changes"] == 0
    move = {"op": "move", "object_id": "cart", "position": [0.6, -0.5, 1.5]}
    assert client.post("/api/changes", json=move).json()["change_id"] == 1
    assert client.post("/api/route", json=request).json()["changes"] == 1
    client.post("/api/changes/reset")
    assert client.post("/api/route", json=request).json()["changes"] == 0


def test_placeholder_route_says_how_many_changes_the_backend_holds(client):
    request = {"start": [0, 0, 0], "object_id": "near"}
    assert client.post("/api/route", json=request).json()["changes"] == 0


def test_turning_into_another_object_is_refused(tmp_path):
    long_cart = box("cart", [1, 1, 0], "movable")
    long_cart["bbox_min"], long_cart["bbox_max"] = [-0.8, 0.5, -0.1], [2.8, 1.5, 0.1]
    other = box("crate", [1, 1, 1.2], "fixed")
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "assets": [long_cart, other]}))
    client = TestClient(create_app(path, database=FakeDatabase()))
    straight = {"position": [1, 1, 0], "yaw": 0}
    assert client.post("/api/objects/cart/check-move", json=straight).json()["ok"] is True
    turned = {"position": [1, 1, 0], "yaw": math.pi / 2}
    check = client.post("/api/objects/cart/check-move", json=turned).json()
    assert check["ok"] is False
    assert check["blockers"] == ["crate"]
    rotate = {"op": "rotate", "object_id": "cart", "yaw": math.pi / 2}
    assert client.post("/api/changes", json=rotate).status_code == 409
    assert client.get("/api/assets/cart").json()["yaw"] == 0


def test_viewer_commands_reach_the_viewer_once_and_report_back(client):
    assert client.get("/api/viewer/commands").json() == {"last_id": 0, "commands": []}
    sent = client.post(
        "/api/viewer/commands", json={"action": "route_to", "args": {"object_id": "near"}}
    ).json()
    assert client.get("/api/viewer/commands").json()["commands"] == []
    found = client.get("/api/viewer/commands", params={"after": 0}).json()["commands"]
    assert [c["id"] for c in found] == [sent["id"]]
    assert client.get("/api/viewer/commands", params={"after": sent["id"]}).json()["commands"] == []
    client.post(f"/api/viewer/commands/{sent['id']}/result", json={"ok": True})
    assert client.get(f"/api/viewer/commands/{sent['id']}").json()["result"]["ok"] is True


@pytest.mark.parametrize(
    "command",
    [
        {"action": "explode"},
        {"action": "route_to"},
        {"action": "set_range", "args": {"metres": "far"}},
        {"action": "move_object", "args": {"object_id": "near", "position": [1, 2]}},
    ],
)
def test_bad_viewer_commands_are_refused(client, command):
    assert client.post("/api/viewer/commands", json=command).status_code == 422


def test_every_viewer_action_is_listed_with_what_it_needs(client):
    actions = client.get("/api/viewer/actions").json()["actions"]
    assert {"route_to", "move_object", "rotate_object", "undo_changes"} <= set(actions)
    assert all("does" in spec and "args" in spec for spec in actions.values())


def test_anything_can_be_deleted_and_undo_brings_it_back(client):
    assert client.post("/api/changes", json={"op": "remove", "object_id": "far"}).status_code == 200
    assert all(a["object_id"] != "far" for a in client.get("/api/assets").json()["assets"])
    client.post("/api/changes/reset")
    assert any(a["object_id"] == "far" for a in client.get("/api/assets").json()["assets"])


def test_a_duplicate_is_the_same_object_elsewhere_without_the_record_link(tmp_path):
    source = box("pump", [1, 1, 0], "movable")
    source["label"] = "pump"
    source["mapping"] = {"tag": "P-005", "asset_id": "A", "method": "manual", "confidence": 0.3}
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "assets": [source]}))
    client = TestClient(create_app(path, database=FakeDatabase()))
    change = {"op": "duplicate", "object_id": "pump", "position": [3, 1, 0]}
    made = client.post("/api/changes", json=change).json()["parts"]
    copy = client.get(f"/api/assets/{made[0]}").json()
    assert copy["label"] == "pump" and copy["center"] == [3, 1, 0]
    assert copy["mapping"] is None and copy["duplicated_from"] == "pump"
    assert client.get("/api/assets/pump").json()["mapping"]["tag"] == "P-005"
    second = {"op": "duplicate", "object_id": copy["object_id"], "position": [5, 1, 0]}
    again = client.post("/api/changes", json=second).json()["parts"][0]
    assert again != copy["object_id"]
    assert client.get(f"/api/assets/{again}").json()["duplicated_from"] == "pump"
    split = {"op": "split", "object_id": copy["object_id"], "details": {}}
    assert client.post("/api/changes", json=split).status_code == 409
    client.post("/api/changes/reset")
    assert all(
        a["object_id"] != copy["object_id"] for a in client.get("/api/assets").json()["assets"]
    )


def test_a_copy_has_its_own_id_and_the_operator_can_name_it(tmp_path):
    source = box("pump", [1, 1, 0], "movable")
    source["mapping"] = {"tag": "P-005", "asset_id": "A", "method": "manual", "confidence": 0.3}
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "assets": [source]}))
    client = TestClient(create_app(path, database=FakeDatabase()))
    change = {"op": "duplicate", "object_id": "pump", "position": [3, 1, 0]}
    copy_id = client.post("/api/changes", json=change).json()["parts"][0]
    assert copy_id != "pump"
    assert client.get(f"/api/assets/{copy_id}").json()["name"] == "P-005 copy 1"

    def rename(object_id, name):
        change = {"op": "rename", "object_id": object_id, "details": {"name": name}}
        return client.post("/api/changes", json=change).status_code

    assert rename(copy_id, "  Spare pump ") == 200
    assert client.get(f"/api/assets/{copy_id}").json()["name"] == "Spare pump"
    assert rename(copy_id, "p-005") == 409  # A record's tag would look like that device.
    assert rename(copy_id, "   ") == 409
    assert rename("pump", "Something else") == 409  # Its record names it.


def test_undo_takes_back_only_the_latest_change(client):
    first = {"op": "move", "object_id": "near", "position": [2, 1, 0]}
    second = {"op": "move", "object_id": "near", "position": [3, 1, 0]}
    client.post("/api/changes", json=first)
    client.post("/api/changes", json=second)

    undone = client.post("/api/changes/undo").json()
    assert undone["undone"]["position"] == [3, 1, 0]
    assert [c["position"] for c in undone["changes"]] == [[2, 1, 0]]
    assert client.get("/api/assets/near").json()["center"] == [2, 1, 0]

    client.post("/api/changes/undo")
    assert client.get("/api/assets/near").json()["center"] == [1, 1, 0]
    assert client.post("/api/changes/undo").status_code == 409


def test_undo_brings_back_a_deleted_object(client):
    client.post("/api/changes", json={"op": "remove", "object_id": "near"})
    assert "near" not in [a["object_id"] for a in client.get("/api/assets").json()["assets"]]
    client.post("/api/changes/undo")
    assert "near" in [a["object_id"] for a in client.get("/api/assets").json()["assets"]]


def test_removing_only_the_info_keeps_a_movable_object_in_the_way(tmp_path):
    assets = [box("target", [5.5, -0.5, 1.0], "fixed"), box("bucket", [3.0, -0.5, 1.0], "movable")]
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "assets": assets}))
    client = TestClient(create_app(path, open_floor(tmp_path), database=FakeDatabase()))
    request = {"start": [1.0, 0.0, 1.0], "object_id": "target"}
    assert client.post("/api/route", json=request).status_code == 409  # the bucket blocks it

    forget = {"op": "remove", "object_id": "bucket", "details": {"keep_splats": True}}
    assert client.post("/api/changes", json=forget).status_code == 200
    assert "bucket" not in [a["object_id"] for a in client.get("/api/assets").json()["assets"]]
    assert client.post("/api/route", json=request).status_code == 409  # still in the scan

    client.post("/api/changes/undo")
    client.post("/api/changes", json={"op": "remove", "object_id": "bucket"})
    assert client.post("/api/route", json=request).status_code == 200  # really gone


def test_raising_an_object_moves_its_whole_box_up(client):
    raised = {"op": "move", "object_id": "near", "position": [1, 0.5, 0]}  # +y is down: 0.5 m up
    assert client.post("/api/changes", json=raised).status_code == 200
    asset = client.get("/api/assets/near").json()
    assert asset["center"] == [1, 0.5, 0]
    assert asset["bbox_min"][1] == 0.0 and asset["bbox_max"][1] == 1.0


def test_walkable_floor_follows_a_moved_object(tmp_path):
    np = pytest.importorskip("numpy")
    import base64

    assets = [box("cart", [5.0, -0.5, 1.0], "movable")]
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "assets": assets}))
    client = TestClient(create_app(path, open_floor(tmp_path), database=FakeDatabase()))

    def walkable():
        body = client.get("/api/plan/walkable").json()
        assert body["shape"] == [120, 40] and body["axes"] == [0, 2]
        bits = np.frombuffer(base64.b64decode(body["mask"]), dtype=np.uint8)
        return np.unpackbits(bits)[: 120 * 40].reshape(120, 40).astype(bool)

    def at(mask, x, z):  # 5 cm cells from the origin (0, 0), x along rows, z along columns
        return mask[int(x / 0.05), int(z / 0.05)]

    before = walkable()
    assert before.any() and not at(before, 5.0, 1.0)
    client.post(
        "/api/changes", json={"op": "move", "object_id": "cart", "position": [1.0, -0.5, 1.0]}
    )
    after = walkable()
    assert at(after, 5.0, 1.0) and not at(after, 1.0, 1.0)


def test_walkable_floor_needs_a_floor_map(client):
    assert client.get("/api/plan/walkable").status_code == 404
