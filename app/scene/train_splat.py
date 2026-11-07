"""Train a Gaussian splat from a COLMAP model and its frames, using gsplat. Needs a GPU.

    python -m app.scene.train_splat SPARSE_DIR IMAGES_DIR OUT_DIR --iterations 30000

Writes splat.ply, in the same format as `Equipment Room.ply`, and summary.json with PSNR on frames
held out of training, so quality can be compared fairly. Scene units are COLMAP's, not metres.
"""

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np

from app.scene.load import Splats, write_splats

SH_ZERO = 0.28209479177387814


def split_frames(names: list[str], every: int = 8) -> tuple[list[str], list[str]]:
    """Return (training, held-out) names, holding out every `every`-th frame in sorted order."""
    ordered = sorted(names)
    return (
        [name for index, name in enumerate(ordered) if index % every != 0],
        [name for index, name in enumerate(ordered) if index % every == 0],
    )


def drop_blurriest(names: list[str], manifest: Path, share: float) -> list[str]:
    """Remove the given share of names with the lowest sharpness in manifest.csv."""
    with manifest.open() as file:
        sharpness = {row["file"]: float(row["sharpness"]) for row in csv.DictReader(file)}
    ranked = sorted(names, key=lambda name: sharpness.get(name, 0.0))
    return [name for name in names if name not in set(ranked[: int(len(ranked) * share)])]


def to_splats(
    means: np.ndarray,
    scales: np.ndarray,
    quats: np.ndarray,
    opacities: np.ndarray,
    sh0: np.ndarray,
    shn: np.ndarray,
) -> Splats:
    """Return splats from trained values. Scales and opacities are logs and logits, as stored."""
    count, coefficients = len(means), shn.shape[1]
    fields = ["x", "y", "z", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    fields += ["f_dc_0", "f_dc_1", "f_dc_2", "opacity"]
    fields += [f"f_rest_{index}" for index in range(coefficients * 3)]
    data = np.empty(count, dtype=[(name, "<f4") for name in fields])
    data["x"], data["y"], data["z"] = means.T
    for axis in range(3):
        data[f"scale_{axis}"] = scales[:, axis]
        data[f"f_dc_{axis}"] = sh0[:, axis]
    for index in range(4):
        data[f"rot_{index}"] = quats[:, index]
    data["opacity"] = opacities
    # The file stores all red coefficients, then green, then blue.
    rest = shn.transpose(0, 2, 1).reshape(count, -1)
    for index in range(rest.shape[1]):
        data[f"f_rest_{index}"] = rest[:, index]
    return Splats(data)


def initial_scales(points: np.ndarray) -> np.ndarray:
    """Return a log scale for each point, from the distance to its three nearest neighbours."""
    from scipy.spatial import cKDTree

    distances, _ = cKDTree(points).query(points, k=4)
    return np.log(np.clip(distances[:, 1:].mean(axis=1), 1e-4, None))[:, None].repeat(3, axis=1)


def load_colmap(sparse_dir: Path) -> dict:
    """Return points, colors, a pinhole K, image size, and world-to-camera matrices by file name."""
    import pycolmap

    model = pycolmap.Reconstruction(str(sparse_dir))
    points = model.points3D.values()
    cameras = {}
    camera = None
    for image in model.images.values():
        camera = image.camera
        matrix = np.eye(4)
        matrix[:3] = image.cam_from_world().matrix()
        cameras[Path(image.name).name] = matrix
    return {
        "points": np.array([point.xyz for point in points]),
        "colors": np.array([point.color for point in points]) / 255.0,
        "K": camera.calibration_matrix(),
        "width": camera.width,
        "height": camera.height,
        "cameras": cameras,
    }


def ssim_loss(render, target):
    """Return 1 - SSIM between two images shaped (H, W, 3), using an 11-pixel Gaussian window."""
    import torch
    import torch.nn.functional as functional

    coords = torch.arange(11, device=render.device, dtype=render.dtype) - 5
    gaussian = torch.exp(-(coords**2) / (2 * 1.5**2))
    gaussian = gaussian / gaussian.sum()
    kernel = (gaussian[:, None] @ gaussian[None])[None, None].repeat(3, 1, 1, 1)
    first = render.permute(2, 0, 1)[None]
    second = target.permute(2, 0, 1)[None]

    def blur(image):
        return functional.conv2d(image, kernel, padding=5, groups=3)

    mean_a, mean_b = blur(first), blur(second)
    variance_a = blur(first**2) - mean_a**2
    variance_b = blur(second**2) - mean_b**2
    covariance = blur(first * second) - mean_a * mean_b
    value = ((2 * mean_a * mean_b + 0.0001) * (2 * covariance + 0.0009)) / (
        (mean_a**2 + mean_b**2 + 0.0001) * (variance_a + variance_b + 0.0009)
    )
    return 1 - value.mean()


def train(args: argparse.Namespace) -> None:
    import torch
    from gsplat import rasterization
    from gsplat.strategy import DefaultStrategy
    from PIL import Image

    device = "cuda"
    data = load_colmap(args.sparse_dir)
    names = [name for name in data["cameras"] if (args.images_dir / name).exists()]
    train_names, test_names = split_frames(names)
    if args.manifest:
        train_names = drop_blurriest(train_names, args.manifest, args.drop_blurry)
    print(f"{len(train_names)} training frames, {len(test_names)} held out", flush=True)

    def tensor(values) -> torch.Tensor:
        return torch.as_tensor(np.asarray(values), dtype=torch.float32, device=device)

    def load_image(name: str) -> torch.Tensor:
        return tensor(np.array(Image.open(args.images_dir / name).convert("RGB")) / 255.0)

    images = {
        name: np.array(Image.open(args.images_dir / name).convert("RGB")) for name in train_names
    }
    K = tensor(data["K"])[None]
    width, height = data["width"], data["height"]
    views = {name: tensor(data["cameras"][name])[None] for name in names}

    centers = np.array([np.linalg.inv(data["cameras"][name])[:3, 3] for name in names])
    scene_scale = float(np.linalg.norm(centers - centers.mean(axis=0), axis=1).max() * 1.1)

    points = data["points"]
    count = len(points)
    params = torch.nn.ParameterDict(
        {
            "means": torch.nn.Parameter(tensor(points)),
            "scales": torch.nn.Parameter(tensor(initial_scales(points))),
            "quats": torch.nn.Parameter(
                torch.nn.functional.normalize(torch.rand(count, 4, device=device) - 0.5, dim=-1)
            ),
            "opacities": torch.nn.Parameter(tensor(np.full(count, -2.197))),
            "sh0": torch.nn.Parameter(tensor((data["colors"] - 0.5) / SH_ZERO)),
            "shN": torch.nn.Parameter(tensor(np.zeros((count, 15, 3)))),
        }
    )
    rates = {
        "means": 1.6e-4 * scene_scale,
        "scales": 5e-3,
        "quats": 1e-3,
        "opacities": 2.5e-2,
        "sh0": 2.5e-3,
        "shN": 2.5e-3 / 20,
    }
    optimizers = {
        name: torch.optim.Adam([params[name]], lr=rate, eps=1e-15) for name, rate in rates.items()
    }
    position_decay = (1.6e-6 / 1.6e-4) ** (1 / max(args.iterations, 1))
    scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizers["means"], gamma=position_decay)
    strategy = DefaultStrategy(
        refine_start_iter=500,
        refine_stop_iter=min(15000, args.iterations // 2),
        refine_every=100,
        reset_every=3000,
        verbose=False,
    )
    strategy.check_sanity(params, optimizers)
    state = strategy.initialize_state(scene_scale=scene_scale)

    def render(name: str, degree: int):
        colors = torch.cat([params["sh0"][:, None], params["shN"]], dim=1)
        return rasterization(
            means=params["means"],
            quats=torch.nn.functional.normalize(params["quats"], dim=-1),
            scales=torch.exp(params["scales"]),
            opacities=torch.sigmoid(params["opacities"]),
            colors=colors,
            viewmats=views[name],
            Ks=K,
            width=width,
            height=height,
            sh_degree=degree,
            render_mode="RGB",
            packed=False,
        )

    def evaluate(limit: int | None = None) -> float:
        scores = []
        with torch.no_grad():
            for name in test_names[:limit]:
                image, _, _ = render(name, 3)
                error = ((image[0].clamp(0, 1) - load_image(name)) ** 2).mean()
                scores.append(float(-10 * torch.log10(error)))
        return float(np.mean(scores))

    random = np.random.default_rng(0)
    start = time.perf_counter()
    for step in range(args.iterations):
        name = train_names[random.integers(len(train_names))]
        target = tensor(images[name] / 255.0)
        degree = min(step // 1000, 3)
        image, _, info = render(name, degree)
        strategy.step_pre_backward(params, optimizers, state, step, info)
        l1 = torch.abs(image[0] - target).mean()
        loss = 0.8 * l1 + 0.2 * ssim_loss(image[0], target)
        loss.backward()
        strategy.step_post_backward(params, optimizers, state, step, info, packed=False)
        for optimizer in optimizers.values():
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
        scheduler.step()
        if (step + 1) % args.report_every == 0 or step + 1 == args.iterations:
            psnr = evaluate(limit=20)
            minutes = (time.perf_counter() - start) / 60
            count = len(params["means"])
            print(
                f"step {step + 1} splats {count} heldout20 {psnr:.2f} dB {minutes:.1f} min",
                flush=True,
            )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with torch.no_grad():
        splats = to_splats(
            params["means"].cpu().numpy(),
            params["scales"].cpu().numpy(),
            torch.nn.functional.normalize(params["quats"], dim=-1).cpu().numpy(),
            params["opacities"].cpu().numpy(),
            params["sh0"].cpu().numpy(),
            params["shN"].cpu().numpy(),
        )
    write_splats(splats, args.out_dir / "splat.ply")
    summary = {
        "iterations": args.iterations,
        "splats": len(splats),
        "train_frames": len(train_names),
        "heldout_frames": len(test_names),
        "heldout_psnr": round(evaluate(), 2),
        "minutes": round((time.perf_counter() - start) / 60, 1),
        "peak_gpu_gb": round(torch.cuda.max_memory_allocated() / 1e9, 1),
        "scene_scale": round(scene_scale, 3),
    }
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sparse_dir", type=Path)
    parser.add_argument("images_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--iterations", type=int, default=30000)
    parser.add_argument("--report-every", type=int, default=5000)
    parser.add_argument("--manifest", type=Path, help="manifest.csv from select_frames.py")
    parser.add_argument("--drop-blurry", type=float, default=0.1)
    train(parser.parse_args())


if __name__ == "__main__":
    main()
