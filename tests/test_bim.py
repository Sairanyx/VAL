import re

import pytest

np = pytest.importorskip("numpy")

from app.bim.ifc import string, write_ifc  # noqa: E402
from app.bim.model import build_model, ifc_guid  # noqa: E402
from app.bim.room import estimate_room  # noqa: E402

UP = [0.0, -1.0, 0.0]  # +y points down, as in Equipment Room
FLOOR = -1.0  # floor along up, so the floor is at y = 1


def room_points():
    """Walls at x = -3 and 4, z = -2 and 3, with a denser cabinet row just inside x = -3."""
    rng = np.random.default_rng(0)
    parts = []
    for axis, value, other in (
        (0, -3, (-2, 3)),
        (0, 4, (-2, 3)),
        (2, -2, (-3, 4)),
        (2, 3, (-3, 4)),
    ):
        pts = np.empty((2000, 3))
        pts[:, axis] = value + rng.normal(0, 0.01, 2000)
        pts[:, 2 - axis] = rng.uniform(*other, 2000)
        pts[:, 1] = 1 - rng.uniform(0, 2.5, 2000)
        parts.append(pts)
    cabinets = np.column_stack(
        [rng.normal(-2.6, 0.01, 3600), 1 - rng.uniform(0.5, 1.8, 3600), rng.uniform(-2, 3, 3600)]
    )
    parts.append(cabinets)
    return np.concatenate(parts)


def assets_file():
    return {
        "scene_id": "test_room",
        "up": UP,
        "floor_height_along_up": FLOOR,
        "assets": [
            {
                "object_id": "obj-1",
                "label": "pump",
                "center": [0.0, 0.5, 0.0],
                "bbox_min": [-0.2, 0.2, -0.3],
                "bbox_max": [0.2, 0.8, 0.3],
                "mapping": {
                    "tag": "P-005",
                    "asset_id": "A-1",
                    "method": "manual_visual_unconfirmed",
                },
            },
            {
                "object_id": "obj-2",
                "label": "object",
                "center": [1.0, 0.75, 1.0],
                "bbox_min": [0.5, 0.5, 0.5],
                "bbox_max": [1.5, 1.0, 1.5],
                "mapping": None,
            },
            {
                "object_id": "obj-3",
                "label": "tank",
                "center": [2.0, 0.4, 2.0],
                "bbox_min": [1.7, -0.2, 1.7],
                "bbox_max": [2.3, 1.0, 2.3],
                "mapping": {"tag": "T-1", "asset_id": "A-2", "method": "procedural_class"},
            },
        ],
    }


SHAPES = {
    "obj-3": {
        "type": "cylinder",
        "center": [2.0, 0.4, 2.0],
        "axis": [0.0, -1.0, 0.0],
        "radius": 0.3,
        "height": 1.2,
        "score": 0.8,
        "use_shape": True,
    }
}


def model():
    pts = room_points()
    room = estimate_room(pts, np.ones(len(pts)), UP, FLOOR)
    return build_model(assets_file(), SHAPES, room)


def test_room_finds_outermost_wall_not_denser_equipment():
    room = model()["room"]
    faces = room["faces"]
    assert faces["first_min"] == pytest.approx(-3, abs=0.06)
    assert faces["first_max"] == pytest.approx(4, abs=0.06)
    assert faces["second_min"] == pytest.approx(-2, abs=0.06)
    assert faces["second_max"] == pytest.approx(3, abs=0.06)
    assert room["ceiling_height"] == pytest.approx(2.5, abs=0.05)


def test_room_needs_an_axis_up():
    pts = room_points()
    with pytest.raises(ValueError, match="scene axis"):
        estimate_room(pts, np.ones(len(pts)), [0.0, -0.7, 0.7], FLOOR)


def test_elements_keep_identity_unconfirmed_and_use_fitted_shapes():
    elements = {e["object_id"]: e for e in model()["elements"]}
    pump, unknown, tank = elements["obj-1"], elements["obj-2"], elements["obj-3"]
    assert pump["ifc_class"] == "IfcPump"
    assert pump["name"].startswith("P-005?")
    assert pump["psets"]["Valmet_Identification"]["IdentityConfirmed"] is False
    assert pump["psets"]["Valmet_Geometry"]["Source"] == "axis-aligned bounding box"
    assert unknown["ifc_class"] == "IfcBuildingElementProxy"
    assert "Valmet_Mapping" not in unknown["psets"]
    assert tank["ifc_class"] == "IfcTank"
    assert tank["geometry"]["type"] == "cylinder"
    assert tank["name"].startswith("T-1?")
    classes = sorted(e["ifc_class"] for e in model()["elements"] if e["object_id"] is None)
    assert classes == ["IfcSlab", "IfcWall", "IfcWall", "IfcWall", "IfcWall"]


def test_guids_are_stable_and_valid():
    guid = ifc_guid("scene", "obj-1")
    assert guid == ifc_guid("scene", "obj-1") != ifc_guid("scene", "obj-2")
    assert re.fullmatch(r"[0-3][0-9A-Za-z_$]{21}", guid)


def test_strings_are_escaped_for_step():
    assert string("it's") == "'it''s'"
    assert string("ä") == "'\\X2\\00E4\\X0\\'"


def test_ifc_file_is_written(tmp_path):
    path = tmp_path / "model.ifc"
    write_ifc(model(), path, timestamp="2026-01-01T00:00:00")
    text = path.read_text()
    assert "FILE_SCHEMA(('IFC4'));" in text
    assert text.count("IFCWALL(") == 4 and "IFCPUMP(" in text and "IFCTANK(" in text


def test_ifc_validates_and_places_geometry(tmp_path):
    pytest.importorskip("ifcopenshell")
    import ifcopenshell.geom
    import ifcopenshell.util.element
    import ifcopenshell.validate

    path = tmp_path / "model.ifc"
    write_ifc(model(), path)
    f = ifcopenshell.open(str(path))
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, log)
    assert log.statements == []

    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)

    def bounds(entity):
        verts = np.array(ifcopenshell.geom.create_shape(settings, entity).geometry.verts)
        verts = verts.reshape(-1, 3)
        return verts.min(0), verts.max(0)

    # IFC is Z-up from the floor: X = x, Y = z, Z = 1 - y for this scene.
    lo, hi = bounds(f.by_type("IfcPump")[0])
    np.testing.assert_allclose(lo, [-0.2, -0.3, 0.2], atol=1e-4)
    np.testing.assert_allclose(hi, [0.2, 0.3, 0.8], atol=1e-4)
    lo, hi = bounds(f.by_type("IfcTank")[0])
    np.testing.assert_allclose([lo[2], hi[2]], [0.0, 1.2], atol=1e-4)
    np.testing.assert_allclose((lo[:2] + hi[:2]) / 2, [2.0, 2.0], atol=1e-3)
    pump = f.by_type("IfcPump")[0]
    assert ifcopenshell.util.element.get_psets(pump)["Valmet_Mapping"]["Tag"] == "P-005"


def cube_surface(n=4000, side=0.4):
    """Points on the surface of a cube from 0 to `side`."""
    rng = np.random.default_rng(1)
    pts = rng.uniform(0, side, (n, 3))
    axis = rng.integers(0, 3, n)
    pts[np.arange(n), axis] = rng.choice([0.0, side], n)
    return pts


def test_scan_mesh_follows_the_surface_and_faces_outwards():
    from app.bim.shapes import object_mesh

    mesh = object_mesh(cube_surface())
    v, f = mesh["vertices"].astype(np.float64), mesh["faces"]
    assert (v.min(0) > -0.05).all() and (v.max(0) < 0.45).all()
    assert (v.max(0) - v.min(0) > 0.35).all()
    signed = np.einsum("ij,ij->i", v[f[:, 0]], np.cross(v[f[:, 1]], v[f[:, 2]])).sum() / 6
    assert signed > 0  # outward faces give a positive volume
    assert object_mesh(np.zeros((3, 3))) is None


def test_object_splats_use_labels_and_prefer_cut_pieces():
    from app.bim.__main__ import object_splats
    from app.scene.load import Splats

    data = np.zeros(4, dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4")])
    data["x"] = [0, 1, 2, 3]
    scene = Splats(data)
    assets = [{"object_id": "a", "splats": 2}, {"object_id": "b", "splats": 1}]
    piece = Splats(data[:1])
    out = object_splats(scene, np.array([0, -1, 1, 0]), assets, {"b": piece})
    assert out["a"].positions[:, 0].tolist() == [0, 3]
    assert out["b"] is piece
    with pytest.raises(ValueError, match="counts differ"):
        object_splats(scene, np.array([0, 0, 0, 0]), assets, {})


def test_ifc_writes_scan_meshes_as_triangles(tmp_path):
    from app.bim.shapes import object_mesh

    # A 0.4 m cube surface standing on the floor (y = 1 is the floor, +y down) around the pump.
    points = cube_surface() - [0.2, 0.4, 0.2] + [0.0, 1.0, 0.0]
    meshes = {"obj-1": object_mesh(points)}
    m = build_model(assets_file(), SHAPES, model()["room"], meshes)
    pump = next(e for e in m["elements"] if e["object_id"] == "obj-1")
    assert pump["psets"]["Valmet_Geometry"]["Source"].startswith("scan surface mesh")
    path = tmp_path / "model.ifc"
    write_ifc(m, path, meshes=meshes)
    assert path.read_text().count("IFCTRIANGULATEDFACESET(") == 1
    pytest.importorskip("ifcopenshell")
    import ifcopenshell.geom
    import ifcopenshell.validate

    f = ifcopenshell.open(str(path))
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, log)
    assert log.statements == []
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    shape = ifcopenshell.geom.create_shape(settings, f.by_type("IfcPump")[0])
    verts = np.array(shape.geometry.verts).reshape(-1, 3)
    # Z is height above the floor: the cube spans 0 to 0.4 m, within a voxel.
    assert verts[:, 2].min() == pytest.approx(0.0, abs=0.05)
    assert verts[:, 2].max() == pytest.approx(0.4, abs=0.05)
