"""Decide which splats belong to each movable object, using its segmentation masks from many views.

    python -m app.scene.movable_members SCENE.ply ASSETS.json OBJECT_MASKS.json MASKS_DIR OUT.npz \\
        --views RENDER_DIR RENDER_DIR

A splat near an object joins it if it lands inside the object's masks in most views that see it.
Its neighbours land inside only now and then, so this separates a cart from the box beside it,
which a box alone can't. Saves members by position, so they apply to lighter copies of the scene.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from app.scene.load import read_splats
from app.scene.split_movable import BOX_KEYS, inside_box, low_parts

MAX_VIEWS = 40
MIN_VIEWS = 3
MIN_SHARE = 0.6  # share of a splat's views in which it must land inside the object's mask
MERGE_INSIDE = 0.7  # share of a small box inside a larger one for it to count as part of it
MERGE_MAX_SMALL = 0.5  # the smaller box can be at most this share of the larger one's volume


def box_volume(asset: dict) -> float:
    sides = np.asarray(asset["bbox_max"]) - np.asarray(asset["bbox_min"])
    return float(np.prod(np.abs(sides)))


def share_inside(small: dict, large: dict) -> float:
    """Return how much of the first box lies inside the second."""
    low = np.maximum(small["bbox_min"], large["bbox_min"])
    high = np.minimum(small["bbox_max"], large["bbox_max"])
    return float(np.prod(np.clip(high - low, 0, None))) / max(box_volume(small), 1e-9)


def merge_fragments(assets: list[dict]) -> dict[str, list[str]]:
    """Return each whole object and the fragments of it: smaller boxes mostly inside larger ones."""
    ordered = sorted(assets, key=box_volume, reverse=True)
    groups: dict[str, list[str]] = {}
    wholes: list[dict] = []
    for asset in ordered:
        home = next(
            (
                whole
                for whole in wholes
                if box_volume(asset) <= MERGE_MAX_SMALL * box_volume(whole)
                and share_inside(asset, whole) >= MERGE_INSIDE
            ),
            None,
        )
        if home is None:
            wholes.append(asset)
            groups[asset["object_id"]] = []
        else:
            groups[home["object_id"]].append(asset["object_id"])
    return groups


def vote_shares(
    positions: np.ndarray, views: list[tuple[np.ndarray, np.ndarray, np.ndarray]]
) -> tuple[np.ndarray, np.ndarray]:
    """Return each point's share of views landing in the mask, and how many views saw it.

    Each view is (intrinsics, world_to_camera, mask). A point outside the image isn't counted.
    """
    inside = np.zeros(len(positions), dtype=np.int32)
    seen = np.zeros(len(positions), dtype=np.int32)
    for camera, world_to_camera, mask in views:
        local = positions @ world_to_camera[:3, :3].T + world_to_camera[:3, 3]
        depth = local[:, 2]
        ahead = depth > 0.05
        with np.errstate(divide="ignore", invalid="ignore"):
            cols = camera[0, 0] * local[:, 0] / depth + camera[0, 2]
            rows = camera[1, 1] * local[:, 1] / depth + camera[1, 2]
        height, width = mask.shape
        visible = ahead & (cols >= 0) & (cols < width) & (rows >= 0) & (rows < height)
        seen += visible
        hits = np.flatnonzero(visible)
        inside[hits] += mask[rows[hits].astype(int), cols[hits].astype(int)]
    return inside / np.maximum(seen, 1), seen


def load_cameras(render_dirs: list[Path]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    cameras = {}
    for directory in render_dirs:
        meta = json.loads((directory / "cameras.json").read_text())
        intrinsics = np.asarray(meta["intrinsics"], dtype=np.float64)
        for entry in meta["cameras"]:
            matrix = np.asarray(entry["world_to_camera"], dtype=np.float64)
            cameras[entry["name"]] = (intrinsics, matrix)
    return cameras


def object_views(
    entries: list[list], cameras: dict, masks_dir: Path
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Load an object's masks, evenly spread, merging masks from the same view."""
    by_view: dict[str, list[int]] = {}
    for view, mask_id in entries:
        by_view.setdefault(view, []).append(mask_id)
    names = sorted(by_view)
    if len(names) > MAX_VIEWS:
        names = [names[i] for i in np.linspace(0, len(names) - 1, MAX_VIEWS).astype(int)]
    views = []
    for name in names:
        ids = np.array(Image.open(masks_dir / "object_mask" / f"{name}.png"))
        intrinsics, matrix = cameras[name]
        views.append((intrinsics, matrix, np.isin(ids, by_view[name])))
    return views


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("assets", type=Path)
    parser.add_argument("object_masks", type=Path)
    parser.add_argument("masks_dir", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--views", type=Path, nargs="+", required=True)
    parser.add_argument("--up", type=float, nargs=3, default=(0.0, -1.0, 0.0))
    args = parser.parse_args()

    document = json.loads(args.assets.read_text())
    assets = [a for a in document["assets"] if a["mobility"] == "movable"]
    by_id = {asset["object_id"]: asset for asset in assets}
    masks = json.loads(args.object_masks.read_text())
    cameras = load_cameras(args.views)
    splats = read_splats(args.scene)
    positions = splats.positions
    up = np.asarray(args.up, dtype=np.float64)
    floor_height = float(document["floor_y"]) * float(up @ np.array([0.0, 1.0, 0.0]))
    colors = np.stack([splats.data[f"f_dc_{i}"] for i in range(3)], axis=1)

    groups = merge_fragments(assets)
    saved = {}
    summary = {}
    for whole, fragments in groups.items():
        parts = [by_id[whole], *(by_id[fragment] for fragment in fragments)]
        low = np.min([np.minimum(p["bbox_min"], p["bbox_max"]) for p in parts], axis=0)
        high = np.max([np.maximum(p["bbox_min"], p["bbox_max"]) for p in parts], axis=0)
        box = {BOX_KEYS[0]: low, BOX_KEYS[1]: high}
        near = inside_box(positions, box, floor_height, up)
        near |= low_parts(splats, box, floor_height, up, colors)
        entries = [entry for part in parts for entry in masks.get(part["object_id"], [])]
        views = object_views(entries, cameras, args.masks_dir)
        candidates = np.flatnonzero(near)
        shares, seen = vote_shares(positions[candidates], views)
        chosen = candidates[(shares >= MIN_SHARE) & (seen >= MIN_VIEWS)]
        saved[whole] = positions[chosen].astype(np.float32)
        summary[whole] = {
            "label": by_id[whole].get("label"),
            "fragments": fragments,
            "views": len(views),
            "in_box": len(candidates),
            "members": len(chosen),
            "bbox_min": [round(float(v), 3) for v in low],
            "bbox_max": [round(float(v), 3) for v in high],
        }
        print(whole, summary[whole]["label"], len(views), len(candidates), len(chosen), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out, **saved)
    args.out.with_suffix(".json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
