import base64
import io
import json

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from fastapi.testclient import TestClient  # noqa: E402

from app.api.main import create_app  # noqa: E402
from app.api.select_object import (  # noqa: E402
    NothingSelected,
    already_known,
    known_tag,
    mobility_for,
    pick_object,
    suggest_config,
)
from app.scene.load import Splats  # noqa: E402

FLOOR_Y = 1.0  # The scene's +y points down.
ORIGIN = [0.0, 0.0, 0.0]


def cloud(center, size, count, seed=0):
    random = np.random.default_rng(seed)
    return random.uniform(np.array(center) - size, np.array(center) + size, (count, 3))


def scene(*groups):
    points = np.concatenate(groups)
    names = ["x", "y", "z", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    names += ["f_dc_0", "f_dc_1", "f_dc_2", "opacity"]
    data = np.zeros(len(points), dtype=[(name, "<f4") for name in names])
    data["x"], data["y"], data["z"] = points.T
    data["opacity"] = 5.0
    return Splats(data)


def rays(half):
    """Four corner rays looking along +z, as wide as `half` per metre of depth."""
    return [[-half, -half, 1.0], [half, -half, 1.0], [half, half, 1.0], [-half, half, 1.0]]


def test_picks_the_near_object_and_not_the_wall_behind():
    near = cloud([0, 0.2, 2], 0.2, 2000)
    wall = cloud([0, 0, 4], [1, 1, 0.02], 8000, seed=1)
    box = pick_object(scene(near, wall), ORIGIN, rays(0.2), FLOOR_Y)
    assert box["center"] == pytest.approx([0, 0.2, 2], abs=0.05)
    assert box["bbox_max"][2] < 3


def test_floor_is_left_out_of_the_box():
    thing = cloud([0, 0.6, 2], 0.2, 2000)
    floor = cloud([0, 1.0, 2], [1, 0.005, 1], 8000, seed=1)
    box = pick_object(scene(thing, floor), ORIGIN, rays(0.3), FLOOR_Y)
    assert box["bbox_max"][1] < 0.9


def test_empty_selection_says_why():
    far_away = cloud([9, 0, 2], 0.2, 500)
    with pytest.raises(NothingSelected, match="Nothing solid"):
        pick_object(scene(far_away), ORIGIN, rays(0.2), FLOOR_Y)


def test_tags_must_be_readable_and_known():
    assert known_tag("pump p-005 grundfos", ["P-005", "P-001"]) == "P-005"
    assert known_tag("P-0051", ["P-005"]) is None
    assert known_tag("", ["P-005"]) is None


def test_mobility_comes_from_rules_not_the_model():
    assert mobility_for("cart")[0] == "movable"
    assert mobility_for("pump")[0] == "fixed"
    assert mobility_for("object")[0] == "unsure"


def test_overlap_finds_objects_already_detected():
    box = {"bbox_min": [0, 0, 0], "bbox_max": [1, 1, 1]}
    inside = {"object_id": "a", "bbox_min": [0.2, 0.2, 0.2], "bbox_max": [0.8, 0.8, 0.8]}
    apart = {"object_id": "b", "bbox_min": [5, 5, 5], "bbox_max": [6, 6, 6]}
    assert already_known(box, [inside, apart]) == ["a"]


class FakeWriter:
    def __init__(self, reply):
        self.reply = reply

    def look(self, image, prompt):
        assert "pump" in prompt
        return self.reply


def test_model_suggests_and_code_decides_mobility():
    reply = '{"label": "cart", "confidence": 0.8, "reason": "wheels", "visible_text": "P-005"}'
    config = suggest_config(FakeWriter(reply), object(), ["P-005"])
    assert config["label"] == "cart" and config["mobility"] == "movable"
    assert config["label_source"] == "vision model, unconfirmed"
    assert config["possible_tag"] == "P-005"


@pytest.mark.parametrize("reply", ["no json", '{"label": "spaceship", "confidence": 0.9}'])
def test_unusable_model_replies_leave_a_plain_object(reply):
    config = suggest_config(FakeWriter(reply), object(), [])
    assert config["label"] == "object" and config["mobility"] == "unsure"
    assert config["label_source"] == "not suggested"


def test_no_model_still_gives_a_config_to_fill_in():
    assert suggest_config(None, None, [])["label"] == "object"


@pytest.fixture
def app_client(tmp_path):
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "floor_y": FLOOR_Y, "assets": []}))
    return TestClient(create_app(path, engine=False, database=False))


def test_confirmed_object_is_saved_with_its_measured_box(app_client):
    details = {
        "bbox_min": [0, 0, 0],
        "bbox_max": [1, 0.5, 2],
        "label": "cart",
        "mobility": "movable",
    }
    change = {"op": "add", "position": [0.5, 0.25, 1], "details": details}
    assert app_client.post("/api/changes", json=change).status_code == 200
    added = app_client.get("/api/assets").json()["assets"][0]
    assert added["bbox_max"] == [1, 0.5, 2]
    assert added["label"] == "cart"
    assert added["status"] == "new, unconfirmed"
    assert added["label_grade"] == "operator_added"
    assert added["mapping"] is None


def test_new_objects_without_details_keep_the_old_default(app_client):
    change = {"op": "add", "position": [0, 0, 0]}
    assert app_client.post("/api/changes", json=change).status_code == 200
    added = app_client.get("/api/assets").json()["assets"][0]
    assert added["label"] == "other" and added["mobility"] == "fixed"


def test_operator_cannot_set_mapping_or_status(app_client):
    details = {"bbox_min": [0, 0, 0], "bbox_max": [1, 1, 1], "mapping": {"tag": "P-005"}}
    details["status"] = "detected"
    change = {"op": "add", "position": [0.5, 0.5, 0.5], "details": details}
    assert app_client.post("/api/changes", json=change).status_code == 200
    added = app_client.get("/api/assets").json()["assets"][0]
    assert added["mapping"] is None and added["status"] == "new, unconfirmed"


def test_proposal_without_a_scene_file_says_so(app_client):
    pixels = io.BytesIO()
    body = {
        "origin": ORIGIN,
        "corners": rays(0.2),
        "rectangle": [0.4, 0.4, 0.6, 0.6],
        "image": "data:image/jpeg;base64," + base64.b64encode(pixels.getvalue()).decode(),
    }
    response = app_client.post("/api/objects/propose", json=body)
    assert response.status_code == 503
    assert "SCENE_PLY" in response.json()["detail"]


def test_splitting_gives_the_selected_part_and_the_rest_their_own_boxes():
    from app.api.select_object import split_object

    table = cloud([-0.3, 0.5, 2], 0.15, 2000)
    chair = cloud([0.3, 0.5, 2], 0.15, 2000, seed=1)
    parent = {"bbox_min": [-0.5, 0.3, 1.8], "bbox_max": [0.5, 0.7, 2.2]}
    # Corner rays around the left part only.
    left = [[-0.25, -0.05, 1.0], [-0.05, -0.05, 1.0], [-0.05, 0.35, 1.0], [-0.25, 0.35, 1.0]]
    part, rest = split_object(scene(table, chair), parent, ORIGIN, left, FLOOR_Y)
    assert part["center"][0] == pytest.approx(-0.3, abs=0.06)
    assert rest["center"][0] == pytest.approx(0.3, abs=0.06)
    assert part["bbox_max"][0] < rest["bbox_min"][0]


def test_selecting_all_of_an_object_is_not_a_split():
    from app.api.select_object import split_object

    only = cloud([0, 0.5, 2], 0.15, 2000)
    parent = {"bbox_min": [-0.3, 0.2, 1.7], "bbox_max": [0.3, 0.8, 2.3]}
    with pytest.raises(NothingSelected, match="nearly all"):
        split_object(scene(only), parent, ORIGIN, rays(0.3), FLOOR_Y)


def parts_of(first_label, second_label):
    return [
        {"bbox_min": [0, 0, 0], "bbox_max": [1, 1, 1], "label": first_label, "mobility": "movable"},
        {"bbox_min": [2, 0, 0], "bbox_max": [3, 1, 1], "label": second_label, "mobility": "fixed"},
    ]


def box_asset(object_id, mapping=None):
    return {
        "object_id": object_id,
        "label": "chair",
        "label_confidence": 0.5,
        "center": [1.5, 0.5, 0.5],
        "bbox_min": [0, 0, 0],
        "bbox_max": [3, 1, 1],
        "mapping": mapping,
        "mobility": "movable",
    }


def split_client(tmp_path, mapping=None):
    path = tmp_path / "assets.json"
    assets = [box_asset("obj-1", mapping)]
    path.write_text(json.dumps({"scene_id": "t", "floor_y": FLOOR_Y, "assets": assets}))
    return TestClient(create_app(path, engine=False, database=False))


def test_split_replaces_an_object_with_two_and_undo_brings_it_back(tmp_path):
    client = split_client(tmp_path)
    change = {
        "op": "split",
        "object_id": "obj-1",
        "details": {"parts": parts_of("chair", "box")},
    }
    reply = client.post("/api/changes", json=change)
    assert reply.status_code == 200
    assert reply.json()["parts"] == ["obj-1.1", "obj-1.2"]
    assets = {a["object_id"]: a for a in client.get("/api/assets").json()["assets"]}
    assert set(assets) == {"obj-1.1", "obj-1.2"}
    assert assets["obj-1.1"]["label"] == "chair" and assets["obj-1.1"]["mapping"] is None
    assert assets["obj-1.2"]["bbox_max"] == [3, 1, 1]
    assert assets["obj-1.2"]["status"] == "new, unconfirmed"
    assert client.get("/api/assets/obj-1").status_code == 404
    client.post("/api/changes/reset")
    assets = client.get("/api/assets").json()["assets"]
    assert [a["object_id"] for a in assets] == ["obj-1"]


def test_an_object_linked_to_a_record_cannot_be_split(tmp_path):
    client = split_client(tmp_path, mapping={"tag": "P-005", "asset_id": "ASSET-017"})
    change = {
        "op": "split",
        "object_id": "obj-1",
        "details": {"parts": parts_of("chair", "box")},
    }
    reply = client.post("/api/changes", json=change)
    assert reply.status_code == 409 and "P-005" in reply.json()["detail"]


def test_rest_of_a_split_ignores_scraps_left_behind():
    from app.api.select_object import split_object

    table = cloud([-0.3, 0.5, 2], 0.15, 2000)
    chair = cloud([0.4, 0.5, 2], 0.12, 2000, seed=1)
    leg = cloud([-0.42, 0.65, 2], [0.02, 0.05, 0.02], 200, seed=2)  # Missed by the selection.
    parent = {"bbox_min": [-0.5, 0.3, 1.8], "bbox_max": [0.6, 0.72, 2.2]}
    near_table = [[-0.21, -0.05, 1.0], [-0.04, -0.05, 1.0], [-0.04, 0.3, 1.0], [-0.21, 0.3, 1.0]]
    _, rest = split_object(scene(table, chair, leg), parent, ORIGIN, near_table, FLOOR_Y)
    assert rest["bbox_min"][0] > 0.2  # The chair's box, not stretched back to the table's leg.


def two_objects(tmp_path, mapping=None):
    path = tmp_path / "assets.json"
    first = box_asset("a", mapping)
    second = {
        **box_asset("b"),
        "bbox_min": [4, 0, 0],
        "bbox_max": [5, 2, 1],
        "center": [4.5, 1, 0.5],
    }
    assets = [first, second]
    path.write_text(json.dumps({"scene_id": "t", "floor_y": FLOOR_Y, "assets": assets}))
    return TestClient(create_app(path, engine=False, database=False))


def test_combine_replaces_two_objects_with_one_around_both(tmp_path):
    client = two_objects(tmp_path)
    change = {
        "op": "combine",
        "object_id": "a",
        "details": {"other": "b", "label": "cart", "mobility": "movable", "mapping": {"tag": "X"}},
    }
    reply = client.post("/api/changes", json=change)
    assert reply.status_code == 200 and reply.json()["parts"] == ["a+b"]
    assets = client.get("/api/assets").json()["assets"]
    assert [a["object_id"] for a in assets] == ["a+b"]
    assert assets[0]["bbox_max"] == [5, 2, 1] and assets[0]["label"] == "cart"
    assert assets[0]["mapping"] is None and assets[0]["status"] == "new, unconfirmed"
    client.post("/api/changes/reset")
    assert sorted(a["object_id"] for a in client.get("/api/assets").json()["assets"]) == ["a", "b"]


def test_combine_refuses_linked_objects_and_itself(tmp_path):
    client = two_objects(tmp_path, mapping={"tag": "P-005", "asset_id": "ASSET-017"})
    linked = {"op": "combine", "object_id": "a", "details": {"other": "b"}}
    assert "P-005" in client.post("/api/changes", json=linked).json()["detail"]
    itself = {"op": "combine", "object_id": "b", "details": {"other": "b"}}
    assert client.post("/api/changes", json=itself).status_code == 409
    missing = {"op": "combine", "object_id": "b", "details": {"other": "nope"}}
    assert client.post("/api/changes", json=missing).status_code == 404


def test_any_object_can_be_cut_from_its_home_even_after_moving(tmp_path, monkeypatch):
    from app.scene.load import read_splats, write_splats

    near = cloud([0, 0.5, 0], 0.2, 500)
    far = cloud([3, 0.5, 0], 0.2, 700, seed=1)
    scene_file = tmp_path / "scene.ply"
    write_splats(scene(near, far), scene_file)
    monkeypatch.setenv("SCENE_PLY", str(scene_file))
    asset = {
        **box_asset("cart"),
        "center": [0, 0.5, 0],
        "bbox_min": [-0.25, 0.25, -0.25],
        "bbox_max": [0.25, 0.75, 0.25],
    }
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "floor_y": FLOOR_Y, "assets": [asset]}))
    client = TestClient(create_app(path, engine=False, database=False))
    move = {"op": "move", "object_id": "cart", "position": [2, 0.5, 0]}
    assert client.post("/api/changes", json=move).status_code == 200
    assert client.get("/api/objects/cart/home").json()["center"] == [0, 0.5, 0]
    reply = client.get("/api/objects/cart/splats.ply")
    assert reply.status_code == 200
    saved = tmp_path / "piece.ply"
    saved.write_bytes(reply.content)
    assert len(read_splats(saved)) == 500  # Where it was scanned, not where it stands now.
