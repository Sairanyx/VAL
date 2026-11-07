"""Export coloured object splats for selection highlighting, without changing the scan.

python -m app.scene.highlights SCENE.ply ASSETS_FINAL.json SPLAT_LABELS.npy OUT_DIR

Labels must index the supplied full scene and the assets in their extraction order.
"""

import argparse
import json
import re
from pathlib import Path

import numpy as np

from app.scene.lighten import strip_view_dependence
from app.scene.load import Splats, read_splats, write_splats


def export_highlights(scene: Splats, assets: list[dict], labels: np.ndarray, out: Path) -> dict:
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
        if not counts[index]:
            continue
        subset = strip_view_dependence(scene[labels == index])
        # Zero-order SH encodes RGB as 0.5 + C0 * coefficient.
        for channel, color in enumerate((0.05, 0.9, 1.0)):
            subset.data[f"f_dc_{channel}"] = (color - 0.5) / 0.28209479177387814
        write_splats(subset, out / f"{asset['object_id']}.ply")
        manifest[asset["object_id"]] = {"splats": int(counts[index])}
    (out / "highlights.json").write_text(json.dumps(manifest))
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("assets", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    manifest = export_highlights(
        read_splats(args.scene),
        json.loads(args.assets.read_text())["assets"],
        np.load(args.labels, allow_pickle=False),
        args.out,
    )
    print(json.dumps({"highlight_objects": len(manifest), "out": str(args.out)}))


if __name__ == "__main__":
    main()
