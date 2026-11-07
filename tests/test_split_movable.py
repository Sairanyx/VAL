import pytest

np = pytest.importorskip("numpy")

from app.scene.load import Splats  # noqa: E402
from app.scene.split_movable import split_movable  # noqa: E402

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
        [0.0, 1.0, 0.0],  # On the floor, under the box.
        [0.0, 0.2, 0.0],  # Above the box.
        [3.0, 0.5, 0.0],  # Elsewhere.
    ]
    # Height along up is -y, so the floor at y = 1 is at -1.
    base, pieces = split_movable(
        scene(points), [box("cart", [-0.5, 0.3, -0.5], [0.5, 1.0, 0.5])], -1.0, UP
    )
    assert pieces["cart"].positions[:, 1].tolist() == [0.5]
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
