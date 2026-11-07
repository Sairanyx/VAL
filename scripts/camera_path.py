"""Save where the filming camera went, in scene coordinates, for `app.nav.grid --walked`.

    python scripts/camera_path.py COLMAP_MODEL OUT.npy [--align ALIGN.json]

ALIGN.json is the transform used on the splat: "scale", "R", and "t". Needs pycolmap.
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pycolmap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--align", type=Path)
    args = parser.parse_args()
    centers = {}
    for image in pycolmap.Reconstruction(str(args.model)).images.values():
        pose = image.cam_from_world
        matrix = (pose() if callable(pose) else pose).matrix()
        centers[image.name] = -matrix[:3, :3].T @ matrix[:3, 3]
    path = np.array([centers[name] for name in sorted(centers)])
    if args.align:
        align = json.loads(args.align.read_text())
        path = align["scale"] * path @ np.array(align["R"]).T + np.array(align["t"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.out, path)
    print(f"Wrote {args.out}: {len(path)} camera positions")


if __name__ == "__main__":
    main()
