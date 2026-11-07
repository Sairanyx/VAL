"""Convert splat labels made on a cleaned scene to the original file's order.

    python scripts/remap_labels.py ORIGINAL.ply LABELS.npy OUT.npy --min-opacity 0.05

Pass the cleaning settings the labels were made with. Splats that cleaning removed get label -1.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.scene.load import clean_mask, read_splats  # noqa: E402


def remap(labels: np.ndarray, kept: np.ndarray) -> np.ndarray:
    """Return labels for every splat, given labels for the kept ones only."""
    if len(labels) != int(kept.sum()):
        raise ValueError(f"{len(labels)} labels, but cleaning keeps {int(kept.sum())} splats")
    result = np.full(len(kept), -1, dtype=labels.dtype)
    result[kept] = labels
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("labels", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--min-opacity", type=float, required=True)
    args = parser.parse_args()
    kept = clean_mask(read_splats(args.original), min_opacity=args.min_opacity)
    result = remap(np.load(args.labels), kept)
    np.save(args.out, result)
    print(f"Wrote {args.out}: {len(result)} labels, {int((result >= 0).sum())} on objects")


if __name__ == "__main__":
    main()
