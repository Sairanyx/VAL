"""Decide whether a movable object can stand somewhere: not inside other objects or walls.

Boxes are loose, especially around long pipes, so a slight overlap doesn't count. Things an object
carries or that were split from it share its box at its starting spot, and travel with it.

The room is cluttered, and most objects already touch something where they stand. So a move is only
refused if it makes things worse than at the starting spot, or an object could never be moved.
"""

from dataclasses import dataclass, field

import numpy as np

from app.nav.grid import NavGrid

MIN_OVERLAP = 0.15  # share of the smaller box inside the other, before it counts as a collision
PART_OF_OBJECT = 0.5  # share of a box inside the moving object's own box, at its starting spot
MIN_FREE_FLOOR = 0.8  # share of the floor under an object that must be free
WORSE_BY = 0.05  # how much more overlap or blocked floor than at the start counts as worse
TINY_VOLUME = 0.001  # cubic metres: stray fragments this small don't block anything
WALKS_THROUGH = {"cable", "hose", "light fixture"}  # Thin or overhead: never in the way.


@dataclass
class MoveCheck:
    ok: bool
    reason: str = ""
    blockers: list[str] = field(default_factory=list)


def box_of(asset: dict) -> tuple[np.ndarray, np.ndarray]:
    first, second = np.asarray(asset["bbox_min"], float), np.asarray(asset["bbox_max"], float)
    return np.minimum(first, second), np.maximum(first, second)


def shared_volume(a: tuple[np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray]) -> float:
    return float(np.prod(np.clip(np.minimum(a[1], b[1]) - np.maximum(a[0], b[0]), 0, None)))


def volume(box: tuple[np.ndarray, np.ndarray]) -> float:
    return float(np.prod(box[1] - box[0]))


def overlap_share(a: tuple[np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray]) -> float:
    """Return how much of the smaller box lies inside the other."""
    return shared_volume(a, b) / max(min(volume(a), volume(b)), 1e-9)


def free_floor_share(grid: NavGrid, box: tuple[np.ndarray, np.ndarray]) -> float:
    """Return the share of the floor under a box that the map says is free."""
    axes = list(grid.axes)
    low = np.floor((box[0][axes] - grid.origin) / grid.cell).astype(int)
    high = np.ceil((box[1][axes] - grid.origin) / grid.cell).astype(int)
    rows, cols = grid.free.shape
    wanted = max(int(high[0] - low[0]), 1) * max(int(high[1] - low[1]), 1)
    patch = grid.free[max(low[0], 0) : min(high[0], rows), max(low[1], 0) : min(high[1], cols)]
    return float(patch.sum()) / wanted


def center_is_free(grid: NavGrid, box: tuple[np.ndarray, np.ndarray]) -> bool:
    """Return whether the floor under a box's center is free, so it can't straddle a thin wall."""
    axes = list(grid.axes)
    cell = np.floor((((box[0] + box[1]) / 2)[axes] - grid.origin) / grid.cell).astype(int)
    rows, cols = grid.free.shape
    return bool(0 <= cell[0] < rows and 0 <= cell[1] < cols and grid.free[cell[0], cell[1]])


def check_move(
    asset: dict,
    position: list[float],
    others: list[dict],
    grid: NavGrid | None,
    home: dict | None = None,
) -> MoveCheck:
    """Check an object at a new center. `home` is its record before any moves, if it has moved."""
    low, high = box_of(asset)
    shift = np.asarray(position, float) - np.asarray(asset["center"], float)
    moved = (low + shift, high + shift)
    start = box_of(home or asset)

    blockers = []
    for other in others:
        if other["object_id"] == asset["object_id"] or other.get("label") in WALKS_THROUGH:
            continue
        box = box_of(other)
        if volume(box) < TINY_VOLUME:
            continue
        if shared_volume(box, start) / max(volume(box), 1e-9) >= PART_OF_OBJECT:
            continue
        overlap = overlap_share(moved, box)
        if overlap >= MIN_OVERLAP and overlap > overlap_share(start, box) + WORSE_BY:
            blockers.append(other)
    if blockers:
        blockers.sort(key=lambda other: -overlap_share(moved, box_of(other)))
        first = blockers[0]
        return MoveCheck(
            False,
            f"It would overlap {first.get('label', 'an object')} {first['object_id']}",
            [other["object_id"] for other in blockers],
        )
    if grid is not None:
        free = free_floor_share(grid, moved)
        too_little = free < MIN_FREE_FLOOR and free < free_floor_share(grid, start) - WORSE_BY
        if too_little or (not center_is_free(grid, moved) and center_is_free(grid, start)):
            reason = "There's no free floor here: a wall or fixed equipment is in the way"
            return MoveCheck(False, reason)
    return MoveCheck(True)
