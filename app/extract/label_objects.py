"""Label merged 3D objects with a local vision model, using several views of each.

    python -m app.extract.label_objects ASSETS.json MASKS_DIR OUT.jsonl --model PATH --views 3

MASKS_DIR holds images/, object_mask/ and object_mask_json/. Each object in ASSETS.json lists its
largest masks in `source_masks`. `--only-ids` limits a run to a benchmark set. `--crops-dir` uses
crops from `app.extract.frame_crops` where an object has them, falling back to its masks otherwise.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image

from app.extract.label_vlm import LABELS, VisionLabeler, focus_crop, mask_box

PROMPT = f"""These images show one object in an industrial equipment room, from {{count}} different
views. The object is shown in full color, and everything around it is dimmed, for context.

Choose the label that best fits it, from: {", ".join(LABELS)}.

How to tell similar things apart:
- pipe: a long straight or curved tube. Often insulated and white, with no moving parts.
- pipe fitting: a short piece that joins pipes, such as an elbow, tee, or flange.
- pump: a compact metal casing inline between two pipe flanges, usually with a motor attached.
- motor: a ribbed or finned housing, usually with a cable box and fan cover.
- valve: a body on a pipe, with a handwheel, lever, or small actuator on top.
- tank: a large closed cylinder or vessel.
- electrical cabinet: a flat metal box on a wall.
- control panel: a box with visible buttons or dials.
- other: a clear single object not in this list. Name it in "reason".
- unknown: if you can't tell, if it looks like several things, or if it's only a fragment.

Look at shape first. Only name equipment if you can see its typical parts.

Reply with JSON only:
{{{{"label": "...", "confidence": 0.0, "reason": "evidence, under 12 words", "visible_text": ""}}}}
"visible_text" is text you can actually read on the object, exactly as written, or "" if none."""


def object_crops(
    asset: dict, masks_dir: Path, views: int, margin: float = 0.35
) -> list[Image.Image]:
    """Return focused crops of an object from its largest masks, at most one per view."""
    crops = []
    used = set()
    for source in asset["source_masks"]:
        if len(crops) >= views:
            break
        if source["view"] in used:
            continue
        used.add(source["view"])
        image = np.array(Image.open(masks_dir / "images" / f"{source['view']}.jpg"))
        ids = np.array(Image.open(masks_dir / "object_mask" / f"{source['view']}.png"))
        mask = ids == source["mask_id"]
        if mask.any():
            crops.append(focus_crop(image, mask, mask_box(mask, margin=margin)))
    return crops


def saved_crops(object_id: str, crops_dir: Path | None, views: int) -> list[Image.Image]:
    """Return an object's saved crops, best first, or nothing if it has none."""
    if crops_dir is None:
        return []
    paths = sorted(crops_dir.glob(f"{object_id}_*.jpg"))[:views]
    return [Image.open(path).convert("RGB") for path in paths]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", type=Path)
    parser.add_argument("masks_dir", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--views", type=int, default=3)
    parser.add_argument("--only-ids", type=Path, help="JSON list of object IDs to label")
    parser.add_argument("--crops-dir", type=Path, help="real-frame crops, named OBJECT_RANK.jpg")
    args = parser.parse_args()

    assets = json.loads(args.assets.read_text())["assets"]
    if args.only_ids:
        wanted = set(json.loads(args.only_ids.read_text()))
        assets = [asset for asset in assets if asset["object_id"] in wanted]

    start = time.perf_counter()
    labeler = VisionLabeler(args.model)
    load_seconds = time.perf_counter() - start

    start = time.perf_counter()
    counts: dict[str, int] = {}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as file:
        for asset in assets:
            crops = saved_crops(asset["object_id"], args.crops_dir, args.views)
            source = "frames" if crops else "renders"
            crops = crops or object_crops(asset, args.masks_dir, args.views)
            if not crops:
                continue
            prompt = PROMPT.format(count=len(crops))
            answer, reply = labeler.label(crops, prompt)
            counts[answer["label"]] = counts.get(answer["label"], 0) + 1
            record = {
                "object_id": asset["object_id"],
                "sam_label": asset["label"],
                **answer,
                "views_used": len(crops),
                "crop_source": source,
                "raw": reply[:300],
            }
            file.write(json.dumps(record) + "\n")
            file.flush()
    summary = {
        "model": args.model,
        "views": args.views,
        "objects": len(assets),
        "load_seconds": round(load_seconds, 1),
        "seconds_per_object": round((time.perf_counter() - start) / max(len(assets), 1), 2),
        "peak_gpu_gb": round(labeler.torch.cuda.max_memory_allocated() / 1e9, 1),
        "labels": dict(sorted(counts.items(), key=lambda pair: -pair[1])),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
