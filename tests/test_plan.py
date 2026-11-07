import json

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("PIL")

from fastapi.testclient import TestClient  # noqa: E402

from app.api.main import create_app  # noqa: E402
from app.bim.room import estimate_room  # noqa: E402
from app.plan.export_dxf import layer_for, write_dxf  # noqa: E402
from app.plan.layout import build_layout  # noqa: E402
from app.scene.load import Splats, write_splats  # noqa: E402

FLOOR_Y = 1.0  # The scene's +y points down.


def room_points():
    """A 6 x 4 m room: walls at x = 0 and 6, z = 0 and 4, and a machine in the middle."""
    random = np.random.default_rng(0)
    groups = [
        random.uniform([0, 0], [0.05, 4], (3000, 2)),
        random.uniform([5.95, 0], [6, 4], (3000, 2)),
        random.uniform([0, 0], [6, 0.05], (3000, 2)),
        random.uniform([0, 3.95], [6, 4], (3000, 2)),
        random.uniform([2.5, 1.5], [3.5, 2.5], (3000, 2)),
    ]
    return np.concatenate(groups)


def scene_splats():
    random = np.random.default_rng(1)
    flat = room_points()
    standing = np.stack(
        [flat[:, 0], random.uniform(0, 0.8, len(flat)), flat[:, 1]], axis=1
    )  # Between 0.2 and 1 m above the floor.
    floor = np.stack(
        [
            random.uniform(0, 6, 20000),
            np.full(20000, FLOOR_Y),
            random.uniform(0, 4, 20000),
        ],
        axis=1,
    )
    points = np.concatenate([standing, floor])
    names = ["x", "y", "z", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    names += ["f_dc_0", "f_dc_1", "f_dc_2", "opacity"]
    data = np.zeros(len(points), dtype=[(name, "<f4") for name in names])
    data["x"], data["y"], data["z"] = points.T
    data["opacity"] = 5.0
    return Splats(data)


def test_walls_are_the_room_estimate_the_bim_model_uses():
    splats = scene_splats()
    _, description = build_layout(splats, FLOOR_Y)
    positions = splats.positions.astype(np.float64)
    assert description["room"] == estimate_room(
        positions, splats.opacities, [0.0, -1.0, 0.0], -FLOOR_Y
    )
    xs = [p[0] for wall in description["walls"] for p in (wall["start"], wall["end"])]
    zs = [p[1] for wall in description["walls"] for p in (wall["start"], wall["end"])]
    assert min(xs) == pytest.approx(0, abs=0.1) and max(xs) == pytest.approx(6, abs=0.1)
    assert min(zs) == pytest.approx(0, abs=0.1) and max(zs) == pytest.approx(4, abs=0.1)


def test_layout_has_an_image_and_the_room_extent():
    image, description = build_layout(scene_splats(), FLOOR_Y)
    assert image.width > 100 and image.height > 100
    assert len(description["walls"]) == 4
    assert description["generated_from"] == "scan, not surveyed"
    assert description["x_min"] < 0 < 6 < description["x_max"]


def asset(object_id, label="cart", mapping=None, grade="likely"):
    return {
        "object_id": object_id,
        "label": label,
        "label_grade": grade,
        "label_confidence": 0.5,
        "center": [1.5, 0.75, 1.5],
        "bbox_min": [1, 0.5, 1],
        "bbox_max": [2, 1, 2],
        "mapping": mapping,
        "mobility": "movable",
    }


def test_dxf_layers_keep_identity_honest():
    assert layer_for(asset("a", "pipe fitting"), "P-005") == "OBJECT_PIPE_FITTING"
    linked = asset("b", mapping={"tag": "M-001", "method": "procedural_class"})
    fault = asset("c", mapping={"tag": "P-005", "method": "manual_visual_unconfirmed"})
    assert layer_for(linked, "P-005") == "LINKED" and layer_for(fault, "P-005") == "FAULT"
    _, description = build_layout(scene_splats(), FLOOR_Y)
    text = write_dxf(description, [linked, fault], "P-005")
    assert "M-001?" in text and "P-005?" in text  # Links made by rule or by eye are questions.
    assert "NOT SURVEYED" in text
    confirmed = asset("d", mapping={"tag": "T-1", "method": "nameplate"})
    assert "\nT-1\n" in write_dxf(description, [confirmed])


def test_dxf_opens_in_a_cad_library(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    _, description = build_layout(scene_splats(), FLOOR_Y)
    path = tmp_path / "plan.dxf"
    path.write_text(write_dxf(description, [asset("a")], None))
    document = ezdxf.readfile(path)
    lines = list(document.modelspace().query("LINE"))
    assert len(lines) == 8  # Four walls and a box's four sides.
    assert "OBJECT_CART" in {layer.dxf.name for layer in document.layers}


CYLINDER = {
    "type": "cylinder",
    "center": [1.5, 0.75, 1.5],
    "axis": [0.0, -1.0, 0.0],
    "radius": 0.4,
    "height": 0.5,
    "score": 0.9,
    "use_shape": True,
}


def plan_client(tmp_path, monkeypatch):
    scene_file = tmp_path / "scene.ply"
    write_splats(scene_splats(), scene_file)
    monkeypatch.setenv("SCENE_PLY", str(scene_file))
    path = tmp_path / "assets.json"
    assets = [asset("a"), asset("b")]
    document = {"scene_id": "t", "floor_y": FLOOR_Y, "fault_tag": "P-005", "assets": assets}
    path.write_text(json.dumps(document))
    (tmp_path / "shapes.json").write_text(json.dumps({"a": CYLINDER}))
    return TestClient(create_app(path, engine=False, database=False))


def test_plan_api_serves_description_image_and_current_dxf(tmp_path, monkeypatch):
    client = plan_client(tmp_path, monkeypatch)
    description = client.get("/api/plan").json()
    assert len(description["walls"]) == 4
    image = client.get("/api/plan/floor.png")
    assert image.status_code == 200 and image.content[:4] == b"\x89PNG"
    before = client.get("/api/plan/layout.dxf").text
    move = {"op": "move", "object_id": "a", "position": [3.5, 0.75, 3.0]}
    assert client.post("/api/changes", json=move).status_code == 200
    after = client.get("/api/plan/layout.dxf").text
    assert before != after  # The drawing shows where objects stand now.


def test_ifc_download_shows_the_model_as_it_stands_now(tmp_path, monkeypatch):
    client = plan_client(tmp_path, monkeypatch)
    response = client.get("/api/plan/model.ifc")
    assert response.status_code == 200 and response.text.startswith("ISO-10303-21;")
    assert 'filename="model.ifc"' in response.headers["content-disposition"]
    assert "(b)" in response.text
    assert client.post("/api/changes", json={"op": "remove", "object_id": "b"}).status_code == 200
    added = client.post("/api/changes", json={"op": "add", "position": [4, 0.5, 2]}).json()
    text = client.get("/api/plan/model.ifc").text
    assert "(b)" not in text and f"({added['object_id']})" in text
    assert "new, unconfirmed" in text


def test_moved_object_keeps_its_fitted_shape_in_the_ifc(tmp_path, monkeypatch):
    pytest.importorskip("ifcopenshell")
    import ifcopenshell.geom

    client = plan_client(tmp_path, monkeypatch)
    move = {"op": "move", "object_id": "a", "position": [3.5, 0.75, 3.0]}
    assert client.post("/api/changes", json=move).status_code == 200
    path = tmp_path / "model.ifc"
    path.write_text(client.get("/api/plan/model.ifc").text)
    model = ifcopenshell.open(str(path))
    element = next(e for e in model.by_type("IfcElement") if "(a)" in (e.Name or ""))
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    shape = ifcopenshell.geom.create_shape(settings, element).geometry
    points = np.array(shape.verts).reshape(-1, 3)
    # IFC's X and Y are the scene's x and z. The 0.8 m cylinder is where the object stands now.
    np.testing.assert_allclose(
        (points.min(axis=0) + points.max(axis=0))[:2] / 2, [3.5, 3.0], atol=0.01
    )
    np.testing.assert_allclose((points.max(axis=0) - points.min(axis=0))[:2], [0.8, 0.8], atol=0.01)


def test_plan_without_a_scene_says_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("SCENE_PLY", raising=False)
    path = tmp_path / "assets.json"
    path.write_text(json.dumps({"scene_id": "t", "floor_y": FLOOR_Y, "assets": []}))
    client = TestClient(create_app(path, engine=False, database=False))
    response = client.get("/api/plan")
    assert response.status_code == 503 and "SCENE_PLY" in response.json()["detail"]
    assert client.get("/api/plan/model.ifc").status_code == 503
