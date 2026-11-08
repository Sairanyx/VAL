"""Split a scene into one PLY per object plus a background, from one label per splat.

    uv run --no-project --with numpy python -m app.scene.split clean.ply labels.npy OUT_DIR

Labels follow `splat_labels.npy`: an index into assets, or -1 for background. Writes
objects/obj-NNNN.ply, background.ply, and tinted/obj-NNNN.ply, which has a flat color per object for
the separated view. Numbers match `obj-NNNN` in assets.json, counting from label 0 as obj-0001.
"""

import argparse
import colorsys
import json
from pathlib import Path

import numpy as np

from app.scene.lighten import strip_view_dependence
from app.scene.load import Splats, read_splats, write_splats

SH_ZERO = 0.28209479177387814


def object_name(label: int) -> str:
    return f"obj-{label + 1:04d}"


def tint_color(label: int) -> tuple[float, float, float]:
    """Return a distinct, bright RGB color. The golden ratio spreads hues as labels grow."""
    return colorsys.hsv_to_rgb((label * 0.61803398875) % 1.0, 0.75, 1.0)


def tinted(splats: Splats, color: tuple[float, float, float], strength: float = 0.6) -> Splats:
    """Return base-color splats blended toward `color`, keeping some of their original shading."""
    result = strip_view_dependence(splats)
    for channel, value in enumerate(color):
        name = f"f_dc_{channel}"
        original = 0.5 + SH_ZERO * result.data[name]
        blended = (1 - strength) * original + strength * value
        result.data[name] = (blended - 0.5) / SH_ZERO
    return result


def split_scene(splats: Splats, labels: np.ndarray, out_dir: Path) -> dict:
    """Write the object, tinted, and background PLY files, and return a summary."""
    if len(labels) != len(splats):
        raise ValueError(f"{len(labels)} labels for {len(splats)} splats: wrong scene or labels")
    objects_dir, tinted_dir = out_dir / "objects", out_dir / "tinted"
    objects_dir.mkdir(parents=True, exist_ok=True)
    tinted_dir.mkdir(parents=True, exist_ok=True)

    order = np.argsort(labels, kind="stable")
    values, starts = np.unique(labels[order], return_index=True)
    groups = np.split(order, starts[1:])
    counts = {}
    for label, group in zip(values.tolist(), groups, strict=True):
        part = splats[group]
        if label < 0:
            write_splats(part, out_dir / "background.ply")
            continue
        name = object_name(label)
        write_splats(part, objects_dir / f"{name}.ply")
        write_splats(tinted(part, tint_color(label)), tinted_dir / f"{name}.ply")
        counts[name] = len(group)
    return {
        "objects": len(counts),
        "object_splats": sum(counts.values()),
        "background_splats": int((labels < 0).sum()),
        "largest": max(counts.values(), default=0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("out_dir", type=Path)
    args = parser.parse_args()
    summary = split_scene(read_splats(args.scene), np.load(args.labels), args.out_dir)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
