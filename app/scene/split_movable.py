"""Cut movable objects out of a scene, so that dragging one in the viewer moves the real thing.

    python -m app.scene.split_movable SCENE.ply ASSETS.json OUT_DIR --objects obj-0067 obj-0008

Writes base.ply, without those objects, plus pieces/OBJECT.ply and pieces.json. Everything inside an
object's box goes with it, including faint splats that carry no label, because leaving those behind
shows as a ghost. It uses positions only, so it works on the full scene and on lighter copies.

Best for free-standing objects: anything else inside the box moves too. An object's box often stops
above its base, so each cut reaches down to the floor.

The floor left behind is dark, so it's replaced with real floor splats copied from a clear spot
nearby, like a clone stamp. That's made up, not scanned: patches.json records where, and nothing but
the viewer should use base.ply. Floor maps and object extraction must use the original scene.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from app.scene.load import Splats, read_splats, write_splats

BOX_MARGIN = 0.03  # metres around the box, to catch splats at its edge
FLOOR_MARGIN = 0.03  # metres above the floor to stop at, so the floor itself stays
BOX_KEYS = ("bbox_min", "bbox_max")
FLOOR_BAND = 0.06  # metres either side of the floor that count as the floor's own splats
PATCH_MARGIN = 0.1  # metres around an object's footprint to replace
SEARCH_RANGE = 3.0  # metres to look for clear floor to copy
SEARCH_STEP = 0.1
RING_WIDTH = 0.15  # metres around the patch whose color the copied floor should match
MIN_DENSITY_SHARE = 0.7  # copied floor must have this share of the floor's splats around the patch
DISTANCE_COST = 0.03  # color difference that one metre of extra distance is worth
MATCH_DISTANCE = 1e-4  # metres: the same splat in another copy of the scene
LOW_PART_OPACITY = 0.3
LOW_PART_DIFFERENCE = 2.0  # summed color difference from the floor, in stored color units
LOW_HEIGHT = 0.6  # metres: boxes starting lower than this above the floor sit on it


def inside_box(
    positions: np.ndarray, asset: dict, floor_height: float, up: np.ndarray
) -> np.ndarray:
    """Return which splats belong to an object: in its box, reaching down to the floor."""
    low = np.minimum(asset["bbox_min"], asset["bbox_max"]) - BOX_MARGIN
    high = np.maximum(asset["bbox_min"], asset["bbox_max"]) + BOX_MARGIN
    axis = int(np.argmax(np.abs(up)))
    across = [i for i in range(3) if i != axis]
    in_box = ((positions[:, across] >= low[across]) & (positions[:, across] <= high[across])).all(1)
    heights = positions @ up
    top = float(max(asset["bbox_min"] @ up, asset["bbox_max"] @ up)) + BOX_MARGIN
    return in_box & (heights > floor_height + FLOOR_MARGIN) & (heights <= top)


def low_parts(
    splats: Splats, asset: dict, floor_height: float, up: np.ndarray, colors: np.ndarray
) -> np.ndarray:
    """Return splats in the floor band under an object that don't look like the floor around it.

    A chair's base lies so low that height alone can't separate it from the floor.
    """
    axis = int(np.argmax(np.abs(up)))
    across = [i for i in range(3) if i != axis]
    low, high = footprint(asset, across)
    center, half = (low + high) / 2, (high - low) / 2
    offsets = np.abs(splats.positions[:, across] - center)
    on_floor = np.abs(splats.positions @ up - floor_height) <= FLOOR_BAND
    under = on_floor & (offsets <= half + BOX_MARGIN).all(axis=1)
    around = on_floor & (offsets <= half + RING_WIDTH).all(axis=1) & ~under
    if not around.any():
        return np.zeros(len(splats), dtype=bool)
    usual = np.median(colors[around], axis=0)
    solid = splats.opacities >= LOW_PART_OPACITY
    return under & solid & (np.abs(colors - usual).sum(axis=1) > LOW_PART_DIFFERENCE)


def split_movable(
    splats: Splats, assets: list[dict], floor_height: float, up: np.ndarray
) -> tuple[Splats, dict[str, Splats]]:
    """Return the scene without these objects, and each object's splats. First box in wins."""
    taken = np.zeros(len(splats), dtype=bool)
    pieces = {}
    colors = np.stack([splats.data[f"f_dc_{i}"] for i in range(3)], axis=1)
    for asset in assets:
        prepared = {key: np.asarray(asset[key], dtype=np.float64) for key in BOX_KEYS}
        members = inside_box(splats.positions, prepared, floor_height, up)
        members |= low_parts(splats, prepared, floor_height, up, colors)
        members &= ~taken
        taken |= members
        pieces[asset["object_id"]] = splats[members]
    return splats[~taken], pieces


def split_by_members(
    splats: Splats, members: dict[str, np.ndarray]
) -> tuple[Splats, dict[str, Splats]]:
    """Split using saved member positions, from `app.scene.movable_members`.

    Matching by position lets one set of members work on the full scene and on lighter copies.
    """
    from scipy.spatial import cKDTree

    tree = cKDTree(splats.positions)
    taken = np.zeros(len(splats), dtype=bool)
    pieces = {}
    for object_id, points in members.items():
        distances, found = tree.query(points, distance_upper_bound=MATCH_DISTANCE)
        mask = np.zeros(len(splats), dtype=bool)
        mask[found[np.isfinite(distances)]] = True
        mask &= ~taken
        taken |= mask
        pieces[object_id] = splats[mask]
    return splats[~taken], pieces


def footprint(asset: dict, across: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Return the two corners of an object's box on the floor."""
    low = np.minimum(asset["bbox_min"], asset["bbox_max"])[across]
    high = np.maximum(asset["bbox_min"], asset["bbox_max"])[across]
    return low, high


def find_clear_floor(
    floor_points: np.ndarray,
    colors: np.ndarray,
    center: np.ndarray,
    size: np.ndarray,
    blockers: np.ndarray,
) -> np.ndarray | None:
    """Return the center of a clear area of floor like the one around a patch, or None.

    `blockers` holds (low, high) footprints, of shape (N, 4), that must not overlap it.
    """
    in_ring = (np.abs(floor_points - center) <= size / 2 + RING_WIDTH).all(axis=1)
    in_patch = (np.abs(floor_points - center) <= size / 2).all(axis=1)
    ring = in_ring & ~in_patch
    if not ring.any():
        return None
    wanted = np.median(colors[ring], axis=0)
    ring_area = np.prod(size + 2 * RING_WIDTH) - np.prod(size)
    needed = MIN_DENSITY_SHARE * ring.sum() / ring_area * np.prod(size)
    best, best_score = None, np.inf
    for dx in np.arange(-SEARCH_RANGE, SEARCH_RANGE + SEARCH_STEP / 2, SEARCH_STEP):
        for dz in np.arange(-SEARCH_RANGE, SEARCH_RANGE + SEARCH_STEP / 2, SEARCH_STEP):
            spot = center + [dx, dz]
            low, high = spot - size / 2, spot + size / 2
            overlaps = (
                (blockers[:, 0] < high[0])
                & (blockers[:, 2] > low[0])
                & (blockers[:, 1] < high[1])
                & (blockers[:, 3] > low[1])
            )
            if overlaps.any() or (np.abs([dx, dz]) < size).all():
                continue
            members = (np.abs(floor_points - spot) <= size / 2).all(axis=1)
            if members.sum() < needed:
                continue
            difference = np.abs(np.median(colors[members], axis=0) - wanted).sum()
            score = difference + DISTANCE_COST * np.hypot(dx, dz)
            if score < best_score:
                best, best_score = spot, score
    return best


def patch_floor(
    base: Splats,
    moved: list[dict],
    all_assets: list[dict],
    floor_height: float,
    up: np.ndarray,
) -> tuple[Splats, list[dict]]:
    """Replace the floor under moved objects with floor copied from clear spots, with a record."""
    axis = int(np.argmax(np.abs(up)))
    across = [i for i in range(3) if i != axis]
    heights = base.positions @ up
    on_floor = np.abs(heights - floor_height) <= FLOOR_BAND
    floor_data = base.data[on_floor]
    floor_points = base.positions[on_floor][:, across]
    colors = np.stack([floor_data[f"f_dc_{i}"] for i in range(3)], axis=1)
    standing = []
    for asset in all_assets:
        bottom = min(np.dot(asset["bbox_min"], up), np.dot(asset["bbox_max"], up))
        if bottom - floor_height < LOW_HEIGHT:
            standing.append(np.concatenate(footprint(asset, across)))
    blockers = np.array(standing).reshape(-1, 4)

    keep = np.ones(len(base), dtype=bool)
    added = []
    record = []
    for asset in moved:
        low, high = footprint(asset, across)
        size = high - low + 2 * PATCH_MARGIN
        center = (low + high) / 2
        spot = find_clear_floor(floor_points, colors, center, size, blockers)
        if spot is None:
            record.append({"object_id": asset["object_id"], "patched": False})
            continue
        inside = (np.abs(base.positions[:, across] - center) <= size / 2).all(axis=1)
        keep &= ~(inside & on_floor)
        copied = floor_data[(np.abs(floor_points - spot) <= size / 2).all(axis=1)].copy()
        names = ["x", "y", "z"]
        for index, name in zip(across, (0, 1), strict=True):
            copied[names[index]] += center[name] - spot[name]
        added.append(copied)
        record.append(
            {
                "object_id": asset["object_id"],
                "patched": True,
                "center": [round(float(v), 3) for v in center],
                "size": [round(float(v), 3) for v in size],
                "copied_from": [round(float(v), 3) for v in spot],
                "splats": len(copied),
            }
        )
    return Splats(np.concatenate([base.data[keep], *added])), record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("assets", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--objects", nargs="+", required=True)
    parser.add_argument("--members", type=Path, help="members.npz, for cleaner cuts than a box")
    parser.add_argument("--box", nargs="*", default=[], help="objects to cut by box regardless")
    parser.add_argument("--up", type=float, nargs=3, default=(0.0, -1.0, 0.0))
    args = parser.parse_args()
    document = json.loads(args.assets.read_text())
    by_id = {asset["object_id"]: asset for asset in document["assets"]}
    for object_id in args.objects:
        if by_id.get(object_id, {}).get("mobility") != "movable":
            parser.error(f"{object_id} isn't a movable object in {args.assets}")
    up = np.asarray(args.up, dtype=np.float64)
    floor_height = float(document["floor_y"]) * float(up @ np.array([0.0, 1.0, 0.0]))
    chosen = [by_id[i] for i in args.objects]
    scene = read_splats(args.scene)
    base, pieces = split_movable(
        scene,
        [by_id[i] for i in args.objects if not args.members or i in args.box],
        floor_height,
        up,
    )
    if args.members:
        with np.load(args.members) as saved:
            members = {i: saved[i] for i in args.objects if i not in args.box}
        base, by_members = split_by_members(base, members)
        pieces.update(by_members)
    base, patches = patch_floor(base, chosen, document["assets"], floor_height, up)
    (args.out / "pieces").mkdir(parents=True, exist_ok=True)
    write_splats(base, args.out / "base.ply")
    for object_id, piece in pieces.items():
        write_splats(piece, args.out / "pieces" / f"{object_id}.ply")
    (args.out / "pieces.json").write_text(json.dumps(list(pieces)))
    (args.out / "patches.json").write_text(json.dumps(patches, indent=1))
    sizes = {object_id: len(piece) for object_id, piece in pieces.items()}
    print(json.dumps({"base": len(base), "pieces": sizes, "patches": patches}))


if __name__ == "__main__":
    main()
