"""Cut movable objects out of a scene, so that dragging one in the viewer moves the real thing.

    python -m app.scene.split_movable SCENE.ply ASSETS.json OUT_DIR --objects obj-0067 obj-0008

Writes base.ply, without those objects, plus pieces/OBJECT.ply and pieces.json. Everything inside an
object's box goes with it, including faint splats that carry no label, because leaving those behind
shows as a ghost. It uses positions only, so it works on the full scene and on lighter copies.

Best for free-standing objects: anything else inside the box moves too. The scan saw the floor
under most objects, so what's left behind is usually a dark patch, not a hole.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from app.scene.load import Splats, read_splats, write_splats

BOX_MARGIN = 0.03  # metres around the box, to catch splats at its edge
FLOOR_MARGIN = 0.03  # metres above the floor to stop at, so the floor itself stays


def inside_box(
    positions: np.ndarray, asset: dict, floor_height: float, up: np.ndarray
) -> np.ndarray:
    """Return which splats belong to an object: in its box, and above the floor."""
    low = np.minimum(asset["bbox_min"], asset["bbox_max"]) - BOX_MARGIN
    high = np.maximum(asset["bbox_min"], asset["bbox_max"]) + BOX_MARGIN
    in_box = ((positions >= low) & (positions <= high)).all(axis=1)
    return in_box & (positions @ up > floor_height + FLOOR_MARGIN)


def split_movable(
    splats: Splats, assets: list[dict], floor_height: float, up: np.ndarray
) -> tuple[Splats, dict[str, Splats]]:
    """Return the scene without these objects, and each object's splats. First box in wins."""
    taken = np.zeros(len(splats), dtype=bool)
    pieces = {}
    for asset in assets:
        members = inside_box(splats.positions, asset, floor_height, up) & ~taken
        taken |= members
        pieces[asset["object_id"]] = splats[members]
    return splats[~taken], pieces


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("assets", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--objects", nargs="+", required=True)
    parser.add_argument("--up", type=float, nargs=3, default=(0.0, -1.0, 0.0))
    args = parser.parse_args()
    document = json.loads(args.assets.read_text())
    by_id = {asset["object_id"]: asset for asset in document["assets"]}
    for object_id in args.objects:
        if by_id.get(object_id, {}).get("mobility") != "movable":
            parser.error(f"{object_id} isn't a movable object in {args.assets}")
    up = np.asarray(args.up, dtype=np.float64)
    floor_height = float(document["floor_y"]) * float(up @ np.array([0.0, 1.0, 0.0]))
    base, pieces = split_movable(
        read_splats(args.scene), [by_id[i] for i in args.objects], floor_height, up
    )
    (args.out / "pieces").mkdir(parents=True, exist_ok=True)
    write_splats(base, args.out / "base.ply")
    for object_id, piece in pieces.items():
        write_splats(piece, args.out / "pieces" / f"{object_id}.ply")
    (args.out / "pieces.json").write_text(json.dumps(list(pieces)))
    sizes = {object_id: len(piece) for object_id, piece in pieces.items()}
    print(json.dumps({"base": len(base), "pieces": sizes}))


if __name__ == "__main__":
    main()
