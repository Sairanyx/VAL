"""Estimate a rectangular room from a scan: floor, ceiling height and four wall faces.

Wall faces are the outermost dense scan bands near each horizontal edge, at body height.
This is an estimate for a simulated model, not a survey: the room must be roughly a rectangle
aligned with the scene's horizontal axes, and the up direction must be a scene axis.
"""

import numpy as np

BIN = 0.05
STRONG = 0.15
BAND = 1.0  # metres inwards from the outermost points in which a wall face is searched for


def horizontal_axes(up: np.ndarray) -> tuple[int, int, int]:
    up = np.asarray(up, dtype=float)
    up_axis = int(np.argmax(np.abs(up)))
    if abs(up[up_axis]) < 0.99 * np.linalg.norm(up):
        raise ValueError("The room estimate needs the up direction to be a scene axis")
    first, second = (axis for axis in range(3) if axis != up_axis)
    return up_axis, first, second


def wall_face(coords: np.ndarray, outer: float, inward: int) -> tuple[float, float]:
    """Outermost dense band near an edge, and its density relative to the band's peak.

    Equipment often stands just in front of a wall and can be denser than the wall itself, so the
    face is the first bin, coming from outside, with at least STRONG of the peak density.
    """
    lo, hi = sorted((outer - inward * 0.5, outer + inward * BAND))
    counts, edges = np.histogram(coords, bins=max(int(round((hi - lo) / BIN)), 1), range=(lo, hi))
    if not counts.any():
        raise ValueError("No scan points near a room edge")
    order = range(len(counts)) if inward > 0 else range(len(counts) - 1, -1, -1)
    face = next(i for i in order if counts[i] >= STRONG * counts.max())
    return float((edges[face] + edges[face + 1]) / 2), float(counts[face] / counts.max())


def estimate_room(
    positions: np.ndarray,
    opacities: np.ndarray,
    up: list[float],
    floor_along_up: float,
    min_opacity: float = 0.5,
) -> dict:
    up_axis, first, second = horizontal_axes(np.asarray(up))
    unit = np.zeros(3)
    unit[up_axis] = np.sign(up[up_axis])
    solid = opacities > min_opacity
    height = positions @ unit - floor_along_up
    if not solid.any():
        raise ValueError("No solid splats to estimate the room from")
    ceiling = float(np.percentile(height[solid], 99))
    body = solid & (height > 0.5) & (height < min(2.0, ceiling - 0.2))
    if body.sum() < 100:
        raise ValueError("Too few splats at body height to find walls")
    faces, support = {}, {}
    for name, axis in (("first", first), ("second", second)):
        coords = positions[body, axis]
        low, high = np.percentile(coords, [1, 99])
        faces[f"{name}_min"], support[f"{name}_min"] = wall_face(coords, low, +1)
        faces[f"{name}_max"], support[f"{name}_max"] = wall_face(coords, high, -1)
    return {
        "up": unit.tolist(),
        "axes": [first, second],
        "floor_along_up": float(floor_along_up),
        "ceiling_height": round(ceiling, 3),
        "faces": {key: round(value, 3) for key, value in faces.items()},
        "wall_support": {key: round(value, 3) for key, value in support.items()},
        "method": "outermost dense scan band near each room edge at 0.5-2.0 m height; "
        "ceiling is the 99th percentile height of solid splats",
    }
