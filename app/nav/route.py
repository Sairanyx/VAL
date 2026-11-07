"""Plan routes on the floor map, around permanent obstacles and movable objects' footprints."""

import heapq
import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from app.nav.grid import BODY_BAND, LOW_BAND, NavGrid

VIEW_DISTANCE = 2.0  # metres across the floor from the object
# Bodies and what blocks them. Anything shorter than the step or above the head leaves floor free.
BODIES = {"robot": (0.3, LOW_BAND), "person": (0.6, BODY_BAND)}

Point = tuple[float, float, float]


def placeholder_route(start: Point, goal: Point, floor_y: float) -> tuple[list[Point], float]:
    """Return an L-shaped path on the floor. It ignores obstacles, so it isn't a real route."""
    a = (start[0], floor_y, start[2])
    corner = (goal[0], floor_y, start[2])
    b = (goal[0], floor_y, goal[2])
    path = [a, corner, b]
    return path, sum(math.dist(p, q) for p, q in zip(path, path[1:], strict=False))


@dataclass
class Route:
    path: list[Point]  # Scene coordinates, on the floor.
    length: float
    stop_distance: float  # Metres from the route's end to the target object's box.
    view_from: Point  # On the route, far enough back to see the whole object.


class NoRoute(ValueError):
    """No route exists, with a reason suitable for showing to the user."""


def to_cell(grid: NavGrid, point: Point) -> tuple[int, int]:
    coordinates = np.asarray(point, dtype=np.float64)[list(grid.axes)]
    return tuple(np.floor((coordinates - grid.origin) / grid.cell).astype(int).tolist())


def cell_to_point(grid: NavGrid, cell: tuple[int, int]) -> Point:
    position = [0.0, 0.0, 0.0]
    for axis, index, origin in zip(grid.axes, cell, grid.origin, strict=True):
        position[axis] = float(origin + (index + 0.5) * grid.cell)
    up_axis = 3 - sum(grid.axes)
    position[up_axis] = float(grid.floor_height / grid.up[up_axis])
    return tuple(position)


def box_cells(grid: NavGrid, low: Point, high: Point) -> tuple[slice, slice]:
    """Return array slices for the floor cells under a box, clipped to the map."""
    first, second = to_cell(grid, low), to_cell(grid, high)
    size = grid.free.shape
    return tuple(
        slice(max(min(a, b), 0), min(max(a, b) + 1, limit))
        for a, b, limit in zip(first, second, size, strict=True)
    )


def in_band(grid: NavGrid, low: Point, high: Point, band: tuple[float, float]) -> bool:
    """True if a box overlaps this height range above the floor."""
    heights = sorted(float(np.dot(corner, grid.up)) - grid.floor_height for corner in (low, high))
    return heights[0] <= band[1] and heights[1] >= band[0]


def clearance_with_footprints(
    grid: NavGrid, footprints: list[tuple[Point, Point]], band: tuple[float, float] = BODY_BAND
) -> np.ndarray:
    """Return clearance in metres, with boxes blocked if they overlap the body's height range."""
    free = grid.clearance_low > 0 if band == LOW_BAND else grid.free.copy()
    for low, high in footprints:
        if in_band(grid, low, high, band):
            free[box_cells(grid, low, high)] = False
    return ndimage.distance_transform_edt(free) * grid.cell


def nearest_open_cell(
    fits: np.ndarray, cell: tuple[int, int], limit: float
) -> tuple[int, int] | None:
    """Return the closest cell where the body fits, within `limit` cells of `cell`."""
    open_cells = np.argwhere(fits)
    if not len(open_cells):
        return None
    distances = np.linalg.norm(open_cells - np.asarray(cell), axis=1)
    best = int(np.argmin(distances))
    return tuple(open_cells[best].tolist()) if distances[best] <= limit else None


def search(clearance: np.ndarray, fits: np.ndarray, start: tuple[int, int]) -> tuple[dict, dict]:
    """Dijkstra from `start` over cells where the body fits, preferring open space.

    Returns each reached cell's cost and predecessor. Costs rise near obstacles, so routes keep to
    the middle of aisles, as a person would, unless a tight spot is the only way through.
    """
    costs = {start: 0.0}
    previous: dict[tuple[int, int], tuple[int, int]] = {}
    queue = [(0.0, start)]
    steps = [(i, j) for i in (-1, 0, 1) for j in (-1, 0, 1) if i or j]
    while queue:
        cost, (x, y) = heapq.heappop(queue)
        if cost > costs[(x, y)]:
            continue
        for dx, dy in steps:
            cell = (x + dx, y + dy)
            if (
                not (0 <= cell[0] < fits.shape[0] and 0 <= cell[1] < fits.shape[1])
                or not fits[cell]
            ):
                continue
            # Diagonal moves mustn't cut across a blocked corner.
            if dx and dy and not (fits[x + dx, y] and fits[x, y + dy]):
                continue
            step = math.hypot(dx, dy) * (1 + 0.5 / max(clearance[cell], 0.1))
            if cost + step < costs.get(cell, math.inf):
                costs[cell] = cost + step
                previous[cell] = (x, y)
                heapq.heappush(queue, (cost + step, cell))
    return costs, previous


def line_is_clear(fits: np.ndarray, a: tuple[int, int], b: tuple[int, int]) -> bool:
    count = max(abs(b[0] - a[0]), abs(b[1] - a[1])) * 2 + 1
    rows = np.linspace(a[0], b[0], count).round().astype(int)
    cols = np.linspace(a[1], b[1], count).round().astype(int)
    return bool(fits[rows, cols].all())


def shorten(cells: list[tuple[int, int]], fits: np.ndarray) -> list[tuple[int, int]]:
    """Replace the staircase of grid steps with straight lines wherever the body still fits."""
    result = [cells[0]]
    index = 0
    while index < len(cells) - 1:
        reach = len(cells) - 1
        while reach > index + 1 and not line_is_clear(fits, cells[index], cells[reach]):
            reach -= 1
        result.append(cells[reach])
        index = reach
    return result


def viewing_point(
    grid: NavGrid, points: list[Point], target: Point, distance: float = VIEW_DISTANCE
) -> Point:
    """Return the last point on the route at least `distance` metres from the target, across the
    floor. Close up, a splat shows what the scan never saw, so the view is better from further back.
    Doesn't check that nothing is in the way.
    """
    axes = list(grid.axes)
    goal = np.asarray(target)[axes]

    def away(point: Point) -> float:
        return float(np.linalg.norm(np.asarray(point)[axes] - goal))

    for near, far in zip(points[:0:-1], points[-2::-1], strict=True):
        if away(far) >= distance:
            # Step back along this piece of the route until the distance is reached.
            steps = max(2, int(math.dist(near, far) / grid.cell) + 1)
            for share in np.linspace(0, 1, steps):
                point = tuple(float(a + (b - a) * share) for a, b in zip(near, far, strict=True))
                if away(point) >= distance:
                    return point
    return points[0]


def plan_route(
    grid: NavGrid,
    start: Point,
    target_low: Point,
    target_high: Point,
    width: float = 0.6,
    footprints: list[tuple[Point, Point]] | None = None,
    max_stop_distance: float = 2.0,
    start_search: float = 1.5,
    band: tuple[float, float] = BODY_BAND,
) -> Route:
    """Return a route ending at the reachable point closest to the target's box.

    A technician needs to reach and see a machine, not stand on it, so the route may stop short by
    up to `max_stop_distance` metres. Beyond that it raises NoRoute and says why.
    """
    clearance = clearance_with_footprints(grid, footprints or [], band)
    fits = clearance >= width / 2
    if not fits.any():
        raise NoRoute(f"No floor is wide enough for a {width} m body.")
    begin = nearest_open_cell(fits, to_cell(grid, start), start_search / grid.cell)
    if begin is None:
        raise NoRoute(f"The start point isn't within {start_search} m of open floor.")
    costs, previous = search(clearance, fits, begin)

    # Distance from every cell to the target's box, in metres.
    away = np.ones(grid.free.shape, dtype=bool)
    away[box_cells(grid, target_low, target_high)] = False
    distance = ndimage.distance_transform_edt(away) * grid.cell
    reached = np.array(list(costs), dtype=np.int64)
    gaps = distance[reached[:, 0], reached[:, 1]]
    closest = gaps.min()
    if closest > max_stop_distance:
        raise NoRoute(
            f"The closest reachable floor is {closest:.1f} m from the object, "
            f"for a {width} m body. Something may be blocking the way."
        )
    # Among nearly equal stopping points, prefer the one that's cheapest to walk to.
    candidates = reached[gaps <= closest + grid.cell * 2]
    end = min((tuple(c) for c in candidates.tolist()), key=lambda c: costs[c])

    cells = [end]
    while cells[-1] != begin:
        cells.append(previous[cells[-1]])
    cells.reverse()
    points = [cell_to_point(grid, cell) for cell in shorten(cells, fits)]
    length = sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))
    center = tuple((a + b) / 2 for a, b in zip(target_low, target_high, strict=True))
    return Route(points, length, float(distance[end]), viewing_point(grid, points, center))
