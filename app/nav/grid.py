"""Build the permanent floor map from a splat scene, using Viktor's loader and cleaning.

    uv run python -m app.nav.grid "Equipment Room.ply" --out nav_grid.npz --preview floor.png

A cell is free if floor was seen there and nothing solid is at body height. Everything else counts
as blocked, including areas the scan never saw. Clearance is the distance to the nearest blocked
cell, so one map serves every body size: a body fits where clearance is at least its radius.
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import ndimage

from app.scene.load import clean_mask, estimate_floor, read_splats

CELL = 0.05
FLOOR_BAND = 0.08
BODY_BAND = (0.15, 1.9)
LOW_BAND = (0.15, 0.6)
SOLID_OPACITY = 0.3
SOLID_HITS = 3
FLOOR_HITS = 2
PERSON_RADIUS = 0.3


@dataclass
class NavGrid:
    origin: np.ndarray  # world position of cell (0, 0) on the two floor axes
    cell: float
    floor_height: float  # along `up`
    up: np.ndarray
    axes: tuple[int, int]  # the two position columns that make up the floor
    free: np.ndarray
    clearance: np.ndarray  # metres, for bodies up to the top of BODY_BAND
    clearance_low: np.ndarray  # metres, for low robots that can pass under things

    def save(self, path: Path) -> None:
        np.savez_compressed(
            path,
            origin=self.origin,
            cell=self.cell,
            floor_height=self.floor_height,
            up=self.up,
            axes=np.asarray(self.axes),
            free=self.free,
            clearance=self.clearance.astype(np.float32),
            clearance_low=self.clearance_low.astype(np.float32),
        )


def _count(cols: np.ndarray, rows: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    counts = np.zeros(shape, dtype=np.int32)
    np.add.at(counts, (cols, rows), 1)
    return counts


def largest_region(mask: np.ndarray) -> np.ndarray:
    labels, found = ndimage.label(mask)
    if not found:
        return np.zeros_like(mask)
    return labels == 1 + int(np.argmax(np.bincount(labels.ravel())[1:]))


def build_nav_grid(
    positions: np.ndarray,
    opacities: np.ndarray,
    up: tuple[float, float, float],
    floor_height: float | None = None,
    cell: float = CELL,
    margin: float = 0.2,
) -> NavGrid:
    """Build the map. `up` must point along one axis, such as (0, -1, 0)."""
    direction = np.asarray(up, dtype=np.float64)
    up_axis = int(np.argmax(np.abs(direction)))
    if floor_height is None:
        floor_height = estimate_floor(positions, up)
    heights = positions @ direction - floor_height
    axes = tuple(i for i in range(3) if i != up_axis)
    origin = np.percentile(positions[:, axes], 0.1, axis=0) - margin
    top = np.percentile(positions[:, axes], 99.9, axis=0) + margin
    shape = tuple(np.ceil((top - origin) / cell).astype(int))
    cells = np.floor((positions[:, axes] - origin) / cell).astype(np.int64)
    inside = ((cells >= 0) & (cells < np.asarray(shape))).all(axis=1)
    solid = inside & (opacities >= SOLID_OPACITY)

    def counts(mask: np.ndarray) -> np.ndarray:
        return _count(cells[mask, 0], cells[mask, 1], shape)

    def blocked(band: tuple[float, float]) -> np.ndarray:
        return counts(solid & (heights >= band[0]) & (heights <= band[1])) >= SOLID_HITS

    # Closing fills small gaps in the scanned floor, without crossing wider unseen areas.
    floor_seen = counts(inside & (np.abs(heights) <= FLOOR_BAND)) >= FLOOR_HITS
    floor_seen = ndimage.binary_closing(floor_seen, iterations=2)
    free = floor_seen & ~blocked(BODY_BAND)
    low_free = floor_seen & ~blocked(LOW_BAND)
    return NavGrid(
        origin=origin,
        cell=cell,
        floor_height=float(floor_height),
        up=direction,
        axes=axes,
        free=free,
        clearance=ndimage.distance_transform_edt(free) * cell,
        clearance_low=ndimage.distance_transform_edt(low_free) * cell,
    )


def summarize(grid: NavGrid) -> dict:
    area = grid.cell**2
    summary = {
        "shape": list(grid.free.shape),
        "cell": grid.cell,
        "floor_height_along_up": round(grid.floor_height, 3),
        "free_m2": round(float(grid.free.sum()) * area, 1),
    }
    for width in (0.3, 0.6, 0.8, 1.0, 1.5):
        fits = grid.clearance >= width / 2
        summary[f"connected_m2_width_{width}"] = round(float(largest_region(fits).sum()) * area, 1)
    return summary


def save_preview(grid: NavGrid, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    extent = [
        grid.origin[1],
        grid.origin[1] + grid.free.shape[1] * grid.cell,
        grid.origin[0] + grid.free.shape[0] * grid.cell,
        grid.origin[0],
    ]
    walk = largest_region(grid.clearance >= PERSON_RADIUS)
    fig, (left, right) = plt.subplots(1, 2, figsize=(14, 6))
    left.imshow(grid.free, cmap="gray", extent=extent)
    left.set_title("Free floor")
    shown = np.ma.masked_where(~grid.free, grid.clearance)
    image = right.imshow(shown, cmap="viridis", vmin=0, vmax=1.0, extent=extent)
    right.contour(
        walk, levels=[0.5], colors="red", extent=(extent[0], extent[1], extent[3], extent[2])
    )
    right.set_title("Clearance in metres. Red: connected area for a 0.6 m person")
    fig.colorbar(image, ax=right)
    fig.tight_layout()
    fig.savefig(path, dpi=100)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--up", type=float, nargs=3, default=(0.0, -1.0, 0.0))
    args = parser.parse_args()
    splats = read_splats(args.scene)
    splats = splats[clean_mask(splats)]
    grid = build_nav_grid(splats.positions, splats.opacities, tuple(args.up))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    grid.save(args.out)
    if args.preview:
        save_preview(grid, args.preview)
    print(json.dumps(summarize(grid), indent=2))


if __name__ == "__main__":
    main()
