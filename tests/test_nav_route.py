import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from app.nav.grid import build_nav_grid  # noqa: E402
from app.nav.route import NoRoute, line_is_clear, plan_route, viewing_point  # noqa: E402


def room():
    """A 6 x 6 m floor. A wall at x = 3 has a 1.2 m gap at the far end, z from 4.8 to 6."""
    rng = np.random.default_rng(0)
    floor = rng.uniform([0, 0, 0], [6, 0, 6], (120000, 3))
    wall = rng.uniform([2.95, -1.8, 0], [3.05, -0.2, 4.8], (40000, 3))
    points = np.concatenate([floor, wall])
    return build_nav_grid(points, np.ones(len(points)), (0, -1, 0), floor_height=0.0)


GRID = room()
START = (1.0, 0.0, 1.0)
TARGET = ((5.0, 0.0, 1.0), (5.4, -1.0, 1.4))


def cells_of(route):
    return [(p[0], p[2]) for p in route.path]


def crosses_wall(route, grid=GRID):
    for a, b in zip(route.path, route.path[1:], strict=False):
        for t in np.linspace(0, 1, 200):
            x = a[0] + (b[0] - a[0]) * t
            z = a[2] + (b[2] - a[2]) * t
            if 2.95 <= x <= 3.05 and z < 4.8:
                return True
    return False


def test_route_goes_through_the_gap_and_not_the_wall():
    route = plan_route(GRID, START, *TARGET, width=0.6)
    assert not crosses_wall(route)
    assert max(p[2] for p in route.path) > 4.8
    assert route.length > math.dist(START, TARGET[0])


def test_route_stays_on_the_floor_and_stops_close_to_the_target():
    route = plan_route(GRID, START, *TARGET, width=0.6)
    assert all(p[1] == pytest.approx(0.0) for p in route.path)
    assert route.stop_distance < 0.8


def test_too_wide_a_body_gets_a_reason_instead_of_a_route():
    with pytest.raises(NoRoute, match="closest reachable floor"):
        plan_route(GRID, START, *TARGET, width=2.0, max_stop_distance=0.5)


def test_footprint_in_the_gap_blocks_then_moving_it_reopens_the_route():
    in_gap = ((2.5, 0.0, 4.6), (3.5, -1.0, 6.0))
    with pytest.raises(NoRoute):
        plan_route(GRID, START, *TARGET, width=0.6, footprints=[in_gap])
    moved = ((0.2, 0.0, 5.0), (0.8, -1.0, 5.6))
    assert plan_route(GRID, START, *TARGET, width=0.6, footprints=[moved])


def test_start_inside_an_obstacle_snaps_to_nearby_floor():
    route = plan_route(GRID, (3.0, 0.0, 2.0), *TARGET, width=0.6)
    assert route.path


def test_start_far_from_any_floor_is_refused():
    with pytest.raises(NoRoute, match="start point"):
        plan_route(GRID, (40.0, 0.0, 40.0), *TARGET, width=0.6)


def test_line_check_sees_blocked_cells():
    fits = np.ones((10, 10), dtype=bool)
    fits[5, :] = False
    assert not line_is_clear(fits, (0, 0), (9, 9))
    assert line_is_clear(fits, (0, 0), (4, 9))


def test_viewing_point_stands_back_from_the_target_along_the_route():
    points = [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (6.0, 0.0, 0.0)]
    point = viewing_point(GRID, points, (6.5, 1.0, 0.0), distance=2.0)
    assert point[0] == pytest.approx(4.5, abs=GRID.cell)
    assert viewing_point(GRID, points[:2], (4.5, 1.0, 0.0), distance=9.0) == points[0]
