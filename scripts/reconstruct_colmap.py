"""Estimate cameras and sparse points from ordered video frames with COLMAP.

    python scripts/reconstruct_colmap.py FRAMES_DIR OUT_DIR --vocab-tree VOCAB.bin

Uses sequential matching with loop detection. Keeps the largest model in OUT_DIR/sparse
and writes summary.json.
"""

import argparse
import json
import os
import time
from pathlib import Path

import pycolmap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--vocab-tree", type=Path, required=True)
    parser.add_argument("--overlap", type=int, default=20)
    parser.add_argument("--limit", type=int, help="use only the first N frames, for smoke tests")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    names = sorted(path.name for path in args.frames_dir.glob("*.jpg"))[: args.limit]
    threads = len(os.sched_getaffinity(0))
    database = args.out_dir / "database.db"
    timings = {}

    start = time.perf_counter()
    reader = pycolmap.ImageReaderOptions()
    reader.camera_model = "OPENCV"
    extraction = pycolmap.FeatureExtractionOptions()
    extraction.num_threads = threads
    extraction.use_gpu = False
    pycolmap.extract_features(
        database,
        args.frames_dir,
        image_names=names,
        camera_mode=pycolmap.CameraMode.SINGLE,
        reader_options=reader,
        extraction_options=extraction,
    )
    timings["extract_seconds"] = round(time.perf_counter() - start)
    print(f"Extracted features: {timings['extract_seconds']} s", flush=True)

    start = time.perf_counter()
    matching = pycolmap.FeatureMatchingOptions()
    matching.num_threads = threads
    matching.use_gpu = False
    pairing = pycolmap.SequentialPairingOptions()
    pairing.overlap = args.overlap
    pairing.loop_detection = True
    pairing.vocab_tree_path = str(args.vocab_tree)
    pycolmap.match_sequential(database, matching_options=matching, pairing_options=pairing)
    timings["match_seconds"] = round(time.perf_counter() - start)
    print(f"Matched features: {timings['match_seconds']} s", flush=True)

    start = time.perf_counter()
    mapping = pycolmap.IncrementalPipelineOptions()
    mapping.num_threads = threads
    models = pycolmap.incremental_mapping(
        database, args.frames_dir, args.out_dir / "models", options=mapping
    )
    timings["map_seconds"] = round(time.perf_counter() - start)

    sizes = sorted((model.num_reg_images() for model in models.values()), reverse=True)
    summary = {"frames": len(names), "threads": threads, "model_sizes": sizes, **timings}
    if models:
        best = max(models.values(), key=lambda model: model.num_reg_images())
        sparse = args.out_dir / "sparse"
        sparse.mkdir(exist_ok=True)
        best.write(sparse)
        best.export_PLY(args.out_dir / "points.ply")
        summary |= {
            "registered": best.num_reg_images(),
            "points3d": best.num_points3D(),
            "mean_reprojection_error_px": round(best.compute_mean_reprojection_error(), 3),
        }
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
