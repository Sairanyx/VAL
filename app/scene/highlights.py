"""Export coloured object splats for selection highlighting, without changing the scan.

python -m app.scene.highlights SCENE.ply ASSETS_FINAL.json SPLAT_LABELS.npy OUT_DIR [--pieces CUT]

Labels must index the supplied full scene and the assets in their extraction order.
Objects cut out by app.scene.split_movable use their whole piece instead of the labelled splats.
"""

import argparse
import json
import re
from pathlib import Path

import numpy as np

from app.scene.lighten import strip_view_dependence
from app.scene.load import Splats, read_splats, write_splats


def tint(splats: Splats) -> Splats:
    splats = strip_view_dependence(splats)
    # Zero-order SH encodes RGB as 0.5 + C0 * coefficient.
    for channel, color in enumerate((0.05, 0.9, 1.0)):
        splats.data[f"f_dc_{channel}"] = (color - 0.5) / 0.28209479177387814
    return splats


def export_highlights(
    scene: Splats,
    assets: list[dict],
    labels: np.ndarray,
    out: Path,
    pieces: dict[str, Splats] | None = None,
) -> dict:
    pieces = pieces or {}
    if labels.shape != (len(scene),) or labels.dtype.kind not in "iu":
        raise ValueError("Labels must be a one-dimensional integer array indexing the full scene")
    if labels.size and (labels.min() < -1 or labels.max() >= len(assets)):
        raise ValueError("Label index is outside the asset list")
    ids = [asset["object_id"] for asset in assets]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[\w-]+", i) for i in ids):
        raise ValueError("Object IDs must be unique safe file names")
    counts = np.bincount(labels[labels >= 0], minlength=len(assets))
    if any(int(count) != asset["splats"] for count, asset in zip(counts, assets, strict=True)):
        raise ValueError(
            "Splat counts differ from assets: use the extraction's scene and asset order"
        )
    out.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for index, asset in enumerate(assets):
        object_id = asset["object_id"]
        if object_id in pieces:
            subset, source = pieces[object_id], "piece"
        elif counts[index]:
            subset, source = scene[labels == index], "segmentation"
        else:
            continue
        write_splats(tint(subset), out / f"{object_id}.ply")
        manifest[object_id] = {"splats": len(subset), "source": source}
    (out / "highlights.json").write_text(json.dumps(manifest))
    return manifest


def read_pieces(cut: Path) -> dict[str, Splats]:
    ids = json.loads((cut / "pieces.json").read_text())
    return {i: read_splats(cut / "pieces" / f"{i}.ply") for i in ids}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("assets", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--pieces", type=Path, help="cut folder from app.scene.split_movable")
    args = parser.parse_args()
    manifest = export_highlights(
        read_splats(args.scene),
        json.loads(args.assets.read_text())["assets"],
        np.load(args.labels, allow_pickle=False),
        args.out,
        read_pieces(args.pieces) if args.pieces else None,
    )
    whole = sum(item["source"] == "piece" for item in manifest.values())
    print(
        json.dumps(
            {"highlight_objects": len(manifest), "whole_pieces": whole, "out": str(args.out)}
        )
    )


if __name__ == "__main__":
    main()
