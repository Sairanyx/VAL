import pytest

np = pytest.importorskip("numpy")

from app.scene.load import Splats  # noqa: E402
from app.scene.split_movable import (  # noqa: E402
    find_clear_floor,
    patch_floor,
    split_by_members,
    split_movable,
)

UP = np.array([0.0, -1.0, 0.0])  # The scene's +y points down, with the floor at y = 1.


def scene(points):
    names = ["x", "y", "z", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    names += ["f_dc_0", "f_dc_1", "f_dc_2", "opacity"]
    data = np.zeros(len(points), dtype=[(name, "<f4") for name in names])
    data["x"], data["y"], data["z"] = np.array(points, dtype=np.float32).T
    return Splats(data)


def box(object_id, low, high):
    return {"object_id": object_id, "bbox_min": low, "bbox_max": high}


def test_object_takes_what_is_in_its_box_but_leaves_the_floor():
    points = [
        [0.0, 0.5, 0.0],  # In the box.
        [0.0, 0.9, 0.0],  # Under the box's stated bottom, like a chair's base.
        [0.0, 1.0, 0.0],  # On the floor, under the box.
        [0.0, 0.2, 0.0],  # Above the box.
        [3.0, 0.5, 0.0],  # Elsewhere.
    ]
    # Height along up is -y, so the floor at y = 1 is at -1.
    base, pieces = split_movable(
        scene(points), [box("cart", [-0.5, 0.3, -0.5], [0.5, 0.7, 0.5])], -1.0, UP
    )
    assert sorted(pieces["cart"].positions[:, 1].tolist()) == pytest.approx([0.5, 0.9])
    assert sorted(base.positions[:, 1].tolist()) == pytest.approx([0.2, 0.5, 1.0])
    assert len(base) == 3


def test_overlapping_boxes_never_share_a_splat():
    points = [[0.0, 0.5, 0.0], [0.4, 0.5, 0.0]]
    base, pieces = split_movable(
        scene(points),
        [
            box("a", [-0.2, 0.3, -0.2], [0.2, 0.7, 0.2]),
            box("b", [-0.2, 0.3, -0.2], [0.6, 0.7, 0.2]),
        ],
        -1.0,
        UP,
    )
    assert len(pieces["a"]) == 1 and len(pieces["b"]) == 1 and len(base) == 0


def floor_cloud(x_low, x_high, z_low, z_high, color, count=4000):
    random = np.random.default_rng(0)
    points = np.stack(
        [
            random.uniform(x_low, x_high, count),
            np.full(count, 1.0),
            random.uniform(z_low, z_high, count),
        ],
        axis=1,
    )
    splats = scene(points)
    splats.data["f_dc_0"] = color
    return splats


def test_clear_floor_matches_the_color_around_the_patch_and_avoids_objects():
    points = np.array(
        [[x, z] for x in np.arange(-3, 3, 0.05) for z in np.arange(-3, 3, 0.05)], dtype=float
    )
    colors = np.zeros((len(points), 3))
    colors[points[:, 0] > 1.5, 0] = 1.0  # A differently colored area shouldn't be chosen.
    blockers = np.array([[-2.0, -3.0, -0.8, 3.0]])  # An object fills this strip.
    spot = find_clear_floor(points, colors, np.zeros(2), np.array([0.5, 0.5]), blockers)
    assert spot is not None
    assert spot[0] < 1.25 and not (-2.25 < spot[0] < -0.55)
    assert max(abs(spot[0]), abs(spot[1])) >= 0.5  # It doesn't copy the patch onto itself.


def test_patch_replaces_dark_floor_under_a_moved_object_and_records_it():
    light = floor_cloud(-3, 3, -3, 3, 1.0, count=20000)
    in_patch = (np.abs(light.positions[:, [0, 2]]) < 0.4).all(axis=1)
    light.data["f_dc_0"][in_patch] = -1.0  # The floor under the object is dark.
    asset = box("cart", [-0.3, 0.5, -0.3], [0.3, 0.9, 0.3])
    patched, record = patch_floor(light, [asset], [asset], -1.0, UP)
    assert record[0]["patched"] is True and record[0]["copied_from"]
    under = (np.abs(patched.positions[:, [0, 2]]) < 0.3).all(axis=1)
    assert under.sum() > 0
    assert patched.data["f_dc_0"][under].min() == 1.0


def test_no_clear_floor_leaves_the_scene_as_it_was_and_says_so():
    tiny = floor_cloud(-0.5, 0.5, -0.5, 0.5, 1.0, count=500)
    asset = box("cart", [-0.45, 0.5, -0.45], [0.45, 0.9, 0.45])
    patched, record = patch_floor(tiny, [asset], [asset], -1.0, UP)
    assert record[0]["patched"] is False
    assert len(patched) == len(tiny)


def test_a_low_base_unlike_the_floor_goes_with_its_object():
    floor = floor_cloud(-2, 2, -2, 2, -1.0, count=8000)
    floor.data["opacity"] = 5.0
    under = (np.abs(floor.positions[:, [0, 2]]) < 0.1).all(axis=1)
    floor.data["f_dc_0"][under] = 2.0  # A pale base, as low as the floor.
    asset = box("chair", [-0.3, 0.2, -0.3], [0.3, 0.7, 0.3])
    base, pieces = split_movable(floor, [asset], -1.0, UP)
    assert len(pieces["chair"]) == int(under.sum())
    assert len(base) == len(floor) - int(under.sum())


def test_members_are_found_by_position_even_in_a_lighter_copy():
    pytest.importorskip("scipy")
    light_copy = scene([[0.0, 0.5, 0.0], [3.0, 0.5, 0.0]])
    members = {"cart": np.array([[0.0, 0.5, 0.0], [9.0, 9.0, 9.0]], dtype=np.float32)}
    base, pieces = split_by_members(light_copy, members)
    assert pieces["cart"].positions[:, 0].tolist() == [0.0]  # The missing splat is skipped.
    assert base.positions[:, 0].tolist() == [3.0]
