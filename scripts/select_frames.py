# /// script
# requires-python = ">=3.12"
# dependencies = ["opencv-python-headless>=4.10"]
# ///
"""Keep the sharpest frame from each even window of a video.

    uv run scripts/select_frames.py VIDEO OUT_DIR --count 1500

Writes JPEGs, which carry no video metadata or audio, and a manifest.csv of what was kept.
"""

import argparse
import csv
from itertools import pairwise
from pathlib import Path


def pick_sharpest(scores: list[float], count: int) -> list[int]:
    """Split scores into `count` even windows and return the best index from each."""
    if not 0 < count <= len(scores):
        raise ValueError(f"count must be between 1 and {len(scores)}, got {count}")
    edges = [i * len(scores) // count for i in range(count + 1)]
    return [max(range(start, stop), key=scores.__getitem__) for start, stop in pairwise(edges)]


def sharpness(frame) -> float:
    """Variance of the Laplacian at half size, which is less sensitive to sensor noise."""
    import cv2

    gray = cv2.cvtColor(cv2.resize(frame, None, fx=0.5, fy=0.5), cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def read_frames(video: Path):
    import cv2

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise SystemExit(f"Could not open {video}")
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        yield frame
    capture.release()


def main() -> None:
    import cv2

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--count", type=int, default=1500)
    parser.add_argument("--quality", type=int, default=95)
    args = parser.parse_args()

    scores = [sharpness(frame) for frame in read_frames(args.video)]
    keep = set(pick_sharpest(scores, args.count))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "manifest.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["file", "source_frame", "sharpness"])
        for index, frame in enumerate(read_frames(args.video)):
            if index in keep:
                name = f"frame_{index:05d}.jpg"
                cv2.imwrite(
                    str(args.out_dir / name), frame, [cv2.IMWRITE_JPEG_QUALITY, args.quality]
                )
                writer.writerow([name, index, round(scores[index], 1)])
    print(f"Kept {len(keep)} of {len(scores)} frames in {args.out_dir}")


if __name__ == "__main__":
    main()
