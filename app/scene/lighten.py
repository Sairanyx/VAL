"""Make a smaller version of a splat scene for tablets.

    uv run --no-project --with numpy python -m app.scene.lighten clean.ply light.ply
    uv run --no-project --with numpy python -m app.scene.lighten clean.ply light.ply --splats 400000

Always drops view-dependent color (`f_rest_*`), which is most of the file size and barely shows:
each splat takes 56 bytes, not 236. Keeping every splat looks close to the original, so try that
first. `--splats` keeps a random subset and enlarges it to cover the same area, which looks softer
and damages thin details, so use it only if a tablet needs it.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from app.scene.load import Splats, read_splats, write_splats


def strip_view_dependence(splats: Splats) -> Splats:
    """Return splats without `f_rest_*`, keeping only their base color."""
    names = [name for name in splats.data.dtype.names if not name.startswith("f_rest_")]
    stripped = np.empty(len(splats), dtype=[(name, splats.data.dtype[name]) for name in names])
    for name in names:
        stripped[name] = splats.data[name]
    return Splats(stripped)


def lighten(splats: Splats, target: int | None = None, seed: int = 0) -> Splats:
    """Return base-color splats, reduced to a random `target` if given, in their original order."""
    if target is None or target >= len(splats):
        return strip_view_dependence(splats)
    keep = np.sort(np.random.default_rng(seed).choice(len(splats), target, replace=False))
    light = strip_view_dependence(splats[keep])
    # Fewer splats cover less area. Area grows with scale squared, and scales are stored as logs.
    growth = np.log(np.sqrt(len(splats) / target))
    for axis in range(3):
        light.data[f"scale_{axis}"] += growth
    return light


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--splats", type=int, help="keep this many, instead of all")
    args = parser.parse_args()

    splats = read_splats(args.input)
    light = lighten(splats, args.splats)
    write_splats(light, args.output)
    print(
        json.dumps(
            {
                "input_splats": len(splats),
                "output_splats": len(light),
                "output_mb": round(args.output.stat().st_size / 1e6, 1),
            }
        )
    )


if __name__ == "__main__":
    main()
