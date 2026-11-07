"""Label segmented objects with a local vision model, such as Qwen.

    python -m app.extract.label_vlm SCENE_DIR OUT_DIR --model PATH --limit 60

SCENE_DIR holds images/, object_mask/ (one uint16 PNG of mask IDs per image) and object_mask_json/
({id: {"label", "score"}}). Writes labels.jsonl and the crops the model saw. Runs offline.

Labels describe what an object looks like. They never prove an Excel identity, so text read from a
nameplate is only stored as evidence.
"""

import argparse
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

LABELS = (
    "pump",
    "valve",
    "motor",
    "pipe",
    "pipe fitting",
    "tank",
    "gauge",
    "sensor",
    "electrical cabinet",
    "control panel",
    "cable",
    "light fixture",
    "bag",
    "hose",
    "ladder",
    "shelf",
    "cart",
    "box",
    "bucket",
    "barrel",
    "chair",
    "appliance",
    "tool",
    "door",
    "wall",
    "floor",
    "ceiling",
    "other",
    "unknown",
)

STRUCTURE = {"wall", "floor", "ceiling"}

PROMPT = f"""This is a photo-like view of an industrial equipment room. The object to identify is
shown in full color. Everything around it is dimmed, for context.

Choose the label that best fits the object, from: {", ".join(LABELS)}.
A pump usually has a motor on top and pipe flanges on its sides. A valve has a handwheel, lever, or
actuator on a pipe. Use "unknown" if you can't tell, or if it isn't one single object.

Reply with JSON only:
{{"label": "...", "confidence": 0.0, "description": "under 12 words", "visible_text": ""}}
"visible_text" is any text you can actually read on the object, exactly as written, or "" if
none."""


@dataclass
class Crop:
    image_name: str
    mask_id: int
    sam_label: str
    sam_score: float
    area_share: float
    box: tuple[int, int, int, int]


def parse_answer(text: str) -> dict:
    """Read the model's JSON reply. Anything unusable becomes "unknown" with zero confidence."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    found = re.search(r"\{.*\}", text, flags=re.S)
    result = {"label": "unknown", "confidence": 0.0, "description": "", "visible_text": ""}
    if not found:
        return result
    try:
        answer = json.loads(found.group())
    except json.JSONDecodeError:
        return result
    if not isinstance(answer, dict):
        return result
    label = str(answer.get("label", "")).strip().lower()
    if label not in LABELS:
        return result
    try:
        confidence = float(answer.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "label": label,
        "confidence": min(max(confidence, 0.0), 1.0),
        "description": str(answer.get("description") or answer.get("reason") or "")[:120],
        "visible_text": str(answer.get("visible_text", ""))[:120],
    }


def mask_box(mask: np.ndarray, margin: float = 0.25) -> tuple[int, int, int, int]:
    """Return (left, top, right, bottom) around a boolean mask, with some context around it."""
    rows, columns = np.nonzero(mask)
    top, bottom, left, right = rows.min(), rows.max() + 1, columns.min(), columns.max() + 1
    pad_y, pad_x = int((bottom - top) * margin) + 4, int((right - left) * margin) + 4
    height, width = mask.shape
    return (
        int(max(left - pad_x, 0)),
        int(max(top - pad_y, 0)),
        int(min(right + pad_x, width)),
        int(min(bottom + pad_y, height)),
    )


def focus_crop(image: np.ndarray, mask: np.ndarray, box: tuple[int, int, int, int]) -> Image.Image:
    """Return a crop with the object in full color and its surroundings dimmed."""
    left, top, right, bottom = box
    dimmed = (image * 0.35).astype(np.uint8)
    combined = np.where(mask[..., None], image, dimmed)[top:bottom, left:right]
    crop = Image.fromarray(combined)
    longest = max(crop.size)
    if longest < 448:
        scale = 448 / longest
        size = (round(crop.width * scale), round(crop.height * scale))
        crop = crop.resize(size, Image.BICUBIC)
    return crop


def list_crops(
    scene_dir: Path,
    min_area_share: float = 0.002,
    max_area_share: float = 0.5,
) -> list[Crop]:
    """Return candidate masks, skipping tiny ones, huge ones, and walls, floors, and ceilings."""
    crops = []
    for path in sorted((scene_dir / "object_mask").glob("*.png")):
        ids = np.array(Image.open(path))
        info = json.loads((scene_dir / "object_mask_json" / f"{path.stem}.json").read_text())
        values, counts = np.unique(ids[ids > 0], return_counts=True)
        for value, count in zip(values.tolist(), counts.tolist(), strict=True):
            share = count / ids.size
            entry = info.get(str(value), {})
            if not min_area_share <= share <= max_area_share or entry.get("label") in STRUCTURE:
                continue
            crops.append(
                Crop(
                    image_name=path.stem,
                    mask_id=value,
                    sam_label=str(entry.get("label", "")),
                    sam_score=float(entry.get("score", 0.0)),
                    area_share=round(share, 5),
                    box=mask_box(ids == value),
                )
            )
    return crops


def sample_evenly(crops: list[Crop], limit: int | None) -> list[Crop]:
    """Return up to `limit` crops, spaced evenly, so every view is represented."""
    if limit is None or len(crops) <= limit:
        return crops
    return [crops[index] for index in np.linspace(0, len(crops) - 1, limit).astype(int)]


class VisionLabeler:
    """Runs a local Hugging Face image-text-to-text model, loaded with no network access."""

    def __init__(self, model_path: str) -> None:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self.torch = torch
        self.processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
        self.model = AutoModelForImageTextToText.from_pretrained(
            model_path, dtype="auto", device_map="cuda", local_files_only=True
        ).eval()

    def label(
        self, crop: Image.Image | list[Image.Image], prompt: str = PROMPT
    ) -> tuple[dict, str]:
        """Return the parsed answer and the model's raw reply, for one or more views."""
        crops = crop if isinstance(crop, list) else [crop]
        images = [{"type": "image", "image": item} for item in crops]
        messages = [{"role": "user", "content": [*images, {"type": "text", "text": prompt}]}]
        inputs = self.processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
            enable_thinking=False,
        ).to(self.model.device)
        with self.torch.inference_mode():
            output = self.model.generate(**inputs, max_new_tokens=120, do_sample=False)
        reply = self.processor.batch_decode(
            output[:, inputs["input_ids"].shape[1] :], skip_special_tokens=True
        )[0]
        return parse_answer(reply), reply


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    crops_dir = args.out_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    candidates = list_crops(args.scene_dir)
    chosen = sample_evenly(candidates, args.limit)
    print(f"{len(candidates)} candidate masks, labelling {len(chosen)}", flush=True)

    start = time.perf_counter()
    labeler = VisionLabeler(args.model)
    load_seconds = time.perf_counter() - start

    start = time.perf_counter()
    counts: dict[str, int] = {}
    with (args.out_dir / "labels.jsonl").open("w") as file:
        for item in chosen:
            image = np.array(Image.open(args.scene_dir / "images" / f"{item.image_name}.jpg"))
            ids = np.array(Image.open(args.scene_dir / "object_mask" / f"{item.image_name}.png"))
            crop = focus_crop(image, ids == item.mask_id, item.box)
            name = f"{item.image_name}_{item.mask_id:04d}.jpg"
            crop.save(crops_dir / name, quality=90)
            answer, reply = labeler.label(crop)
            counts[answer["label"]] = counts.get(answer["label"], 0) + 1
            record = {**vars(item), **answer, "crop": name, "raw": reply[:300]}
            file.write(json.dumps(record) + "\n")
            file.flush()
    seconds = time.perf_counter() - start
    summary = {
        "model": args.model,
        "candidates": len(candidates),
        "labelled": len(chosen),
        "load_seconds": round(load_seconds, 1),
        "seconds_per_crop": round(seconds / max(len(chosen), 1), 2),
        "peak_gpu_gb": round(labeler.torch.cuda.max_memory_allocated() / 1e9, 1),
        "labels": dict(sorted(counts.items(), key=lambda pair: -pair[1])),
    }
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
