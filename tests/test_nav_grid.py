import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from app.nav.grid import build_nav_grid, largest_region, vacate  # noqa: E402


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


def test_removable_splats_covers_movable_and_low_clutter_but_not_equipment():
    from app.nav.grid import removable_splats

    up = np.array([0.0, -1.0, 0.0])
    low = {"bbox_min": [0, 0, 0], "bbox_max": [1, -0.2, 1]}  # Top is 0.2 m above the floor.
    tall = {"bbox_min": [0, 0, 0], "bbox_max": [1, -1.0, 1]}
    assets = [
        {**low, "suggested_label": "hose", "mobility": "unsure"},
        {**tall, "suggested_label": "hose", "mobility": "unsure"},
        {**tall, "suggested_label": "cart", "mobility": "movable"},
        {**low, "suggested_label": "pump", "mobility": "fixed"},
    ]
    labels = np.array([0, 1, 2, 3, -1])
    assert removable_splats(labels, assets, up, 0.0).tolist() == [True, False, True, False, False]


def test_left_out_splats_do_not_block_the_map():
    points, opacity = room()
    wall = points[:, 1] < -0.1
    grid = build_nav_grid(points, opacity, (0, -1, 0), floor_height=0.0, not_obstacles=wall)
    # With the wall left out, the whole floor connects at a width the 1 m gap alone also allows.
    assert largest_region(grid.clearance >= 0.75).sum() * grid.cell**2 > 3.0


def test_grid_round_trips_through_a_file(tmp_path):
    from app.nav.grid import load_grid

    points, opacity = room()
    grid = build_nav_grid(points, opacity, (0, -1, 0), floor_height=0.0)
    grid.save(tmp_path / "grid.npz")
    loaded = load_grid(tmp_path / "grid.npz")
    assert loaded.axes == grid.axes
    assert loaded.cell == pytest.approx(grid.cell)
    np.testing.assert_array_equal(loaded.free, grid.free)


def moved_away():
    """A cart stood at x and z from 0.8 to 1.4, hiding the floor under it. A cabinet overlaps its
    box, from x 1.3 to 1.6."""
    rng = np.random.default_rng(1)
    floor = rng.uniform([0, 0, 0], [4, 0, 4], (60000, 3))
    under = (floor[:, 0] > 0.8) & (floor[:, 0] < 1.4) & (floor[:, 2] > 0.8) & (floor[:, 2] < 1.4)
    floor = floor[~under]
    cart = rng.uniform([0.8, -1.0, 0.8], [1.4, -0.2, 1.4], (6000, 3))
    cabinet = rng.uniform([1.3, -1.8, 0.8], [1.6, -0.2, 1.4], (6000, 3))
    points = np.concatenate([floor, cart, cabinet])
    own = np.zeros(len(points), dtype=bool)
    own[len(floor) : len(floor) + len(cart)] = True
    return points, np.ones(len(points)), own


def test_a_moved_objects_old_spot_opens_but_what_else_stood_there_still_blocks():
    points, opacity, own = moved_away()
    grid = build_nav_grid(points, opacity, (0, -1, 0), floor_height=0.0)

    def cell(x, z):
        return tuple(((np.array([x, z]) - grid.origin) / grid.cell).astype(int))

    assert not grid.free[cell(1.0, 1.1)]
    opened = vacate(grid, points, opacity, own, [([0.8, -1.0, 0.8], [1.4, -0.2, 1.4])])
    assert opened.free[cell(1.0, 1.1)]  # unseen floor, but the cart stood on it
    assert opened.clearance_low[cell(1.0, 1.1)] > 0
    assert not opened.free[cell(1.35, 1.1)]  # the cabinet, inside the cart's old box
    assert not opened.free[cell(1.5, 1.1)]
    assert opened.free.sum() > grid.free.sum()
    assert opened.clearance[cell(1.0, 1.1)] > 0


def test_nothing_left_keeps_the_map():
    points, opacity, own = moved_away()
    grid = build_nav_grid(points, opacity, (0, -1, 0), floor_height=0.0)
    assert vacate(grid, points, opacity, own, []) is grid
