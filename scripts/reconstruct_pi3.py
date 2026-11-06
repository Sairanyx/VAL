"""Reconstruct cameras and points from frames with Pi3X, for comparison against Valmet's PLY.

    python scripts/reconstruct_pi3.py FRAMES_DIR OUT_DIR --weights WEIGHTS_DIR --frames 100

Needs a GPU and the `pi3` package. Writes points.ply, cameras.npz and summary.json.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch
from pi3.models.pi3x import Pi3X
from pi3.utils.basic import load_images_as_tensor


def write_ply(path: Path, xyz: np.ndarray, rgb: np.ndarray) -> None:
    vertex = np.empty(
        len(xyz),
        dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"), ("b", "u1")],
    )
    vertex["x"], vertex["y"], vertex["z"] = xyz.T
    vertex["r"], vertex["g"], vertex["b"] = rgb.T
    header = (
        "ply\nformat binary_little_endian 1.0\n"
        f"element vertex {len(xyz)}\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n"
    )
    with path.open("wb") as file:
        file.write(header.encode())
        vertex.tofile(file)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--min-confidence", type=float, default=0.5)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    available = len(list(args.frames_dir.glob("*.jpg")))
    interval = max(available // args.frames, 1)
    images = load_images_as_tensor(str(args.frames_dir), interval=interval)[: args.frames]

    start = time.perf_counter()
    model = Pi3X.from_pretrained(str(args.weights)).to("cuda").eval()
    load_seconds = time.perf_counter() - start

    start = time.perf_counter()
    with torch.no_grad(), torch.amp.autocast("cuda", dtype=torch.bfloat16):
        output = model(images.cuda()[None])
    infer_seconds = time.perf_counter() - start

    points = output["points"][0].float().cpu().numpy()
    confidence = torch.sigmoid(output["conf"][0, ..., 0]).float().cpu().numpy()
    poses = output["camera_poses"][0].float().cpu().numpy()
    colors = (images.permute(0, 2, 3, 1).numpy() * 255).astype(np.uint8)

    keep = confidence > args.min_confidence
    write_ply(args.out_dir / "points.ply", points[keep], colors[keep])
    np.savez_compressed(args.out_dir / "cameras.npz", camera_to_world=poses)

    centers = poses[:, :3, 3]
    summary = {
        "frames": len(images),
        "frame_interval": interval,
        "image_size_hw": list(images.shape[-2:]),
        "gpu": torch.cuda.get_device_name(0),
        "load_seconds": round(load_seconds, 1),
        "infer_seconds": round(infer_seconds, 1),
        "peak_gpu_gb": round(torch.cuda.max_memory_allocated() / 1e9, 1),
        "points_kept": int(keep.sum()),
        "points_total": int(keep.size),
        "bounds_min": np.percentile(points[keep], 0.5, axis=0).round(2).tolist(),
        "bounds_max": np.percentile(points[keep], 99.5, axis=0).round(2).tolist(),
        "camera_path_length": round(
            float(np.linalg.norm(np.diff(centers, axis=0), axis=1).sum()), 2
        ),
        "metric": float(output["metric"].float().cpu().numpy().reshape(-1)[0]),
    }
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
