"""Placeholder route, so the viewer can connect before the floor map exists."""

import math

Point = tuple[float, float, float]


def placeholder_route(start: Point, goal: Point, floor_y: float) -> tuple[list[Point], float]:
    """Return an L-shaped path on the floor. It ignores obstacles, so it isn't a real route."""
    a = (start[0], floor_y, start[2])
    corner = (goal[0], floor_y, start[2])
    b = (goal[0], floor_y, goal[2])
    path = [a, corner, b]
    return path, sum(math.dist(p, q) for p, q in zip(path, path[1:], strict=False))
