"""Object shapes from their own splats: a smoothed voxel surface mesh, and true-colour splat files.

The mesh follows the scanned surface at a few centimetres, so it is much closer to the object than
a box, but only where the scan saw it: hidden sides are not invented.
"""

import numpy as np

MIN_OPACITY = 0.3
CELLS_ACROSS = 32
MIN_VOXEL = 0.02
SMOOTH_STEPS = 6

# For a voxel face pointing along +axis, the other two axes in right-handed order.
_CORNERS = np.array([[0, 0], [1, 0], [1, 1], [0, 1]])


def voxel_size(points: np.ndarray) -> float:
    extent = float((points.max(0) - points.min(0)).max()) if len(points) else 0.0
    return max(extent / CELLS_ACROSS, MIN_VOXEL)


def occupied_voxels(points: np.ndarray, size: float) -> np.ndarray:
    keys, counts = np.unique(np.floor(points / size).astype(np.int64), axis=0, return_counts=True)
    if not len(keys):
        return keys
    # A voxel with one splat and no neighbours is usually a floater.
    occupied = {tuple(k) for k in keys}
    steps = np.vstack([np.eye(3, dtype=np.int64), -np.eye(3, dtype=np.int64)])
    lonely = np.array([all(tuple(k + s) not in occupied for s in steps) for k in keys], dtype=bool)
    return keys[(counts >= 2) | ~lonely]


def surface(voxels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Outward faces of a voxel set as triangles, on integer corner coordinates."""
    occupied = {tuple(v) for v in voxels}
    quads = []
    for axis in range(3):
        others = [(axis + 1) % 3, (axis + 2) % 3]
        for sign in (1, -1):
            step = np.zeros(3, dtype=np.int64)
            step[axis] = sign
            open_side = np.array([tuple(v + step) not in occupied for v in voxels], dtype=bool)
            base = voxels[open_side]
            if not len(base):
                continue
            corners = np.repeat(base[:, None, :], 4, axis=1)
            corners[:, :, axis] += 1 if sign > 0 else 0
            order = _CORNERS if sign > 0 else _CORNERS[::-1]
            corners[:, :, others[0]] += order[:, 0]
            corners[:, :, others[1]] += order[:, 1]
            quads.append(corners)
    if not quads:
        return np.zeros((0, 3), np.int64), np.zeros((0, 3), np.int64)
    corners = np.concatenate(quads)
    vertices, index = np.unique(corners.reshape(-1, 3), axis=0, return_inverse=True)
    quad = index.reshape(-1, 4)
    faces = np.concatenate([quad[:, [0, 1, 2]], quad[:, [0, 2, 3]]])
    return vertices, faces


def smooth(vertices: np.ndarray, faces: np.ndarray, steps: int = SMOOTH_STEPS) -> np.ndarray:
    """Taubin smoothing: rounds off voxel steps without shrinking the shape."""
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    a, b = edges[:, 0], edges[:, 1]
    degree = np.bincount(np.concatenate([a, b]), minlength=len(vertices))[:, None]
    points = vertices.astype(np.float64)
    for factor in [0.5, -0.53] * steps:
        total = np.zeros_like(points)
        np.add.at(total, a, points[b])
        np.add.at(total, b, points[a])
        points = points + factor * (total / np.maximum(degree, 1) - points)
    return points


def object_mesh(points: np.ndarray) -> dict | None:
    """Smoothed surface mesh of an object's splat centres, in the same coordinates."""
    if len(points) < 10:
        return None
    size = voxel_size(points)
    voxels = occupied_voxels(points, size)
    if not len(voxels):
        return None
    corners, faces = surface(voxels)
    vertices = smooth(corners, faces) * size
    return {
        "vertices": vertices.astype(np.float32),
        "faces": faces.astype(np.uint32),
        "voxel": size,
    }
