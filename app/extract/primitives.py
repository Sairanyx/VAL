"""Fit clean shapes to simple objects, for a tidy, light "objects" view.

    python -m app.extract.primitives ASSETS.json SCENE.ply LABELS.npy OUT.json

Tanks, buckets, and barrels become cylinders. Boxes, cabinets, and appliances become boxes aligned
to the floor. Each fit gets a score: the share of the object's splats near the shape's surface.
Objects with a poor fit, or of any other class, get no shape, so the viewer uses their splats.
"""

import argparse
import json
from pathlib import Path

import numpy as np

CYLINDER_LABELS = {"tank", "bucket", "barrel"}
BOX_LABELS = {"box", "electrical cabinet", "control panel", "appliance"}
MIN_SCORE = 0.5


def basis_from_up(up: np.ndarray) -> np.ndarray:
    """Return a 3x3 matrix whose rows are two floor directions and then `up`."""
    axis = up / np.linalg.norm(up)
    helper = np.eye(3)[np.argmin(np.abs(axis))]
    first = np.cross(axis, helper)
    first /= np.linalg.norm(first)
    return np.stack([first, np.cross(axis, first), axis])


def circle_through(points: np.ndarray) -> tuple[np.ndarray, float]:
    """Return the least-squares circle through 2D points."""
    system = np.column_stack([2 * points, np.ones(len(points))])
    target = (points**2).sum(axis=1)
    solution = np.linalg.lstsq(system, target, rcond=None)[0]
    center = solution[:2]
    return center, float(np.sqrt(max(solution[2] + center @ center, 1e-12)))


def fit_circle(points: np.ndarray, tries: int = 300, seed: int = 0) -> tuple[np.ndarray, float]:
    """Return a 2D center and radius using RANSAC, so stray splats don't pull the circle away.

    Works from a partial arc, which matters because the scan rarely sees all round an object.
    Circles far larger than the object are rejected, as a nearly flat arc fits any large circle.
    """
    random = np.random.default_rng(seed)
    span = float((points.max(axis=0) - points.min(axis=0)).max())
    tolerance = max(0.01, span * 0.03)
    best_inliers = points
    best_count = -1
    for _ in range(tries):
        sample = points[random.choice(len(points), 3, replace=False)]
        center, radius = circle_through(sample)
        if radius > span * 1.5:
            continue
        inliers = np.abs(np.linalg.norm(points - center, axis=1) - radius) < tolerance
        if inliers.sum() > best_count:
            best_count, best_inliers = int(inliers.sum()), points[inliers]
    return circle_through(best_inliers)


def fit_cylinder(points: np.ndarray, up: np.ndarray, tolerance: float = 0.03) -> dict:
    """Return an upright cylinder fitted to the points, in scene coordinates."""
    basis = basis_from_up(up)
    local = points @ basis.T
    center_2d, radius = fit_circle(local[:, :2])
    bottom, top = np.percentile(local[:, 2], [1, 99])
    distance = np.linalg.norm(local[:, :2] - center_2d, axis=1)
    near_side = np.abs(distance - radius) < max(tolerance, radius * 0.1)
    near_caps = (distance < radius) & (
        (np.abs(local[:, 2] - bottom) < tolerance) | (np.abs(local[:, 2] - top) < tolerance)
    )
    center = np.array([center_2d[0], center_2d[1], (bottom + top) / 2]) @ basis
    return {
        "type": "cylinder",
        "center": center.round(4).tolist(),
        "axis": (up / np.linalg.norm(up)).round(4).tolist(),
        "radius": round(radius, 4),
        "height": round(float(top - bottom), 4),
        "score": round(float((near_side | near_caps).mean()), 3),
    }


def fit_box(points: np.ndarray, up: np.ndarray, tolerance: float = 0.03) -> dict:
    """Return a box aligned to the floor, turned to match the object's main direction."""
    basis = basis_from_up(up)
    local = points @ basis.T
    flat = local[:, :2] - np.median(local[:, :2], axis=0)
    _, vectors = np.linalg.eigh(flat.T @ flat)
    turn = vectors[:, ::-1]
    if np.linalg.det(turn) < 0:
        turn[:, 1] *= -1
    turned = np.column_stack([local[:, :2] @ turn, local[:, 2]])
    low, high = np.percentile(turned, [2, 98], axis=0)
    margin = np.minimum(np.abs(turned - low), np.abs(turned - high))
    inside = ((turned >= low - tolerance) & (turned <= high + tolerance)).all(axis=1)
    middle = (low + high) / 2
    center = np.array([*(turn @ middle[:2]), middle[2]]) @ basis
    # Rows are the box's axes in scene coordinates.
    axes = np.column_stack([turn.T, np.zeros(2)])
    axes = np.vstack([axes, [0.0, 0.0, 1.0]]) @ basis
    return {
        "type": "box",
        "center": center.round(4).tolist(),
        "axes": axes.round(4).tolist(),
        "size": (high - low).round(4).tolist(),
        "score": round(float(((margin.min(axis=1) < tolerance) & inside).mean()), 3),
    }


def fit_object(points: np.ndarray, label: str, up: np.ndarray) -> dict | None:
    """Return a fitted shape for this class, or None if the class has no shape or too few points."""
    if len(points) < 30:
        return None
    if label in CYLINDER_LABELS:
        return fit_cylinder(points, up)
    if label in BOX_LABELS:
        return fit_box(points, up)
    return None


def main() -> None:
    from app.scene.load import read_splats

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", type=Path)
    parser.add_argument("scene", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()

    document = json.loads(args.assets.read_text())
    up = np.asarray(document.get("up", (0.0, -1.0, 0.0)), dtype=np.float64)
    splats = read_splats(args.scene)
    labels = np.load(args.labels)
    positions, colors = splats.positions, splats.base_colors
    shapes = {}
    for index, asset in enumerate(document["assets"]):
        members = np.flatnonzero(labels == index)
        shape = fit_object(positions[members], asset.get("suggested_label", asset["label"]), up)
        if shape is None:
            continue
        shape["color"] = np.median(colors[members], axis=0).round(3).tolist()
        shape["use_shape"] = shape["score"] >= MIN_SCORE
        shape["label"] = asset["label"]
        shapes[asset["object_id"]] = shape
    args.out.write_text(json.dumps(shapes, indent=1))
    scores = [shape["score"] for shape in shapes.values()]
    print(
        json.dumps(
            {
                "shapes": len(shapes),
                "good_fits": sum(shape["use_shape"] for shape in shapes.values()),
                "median_score": round(float(np.median(scores)), 3) if scores else None,
            }
        )
    )


if __name__ == "__main__":
    main()
