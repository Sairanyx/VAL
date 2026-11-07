import pytest

np = pytest.importorskip("numpy")

from app.scene.cover import cover_boxes  # noqa: E402


def inside(points, boxes):
    found = np.zeros(len(points), dtype=bool)
    for box in boxes:
        found |= ((points >= box["bbox_min"]) & (points <= box["bbox_max"])).all(axis=1)
    return found


def test_an_l_shape_is_covered_without_the_empty_corner_of_its_box():
    random = np.random.default_rng(0)
    arm = random.uniform([0, 0, 0], [1, 0.2, 0.2], (4000, 3))
    leg = random.uniform([0, 0, 0], [0.2, 1, 0.2], (4000, 3))
    points = np.concatenate([arm, leg])
    boxes = cover_boxes(points)
    assert 0 < len(boxes) <= 12
    assert inside(points, boxes).mean() > 0.99
    neighbour = random.uniform([0.6, 0.6, 0], [0.9, 0.9, 0.2], (500, 3))  # in the bounding box
    assert inside(neighbour, boxes).mean() == 0


def test_box_limit_makes_the_cover_coarser_not_incomplete():
    points = np.random.default_rng(1).uniform(0, 1, (20000, 3))
    boxes = cover_boxes(points, max_boxes=3)
    assert len(boxes) <= 3 and inside(points, boxes).mean() > 0.99


def test_no_points_means_no_boxes():
    assert cover_boxes(np.empty((0, 3))) == []


def test_cover_stays_inside_the_objects_box_despite_strays():
    random = np.random.default_rng(2)
    body = random.uniform(0, 1, (3000, 3))
    strays = np.array([[5.0, 5.0, 5.0]] * 10)
    limit = (np.zeros(3), np.ones(3))
    boxes = cover_boxes(np.concatenate([body, strays]), limit)
    assert all(min(box["bbox_min"]) >= 0 and max(box["bbox_max"]) <= 1 for box in boxes)
    assert inside(body, boxes).mean() > 0.99
