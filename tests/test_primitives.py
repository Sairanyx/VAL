import pytest

np = pytest.importorskip("numpy")

from app.extract.primitives import (  # noqa: E402
    MIN_SCORE,
    basis_from_up,
    fit_box,
    fit_circle,
    fit_cylinder,
    fit_object,
    good_fit,
)

UP = np.array([0.0, -1.0, 0.0])


def test_basis_is_orthonormal_and_ends_with_up():
    basis = basis_from_up(UP)
    np.testing.assert_allclose(basis @ basis.T, np.eye(3), atol=1e-9)
    np.testing.assert_allclose(basis[2], UP)


def test_circle_fit_recovers_a_partial_arc_despite_stray_points():
    random = np.random.default_rng(0)
    angles = random.uniform(0, np.pi, 300)  # Only half the circle was seen.
    points = np.column_stack([1 + 0.5 * np.cos(angles), 2 + 0.5 * np.sin(angles)])
    strays = random.uniform(-1, 3, (20, 2))
    center, radius = fit_circle(np.vstack([points, strays]))
    np.testing.assert_allclose(center, [1, 2], atol=0.05)
    assert radius == pytest.approx(0.5, abs=0.05)


def test_cylinder_fit_recovers_position_size_and_a_good_score():
    random = np.random.default_rng(1)
    angles = random.uniform(0, 2 * np.pi, 800)
    height = random.uniform(-1.0, 0.2, 800)  # y is down, so this spans y from -1.0 to 0.2.
    points = np.column_stack([3 + 0.4 * np.cos(angles), height, 1 + 0.4 * np.sin(angles)])
    shape = fit_cylinder(points, UP)
    np.testing.assert_allclose(shape["center"], [3, -0.4, 1], atol=0.05)
    assert shape["radius"] == pytest.approx(0.4, abs=0.02)
    assert shape["height"] == pytest.approx(1.2, abs=0.05)
    assert shape["score"] > 0.9


def surface_of_box(random, size, count=3000):
    points = random.uniform(-0.5, 0.5, (count, 3)) * size
    faces = random.integers(0, 3, count)
    signs = random.choice([-0.5, 0.5], count)
    points[np.arange(count), faces] = signs * np.array(size)[faces]
    return points


def test_nearly_flat_arc_is_not_trusted_for_a_radius():
    random = np.random.default_rng(3)

    def arc(degrees):
        angles = np.radians(random.uniform(0, degrees, 500))
        return np.column_stack([np.cos(angles), random.uniform(-1.0, 0.0, 500), np.sin(angles)])

    flat, round_enough = fit_cylinder(arc(50), UP), fit_cylinder(arc(120), UP)
    assert flat["score"] >= MIN_SCORE and flat["flat_arc"] and not good_fit(flat)
    assert not round_enough["flat_arc"] and good_fit(round_enough)


def test_box_fit_recovers_a_turned_box():
    random = np.random.default_rng(2)
    points = surface_of_box(random, (1.0, 0.6, 0.4))
    angle = np.radians(30)
    turn = np.array(
        [[np.cos(angle), 0, -np.sin(angle)], [0, 1, 0], [np.sin(angle), 0, np.cos(angle)]]
    )
    points = points @ turn.T + [2.0, 0.0, -1.0]
    shape = fit_box(points, UP)
    np.testing.assert_allclose(shape["center"], [2, 0, -1], atol=0.05)
    assert sorted(shape["size"]) == pytest.approx([0.4, 0.6, 1.0], abs=0.05)
    assert shape["score"] > 0.8
    axes = np.array(shape["axes"])
    np.testing.assert_allclose(axes @ axes.T, np.eye(3), atol=1e-3)


def test_random_cloud_scores_lower_than_a_real_cylinder():
    random = np.random.default_rng(3)
    blob = random.normal(0, 0.3, (1000, 3))
    assert fit_cylinder(blob, UP)["score"] < 0.8


def test_other_classes_and_tiny_objects_get_no_shape():
    points = np.random.default_rng(4).normal(size=(100, 3))
    assert fit_object(points, "pump", UP) is None
    assert fit_object(points[:10], "tank", UP) is None
    assert fit_object(points, "tank", UP)["type"] == "cylinder"
    assert fit_object(points, "electrical cabinet", UP)["type"] == "box"
