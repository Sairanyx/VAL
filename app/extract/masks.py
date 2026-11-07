"""Stage 1: find objects in each rendered view with SAM3 text prompts, and record which splats each
mask covers.

Each view gets OUT/claims/NAME.npz (existing files are skipped, so a stopped run can resume) and a
small OUT/overlays/NAME.jpg to check the masks by eye. Torch and transformers load only when SAM3
runs, so the rest of this file works without them.
"""

import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import binary_erosion, convolve

from app.extract.geometry import View, load_views, visible_points

PROMPTS = [
    # Classes the Excel pack has records for
    "pump",
    "valve",
    "electric motor",
    "pressure gauge",
    "pressure transmitter",
    "sensor",
    # Other plant equipment
    "expansion tank",
    "tank",
    "boiler",
    "electrical cabinet",
    "control panel",
    "switch box",
    "pipe",
    "fire extinguisher",
    "fan",
    # Everything else, since more framed objects score higher
    "ladder",
    "trolley",
    "chair",
    "cardboard box",
    "shelf",
    "washing machine",
    "bucket",
    "vacuum cleaner",
    "trash bin",
    "lamp",
    "cable reel",
    "hose",
    "plastic crate",
    "door",
    "sign",
    "toolbox",
    "canister",
    "bottle",
    "table",
    "cabinet",
]


class Sam3Segmenter:
    """SAM3 with text prompts. Encodes each image once, then runs every prompt against it."""

    def __init__(self, model_id: str = "facebook/sam3", device: str | None = None, dtype=None):
        import torch
        from transformers import Sam3Model, Sam3Processor

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        # SAM3's text encoder and mask decoder overflow to NaN in float16, so use bfloat16 where
        # the GPU supports it (LUMI, 5090, L40) and float32 otherwise (GTX 1650).
        bf16 = self.device == "cuda" and torch.cuda.is_bf16_supported(including_emulation=False)
        self.dtype = dtype or (torch.bfloat16 if bf16 else torch.float32)
        self.processor = Sam3Processor.from_pretrained(model_id)
        self.model = Sam3Model.from_pretrained(model_id, dtype=self.dtype).to(self.device).eval()
        self.text = {}

    def _text_inputs(self, prompt: str):
        if prompt not in self.text:
            self.text[prompt] = self.processor(text=prompt, return_tensors="pt").to(self.device)
        return self.text[prompt]

    def segment(
        self, image: Image.Image, prompts: list[str], threshold: float = 0.4
    ) -> list[tuple[int, float, np.ndarray]]:
        """Return (prompt index, score, boolean mask) for every instance found."""
        torch = self.torch
        inputs = self.processor(images=image, return_tensors="pt").to(self.device)
        found = []
        with torch.inference_mode():
            vision = self.model.get_vision_features(pixel_values=inputs.pixel_values.to(self.dtype))
            for index, prompt in enumerate(prompts):
                text = self._text_inputs(prompt)
                outputs = self.model(
                    vision_embeds=vision,
                    input_ids=text.input_ids,
                    attention_mask=text.attention_mask,
                )
                result = self.processor.post_process_instance_segmentation(
                    outputs, threshold=threshold, target_sizes=[(image.height, image.width)]
                )[0]
                masks = result["masks"].bool().cpu().numpy()
                for score, mask in zip(result["scores"].float().tolist(), masks, strict=True):
                    found.append((index, float(score), mask))
        return found


def view_quality(image: np.ndarray, depth: np.ndarray) -> dict:
    """Sharpness (Laplacian variance), overexposed share, and depth coverage of a view."""
    gray = image[::2, ::2].astype(np.float32).mean(axis=2)
    laplacian = convolve(gray, np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32))
    return {
        "sharpness": round(float(laplacian.var()), 1),
        "overexposed": round(float((image.min(axis=2) > 245).mean()), 3),
        "coverage": round(float((depth > 0).mean()), 3),
    }


def is_usable(quality: dict, min_sharpness: float, max_overexposed: float = 0.15) -> bool:
    return (
        quality["sharpness"] >= min_sharpness
        and quality["overexposed"] <= max_overexposed
        and quality["coverage"] >= 0.6
    )


def mask_claims(
    found: list[tuple[int, float, np.ndarray]],
    view: View,
    depth: np.ndarray,
    points: np.ndarray,
    erode: int = 3,
    min_pixels: int = 400,
    max_fraction: float = 0.35,
    min_splats: int = 20,
) -> list[dict]:
    """Turn masks into claims on the splats visible inside them.

    Masks are eroded first, so pixels at an object's edge, where depth may belong to whatever is
    behind it, don't pull in background splats.
    """
    index, rows, columns = visible_points(points, view, depth)
    claims = []
    for prompt, score, mask in found:
        pixels = int(mask.sum())
        if pixels < min_pixels or pixels > max_fraction * mask.size:
            continue
        core = binary_erosion(mask, iterations=erode) if erode else mask
        splats = index[core[rows, columns]]
        if len(splats) < min_splats:
            continue
        mask_rows, mask_columns = np.nonzero(mask)
        top, bottom = mask_rows.min(), mask_rows.max() + 1
        left, right = mask_columns.min(), mask_columns.max() + 1
        claims.append(
            {
                "prompt": prompt,
                "score": score,
                "pixels": pixels,
                "box": (int(left), int(top), int(right), int(bottom)),
                "splats": splats.astype(np.int32),
                "mask": mask[top:bottom, left:right],
            }
        )
    return claims


def save_claims(path: Path, claims: list[dict], meta: dict) -> None:
    splat_lengths = [len(claim["splats"]) for claim in claims]
    masks = [claim["mask"] for claim in claims]
    bits = [np.packbits(mask.ravel()) for mask in masks]
    np.savez_compressed(
        path,
        prompt=np.array([claim["prompt"] for claim in claims], dtype=np.int16),
        score=np.array([claim["score"] for claim in claims], dtype=np.float32),
        pixels=np.array([claim["pixels"] for claim in claims], dtype=np.int32),
        box=np.array([claim["box"] for claim in claims], dtype=np.int32).reshape(-1, 4),
        splat_offsets=np.concatenate([[0], np.cumsum(splat_lengths)]).astype(np.int64),
        splats=np.concatenate([claim["splats"] for claim in claims] or [np.zeros(0, np.int32)]),
        mask_offsets=np.concatenate([[0], np.cumsum([len(b) for b in bits])]).astype(np.int64),
        mask_bits=np.concatenate(bits or [np.zeros(0, np.uint8)]),
        meta=np.array(json.dumps(meta)),
    )


def load_claims(path: Path) -> dict:
    with np.load(path) as data:
        claims = {key: data[key] for key in data.files}
    claims["meta"] = json.loads(str(claims["meta"]))
    return claims


def claim_mask(claims: dict, index: int) -> np.ndarray:
    """Return claim `index`'s mask, cropped to its box."""
    left, top, right, bottom = claims["box"][index]
    start, end = claims["mask_offsets"][index], claims["mask_offsets"][index + 1]
    shape = (bottom - top, right - left)
    bits = np.unpackbits(claims["mask_bits"][start:end], count=shape[0] * shape[1])
    return bits.reshape(shape).astype(bool)


def draw_overlay(image: Image.Image, claims: list[dict], prompts: list[str], path: Path) -> None:
    """Save a half-size image with each mask tinted and named."""
    small = image.resize((image.width // 2, image.height // 2))
    tint = np.asarray(small).astype(np.float32)
    random = np.random.default_rng(0)
    labels = []
    for claim in claims:
        color = random.integers(60, 255, 3)
        left, top, right, bottom = claim["box"]
        full = np.zeros((image.height, image.width), dtype=bool)
        full[top:bottom, left:right] = claim["mask"]
        half = full[::2, ::2]
        tint[half] = 0.5 * tint[half] + 0.5 * color
        labels.append((left // 2, top // 2, f"{prompts[claim['prompt']]} {claim['score']:.2f}"))
    result = Image.fromarray(tint.clip(0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(result)
    for x, y, text in labels:
        draw.text((x + 2, y + 2), text, fill=(255, 255, 255))
    result.save(path, quality=85)


def run_masks(
    scene_dir: Path,
    out_dir: Path,
    render_sets: list[str],
    points: np.ndarray,
    prompts: list[str] = PROMPTS,
    limit: int | None = None,
    stride: int = 1,
    threshold: float = 0.4,
    min_sharpness: float = 20.0,
    model_id: str = "facebook/sam3",
    shard: tuple[int, int] = (0, 1),
) -> dict:
    claims_dir, overlays_dir = out_dir / "claims", out_dir / "overlays"
    claims_dir.mkdir(parents=True, exist_ok=True)
    overlays_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prompts.json").write_text(json.dumps(prompts, indent=1))
    views = [view for name in render_sets for view in load_views(scene_dir / name)[::stride]]
    views = views[:limit] if limit else views
    # Each of several parallel jobs takes every Nth view, so they never write the same file.
    views = views[shard[0] :: shard[1]]
    segmenter = None
    done = skipped = masks = 0
    start = time.perf_counter()
    for number, view in enumerate(views, 1):
        path = claims_dir / f"{view.name}.npz"
        if path.exists():
            continue
        image = Image.open(view.image_path).convert("RGB")
        depth = np.load(view.depth_path)
        quality = view_quality(np.asarray(image), depth)
        if not is_usable(quality, min_sharpness):
            save_claims(path, [], {"view": view.name, "skipped": True, **quality})
            skipped += 1
            continue
        if segmenter is None:
            segmenter = Sam3Segmenter(model_id)
        tick = time.perf_counter()
        found = segmenter.segment(image, prompts, threshold)
        claims = mask_claims(found, view, depth, points)
        seconds = round(time.perf_counter() - tick, 2)
        meta = {"view": view.name, "skipped": False, "seconds": seconds, **quality}
        save_claims(path, claims, {**meta, "found": len(found)})
        draw_overlay(image, claims, prompts, overlays_dir / f"{view.name}.jpg")
        done += 1
        masks += len(claims)
        print(f"[{number}/{len(views)}] {view.name}: {len(claims)} masks, {seconds} s", flush=True)
    summary = {
        "views": len(views),
        "segmented": done,
        "skipped_low_quality": skipped,
        "masks": masks,
        "seconds": round(time.perf_counter() - start, 1),
    }
    if segmenter is not None and segmenter.device == "cuda":
        summary["peak_gpu_gb"] = round(segmenter.torch.cuda.max_memory_allocated() / 1e9, 2)
    return summary
