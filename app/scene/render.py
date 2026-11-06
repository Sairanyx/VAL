"""Render color and depth views of a splat scene from known cameras. Needs a GPU and gsplat.

    python -m app.scene.render clean.ply OUT_DIR --max-views 400

Writes views/NAME.jpg, depth/NAME.npy (0 where nothing was rendered), and cameras.json with each
view's world-to-camera matrix and intrinsics. Depth is distance along the camera's forward axis.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from gsplat import rasterization
from PIL import Image

from app.scene.cameras import floor_fraction, grid_cameras, intrinsics
from app.scene.load import Splats, estimate_floor, read_splats


def to_tensors(splats: Splats, device: str) -> dict:
    """Convert splats to the inputs gsplat expects."""

    def tensor(values: np.ndarray) -> torch.Tensor:
        return torch.from_numpy(np.asarray(values, dtype=np.float32)).to(device)

    names = splats.data.dtype.names
    dc = np.stack([splats.data[f"f_dc_{channel}"] for channel in range(3)], axis=1)
    rest_count = sum(name.startswith("f_rest_") for name in names)
    degree = {0: 0, 9: 1, 24: 2, 45: 3}[rest_count]
    if rest_count:
        rest = np.stack([splats.data[f"f_rest_{index}"] for index in range(rest_count)], axis=1)
        # The file stores all red coefficients, then green, then blue.
        rest = rest.reshape(len(splats), 3, rest_count // 3).transpose(0, 2, 1)
        colors = np.concatenate([dc[:, None], rest], axis=1)
    else:
        colors = dc[:, None]
    return {
        "means": tensor(splats.positions),
        "quats": tensor(splats.quaternions),
        "scales": tensor(splats.scales),
        "opacities": tensor(splats.opacities),
        "colors": tensor(colors),
        "sh_degree": degree,
    }


def render_view(scene: dict, matrix: np.ndarray, camera: np.ndarray, width: int, height: int):
    """Return color (H, W, 3, 0-1), depth (H, W), and alpha (H, W) as numpy arrays."""
    device = scene["means"].device
    viewmat = torch.from_numpy(matrix.astype(np.float32)).to(device)[None]
    k = torch.from_numpy(camera.astype(np.float32)).to(device)[None]
    with torch.no_grad():
        output, alpha, _ = rasterization(
            **scene, viewmats=viewmat, Ks=k, width=width, height=height, render_mode="RGB+ED"
        )
    output = output[0].cpu().numpy()
    return np.clip(output[..., :3], 0, 1), output[..., 3], alpha[0, ..., 0].cpu().numpy()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--up", type=float, nargs=3, default=(0.0, -1.0, 0.0))
    parser.add_argument("--max-views", type=int, default=400)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fov", type=float, default=75.0)
    parser.add_argument("--spacing", type=float, default=0.75)
    parser.add_argument("--min-coverage", type=float, default=0.8)
    parser.add_argument("--min-median-depth", type=float, default=0.9)
    parser.add_argument("--max-median-depth", type=float, default=float("inf"))
    parser.add_argument("--max-floor-fraction", type=float, default=0.6)
    parser.add_argument("--heights", type=float, nargs="+", default=[0.7, 1.5])
    parser.add_argument("--pitches", type=float, nargs="+", default=[-10.0])
    parser.add_argument("--yaws", type=int, default=6)
    parser.add_argument("--prefix", default="view", help="start of each view's file name")
    args = parser.parse_args()

    start = time.perf_counter()
    splats = read_splats(args.scene)
    up = tuple(args.up)
    floor = estimate_floor(splats.positions, up)
    obstacles = splats.positions[splats.opacities > 0.3].astype(np.float32)
    candidates = grid_cameras(
        obstacles.astype(np.float64),
        up,
        floor,
        heights=tuple(args.heights),
        spacing=args.spacing,
        yaws=args.yaws,
        pitches_degrees=tuple(args.pitches),
    )
    print(f"{len(candidates)} candidate views, floor height {floor:.3f}", flush=True)

    views_dir, depth_dir = args.out_dir / "views", args.out_dir / "depth"
    views_dir.mkdir(parents=True, exist_ok=True)
    depth_dir.mkdir(parents=True, exist_ok=True)

    scene = to_tensors(splats, "cuda")
    camera = intrinsics(args.width, args.height, args.fov)
    kept, rejected = [], 0
    # Random order, so stopping at max_views still covers the whole room. Seeded to be repeatable.
    for index in np.random.default_rng(0).permutation(len(candidates)):
        if len(kept) >= args.max_views:
            break
        matrix = candidates[index]
        color, depth, alpha = render_view(scene, matrix, camera, args.width, args.height)
        solid = alpha > 0.5
        # Rejects views outside the walls or pressed up against a surface.
        typical_depth = np.median(depth[solid]) if solid.any() else 0.0
        if (
            solid.mean() < args.min_coverage
            or typical_depth < args.min_median_depth
            or typical_depth > args.max_median_depth
            or floor_fraction(np.where(solid, depth, 0), camera, matrix, up, floor)
            > args.max_floor_fraction
        ):
            rejected += 1
            continue
        name = f"{args.prefix}_{len(kept):05d}"
        Image.fromarray((color * 255).astype(np.uint8)).save(views_dir / f"{name}.jpg", quality=95)
        np.save(depth_dir / f"{name}.npy", np.where(solid, depth, 0).astype(np.float32))
        kept.append({"name": name, "world_to_camera": matrix.round(6).tolist()})

    summary = {
        "scene": str(args.scene),
        "splats": len(splats),
        "floor_height_along_up": round(floor, 3),
        "up": list(up),
        "width": args.width,
        "height": args.height,
        "intrinsics": camera.tolist(),
        "candidate_views": len(candidates),
        "rejected_views": rejected,
        "views": len(kept),
        "seconds": round(time.perf_counter() - start, 1),
        "peak_gpu_gb": round(torch.cuda.max_memory_allocated() / 1e9, 1),
    }
    (args.out_dir / "cameras.json").write_text(json.dumps({**summary, "cameras": kept}))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
