"""Extract framed, labelled assets from a splat scene's rendered views.

    python -m app.extract masks  --scene data/scene/equipment_room --limit 10   # SAM3, resumable
    python -m app.extract merge  --scene data/scene/equipment_room              # objects + boxes
    python -m app.extract label  --scene data/scene/equipment_room              # VLM, resumable
    python -m app.extract assets --scene data/scene/equipment_room              # assets.json

The scene folder needs clean.ply and render folders from app/scene/render.py.
Intermediate files go in SCENE/extract/. SAM3 is gated: run `hf auth login` with an approved
account first.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np


def floor_y(scene_dir: Path, render_sets: list[str]) -> float:
    info = json.loads((scene_dir / render_sets[0] / "cameras.json").read_text())
    up = np.asarray(info["up"], dtype=np.float64)
    return round(float(info["floor_height_along_up"] * up[1] / np.dot(up, up)), 4)


def splat_positions(scene_dir: Path) -> np.ndarray:
    from app.scene.load import read_splats

    return read_splats(scene_dir / "clean.ply").positions


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("stage", choices=["masks", "merge", "label", "assets"])
    parser.add_argument("--scene", type=Path, default=Path("data/scene/equipment_room"))
    parser.add_argument("--sets", nargs="+", default=["render", "render_detail"])
    parser.add_argument("--limit", type=int, help="process at most this many views or objects")
    parser.add_argument("--stride", type=int, default=1, help="use every Nth view")
    parser.add_argument("--shard", default="0/1", help="I/N: this job takes every Nth view from I")
    parser.add_argument("--threshold", type=float, default=0.4, help="SAM3 instance score")
    parser.add_argument("--min-sharpness", type=float, default=20.0)
    parser.add_argument("--sam-model", default="facebook/sam3")
    parser.add_argument("--vlm-model", default="Qwen/Qwen3-VL-2B-Instruct")
    parser.add_argument("--gpu-memory-gb", type=float, help="VLM GPU budget; the rest goes to CPU")
    args = parser.parse_args()

    out_dir = args.scene / "extract"
    out_dir.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    if args.stage == "masks":
        from app.extract.masks import run_masks

        summary = run_masks(
            args.scene,
            out_dir,
            args.sets,
            splat_positions(args.scene),
            limit=args.limit,
            stride=args.stride,
            threshold=args.threshold,
            min_sharpness=args.min_sharpness,
            model_id=args.sam_model,
            shard=tuple(int(part) for part in args.shard.split("/")),
        )
    elif args.stage == "merge":
        from app.extract.merge import run_merge

        prompts = json.loads((out_dir / "prompts.json").read_text())
        summary = run_merge(
            args.scene,
            out_dir,
            splat_positions(args.scene),
            prompts,
            floor_y(args.scene, args.sets),
            args.sets,
        )
    elif args.stage == "label":
        from app.extract.label import run_label

        summary = run_label(out_dir, args.vlm_model, args.limit, args.gpu_memory_gb)
    else:
        from app.extract.label import write_assets

        summary = write_assets(args.scene, out_dir, args.scene.name, "clean.ply")
    summary["stage_seconds"] = round(time.perf_counter() - start, 1)
    suffix = "" if args.shard == "0/1" else "_" + args.shard.replace("/", "of")
    (out_dir / f"{args.stage}{suffix}_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
