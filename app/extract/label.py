"""Stage 3: label merged objects with a vision-language model, then write assets.json and
splat_labels.npy.

The VLM sees up to three crops of each object, with everything outside the object darkened, and
must answer in JSON with a label from a fixed list. Answers are saved after every object, so a
stopped run can resume. The demo never loads the VLM: it only reads the saved results.
"""

import json
import re
from pathlib import Path

import numpy as np
from PIL import Image

from app.extract.masks import PROMPTS

LABELS = sorted((set(PROMPTS) - {"sensor"}) | {"vibration sensor", "other object"})

QUESTION = """These {count} images show one object from a 3D scan of an industrial equipment room.
The object is the bright region; everything else is darkened. Images are renders, so they may be
blurry.

Answer with JSON only, with these keys:
"label": the best match from this list: {labels}, or "unknown".
"single_object": true if the bright region is one physical object or one clear part of
equipment; false if it is wall, floor, ceiling, empty background, or several unrelated things.
"confidence": a number from 0 to 1 for the label.
"description": at most 15 words describing the object.
"visible_text": any text you can read on it exactly as written, or "".
"""


def parse_answer(text: str, labels: list[str] = LABELS) -> dict:
    """Read the VLM's JSON answer, falling back to safe values for anything missing or invalid."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        answer = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        answer = {}
    label = str(answer.get("label", "unknown")).strip().lower()
    try:
        confidence = float(answer.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    single = answer.get("single_object", False)
    if isinstance(single, str):
        single = single.strip().lower() == "true"
    return {
        "label": label if label in labels else "unknown",
        "single_object": bool(single),
        "confidence": round(min(max(confidence, 0.0), 1.0), 3),
        "description": str(answer.get("description", ""))[:200],
        "visible_text": str(answer.get("visible_text", ""))[:200],
        "parsed": bool(answer),
    }


class QwenLabeler:
    """Qwen3-VL via transformers. On a small GPU, layers that don't fit stay in CPU memory."""

    def __init__(self, model_id: str, gpu_memory_gb: float | None = None):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        self.torch = torch
        cuda = torch.cuda.is_available()
        bf16 = not cuda or torch.cuda.is_bf16_supported(including_emulation=False)
        options = {"dtype": torch.bfloat16 if bf16 else torch.float16}
        if cuda:
            options["device_map"] = "auto"
            if gpu_memory_gb:
                options["max_memory"] = {0: f"{gpu_memory_gb}GiB", "cpu": "24GiB"}
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = AutoModelForImageTextToText.from_pretrained(model_id, **options).eval()

    def ask(self, images: list[Image.Image], question: str, max_new_tokens: int = 200) -> str:
        content = [{"type": "image", "image": image} for image in images]
        content.append({"type": "text", "text": question})
        inputs = self.processor.apply_chat_template(
            [{"role": "user", "content": content}],
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self.model.device)
        with self.torch.inference_mode():
            output = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        new_tokens = output[:, inputs["input_ids"].shape[1] :]
        return self.processor.batch_decode(new_tokens, skip_special_tokens=True)[0]


def run_label(
    out_dir: Path, model_id: str, limit: int | None = None, gpu_memory_gb: float | None = None
) -> dict:
    objects = [
        item
        for item in json.loads((out_dir / "objects.json").read_text())["objects"]
        if item["status"] == "ok"
    ]
    labels_path = out_dir / "labels.json"
    results = json.loads(labels_path.read_text()) if labels_path.exists() else {}
    todo = [item for item in objects if item["object_id"] not in results][:limit]
    labeler = QwenLabeler(model_id, gpu_memory_gb) if todo else None
    question = QUESTION.format(count="{count}", labels=", ".join(LABELS))
    for number, item in enumerate(todo, 1):
        images = [Image.open(out_dir / "crops" / name).convert("RGB") for name in item["crops"]]
        text = labeler.ask(images, question.format(count=len(images)))
        results[item["object_id"]] = {**parse_answer(text), "model": model_id, "raw": text}
        labels_path.write_text(json.dumps(results, indent=1))
        answer = results[item["object_id"]]
        print(
            f"[{number}/{len(todo)}] {item['object_id']} sam3={item['sam3_label']} "
            f"vlm={answer['label']} single={answer['single_object']}",
            flush=True,
        )
    return {"objects": len(objects), "labelled": len(results), "new": len(todo)}


def write_assets(scene_dir: Path, out_dir: Path, scene_id: str, splat_source: str) -> dict:
    """Join merged objects with VLM answers into assets.json, in the fixture's format.

    Objects the VLM calls not a single object are dropped as junk. Without a VLM answer, the SAM3
    label is used. splat_labels.npy gives each splat its object's index in `assets`, or -1.
    """
    merged = json.loads((out_dir / "objects.json").read_text())
    labels_path = out_dir / "labels.json"
    answers = json.loads(labels_path.read_text()) if labels_path.exists() else {}
    object_splats = np.load(out_dir / "object_splats.npy")
    kept = [item for item in merged["objects"] if item["status"] == "ok"]

    # One spare slot at the end, so background splats (-1) also map to -1.
    assets, remap, junk = [], np.full(len(kept) + 1, -1, dtype=np.int32), 0
    for number, item in enumerate(kept):
        answer = answers.get(item["object_id"])
        if answer and answer["parsed"] and not answer["single_object"]:
            junk += 1
            continue
        use_vlm = answer and answer["parsed"] and answer["label"] != "unknown"
        remap[number] = len(assets)
        assets.append(
            {
                "object_id": item["object_id"],
                "label": answer["label"] if use_vlm else item["sam3_label"],
                "label_confidence": answer["confidence"] if use_vlm else item["sam3_confidence"],
                "label_source": "vlm" if use_vlm else "sam3",
                "sam3_label": item["sam3_label"],
                "description": answer["description"] if answer else "",
                "visible_text": answer["visible_text"] if answer else "",
                "center": item["center"],
                "bbox_min": item["bbox_min"],
                "bbox_max": item["bbox_max"],
                "size": item["size"],
                "yaw": item["yaw"],
                "n_splats": item["n_splats"],
                "n_views": item["n_views"],
                "crops": [f"extract/crops/{name}" for name in item["crops"]],
                "mapping": None,
            }
        )
    splat_labels = remap[object_splats]
    np.save(scene_dir / "splat_labels.npy", splat_labels)
    result = {
        "scene_id": scene_id,
        "floor_y": merged["floor_y"],
        "splat_source": splat_source,
        "splat_count": int(len(splat_labels)),
        "assets": assets,
    }
    (scene_dir / "assets.json").write_text(json.dumps(result, indent=1))
    counts = {}
    for asset in assets:
        counts[asset["label"]] = counts.get(asset["label"], 0) + 1
    return {"assets": len(assets), "dropped_as_junk": junk, "labels": counts}
