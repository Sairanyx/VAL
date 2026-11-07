"""Move a splat into another coordinate system with a similarity transform: x' = s R x + t.

    python -m app.scene.transform IN.ply OUT.ply ALIGN.json

ALIGN.json holds "scale", "R" (3x3), and "t". Positions, sizes, rotations, and view-dependent color
all change together. Rotating view-dependent color needs gsplat's spherical harmonics, so a GPU
environment is needed when the file has `f_rest_*` properties.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from app.scene.load import Splats, read_splats, write_splats


def matrix_to_quaternion(matrix: np.ndarray) -> np.ndarray:
    """Return a unit quaternion (w, x, y, z) for a 3x3 rotation matrix."""
    candidates = np.array(
        [
            1 + matrix[0, 0] + matrix[1, 1] + matrix[2, 2],
            1 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2],
            1 - matrix[0, 0] + matrix[1, 1] - matrix[2, 2],
            1 - matrix[0, 0] - matrix[1, 1] + matrix[2, 2],
        ]
    )
    largest = int(np.argmax(candidates))
    root = np.sqrt(max(candidates[largest], 1e-12)) / 2
    scale = 0.25 / root
    if largest == 0:
        result = [
            root,
            (matrix[2, 1] - matrix[1, 2]) * scale,
            (matrix[0, 2] - matrix[2, 0]) * scale,
            (matrix[1, 0] - matrix[0, 1]) * scale,
        ]
    elif largest == 1:
        result = [
            (matrix[2, 1] - matrix[1, 2]) * scale,
            root,
            (matrix[0, 1] + matrix[1, 0]) * scale,
            (matrix[0, 2] + matrix[2, 0]) * scale,
        ]
    elif largest == 2:
        result = [
            (matrix[0, 2] - matrix[2, 0]) * scale,
            (matrix[0, 1] + matrix[1, 0]) * scale,
            root,
            (matrix[1, 2] + matrix[2, 1]) * scale,
        ]
    else:
        result = [
            (matrix[1, 0] - matrix[0, 1]) * scale,
            (matrix[0, 2] + matrix[2, 0]) * scale,
            (matrix[1, 2] + matrix[2, 1]) * scale,
            root,
        ]
    return np.array(result)


def multiply_quaternions(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Return left * right for quaternions (w, x, y, z). `right` may be shaped (N, 4)."""
    w1, x1, y1, z1 = left
    w2, x2, y2, z2 = right.T
    return np.stack(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ],
        axis=1,
    )


def harmonics_rotation(rotation: np.ndarray, degree: int = 3, samples: int = 4000) -> np.ndarray:
    """Return M so that coefficients c become M c when the scene rotates. Excludes the base color.

    Found numerically from gsplat's own harmonics, so it always matches how the renderer reads them.
    """
    import torch
    from gsplat.cuda._torch_impl import _eval_sh_bases_fast

    random = np.random.default_rng(0)
    directions = random.normal(size=(samples, 3))
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)

    def bases(points: np.ndarray) -> np.ndarray:
        tensor = torch.as_tensor(points, dtype=torch.float64)
        count = (degree + 1) ** 2
        return _eval_sh_bases_fast(count, tensor).numpy()[:, 1:]

    # A rotated scene shows at direction d what the original showed at R^T d.
    return np.linalg.lstsq(bases(directions), bases(directions @ rotation), rcond=None)[0]


def transform_splats(
    splats: Splats, scale: float, rotation: np.ndarray, shift: np.ndarray
) -> Splats:
    """Return a transformed copy of the splats."""
    data = splats.data.copy()
    moved = scale * splats.positions @ rotation.T + shift
    data["x"], data["y"], data["z"] = moved.T
    for axis in range(3):
        data[f"scale_{axis}"] += np.log(scale)
    quaternions = multiply_quaternions(matrix_to_quaternion(rotation), splats.quaternions)
    for index in range(4):
        data[f"rot_{index}"] = quaternions[:, index]
    names = [name for name in data.dtype.names if name.startswith("f_rest_")]
    if names:
        coefficients = len(names) // 3
        rest = np.stack([data[name] for name in names], axis=1).reshape(len(data), 3, coefficients)
        turned = rest @ harmonics_rotation(rotation).T
        turned = turned.reshape(len(data), -1)
        for index, name in enumerate(names):
            data[name] = turned[:, index]
    return Splats(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("align", type=Path)
    args = parser.parse_args()
    align = json.loads(args.align.read_text())
    moved = transform_splats(
        read_splats(args.input),
        float(align["scale"]),
        np.array(align["R"], dtype=np.float64),
        np.array(align["t"], dtype=np.float64),
    )
    write_splats(moved, args.output)
    print(f"Wrote {args.output}: {len(moved)} splats")


if __name__ == "__main__":
    main()
