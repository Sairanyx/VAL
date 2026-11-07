import pytest

np = pytest.importorskip("numpy")

from app.scene.lighten import lighten, strip_view_dependence  # noqa: E402
from app.scene.load import Splats, read_splats  # noqa: E402
from app.scene.split import SH_ZERO, object_name, split_scene, tint_color, tinted  # noqa: E402

NAMES = ["x", "y", "z", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
NAMES += ["f_dc_0", "f_dc_1", "f_dc_2", "opacity", "f_rest_0"]


def make_splats(positions) -> Splats:
    positions = np.asarray(positions, dtype=np.float32)
    data = np.zeros(len(positions), dtype=[(name, "<f4") for name in NAMES])
    data["x"], data["y"], data["z"] = positions.T
    data["scale_0"] = data["scale_1"] = data["scale_2"] = -4.0
    data["rot_0"] = 1.0
    data["opacity"] = 5.0
    return Splats(data)


def test_lighten_keeps_order_enlarges_splats_and_drops_view_dependence():
    splats = make_splats(np.arange(12).reshape(4, 3))
    light = lighten(splats, 2)
    assert light.data["x"].tolist() == sorted(light.data["x"].tolist())
    assert len(light) == 2
    assert "f_rest_0" not in light.data.dtype.names
    # Half the splats, so each covers twice the area, and each scale grows by the square root of 2.
    assert np.exp(light.data["scale_0"][0] - splats.data["scale_0"][0]) == pytest.approx(2**0.5)


def test_lighten_without_a_target_keeps_every_splat_at_full_size():
    splats = make_splats(np.zeros((3, 3)))
    for light in (lighten(splats), lighten(splats, 100)):
        assert len(light) == 3
        assert light.data["scale_0"].tolist() == splats.data["scale_0"].tolist()


def test_lighten_is_repeatable():
    splats = make_splats(np.arange(30).reshape(10, 3))
    assert lighten(splats, 4).data["x"].tolist() == lighten(splats, 4).data["x"].tolist()


def test_strip_view_dependence_keeps_other_values():
    splats = make_splats(np.ones((2, 3)))
    assert strip_view_dependence(splats).data["x"].tolist() == [1.0, 1.0]


def test_split_writes_each_object_and_background(tmp_path):
    splats = make_splats(np.arange(15).reshape(5, 3))
    labels = np.array([0, -1, 1, 0, -1])
    summary = split_scene(splats, labels, tmp_path)
    assert summary == {"objects": 2, "object_splats": 3, "background_splats": 2, "largest": 2}
    assert read_splats(tmp_path / "objects" / "obj-0001.ply").data["x"].tolist() == [0.0, 9.0]
    assert read_splats(tmp_path / "objects" / "obj-0002.ply").data["x"].tolist() == [6.0]
    assert read_splats(tmp_path / "background.ply").data["x"].tolist() == [3.0, 12.0]
    assert "f_rest_0" in read_splats(tmp_path / "objects" / "obj-0001.ply").data.dtype.names
    assert "f_rest_0" not in read_splats(tmp_path / "tinted" / "obj-0001.ply").data.dtype.names


def test_split_rejects_labels_from_a_different_scene(tmp_path):
    with pytest.raises(ValueError, match="wrong scene"):
        split_scene(make_splats(np.zeros((2, 3))), np.array([0]), tmp_path)


def test_object_names_match_assets_numbering():
    assert object_name(0) == "obj-0001"


def test_tint_blends_toward_the_color():
    color = (1.0, 0.0, 0.0)
    result = tinted(make_splats(np.zeros((1, 3))), color, strength=1.0)
    assert 0.5 + SH_ZERO * result.data["f_dc_0"][0] == pytest.approx(1.0)
    assert 0.5 + SH_ZERO * result.data["f_dc_1"][0] == pytest.approx(0.0, abs=1e-6)


def test_tint_colors_differ_between_neighbors():
    assert tint_color(0) != tint_color(1)


def test_clustering_separates_two_blobs_and_ignores_floor():
    pytest.importorskip("scipy")
    from app.scene.cluster import cluster_labels, to_assets

    random = np.random.default_rng(0)
    floor = np.column_stack(
        [random.uniform(-3, 3, 20000), np.full(20000, 1.2), random.uniform(-3, 3, 20000)]
    )
    first = random.uniform([-2, 0.2, -2], [-1.5, 0.8, -1.5], (4000, 3))
    second = random.uniform([1.5, 0.2, 1.5], [2, 0.8, 2], (2000, 3))
    ceiling = np.column_stack(
        [random.uniform(-3, 3, 5000), np.full(5000, -1.2), random.uniform(-3, 3, 5000)]
    )
    splats = make_splats(np.vstack([floor, first, second, ceiling]))
    labels = cluster_labels(splats, up=(0, -1, 0))
    assert (labels[:20000] == -1).all()
    assert (labels[20000:24000] == 0).mean() > 0.95
    assert (labels[24000:26000] == 1).mean() > 0.95
    assert (labels[26000:] == -1).all()

    assets = to_assets(splats, labels, "test", 1.2)
    assert [asset["object_id"] for asset in assets["assets"]] == ["obj-0001", "obj-0002"]
    assert assets["assets"][0]["mapping"] is None
