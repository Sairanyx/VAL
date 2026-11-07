import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("PIL")

from app.scene.movable_members import merge_fragments, vote_shares  # noqa: E402

CAMERA = np.array([[100.0, 0, 50], [0, 100.0, 50], [0, 0, 1]])


def looking_along_z(shift_x):
    """A camera at x = shift_x, looking along +z."""
    matrix = np.eye(4)
    matrix[0, 3] = -shift_x
    return matrix


def centre_mask():
    mask = np.zeros((100, 100), dtype=bool)
    mask[40:60, 40:60] = True
    return mask


def test_object_splat_stays_in_its_mask_and_a_neighbour_does_not():
    points = np.array(
        [
            [0.0, 0.0, 2.0],  # The object, in the middle of every view.
            [0.9, 0.0, 2.0],  # A neighbour, in the mask from one view only.
            [0.0, 0.0, -2.0],  # Behind the cameras: never seen.
        ]
    )
    views = [(CAMERA, looking_along_z(x), centre_mask()) for x in (0.0, 0.05, 0.9)]
    # Each view has its mask around the object, so move the mask with the object's position.
    views[2] = (CAMERA, looking_along_z(0.9), np.roll(centre_mask(), -45, axis=1))
    shares, seen = vote_shares(points, views)
    assert shares[0] == 1.0
    assert shares[1] < 0.6
    assert seen[2] == 0


def box(object_id, low, high):
    return {"object_id": object_id, "bbox_min": low, "bbox_max": high}


def test_small_boxes_inside_large_ones_merge_and_separate_things_do_not():
    cart = box("cart", [0, 0, 0], [1, 1, 1])
    handle = box("handle", [0.2, 0.2, 0.2], [0.4, 0.4, 0.4])
    chair = box("chair", [5, 0, 0], [6, 1, 1])
    twin = box("twin", [0, 0, 0], [0.99, 1, 1])  # Nearly as big: not a fragment.
    groups = merge_fragments([handle, chair, cart, twin])
    assert groups["cart"] == ["handle"]
    assert groups["chair"] == []
    assert groups["twin"] == []
