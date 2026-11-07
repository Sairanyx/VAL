"""Camera maths for rendered views. Cameras use OpenCV axes (x right, y down, z forward), and depth
is distance along the camera's forward axis, 0 where nothing was rendered (see app/scene/render.py).
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class View:
    name: str
    image_path: Path
    depth_path: Path
    world_to_camera: np.ndarray
    intrinsics: np.ndarray
    width: int
    height: int


def load_views(render_dir: Path) -> list[View]:
    """Read a render folder: cameras.json, views/NAME.jpg, depth/NAME.npy."""
    render_dir = Path(render_dir)
    info = json.loads((render_dir / "cameras.json").read_text())
    intrinsics = np.array(info["intrinsics"], dtype=np.float64)
    return [
        View(
            name=camera["name"],
            image_path=render_dir / "views" / f"{camera['name']}.jpg",
            depth_path=render_dir / "depth" / f"{camera['name']}.npy",
            world_to_camera=np.array(camera["world_to_camera"], dtype=np.float64),
            intrinsics=intrinsics,
            width=info["width"],
            height=info["height"],
        )
        for camera in info["cameras"]
    ]


def project(points: np.ndarray, view: View) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return pixel columns, rows (floats), and camera depth for world points."""
    rotation, translation = view.world_to_camera[:3, :3], view.world_to_camera[:3, 3]
    camera = points @ rotation.T + translation
    z = camera[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        columns = view.intrinsics[0, 0] * camera[:, 0] / z + view.intrinsics[0, 2]
        rows = view.intrinsics[1, 1] * camera[:, 1] / z + view.intrinsics[1, 2]
    return columns, rows, z


def visible_points(
    points: np.ndarray,
    view: View,
    depth: np.ndarray,
    tolerance: float = 0.03,
    relative_tolerance: float = 0.02,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return indices, rows, and columns of points on the rendered surface of this view.

    A point counts as visible if it lands inside the image and its depth matches the depth map
    within `tolerance + relative_tolerance * depth`, so points hidden behind a surface are skipped.
    """
    columns, rows, z = project(points, view)
    inside = (z > 0.05) & (columns >= 0) & (columns < view.width)
    inside &= (rows >= 0) & (rows < view.height)
    index = np.flatnonzero(inside)
    row, column = rows[index].astype(np.int64), columns[index].astype(np.int64)
    surface = depth[row, column]
    near = (surface > 0) & (np.abs(z[index] - surface) < tolerance + relative_tolerance * surface)
    return index[near], row[near], column[near]


def lift(rows: np.ndarray, columns: np.ndarray, depth: np.ndarray, view: View) -> np.ndarray:
    """Return world points for pixels with depth, using pixel centers."""
    z = depth[rows, columns]
    k = view.intrinsics
    camera = np.stack(
        [(columns + 0.5 - k[0, 2]) / k[0, 0] * z, (rows + 0.5 - k[1, 2]) / k[1, 1] * z, z], axis=1
    )
    rotation, translation = view.world_to_camera[:3, :3], view.world_to_camera[:3, 3]
    return (camera - translation) @ rotation


def upright_box(points: np.ndarray, up_axis: int = 1, low: float = 2, high: float = 98) -> dict:
    """Fit a box that stays upright along `up_axis` and turns about it to fit the points.

    Percentiles instead of min and max keep a few stray splats from stretching the box. Also
    returns the axis-aligned box from the same percentiles.
    """
    points = np.asarray(points, dtype=np.float64)
    aabb_min = np.percentile(points, low, axis=0)
    aabb_max = np.percentile(points, high, axis=0)
    flat = [axis for axis in range(3) if axis != up_axis]
    plane = points[:, flat]
    centered = plane - plane.mean(axis=0)
    yaw = 0.0
    if len(points) >= 3:
        _, vectors = np.linalg.eigh(np.cov(centered.T))
        major = vectors[:, -1]
        yaw = float(np.arctan2(major[1], major[0]))
    cos, sin = np.cos(yaw), np.sin(yaw)
    turn = np.array([[cos, sin], [-sin, cos]])
    local = plane @ turn.T
    local_min, local_max = np.percentile(local, low, axis=0), np.percentile(local, high, axis=0)
    local_center = (local_min + local_max) / 2
    center = np.empty(3)
    center[flat] = local_center @ turn
    center[up_axis] = (aabb_min[up_axis] + aabb_max[up_axis]) / 2
    size = np.empty(3)
    size[flat] = local_max - local_min
    size[up_axis] = aabb_max[up_axis] - aabb_min[up_axis]
    return {
        "center": center.round(4).tolist(),
        "size": size.round(4).tolist(),
        "yaw": round(yaw, 4),
        "bbox_min": aabb_min.round(4).tolist(),
        "bbox_max": aabb_max.round(4).tolist(),
    }
