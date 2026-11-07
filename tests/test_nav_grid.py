import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from app.nav.grid import build_nav_grid, largest_region  # noqa: E402


def room():
    """A 4 x 4 m floor with a wall across x = 2, with a 1 m gap at z from 0 to 1."""
    rng = np.random.default_rng(0)
    floor = rng.uniform([0, 0, 0], [4, 0, 4], (40000, 3))
    wall = rng.uniform([1.95, -1.8, 1], [2.05, -0.2, 4], (20000, 3))
    points = np.concatenate([floor, wall])
    return points, np.ones(len(points))


def test_wall_blocks_and_gap_stays_open():
    points, opacity = room()
    grid = build_nav_grid(points, opacity, (0, -1, 0), floor_height=0.0)

    def cell(x, z):
        return tuple(((np.array([x, z]) - grid.origin) / grid.cell).astype(int))

    assert not grid.free[cell(2.0, 3.0)]
    assert grid.free[cell(2.0, 0.5)]
    assert grid.free[cell(1.0, 3.0)]
    assert 0.4 < grid.clearance[cell(2.0, 0.5)] <= 0.55


def test_clearance_controls_who_fits_through_the_gap():
    points, opacity = room()
    grid = build_nav_grid(points, opacity, (0, -1, 0), floor_height=0.0)
    small = largest_region(grid.clearance >= 0.3)
    wide = largest_region(grid.clearance >= 0.7)

    def side(region, x, z):
        return region[tuple(((np.array([x, z]) - grid.origin) / grid.cell).astype(int))]

    assert side(small, 1.0, 3.0) and side(small, 3.0, 3.0)
    assert side(wide, 1.0, 3.0) != side(wide, 3.0, 3.0)


def test_low_robot_passes_under_overhead_obstacle():
    rng = np.random.default_rng(1)
    floor = rng.uniform([0, 0, 0], [4, 0, 4], (40000, 3))
    pipe = rng.uniform([1.5, -1.5, 0], [2.5, -1.2, 4], (20000, 3))
    points = np.concatenate([floor, pipe])
    grid = build_nav_grid(points, np.ones(len(points)), (0, -1, 0), floor_height=0.0)
    center = tuple(((np.array([2.0, 2.0]) - grid.origin) / grid.cell).astype(int))
    assert grid.clearance[center] == 0
    assert grid.clearance_low[center] > 0.3
