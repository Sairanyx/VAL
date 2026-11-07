"""Find splats floating in empty space, using what rendered views can see through.

Dense scenes have floaters at body height, and counting splats alone can't tell them from a real
object. A ray that passes through a spot on its way to a surface behind shows that spot is empty,
so a spot that rays mostly pass through holds floaters. The inside of real objects is never passed
through, so it stays solid.
"""

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

import numpy as np

CELL = 0.05
HEIGHT_CELL = 0.1
SURFACE_MARGIN = 0.15  # metres before a surface where a ray stops counting, for depth noise
START = 0.1  # metres from the camera where a ray starts counting
PIXEL_STEP = 6
MIN_SOLID_SHARE = 0.2  # share of rays that must end in a spot, rather than pass, for it to be solid

View = tuple[np.ndarray, np.ndarray, np.ndarray]  # intrinsics, world_to_camera, depth


def load_views(directory: Path) -> Iterator[View]:
    """Yield the views in a render folder from `app.scene.render`."""
    meta = json.loads((directory / "cameras.json").read_text())
    intrinsics = np.asarray(meta["intrinsics"], dtype=np.float64)
    for camera in meta["cameras"]:
        depth = np.load(directory / "depth" / f"{camera['name']}.npy")
        yield intrinsics, np.asarray(camera["world_to_camera"], dtype=np.float64), depth


def carved_splats(
    positions: np.ndarray,
    views: Iterable[View],
    up: tuple[float, float, float],
    floor_height: float,
    body_band: tuple[float, float],
    pixel_step: int = PIXEL_STEP,
) -> np.ndarray:
    """Return a mask of splats at body height in spots that rays mostly pass through."""
    direction = np.asarray(up, dtype=np.float64)
    up_axis = int(np.argmax(np.abs(direction)))
    axes = [i for i in range(3) if i != up_axis]
    origin = positions[:, axes].min(axis=0)
    size = positions[:, axes].max(axis=0) - origin
    columns = (np.floor(size / CELL).astype(np.int64) + 1).tolist()
    layers = int(np.ceil((body_band[1] - body_band[0]) / HEIGHT_CELL))
    shape = (columns[0], columns[1], layers)
    total = int(np.prod(shape))

    def voxels(points: np.ndarray) -> np.ndarray:
        """Return voxel numbers, with -1 for points outside the grid."""
        col = np.floor((points[:, axes] - origin) / CELL).astype(np.int64)
        layer = np.floor((points @ direction - floor_height - body_band[0]) / HEIGHT_CELL)
        layer = layer.astype(np.int64)
        inside = (col >= 0).all(axis=1) & (col[:, 0] < shape[0]) & (col[:, 1] < shape[1])
        inside &= (layer >= 0) & (layer < layers)
        numbers = np.full(len(points), -1, dtype=np.int64)
        numbers[inside] = np.ravel_multi_index(
            (col[inside, 0], col[inside, 1], layer[inside]), shape
        )
        return numbers

    def tally(points: np.ndarray) -> np.ndarray:
        numbers = voxels(points)
        return np.bincount(numbers[numbers >= 0], minlength=total)

    passed = np.zeros(total, dtype=np.int64)
    ended = np.zeros(total, dtype=np.int64)
    for intrinsics, world_to_camera, depth in views:
        rows, cols = np.nonzero(depth[::pixel_step, ::pixel_step] > 0)
        if not len(rows):
            continue
        z = depth[rows * pixel_step, cols * pixel_step]
        x = (cols * pixel_step + 0.5 - intrinsics[0, 2]) / intrinsics[0, 0] * z
        y = (rows * pixel_step + 0.5 - intrinsics[1, 2]) / intrinsics[1, 1] * z
        rotation, shift = world_to_camera[:3, :3], world_to_camera[:3, 3]
        ends = (np.stack([x, y, z], axis=1) - shift) @ rotation
        camera = -rotation.T @ shift
        rays = ends - camera
        lengths = np.linalg.norm(rays, axis=1)
        rays /= lengths[:, None]
        ended += tally(ends)
        steps = np.arange(START, lengths.max(), CELL)
        ray, step = np.nonzero(steps[None, :] < (lengths - SURFACE_MARGIN)[:, None])
        passed += tally(camera + rays[ray] * steps[step, None])

    # A spot no ray reached has no evidence against it, so it stays solid.
    seen = passed + ended
    empty = (seen > 0) & (ended < MIN_SOLID_SHARE * seen)
    numbers = voxels(positions)
    carved = np.zeros(len(positions), dtype=bool)
    carved[numbers >= 0] = empty[numbers[numbers >= 0]]
    return carved
