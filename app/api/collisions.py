"""Decide whether a movable object can stand somewhere: not inside other objects or walls.

Boxes are loose, especially around long pipes, so a slight overlap doesn't count. Things an object
carries or that were split from it share its box at its starting spot, and travel with it.

The room is cluttered, and most objects already touch something where they stand. So a move is only
refused if it makes things worse than at the starting spot, or an object could never be moved.

A turned object is checked by its turned footprint, not the larger upright box around it, so turning
something where it stands doesn't look like a collision. The floor map was made from the scan, which
saw each object where it stood, so an object's own spot counts as free floor for it.
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
FLOOR_AXES = (0, 2)  # the scene's floor plane is x and z, with y up or down
UP_AXIS = 1

Box = tuple[np.ndarray, np.ndarray]


@dataclass
class MoveCheck:
    ok: bool
    reason: str = ""
    blockers: list[str] = field(default_factory=list)


@dataclass
class Footprint:
    """An upright box, maybe turned: its corners on the floor, in order, and its height range."""

    corners: np.ndarray  # 4 x 2, along FLOOR_AXES
    low: float
    high: float

    def volume(self) -> float:
        return polygon_area(self.corners) * (self.high - self.low)


def box_of(asset: dict) -> Box:
    first, second = np.asarray(asset["bbox_min"], float), np.asarray(asset["bbox_max"], float)
    return np.minimum(first, second), np.maximum(first, second)


def shared_volume(a: Box, b: Box) -> float:
    return float(np.prod(np.clip(np.minimum(a[1], b[1]) - np.maximum(a[0], b[0]), 0, None)))


def volume(box: Box) -> float:
    return float(np.prod(box[1] - box[0]))


def overlap_share(a: Box, b: Box) -> float:
    """Return how much of the smaller box lies inside the other."""
    return shared_volume(a, b) / max(min(volume(a), volume(b)), 1e-9)


def footprint(
    asset: dict, position: list[float] | None = None, yaw: float | None = None
) -> Footprint:
    """Return an object's footprint at a center and angle, by default where and how it stands now.

    The angle turns its unturned size, the way the viewer turns it: about the up axis, like
    three.js's rotation.y in scene coordinates.
    """
    low, high = box_of(asset)
    center = np.asarray(asset["center"], float)
    spot = center if position is None else np.asarray(position, float)
    angle = float(asset.get("yaw") or 0.0) if yaw is None else float(yaw)
    size = np.asarray(asset.get("base_size") or (high - low), float)
    if not angle:
        size = high - low  # Unturned, the box itself is exact.
    half_x, half_z = size[FLOOR_AXES[0]] / 2, size[FLOOR_AXES[1]] / 2
    local = np.array([[-half_x, -half_z], [half_x, -half_z], [half_x, half_z], [-half_x, half_z]])
    cos, sin = np.cos(angle), np.sin(angle)
    turned = np.stack(
        [local[:, 0] * cos + local[:, 1] * sin, -local[:, 0] * sin + local[:, 1] * cos], 1
    )
    rise = spot[UP_AXIS] - center[UP_AXIS]
    return Footprint(turned + spot[list(FLOOR_AXES)], low[UP_AXIS] + rise, high[UP_AXIS] + rise)


def polygon_area(corners: np.ndarray) -> float:
    if len(corners) < 3:
        return 0.0
    x, z = corners[:, 0], corners[:, 1]
    return float(abs(np.dot(x, np.roll(z, -1)) - np.dot(z, np.roll(x, -1))) / 2)


def clip_to_box(corners: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    """Return the part of a convex polygon inside an upright rectangle, both on the floor."""
    points = [tuple(p) for p in corners]
    for axis, limit, keep_below in (
        (0, low[0], False),
        (0, high[0], True),
        (1, low[1], False),
        (1, high[1], True),
    ):
        if not points:
            break
        kept = []
        for i, current in enumerate(points):
            previous = points[i - 1]
            if on_side(current, axis, limit, keep_below):
                if not on_side(previous, axis, limit, keep_below):
                    kept.append(crossing(previous, current, axis, limit))
                kept.append(current)
            elif on_side(previous, axis, limit, keep_below):
                kept.append(crossing(previous, current, axis, limit))
        points = kept
    return np.array(points, float).reshape(-1, 2)


def on_side(point: tuple, axis: int, limit: float, below: bool) -> bool:
    return point[axis] <= limit if below else point[axis] >= limit


def crossing(a: tuple, b: tuple, axis: int, limit: float) -> tuple:
    t = (limit - a[axis]) / (b[axis] - a[axis])
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))


def shared_with_box(shape: Footprint, box: Box) -> float:
    """Return the volume a footprint shares with an upright box."""
    height = min(shape.high, box[1][UP_AXIS]) - max(shape.low, box[0][UP_AXIS])
    if height <= 0:
        return 0.0
    flat = list(FLOOR_AXES)
    return polygon_area(clip_to_box(shape.corners, box[0][flat], box[1][flat])) * height


def shape_overlap(shape: Footprint, box: Box) -> float:
    """Return how much of the smaller of a footprint and a box lies inside the other."""
    return shared_with_box(shape, box) / max(min(shape.volume(), volume(box)), 1e-9)


def floor_cells(grid: NavGrid, shape: Footprint, own: list[Box]) -> tuple[int, int, bool]:
    """Count the map cells under a footprint and the free ones, and say if its center's is free.

    Cells under `own`, the object's own spots, count as free: the scan saw the object there.
    """
    axes = list(grid.axes)
    rows, cols = grid.free.shape
    low = np.floor((shape.corners.min(0) - grid.origin) / grid.cell).astype(int)
    high = np.ceil((shape.corners.max(0) - grid.origin) / grid.cell).astype(int)
    row_ids = np.arange(low[0], max(high[0], low[0] + 1))
    col_ids = np.arange(low[1], max(high[1], low[1] + 1))
    cells = np.stack(np.meshgrid(row_ids, col_ids, indexing="ij"), -1).reshape(-1, 2)
    centers = (cells + 0.5) * grid.cell + grid.origin
    under = inside_polygon(centers, shape.corners)
    middle = shape.corners.mean(0)
    middle_cell = np.floor((middle - grid.origin) / grid.cell).astype(int)
    if not under.any():  # Smaller than a cell: the cell under its center.
        cells, centers, under = middle_cell[None], middle[None], np.array([True])
    cells, centers = cells[under], centers[under]

    def free(cells: np.ndarray, points: np.ndarray) -> np.ndarray:
        on_map = (
            (cells[:, 0] >= 0) & (cells[:, 0] < rows) & (cells[:, 1] >= 0) & (cells[:, 1] < cols)
        )
        result = np.zeros(len(cells), bool)
        result[on_map] = grid.free[cells[on_map, 0], cells[on_map, 1]]
        for box in own:
            flat = (box[0][axes], box[1][axes])
            result |= ((points >= flat[0]) & (points <= flat[1])).all(1)
        return result

    center_free = bool(free(middle_cell[None], middle[None])[0])
    return len(cells), int(free(cells, centers).sum()), center_free


def inside_polygon(points: np.ndarray, corners: np.ndarray) -> np.ndarray:
    """Return which points lie inside a convex polygon, whichever way round its corners go."""
    signs = []
    for i in range(len(corners)):
        a, b = corners[i], corners[(i + 1) % len(corners)]
        signs.append((b[0] - a[0]) * (points[:, 1] - a[1]) - (b[1] - a[1]) * (points[:, 0] - a[0]))
    signs = np.stack(signs, 1)
    return (signs >= 0).all(1) | (signs <= 0).all(1)


def check_move(
    asset: dict,
    position: list[float],
    others: list[dict],
    grid: NavGrid | None,
    home: dict | None = None,
    yaw: float | None = None,
) -> MoveCheck:
    """Check an object at a new center and angle. `home` is its record before any moves.

    `yaw` is the angle to check, or None to keep the one it has.
    """
    moved = footprint(asset, position, yaw)
    start_record = home or asset
    start = footprint(start_record)
    start_box = box_of(start_record)

    blockers = []
    for other in others:
        if other["object_id"] == asset["object_id"] or other.get("label") in WALKS_THROUGH:
            continue
        box = box_of(other)
        if volume(box) < TINY_VOLUME:
            continue
        if shared_volume(box, start_box) / max(volume(box), 1e-9) >= PART_OF_OBJECT:
            continue
        overlap = shape_overlap(moved, box)
        if overlap >= MIN_OVERLAP and overlap > shape_overlap(start, box) + WORSE_BY:
            blockers.append((overlap, other))
    if blockers:
        blockers.sort(key=lambda pair: -pair[0])
        first = blockers[0][1]
        return MoveCheck(
            False,
            f"It would overlap {first.get('label', 'an object')} {first['object_id']}",
            [other["object_id"] for _, other in blockers],
        )
    if grid is not None:
        own = [start_box, box_of(asset)]
        wanted, free, center_free = floor_cells(grid, moved, own)
        start_wanted, start_free, start_center_free = floor_cells(grid, start, own)
        share = free / max(wanted, 1)
        too_little = share < MIN_FREE_FLOOR and share < start_free / max(start_wanted, 1) - WORSE_BY
        if too_little or (not center_free and start_center_free):
            reason = "There's no free floor here: a wall or fixed equipment is in the way"
            return MoveCheck(False, reason)
    return MoveCheck(True)
