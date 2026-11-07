"""Crop objects out of real video frames, as sharper images to label from. Needs a GPU.

    python -m app.extract.frame_crops ASSETS.json SCENE.ply LABELS.npy SPARSE IMAGES \\
        OWN_SPLAT.ply ALIGN.json OUT_DIR

The video and the scene can come from different days. So an object only counts as seen in a frame
when it lies on the surface that a splat trained on that video shows there, using the video's own
depth. Objects that moved, or that something hides, get no crop from that frame.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from app.extract.label_vlm import focus_crop, mask_box
from app.scene.load import read_splats

POINTS_PER_OBJECT = 400
SOLID_OPACITY = 0.3
DEPTH_TOLERANCE = 0.12  # metres between an object's point and the video's surface
MIN_POINTS = 15
MIN_SEEN_SHARE = 0.4
FULL_SIZE_SHARE = 0.05  # share of the image at which an object is big enough to read
FRAME_STEP = 2
MIN_FRAME_GAP = 10  # in frames of the sorted list, so the crops show different angles
DEPTH_SCALE = 3  # depth maps are this many times smaller than the frames
CROPS_PER_OBJECT = 5


def moved_camera(world_to_camera: np.ndarray, align: dict) -> np.ndarray:
    """Return this camera's matrix in the coordinates the video's splat was aligned into."""
    rotation = np.asarray(align["R"])
    result = np.eye(4)
    result[:3, :3] = world_to_camera[:3, :3] @ rotation.T
    result[:3, 3] = align["scale"] * world_to_camera[:3, 3] - world_to_camera[
        :3, :3
    ] @ rotation.T @ np.asarray(align["t"])
    return result


def seen_points(
    points: np.ndarray, world_to_camera: np.ndarray, camera: np.ndarray, depth: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return pixel positions (N, 2) in depth-map pixels, and which points lie on the surface."""
    in_camera = points @ world_to_camera[:3, :3].T + world_to_camera[:3, 3]
    z = in_camera[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        u = camera[0, 0] * in_camera[:, 0] / z + camera[0, 2]
        v = camera[1, 1] * in_camera[:, 1] / z + camera[1, 2]
    height, width = depth.shape
    inside = (z > 0.3) & (u >= 0) & (u < width) & (v >= 0) & (v < height)
    seen = np.zeros(len(points), dtype=bool)
    rows, cols = v[inside].astype(int), u[inside].astype(int)
    seen[inside] = np.abs(depth[rows, cols] - z[inside]) < DEPTH_TOLERANCE
    return np.stack([u, v], axis=1), seen


def frame_score(pixels: np.ndarray, shape: tuple[int, int], seen_share: float) -> float:
    """Score how well a frame shows an object: mostly visible, large, and not cut off."""
    low, high = pixels.min(axis=0), pixels.max(axis=0)
    height, width = shape
    area = (high[0] - low[0]) * (high[1] - low[1]) / (height * width)
    margin = 0.02 * width
    cut_off = low[0] < margin or low[1] < margin or high[0] > width - margin
    cut_off = cut_off or high[1] > height - margin
    return seen_share * min(area / FULL_SIZE_SHARE, 1.0) * (0.5 if cut_off else 1.0)


def choose_frames(scores: list[tuple[float, int]], limit: int, gap: int) -> list[int]:
    """Return the best-scoring frame numbers, at least `gap` apart."""
    chosen: list[int] = []
    for _, frame in sorted(scores, reverse=True):
        if len(chosen) == limit:
            break
        if all(abs(frame - other) >= gap for other in chosen):
            chosen.append(frame)
    return chosen


def main() -> None:
    from app.scene.render import render_view, to_tensors
    from app.scene.train_splat import load_colmap

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", type=Path)
    parser.add_argument("scene", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("sparse", type=Path)
    parser.add_argument("images", type=Path)
    parser.add_argument("own_splat", type=Path, help="splat from the video, in COLMAP coordinates")
    parser.add_argument("align", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()

    assets = json.loads(args.assets.read_text())["assets"]
    scene, labels = read_splats(args.scene), np.load(args.labels)
    align = json.loads(args.align.read_text())
    video = load_colmap(args.sparse)
    names = sorted(video["cameras"])[::FRAME_STEP]
    camera = video["K"].copy()
    camera[:2] /= DEPTH_SCALE
    width, height = video["width"] // DEPTH_SCALE, video["height"] // DEPTH_SCALE

    random = np.random.default_rng(0)
    solid = scene.opacities >= SOLID_OPACITY
    groups = []
    for index in range(len(assets)):
        members = np.flatnonzero((labels == index) & solid)
        if len(members) > POINTS_PER_OBJECT:
            members = random.choice(members, POINTS_PER_OBJECT, replace=False)
        groups.append(scene.positions[members])

    tensors = to_tensors(read_splats(args.own_splat), "cuda")
    depths = []
    poses = []
    scores: list[list[tuple[float, int]]] = [[] for _ in assets]
    for number, name in enumerate(names):
        matrix = video["cameras"][name]
        _, depth, _ = render_view(tensors, matrix, camera, width, height)
        depth = depth * align["scale"]
        pose = moved_camera(matrix, align)
        depths.append(depth.astype(np.float32))
        poses.append(pose)
        for index, points in enumerate(groups):
            if len(points) < MIN_POINTS:
                continue
            pixels, seen = seen_points(points, pose, camera, depth)
            if seen.sum() >= MIN_POINTS and seen.mean() >= MIN_SEEN_SHARE:
                score = frame_score(pixels[seen], depth.shape, float(seen.mean()))
                scores[index].append((score, number))
    print(f"Checked {len(names)} frames", flush=True)

    args.out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for index, asset in enumerate(assets):
        chosen = choose_frames(scores[index], CROPS_PER_OBJECT, MIN_FRAME_GAP // FRAME_STEP)
        summary[asset["object_id"]] = [names[number] for number in chosen]
        for rank, number in enumerate(chosen):
            image = np.array(Image.open(args.images / names[number]).convert("RGB"))
            pixels, seen = seen_points(groups[index], poses[number], camera, depths[number])
            mask = np.zeros(image.shape[:2], dtype=bool)
            full = np.clip(
                (pixels[seen] * DEPTH_SCALE).astype(int),
                0,
                [image.shape[1] - 1, image.shape[0] - 1],
            )
            mask[full[:, 1], full[:, 0]] = True
            # A sample of points becomes a solid shape, roughly the object's outline.
            mask = ndimage.binary_dilation(mask, iterations=max(image.shape[1] // 90, 4))
            mask = ndimage.binary_closing(mask, iterations=max(image.shape[1] // 90, 4))
            crop = focus_crop(image, mask, mask_box(mask, margin=0.35))
            crop.save(args.out / f"{asset['object_id']}_{rank}.jpg", quality=92)
    (args.out / "frames.json").write_text(json.dumps(summary, indent=1))
    covered = sum(1 for frames in summary.values() if frames)
    print(f"{covered} of {len(assets)} objects have real crops")


if __name__ == "__main__":
    main()
