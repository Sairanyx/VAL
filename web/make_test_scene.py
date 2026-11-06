"""Write a small fake splat scene from an assets file, to test the viewer without Valmet's data.

    uv run python web/make_test_scene.py      # writes data/scene/sample/scene.ply

It makes a grey floor and fills each asset's box with coloured splats. Same axes as the real
scene: +y points down, and the floor is at the assets file's `floor_y`.
"""

import argparse
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SH_C0 = 0.28209479177387814  # degree-0 spherical harmonic, converts RGB to f_dc
COLORS = {"pump": (0.2, 0.4, 0.9), "valve": (0.9, 0.6, 0.1), "ladder": (0.8, 0.8, 0.2)}
FIELDS = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity"]
FIELDS += ["scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]


def splats(xyz: np.ndarray, rgb, size: float) -> np.ndarray:
    n = len(xyz)
    out = np.zeros((n, len(FIELDS)), dtype=np.float32)
    out[:, 0:3] = xyz
    out[:, 3:6] = (np.asarray(rgb) - 0.5) / SH_C0
    out[:, 6] = 4.0  # logit of opacity, about 0.98
    out[:, 7:10] = np.log(size)
    out[:, 10] = 1.0  # identity rotation (w, x, y, z)
    return out


def build(assets: dict, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    floor_y = assets["floor_y"]
    gx, gz = np.meshgrid(np.arange(-4.5, 4.5, 0.05), np.arange(-3.6, 3.6, 0.05))
    floor = np.stack([gx.ravel(), np.full(gx.size, floor_y), gz.ravel()], axis=1)
    shade = 0.35 + 0.1 * ((np.floor(gx.ravel()) + np.floor(gz.ravel())) % 2)  # tiles, to see motion
    parts = [splats(floor, np.stack([shade] * 3, axis=1), 0.03)]
    for a in assets["assets"]:
        lo, hi = np.array(a["bbox_min"]), np.array(a["bbox_max"])
        n = int(4000 * np.prod(hi - lo) + 500)
        pts = rng.uniform(lo, hi, size=(n, 3))
        parts.append(splats(pts, COLORS.get(a["label"], (0.7, 0.7, 0.7)), 0.02))
    return np.concatenate(parts)


def write_ply(path: Path, data: np.ndarray) -> None:
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {len(data)}"]
    header += [f"property float {f}" for f in FIELDS] + ["end_header"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        f.write(("\n".join(header) + "\n").encode())
        f.write(data.astype("<f4").tobytes())


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--assets", type=Path, default=ROOT / "fixtures/sample_assets.json")
    p.add_argument("--out", type=Path, default=ROOT / "data/scene/sample/scene.ply")
    args = p.parse_args()
    data = build(json.loads(args.assets.read_text()))
    write_ply(args.out, data)
    print(f"Wrote {len(data)} splats to {args.out}")


if __name__ == "__main__":
    main()
