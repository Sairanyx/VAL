import pytest

np = pytest.importorskip("numpy")

from app.scene.load import (  # noqa: E402
    Splats,
    clean_mask,
    estimate_floor,
    read_splats,
    valid_mask,
    write_splats,
)

NAMES = ["x", "y", "z", "scale_0", "scale_1", "scale_2", "rot_1", "rot_2", "rot_3", "rot_0"]
NAMES += ["f_dc_0", "f_dc_1", "f_dc_2", "opacity"]


def make_splats(count: int, seed: int = 0) -> Splats:
    random = np.random.default_rng(seed)
    data = np.zeros(count, dtype=[(name, "<f4") for name in NAMES])
    data["x"], data["y"], data["z"] = random.normal(0, 0.05, (3, count))
    data["scale_0"] = data["scale_1"] = data["scale_2"] = -4.0
    data["rot_0"] = 1.0
    data["opacity"] = 5.0
    return Splats(data)


def test_write_then_read_keeps_records_and_property_order(tmp_path):
    splats = make_splats(50)
    write_splats(splats, tmp_path / "scene.ply")
    loaded = read_splats(tmp_path / "scene.ply")
    assert loaded.data.dtype.names == tuple(NAMES)
    np.testing.assert_array_equal(loaded.data, splats.data)


def test_properties_are_found_by_name_not_position():
    splats = make_splats(3)
    splats.data["rot_0"], splats.data["rot_1"] = 0.0, 2.0
    np.testing.assert_allclose(splats.quaternions, [[0, 1, 0, 0]] * 3)


def test_read_rejects_truncated_file(tmp_path):
    path = tmp_path / "scene.ply"
    write_splats(make_splats(50), path)
    path.write_bytes(path.read_bytes()[:-100])
    with pytest.raises(ValueError, match="truncated"):
        read_splats(path)


def test_read_rejects_file_without_splat_properties(tmp_path):
    path = tmp_path / "points.ply"
    header = (
        "ply\nformat binary_little_endian 1.0\nelement vertex 0\nproperty float x\nend_header\n"
    )
    path.write_bytes(header.encode())
    with pytest.raises(ValueError, match="missing splat properties"):
        read_splats(path)


def test_valid_mask_catches_corrupted_records():
    splats = make_splats(4)
    splats.data["x"][1] = np.nan
    splats.data["opacity"][2] = 1e36
    assert valid_mask(splats).tolist() == [True, False, False, True]


def test_clean_mask_removes_transparent_oversized_and_isolated_splats():
    splats = make_splats(400)
    splats.data["opacity"][0] = -10.0  # Far below MIN_OPACITY.
    splats.data["scale_0"][1] = 5.0
    splats.data["x"][2] = 50.0
    keep = clean_mask(splats)
    assert not keep[:3].any()
    assert keep[3:].mean() > 0.9


def test_floor_is_the_dense_low_layer_with_y_pointing_down():
    random = np.random.default_rng(1)
    floor = np.column_stack(
        [random.uniform(-3, 3, 5000), np.full(5000, 1.25), random.uniform(-3, 3, 5000)]
    )
    room = random.uniform([-3, -1.3, -3], [3, 1.2, 3], (5000, 3))
    height = estimate_floor(np.vstack([floor, room]), up=(0, -1, 0))
    assert height == pytest.approx(-1.25, abs=0.03)


def test_clean_mask_keeps_faint_splats_that_build_up_surfaces():
    splats = make_splats(400)
    splats.data["opacity"][:] = -3.0  # About 5% opaque, as most of a floor can be.
    assert clean_mask(splats).mean() > 0.9
