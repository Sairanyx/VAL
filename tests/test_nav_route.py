import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from scipy import ndimage  # noqa: E402

from app.nav.route import FloorMap, NoRoute, astar, plan_route  # noqa: E402


def floor_with_wall(gap_cells):
    """4 x 4 m at 5 cm, y up is negative. A wall at x = 2 m with a gap at the low z end."""
    free = np.ones((80, 80), bool)
    free[[0, -1], :] = free[:, [0, -1]] = False
    free[39:41, gap_cells:] = False
    clearance = ndimage.distance_transform_edt(free) * 0.05
    return FloorMap(
        origin=np.zeros(2),
        cell=0.05,
        floor_height=0.0,
        up=np.array([0.0, -1.0, 0.0]),
        axes=(0, 2),
        clearance=clearance,
        clearance_low=clearance,
    )


TARGET = ([3.2, -1.0, 3.2], [3.4, 0.0, 3.4])
START = [1.0, 0.0, 3.0]


def test_route_goes_through_gap_and_stays_clear():
    floor = floor_with_wall(30)
    fits = floor.fits("person")
    goals = floor.goal_cells(*TARGET)
    path = astar(fits, floor.to_cell(START), goals)
    assert path and goals[path[-1]]
    assert all(fits[cell] for cell in path)
    assert all(
        abs(a[0] - b[0]) <= 1 and abs(a[1] - b[1]) <= 1
        for a, b in zip(path, path[1:], strict=False)
    )
    route = plan_route(floor, START, *TARGET)
    assert route["placeholder"] is False
    assert min(p[2] for p in route["path"]) < 1.5


def test_route_ends_within_reach_of_object():
    floor = floor_with_wall(30)
    end = plan_route(floor, START, *TARGET)["path"][-1]
    assert np.hypot(max(3.2 - end[0], 0), max(3.2 - end[2], 0)) <= 0.8 + 0.05


def test_body_size_decides_who_fits():
    floor = floor_with_wall(16)
    assert plan_route(floor, START, *TARGET, profile="robot")["length"] > 0
    with pytest.raises(NoRoute, match="No connected route"):
        plan_route(floor, START, *TARGET, profile="carrying")


def test_blocked_cells_close_the_route():
    floor = floor_with_wall(30)
    blocked = np.zeros(floor.clearance.shape, bool)
    blocked[39:41, :] = True
    with pytest.raises(NoRoute):
        plan_route(floor, START, *TARGET, blocked=blocked)
