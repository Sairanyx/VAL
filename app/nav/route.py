"""Routes on the floor map: A* for a body size, to free floor beside an object.

A body fits a cell if its clearance is at least the body's radius. Positions are in the scene's
coordinates, and paths stay on the floor.
"""

import heapq
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

Point = tuple[float, float, float]
# Width in metres, and whether it can pass under overhead obstacles.
PROFILES = {"robot": (0.3, True), "person": (0.6, False), "carrying": (1.0, False)}
REACH = 0.8  # how far from an object's box a person can stop and still service it
STEPS = [(a, b, math.hypot(a, b)) for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b]


class NoRoute(ValueError):
    """No path exists. The message says why, for showing to the user."""


@dataclass
class FloorMap:
    origin: np.ndarray
    cell: float
    floor_height: float
    up: np.ndarray
    axes: tuple[int, int]
    clearance: np.ndarray
    clearance_low: np.ndarray

    @classmethod
    def load(cls, path: Path | str) -> "FloorMap":
        with np.load(path) as data:
            return cls(
                origin=data["origin"],
                cell=float(data["cell"]),
                floor_height=float(data["floor_height"]),
                up=data["up"],
                axes=tuple(int(a) for a in data["axes"]),
                clearance=data["clearance"],
                clearance_low=data["clearance_low"],
            )

    def to_cell(self, point: Point | list[float]) -> tuple[int, int]:
        flat = np.asarray(point, dtype=float)[list(self.axes)]
        return tuple(np.floor((flat - self.origin) / self.cell).astype(int).tolist())

    def to_world(self, cell: tuple[int, int]) -> Point:
        point = [0.0, 0.0, 0.0]
        for axis, index, low in zip(self.axes, cell, self.origin, strict=True):
            point[axis] = round(float(low + (index + 0.5) * self.cell), 3)
        up_axis = 3 - sum(self.axes)
        point[up_axis] = round(float(self.floor_height / self.up[up_axis]), 3)
        return tuple(point)

    def fits(self, profile: str, blocked: np.ndarray | None = None) -> np.ndarray:
        width, low = PROFILES[profile]
        fits = (self.clearance_low if low else self.clearance) >= width / 2
        return fits & ~blocked if blocked is not None else fits

    def goal_cells(self, bbox_min: list[float], bbox_max: list[float]) -> np.ndarray:
        """True for cells within reach of an object's box on the floor."""
        rows, cols = np.ogrid[: self.clearance.shape[0], : self.clearance.shape[1]]
        low = np.asarray(bbox_min, dtype=float)[list(self.axes)]
        high = np.asarray(bbox_max, dtype=float)[list(self.axes)]
        x = self.origin[0] + (rows + 0.5) * self.cell
        y = self.origin[1] + (cols + 0.5) * self.cell
        gap_x = np.maximum(np.maximum(low[0] - x, x - high[0]), 0)
        gap_y = np.maximum(np.maximum(low[1] - y, y - high[1]), 0)
        return np.hypot(gap_x, gap_y) <= REACH


def nearest_fit(fits: np.ndarray, cell: tuple[int, int]) -> tuple[int, int] | None:
    free = np.argwhere(fits)
    if not len(free):
        return None
    return tuple(free[np.argmin(((free - cell) ** 2).sum(axis=1))].tolist())


def astar(fits: np.ndarray, start: tuple[int, int], goals: np.ndarray) -> list[tuple[int, int]]:
    """Shortest path from start to any goal cell, in cells. Empty if there's none.

    Diagonal steps can't cut a corner. The search spreads evenly because goals can be many cells.
    """
    goal_list = np.argwhere(goals & fits)
    if not len(goal_list):
        return []
    center = goal_list.mean(axis=0)
    spread = float(np.hypot(*(goal_list - center).T).max())

    def estimate(cell: tuple[int, int]) -> float:
        return max(math.hypot(cell[0] - center[0], cell[1] - center[1]) - spread, 0.0)

    rows, cols = fits.shape
    best = {start: 0.0}
    came: dict[tuple[int, int], tuple[int, int]] = {}
    heap = [(estimate(start), start)]
    while heap:
        _, current = heapq.heappop(heap)
        if goals[current]:
            path = [current]
            while path[-1] in came:
                path.append(came[path[-1]])
            return path[::-1]
        for dr, dc, cost in STEPS:
            r, c = current[0] + dr, current[1] + dc
            if not (0 <= r < rows and 0 <= c < cols and fits[r, c]):
                continue
            if (
                dr
                and dc
                and not (fits[current[0] + dr, current[1]] and fits[current[0], current[1] + dc])
            ):
                continue
            total = best[current] + cost
            if total < best.get((r, c), math.inf):
                best[(r, c)] = total
                came[(r, c)] = current
                heapq.heappush(heap, (total + estimate((r, c)), (r, c)))
    return []


def simplify(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Keep only the cells where direction changes."""
    kept = path[:1]
    for before, here, after in zip(path, path[1:], path[2:], strict=False):
        if (here[0] - before[0], here[1] - before[1]) != (after[0] - here[0], after[1] - here[1]):
            kept.append(here)
    return kept + path[-1:] if len(path) > 1 else kept


def plan_route(
    floor: FloorMap,
    start: Point | list[float],
    bbox_min: list[float],
    bbox_max: list[float],
    profile: str = "person",
    blocked: np.ndarray | None = None,
) -> dict:
    """Route to free floor beside an object. Raises NoRoute if the body can't get there."""
    fits = floor.fits(profile, blocked)
    width = PROFILES[profile][0]
    begin = nearest_fit(fits, floor.to_cell(start))
    if begin is None:
        raise NoRoute(f"No floor is wide enough for a {width} m body.")
    goals = floor.goal_cells(bbox_min, bbox_max)
    if not (goals & fits).any():
        raise NoRoute(f"No free floor beside this object for a {width} m body.")
    path = astar(fits, begin, goals)
    if not path:
        raise NoRoute(f"No connected route to this object for a {width} m body.")
    length = sum(math.dist(a, b) for a, b in zip(path, path[1:], strict=False)) * floor.cell
    return {
        "path": [floor.to_world(cell) for cell in simplify(path)],
        "length": round(length, 3),
        "profile": profile,
        "width": width,
        "start_moved": round(math.dist(begin, floor.to_cell(start)) * floor.cell, 3),
        "placeholder": False,
    }


def placeholder_route(start: Point, goal: Point, floor_y: float) -> tuple[list[Point], float]:
    """Return an L-shaped path on the floor. It ignores obstacles, so it isn't a real route."""
    a = (start[0], floor_y, start[2])
    corner = (goal[0], floor_y, start[2])
    b = (goal[0], floor_y, goal[2])
    path = [a, corner, b]
    return path, sum(math.dist(p, q) for p, q in zip(path, path[1:], strict=False))
