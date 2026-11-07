import json

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fastapi.testclient import TestClient  # noqa: E402

from app.api.collisions import check_move  # noqa: E402
from app.api.main import create_app  # noqa: E402
from app.nav.grid import build_nav_grid  # noqa: E402


def box(object_id, center, half=0.25, label="cart", mobility="movable"):
    c = np.array(center, dtype=float)
    return {
        "object_id": object_id,
        "label": label,
        "label_confidence": 0.5,
        "center": c.tolist(),
        "bbox_min": (c - half).tolist(),
        "bbox_max": (c + half).tolist(),
        "mapping": None,
        "mobility": mobility,
    }


CART = box("cart", [0, 0, 0])
CHAIR = box("chair", [3, 0, 0], label="chair")


def test_open_space_is_fine_and_another_object_blocks():
    assert check_move(CART, [1, 0, 0], [CART, CHAIR], None).ok
    result = check_move(CART, [3, 0, 0], [CART, CHAIR], None)
    assert not result.ok
    assert result.blockers == ["chair"]
    assert "chair" in result.reason


def test_a_slight_touch_is_allowed_because_boxes_are_loose():
    assert check_move(CART, [2.55, 0, 0], [CART, CHAIR], None).ok


def test_passing_overhead_is_not_a_collision():
    pipe = box("pipe", [3, -2, 0], label="pipe")
    assert check_move(CART, [3, 0, 0], [CART, pipe], None).ok


def test_thin_things_and_stray_fragments_do_not_block():
    hose = box("hose", [3, 0, 0], label="hose")
    speck = box("speck", [3, 0, 0], half=0.04, label="object")
    assert check_move(CART, [3, 0, 0], [CART, hose, speck], None).ok


def test_things_inside_its_own_box_at_the_start_travel_with_it():
    bucket = box("bucket", [0, 0, 0], half=0.1, label="bucket")
    assert check_move(CART, [0.05, 0, 0], [CART, bucket], None).ok
    assert check_move(CART, [2, 0, 0], [CART, bucket], None).ok


def test_something_already_touching_it_does_not_trap_it():
    neighbour = box("neighbour", [0.3, 0, 0])
    assert check_move(CART, [-0.1, 0, 0], [CART, neighbour], None).ok
    assert check_move(CART, [0.1, 0, 0], [CART, neighbour], None).ok is False


def room_grid():
    random = np.random.default_rng(0)
    floor = random.uniform([0, 0, 0], [6, 0, 6], (120000, 3))
    wall = random.uniform([2.95, -1.8, 0], [3.05, -0.2, 6], (40000, 3))
    points = np.concatenate([floor, wall])
    return build_nav_grid(points, np.ones(len(points)), (0, -1, 0), floor_height=0.0)


def test_a_wall_on_the_floor_map_blocks():
    grid = room_grid()
    cart = box("cart", [1, -0.5, 1])
    assert check_move(cart, [2, -0.5, 1], [cart], grid).ok
    result = check_move(cart, [3, -0.5, 1], [cart], grid)
    assert not result.ok and "free floor" in result.reason


def app_client(tmp_path):
    path = tmp_path / "assets.json"
    assets = [box("cart", [0, 0, 0]), box("chair", [3, 0, 0], label="chair")]
    path.write_text(json.dumps({"scene_id": "t", "floor_y": 0.25, "assets": assets}))
    return TestClient(create_app(path, engine=False, database=False))


def test_backend_refuses_a_bad_move_and_leaves_the_object_alone(tmp_path):
    client = app_client(tmp_path)
    bad = {"op": "move", "object_id": "cart", "position": [3, 0, 0]}
    response = client.post("/api/changes", json=bad)
    assert response.status_code == 409
    assert "chair" in response.json()["detail"]
    assert client.get("/api/assets/cart").json()["center"] == [0, 0, 0]
    good = {"op": "move", "object_id": "cart", "position": [1, 0, 0]}
    assert client.post("/api/changes", json=good).status_code == 200


def test_check_endpoint_answers_without_moving_anything(tmp_path):
    client = app_client(tmp_path)
    reply = client.post("/api/objects/cart/check-move", json={"position": [3, 0, 0]}).json()
    assert reply["ok"] is False and reply["blockers"] == ["chair"]
    assert client.get("/api/assets/cart").json()["center"] == [0, 0, 0]
    assert client.get("/api/changes").json()["changes"] == []
