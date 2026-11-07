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
