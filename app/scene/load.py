"""Read, validate, clean, and write Gaussian splat PLY files.

    uv run --no-project --with numpy python -m app.scene.load INPUT.ply --out clean.ply

Works with any scene: properties are found by name, not position, and the floor search takes the
scene's up direction. `Equipment Room.ply` has +y pointing down, so its up direction is (0, -1, 0).
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REQUIRED = ["x", "y", "z", "opacity", "scale_0", "scale_1", "scale_2"]
REQUIRED += ["rot_0", "rot_1", "rot_2", "rot_3", "f_dc_0", "f_dc_1", "f_dc_2"]
PLY_TYPES = {"float": "<f4", "float32": "<f4", "double": "<f8", "float64": "<f8", "uchar": "u1"}
# Values beyond this aren't plausible splat data. The damaged PLY had values near 1e36.
MAX_SANE_VALUE = 1e4


@dataclass
class Splats:
    """Splat records, keeping every PLY property so a subset can be written back unchanged."""

    data: np.ndarray

    def __len__(self) -> int:
        return len(self.data)

    def __getitem__(self, selection) -> "Splats":
        return Splats(self.data[selection])

    @property
    def positions(self) -> np.ndarray:
        return np.stack([self.data["x"], self.data["y"], self.data["z"]], axis=1).astype(np.float64)

    @property
    def opacities(self) -> np.ndarray:
        """Opacity from 0 to 1. The file stores it as a logit."""
        return 1 / (1 + np.exp(-self.data["opacity"].astype(np.float64)))

    @property
    def scales(self) -> np.ndarray:
        """Size along each splat axis. The file stores log values."""
        logs = [self.data[f"scale_{axis}"] for axis in range(3)]
        return np.exp(np.stack(logs, axis=1).astype(np.float64))

    @property
    def quaternions(self) -> np.ndarray:
        """Unit rotations as w, x, y, z."""
        parts = [self.data[f"rot_{index}"] for index in range(4)]
        quats = np.stack(parts, axis=1).astype(np.float64)
        return quats / np.linalg.norm(quats, axis=1, keepdims=True)

    @property
    def base_colors(self) -> np.ndarray:
        """RGB from 0 to 1, from the zero-order spherical harmonic only."""
        dc = np.stack([self.data[f"f_dc_{channel}"] for channel in range(3)], axis=1)
        return np.clip(0.5 + 0.28209479177387814 * dc.astype(np.float64), 0, 1)


def read_splats(path: Path) -> Splats:
    """Read a binary little-endian splat PLY, raising ValueError if it isn't complete."""
    with Path(path).open("rb") as file:
        if file.readline().strip() != b"ply":
            raise ValueError(f"{path} is not a PLY file")
        count, fields, in_vertex = None, [], False
        while True:
            line = file.readline()
            if not line:
                raise ValueError(f"{path} has no end_header line")
            words = line.decode("ascii", "replace").split()
            if words == ["end_header"]:
                break
            if words[:1] == ["format"] and words[1] != "binary_little_endian":
                raise ValueError(f"{path} must be binary_little_endian, not {words[1]}")
            if words[:1] == ["element"]:
                in_vertex = words[1] == "vertex"
                count = int(words[2]) if in_vertex else count
            elif words[:1] == ["property"] and in_vertex:
                if words[1] not in PLY_TYPES:
                    raise ValueError(f"Unsupported PLY property type: {words[1]}")
                fields.append((words[2], PLY_TYPES[words[1]]))
        if count is None:
            raise ValueError(f"{path} has no vertex element")
        missing = [name for name in REQUIRED if name not in dict(fields)]
        if missing:
            raise ValueError(f"{path} is missing splat properties: {missing}")
        data = np.fromfile(file, dtype=fields, count=count)
    if len(data) != count:
        raise ValueError(f"{path} is truncated: {len(data)} of {count} records")
    return Splats(data)


def write_splats(splats: Splats, path: Path) -> None:
    """Write splats as binary little-endian PLY, with the same properties they were read with."""
    types = {value: key for key, value in reversed(PLY_TYPES.items())}
    header = ["ply", "format binary_little_endian 1.0", f"element vertex {len(splats)}"]
    for name in splats.data.dtype.names:
        kind = splats.data.dtype[name].newbyteorder("<").str.replace("|", "<").replace("<u1", "u1")
        header.append(f"property {types[kind]} {name}")
    header.append("end_header\n")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as file:
        file.write("\n".join(header).encode("ascii"))
        splats.data.tofile(file)


def valid_mask(splats: Splats) -> np.ndarray:
    """True for records with finite, plausible values in every property."""
    mask = np.ones(len(splats), dtype=bool)
    for name in splats.data.dtype.names:
        values = splats.data[name]
        if values.dtype.kind == "f":
            mask &= np.isfinite(values) & (np.abs(values) < MAX_SANE_VALUE)
    return mask


def clean_mask(
    splats: Splats,
    min_opacity: float = 0.05,
    max_scale_percentile: float = 99.0,
    voxel_size: float = 0.1,
    min_voxel_count: int = 3,
) -> np.ndarray:
    """True for splats to keep: drops invalid, nearly transparent, oversized, and isolated ones.

    Isolated means sharing a voxel with too few other splats, which catches most floaters.
    """
    mask = valid_mask(splats)
    with np.errstate(over="ignore", invalid="ignore"):
        mask &= splats.opacities >= min_opacity
        sizes = splats.scales.max(axis=1)
    if mask.any():
        mask &= sizes <= np.percentile(sizes[mask], max_scale_percentile)
    if mask.any() and min_voxel_count > 1:
        voxels = np.floor(splats.positions[mask] / voxel_size).astype(np.int64)
        _, inverse, counts = np.unique(voxels, axis=0, return_inverse=True, return_counts=True)
        kept = np.flatnonzero(mask)
        mask[kept[counts[inverse.ravel()] < min_voxel_count]] = False
    return mask


def estimate_floor(
    positions: np.ndarray, up: tuple[float, float, float], bin_size: float = 0.02
) -> float:
    """Return the floor's height along `up`: the strongest layer in the lowest 30% of the scene."""
    direction = np.asarray(up, dtype=np.float64)
    heights = positions @ (direction / np.linalg.norm(direction))
    low, high = np.percentile(heights, [0.5, 99.5])
    bins = np.arange(low, high + bin_size, bin_size)
    counts, edges = np.histogram(heights, bins=bins)
    lowest = max(int(len(counts) * 0.3), 1)
    peak = int(np.argmax(counts[:lowest]))
    return float((edges[peak] + edges[peak + 1]) / 2)


def summarize(splats: Splats, up: tuple[float, float, float] | None = None) -> dict:
    """Return plain-number facts about a scene for logs and docs/RESULTS.md."""
    positions = splats.positions
    low, high = np.percentile(positions, [0.5, 99.5], axis=0)
    summary = {
        "splats": len(splats),
        "bounds_min": low.round(3).tolist(),
        "bounds_max": high.round(3).tolist(),
        "extent": (high - low).round(3).tolist(),
        "opacity_above_0.5": int((splats.opacities > 0.5).sum()),
    }
    if up is not None:
        summary["floor_height_along_up"] = round(estimate_floor(positions, up), 3)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--out", type=Path, help="write the cleaned scene here")
    parser.add_argument("--up", type=float, nargs=3, default=(0.0, -1.0, 0.0))
    parser.add_argument("--min-opacity", type=float, default=0.05)
    args = parser.parse_args()

    splats = read_splats(args.input)
    valid = valid_mask(splats)
    keep = clean_mask(splats, min_opacity=args.min_opacity)
    report = {
        "input_splats": len(splats),
        "invalid_splats": int((~valid).sum()),
        "removed_by_cleaning": int(valid.sum() - keep.sum()),
        "cleaned": summarize(splats[keep], tuple(args.up)) if keep.any() else None,
    }
    if args.out:
        write_splats(splats[keep], args.out)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
