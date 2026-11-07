"""Group splats into rough objects by 3D connectivity, with no learned models.

    uv run --no-project --with numpy --with scipy python -m app.scene.cluster clean.ply OUT_DIR

Only a stand-in for Sasha's output, so the viewer and routing can test real objects early. It can't
name anything, and touching objects merge. Writes rough_labels.npy, in `splat_labels.npy` format,
and rough_assets.json, with `label: "unknown"` and `mapping: null`. Coordinates stay in scene axes.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy import ndimage

from app.scene.load import Splats, estimate_floor, read_splats


def cluster_labels(
    splats: Splats,
    up: tuple[float, float, float],
    voxel_size: float = 0.03,
    min_opacity: float = 0.5,
    floor_margin: float = 0.08,
    ceiling_share: float = 0.12,
    min_voxels: int = 8,
    max_object_extent: float = 2.5,
    min_splats: int = 200,
) -> np.ndarray:
    """Return one label per splat: an object index, or -1 for background.

    Floor and ceiling bands are removed first, because they would connect everything. Anything
    larger than `max_object_extent` becomes background, which catches walls and long pipe runs.
    Objects with under `min_splats` splats also become background. Index 0 is the largest object.
    The default voxel size and opacity gave the most solid objects in a sweep on Equipment Room.
    """
    positions = splats.positions
    up_axis = np.asarray(up, dtype=np.float64)
    up_axis /= np.linalg.norm(up_axis)
    heights = positions @ up_axis
    floor = estimate_floor(positions, up)
    top = np.percentile(heights, 99.5)
    ceiling = top - ceiling_share * (top - floor)

    solid = splats.opacities >= min_opacity
    solid &= (heights > floor + floor_margin) & (heights < ceiling)

    origin = positions.min(axis=0)
    cells = np.floor((positions - origin) / voxel_size).astype(np.int32)
    occupied = np.zeros(cells.max(axis=0) + 1, dtype=bool)
    occupied[tuple(cells[solid].T)] = True

    grid, count = ndimage.label(occupied, structure=np.ones((3, 3, 3), dtype=bool))
    if not count:
        return np.full(len(splats), -1, dtype=np.int32)
    indices = np.arange(1, count + 1)
    sizes = ndimage.sum_labels(occupied, grid, indices)
    slices = ndimage.find_objects(grid)
    largest_cells = max_object_extent / voxel_size

    keep = np.zeros(count + 1, dtype=bool)
    for component in range(count):
        extent = max(piece.stop - piece.start for piece in slices[component])
        keep[component + 1] = sizes[component] >= min_voxels and extent <= largest_cells

    # Faint splats inside a kept voxel join that object, and floor and ceiling stay background.
    components = grid[tuple(cells.T)]
    components[~keep[components]] = 0
    components[(heights <= floor + floor_margin) | (heights >= ceiling)] = 0

    # Renumber by final splat count, so index 0 is the largest object.
    totals = np.bincount(components, minlength=count + 1)
    totals[0] = 0
    labels_by_component = np.full(count + 1, -1, dtype=np.int32)
    kept = [c for c in np.argsort(-totals) if totals[c] >= min_splats]
    labels_by_component[kept] = np.arange(len(kept), dtype=np.int32)
    return labels_by_component[components]


def to_assets(splats: Splats, labels: np.ndarray, scene_id: str, floor_y: float | None) -> dict:
    """Return a dictionary in the same shape as fixtures/sample_assets.json."""
    positions = splats.positions
    assets = []
    for label in range(int(labels.max()) + 1 if len(labels) else 0):
        members = positions[labels == label]
        low, high = np.percentile(members, [1, 99], axis=0)
        assets.append(
            {
                "object_id": f"obj-{label + 1:04d}",
                "label": "unknown",
                "label_confidence": 0.0,
                "center": ((low + high) / 2).round(3).tolist(),
                "bbox_min": low.round(3).tolist(),
                "bbox_max": high.round(3).tolist(),
                "splats": len(members),
                "mapping": None,
            }
        )
    return {
        "_note": "Rough 3D clustering, not SAM. Unnamed, and touching objects may be merged.",
        "scene_id": scene_id,
        "floor_y": floor_y,
        "assets": assets,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--up", type=float, nargs=3, default=(0.0, -1.0, 0.0))
    parser.add_argument("--scene-id", default="equipment_room")
    args = parser.parse_args()

    splats = read_splats(args.scene)
    up = tuple(args.up)
    labels = cluster_labels(splats, up)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    np.save(args.out_dir / "rough_labels.npy", labels)
    floor_y = None
    if up == (0.0, -1.0, 0.0):
        floor_y = -estimate_floor(splats.positions, up)
    assets = to_assets(splats, labels, args.scene_id, floor_y)
    (args.out_dir / "rough_assets.json").write_text(json.dumps(assets, indent=1))
    extents = [np.subtract(a["bbox_max"], a["bbox_min"]).max() for a in assets["assets"]]
    print(
        json.dumps(
            {
                "objects": len(assets["assets"]),
                "splats_in_objects": int((labels >= 0).sum()),
                "splats_total": len(labels),
                "median_extent": round(float(np.median(extents)), 2) if extents else 0,
            }
        )
    )


if __name__ == "__main__":
    main()
