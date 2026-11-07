"""Cover an object's splats with a few small boxes, to hide it from the scan without its neighbours.

An object's own bounding box usually holds parts of other things, so hiding that takes them too.
"""

import numpy as np

VOXEL = 0.08  # metres
MIN_SPLATS = 2  # splats a cell needs to count, so that strays don't add boxes
MARGIN = 0.02  # metres around the cover, as splats have some size
MAX_BOXES = 12  # every box is checked against every splat on the GPU


def _merge(cells: set[tuple[int, int, int]]) -> list[tuple[np.ndarray, np.ndarray]]:
    """Join neighbouring cells into boxes, along each axis in turn."""
    boxes = [(np.array(cell), np.array(cell) + 1) for cell in sorted(cells)]
    for axis in range(3):
        others = [other for other in range(3) if other != axis]
        boxes.sort(
            key=lambda box: (
                *[box[0][o] for o in others],
                *[box[1][o] for o in others],
                box[0][axis],
            )
        )
        merged: list[tuple[np.ndarray, np.ndarray]] = []
        for low, high in boxes:
            if merged:
                last_low, last_high = merged[-1]
                same = all(last_low[o] == low[o] and last_high[o] == high[o] for o in others)
                if same and last_high[axis] == low[axis]:
                    last_high[axis] = high[axis]
                    continue
            merged.append((low.copy(), high.copy()))
        boxes = merged
    return boxes


def cover_boxes(
    points: np.ndarray,
    limit: tuple[np.ndarray, np.ndarray] | None = None,
    voxel: float = VOXEL,
    max_boxes: int = MAX_BOXES,
) -> list[dict[str, list[float]]]:
    """Return boxes that together cover the points, coarser if it takes too many.

    `limit` is the object's own box. Labelled splats outside it are strays, and the cover stays
    inside it, so that it can never hide more than the whole box would.
    """
    if limit is not None:
        low_limit, high_limit = np.minimum(*limit), np.maximum(*limit)
        points = points[((points >= low_limit) & (points <= high_limit)).all(axis=1)]
    if not len(points):
        return []
    while True:
        cells, counts = np.unique(np.floor(points / voxel).astype(int), axis=0, return_counts=True)
        kept = cells[counts >= MIN_SPLATS] if (counts >= MIN_SPLATS).any() else cells
        boxes = _merge({tuple(int(v) for v in cell) for cell in kept})
        if len(boxes) <= max_boxes:
            break
        voxel *= 1.5
    result = []
    for low, high in boxes:
        first, second = low * voxel - MARGIN, high * voxel + MARGIN
        if limit is not None:
            first, second = np.maximum(first, low_limit), np.minimum(second, high_limit)
        result.append(
            {
                "bbox_min": [round(float(v), 4) for v in first],
                "bbox_max": [round(float(v), 4) for v in second],
            }
        )
    return result
