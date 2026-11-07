# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2.0"]
# ///
"""Pack rendered views into one tar for sharing, and unpack them again.

    python scripts/views_archive.py pack SCENE_DIR ARCHIVE.tar render render_detail
    uv run scripts/views_archive.py unpack ARCHIVE.tar SCENE_DIR

Depth is stored compressed as whole millimetres, about a quarter of the size. Unpacking restores
the float32 `.npy` files that the pipeline reads, in metres or scene units as they were rendered.
"""

import argparse
import io
import tarfile
from pathlib import Path

import numpy as np

MILLIS_PER_UNIT = 1000


def compress_depth(depth: np.ndarray) -> bytes:
    """Return a compressed npz of depth as uint16 thousandths of a unit. 0 means no depth."""
    if depth.max() * MILLIS_PER_UNIT > np.iinfo(np.uint16).max:
        raise ValueError(f"Depth {depth.max()} is too large to store")
    buffer = io.BytesIO()
    np.savez_compressed(buffer, depth=np.round(depth * MILLIS_PER_UNIT).astype(np.uint16))
    return buffer.getvalue()


def decompress_depth(data: bytes) -> np.ndarray:
    return (np.load(io.BytesIO(data))["depth"] / MILLIS_PER_UNIT).astype(np.float32)


def pack(scene_dir: Path, archive: Path, sets: list[str]) -> None:
    with tarfile.open(archive, "w") as tar:
        for name in sets:
            root = scene_dir / name
            tar.add(root / "cameras.json", arcname=f"{name}/cameras.json")
            for image in sorted((root / "views").glob("*.jpg")):
                tar.add(image, arcname=f"{name}/views/{image.name}")
            for path in sorted((root / "depth").glob("*.npy")):
                data = compress_depth(np.load(path))
                info = tarfile.TarInfo(f"{name}/depth/{path.stem}.npz")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    print(f"Wrote {archive}: {archive.stat().st_size / 1e6:.0f} MB")


def unpack(archive: Path, scene_dir: Path) -> None:
    images = depths = 0
    with tarfile.open(archive) as tar:
        for member in tar:
            if not member.isfile():
                continue
            data = tar.extractfile(member).read()
            target = (scene_dir / member.name).resolve()
            if not target.is_relative_to(scene_dir.resolve()):
                raise ValueError(f"Unsafe path in archive: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.suffix == ".npz":
                np.save(target.with_suffix(".npy"), decompress_depth(data))
                depths += 1
            else:
                target.write_bytes(data)
                images += target.suffix == ".jpg"
    print(f"Unpacked {images} images and {depths} depth maps to {scene_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    packing = commands.add_parser("pack")
    packing.add_argument("scene_dir", type=Path)
    packing.add_argument("archive", type=Path)
    packing.add_argument("sets", nargs="+")
    unpacking = commands.add_parser("unpack")
    unpacking.add_argument("archive", type=Path)
    unpacking.add_argument("scene_dir", type=Path)
    args = parser.parse_args()
    if args.command == "pack":
        pack(args.scene_dir, args.archive, args.sets)
    else:
        unpack(args.archive, args.scene_dir)


if __name__ == "__main__":
    main()
