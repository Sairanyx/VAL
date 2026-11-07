"""Stage 2: merge masks from every view into objects, vote each splat into one object, fit boxes,
and save highlighted crops for the VLM.

Masks from different views are the same object when they claim largely the same splats. Comparing
small voxels instead of single splats lets two views of the same surface match even if they see
slightly different splats.
"""

import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components
from sklearn.cluster import DBSCAN

from app.extract.geometry import load_views, upright_box
from app.extract.masks import claim_mask, load_claims


def collect_claims(claims_dir: Path) -> dict:
    """Gather every mask from every view's claims file into flat lists."""
    files, masks = [], []
    for path in sorted(Path(claims_dir).glob("*.npz")):
        claims = load_claims(path)
        files.append(claims)
        for index in range(len(claims["prompt"])):
            start, end = claims["splat_offsets"][index], claims["splat_offsets"][index + 1]
            masks.append(
                {
                    "file": len(files) - 1,
                    "index": index,
                    "view": claims["meta"]["view"],
                    "prompt": int(claims["prompt"][index]),
                    "score": float(claims["score"][index]),
                    "pixels": int(claims["pixels"][index]),
                    "box": claims["box"][index].tolist(),
                    "splats": claims["splats"][start:end],
                }
            )
    return {"files": files, "masks": masks}


def link_masks(
    mask_splats: list[np.ndarray],
    splat_voxels: np.ndarray,
    min_overlap: float = 0.5,
    min_share: float = 0.2,
) -> np.ndarray:
    """Group masks into objects and return each mask's group number.

    Two masks link when their shared voxels make up at least `min_overlap` of the smaller mask and
    `min_share` of the larger one. The second rule stops a valve from merging into the pipe it
    sits on just because the valve lies entirely inside the pipe's mask.
    """
    count = len(mask_splats)
    if count == 0:
        return np.zeros(0, dtype=np.int64)
    voxels = [np.unique(splat_voxels[splats]) for splats in mask_splats]
    rows = np.repeat(np.arange(count), [len(v) for v in voxels])
    columns = np.concatenate(voxels)
    total = int(splat_voxels.max()) + 1
    occupancy = csr_matrix((np.ones(len(rows), np.float32), (rows, columns)), (count, total))
    sizes = np.array([len(v) for v in voxels], dtype=np.float32)
    shared = (occupancy @ occupancy.T).tocoo()
    first, second, overlap = shared.row, shared.col, shared.data
    smaller = np.minimum(sizes[first], sizes[second])
    larger = np.maximum(sizes[first], sizes[second])
    edge = (first < second) & (overlap >= min_overlap * smaller) & (overlap >= min_share * larger)
    graph = csr_matrix((np.ones(edge.sum()), (first[edge], second[edge])), (count, count))
    return connected_components(graph, directed=False)[1]


def vote_splats(
    mask_splats: list[np.ndarray],
    groups: np.ndarray,
    splat_count: int,
    min_votes: int = 2,
    min_share: float = 0.5,
) -> np.ndarray:
    """Give each splat the group with more than `min_share` of its votes, or -1 if none has."""
    labels = np.full(splat_count, -1, dtype=np.int64)
    if not len(mask_splats):
        return labels
    rows = np.concatenate(mask_splats)
    columns = np.repeat(groups, [len(splats) for splats in mask_splats])
    shape = (splat_count, int(groups.max()) + 1)
    votes = csr_matrix((np.ones(len(rows), np.float32), (rows, columns)), shape)
    votes.sum_duplicates()
    best = np.asarray(votes.argmax(axis=1)).ravel()
    top = votes.max(axis=1).toarray().ravel()
    total = np.asarray(votes.sum(axis=1)).ravel()
    clear = (top >= min_votes) & (top > min_share * total)
    labels[clear] = best[clear]
    return labels


def main_cluster(points: np.ndarray, eps: float = 0.05, min_samples: int = 5) -> np.ndarray:
    """Keep the largest spatial cluster and any cluster at least a quarter its size.

    Drops splats that were voted into an object but sit apart from it, such as a patch of wall
    seen through a gap.
    """
    if len(points) < min_samples:
        return np.ones(len(points), dtype=bool)
    clusters = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(points)
    sizes = np.bincount(clusters[clusters >= 0]) if (clusters >= 0).any() else np.zeros(0)
    if not len(sizes):
        return np.zeros(len(points), dtype=bool)
    return np.isin(clusters, np.flatnonzero(sizes >= 0.25 * sizes.max()))


def save_crop(image_path: Path, mask: np.ndarray, box: list[int], path: Path, size: int = 448):
    """Save the object's surroundings with everything outside its mask darkened."""
    image = np.asarray(Image.open(image_path).convert("RGB")).astype(np.float32)
    height, width = image.shape[:2]
    left, top, right, bottom = box
    full = np.zeros((height, width), dtype=bool)
    full[top:bottom, left:right] = mask
    pad = max(16, int(0.2 * max(right - left, bottom - top)))
    left, top = max(0, left - pad), max(0, top - pad)
    right, bottom = min(width, right + pad), min(height, bottom + pad)
    crop = image[top:bottom, left:right]
    crop[~full[top:bottom, left:right]] *= 0.35
    result = Image.fromarray(crop.clip(0, 255).astype(np.uint8))
    scale = size / max(result.size)
    result = result.resize(
        (max(1, round(result.width * scale)), max(1, round(result.height * scale)))
    )
    result.save(path, quality=92)


def run_merge(
    scene_dir: Path,
    out_dir: Path,
    points: np.ndarray,
    prompts: list[str],
    floor_y: float,
    render_sets: list[str],
    voxel_size: float = 0.04,
    min_splats: int = 50,
    min_views: int = 2,
    max_size: float = 4.0,
    crops_per_object: int = 3,
) -> dict:
    collected = collect_claims(out_dir / "claims")
    masks = collected["masks"]
    mask_splats = [mask["splats"] for mask in masks]
    _, splat_voxels = np.unique(
        np.floor(points / voxel_size).astype(np.int64), axis=0, return_inverse=True
    )
    groups = link_masks(mask_splats, splat_voxels.ravel())
    labels = vote_splats(mask_splats, groups, len(points))

    views = {view.name: view for name in render_sets for view in load_views(scene_dir / name)}
    masks_by_group = {}
    for mask, group in zip(masks, groups, strict=True):
        masks_by_group.setdefault(int(group), []).append(mask)
    crops_dir = out_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    objects = []
    for group in np.unique(labels[labels >= 0]):
        members = np.flatnonzero(labels == group)
        keep = main_cluster(points[members])
        labels[members[~keep]] = -1
        members = members[keep]
        group_masks = masks_by_group[int(group)]
        seen_from = sorted({mask["view"] for mask in group_masks})
        status = "ok"
        if len(members) < min_splats:
            status = "too_small"
        elif len(seen_from) < min_views:
            status = "single_view"
        box = upright_box(points[members]) if len(members) >= 3 else None
        if status == "ok" and max(box["size"]) > max_size:
            status = "too_large"
        if status == "ok" and box["size"][1] < 0.04 and abs(box["bbox_max"][1] - floor_y) < 0.08:
            status = "floor"
        prompt_scores = np.zeros(len(prompts))
        for mask in group_masks:
            prompt_scores[mask["prompt"]] += mask["score"]
        order = np.argsort(-prompt_scores)
        best_prompt = int(order[0])
        objects.append(
            {
                "group": int(group),
                "status": status,
                "n_splats": int(len(members)),
                "n_views": len(seen_from),
                "n_masks": len(group_masks),
                "sam3_label": prompts[best_prompt],
                "sam3_confidence": round(
                    float(prompt_scores[best_prompt] / prompt_scores.sum()), 3
                ),
                "prompt_votes": {
                    prompts[i]: round(float(prompt_scores[i]), 2)
                    for i in order[:3]
                    if prompt_scores[i] > 0
                },
                **(box or {}),
                "_masks": group_masks,
            }
        )

    objects.sort(key=lambda item: -item["n_splats"])
    kept = [item for item in objects if item["status"] == "ok"]
    final_labels = np.full(len(points), -1, dtype=np.int32)
    for number, item in enumerate(kept):
        item["object_id"] = f"obj-{number + 1:04d}"
        final_labels[labels == item["group"]] = number
        item["crops"] = _save_crops(item, collected["files"], views, crops_dir, crops_per_object)
    for item in objects:
        item.pop("_masks")
    np.save(out_dir / "object_splats.npy", final_labels)
    statuses = {}
    for item in objects:
        statuses[item["status"]] = statuses.get(item["status"], 0) + 1
    summary = {
        "masks": len(masks),
        "mask_groups": int(groups.max()) + 1 if len(groups) else 0,
        "objects_by_status": statuses,
        "labelled_splats": int((final_labels >= 0).sum()),
        "splat_count": len(points),
    }
    (out_dir / "objects.json").write_text(
        json.dumps({"floor_y": floor_y, **summary, "objects": objects}, indent=1)
    )
    return summary


def _save_crops(item: dict, files: list[dict], views: dict, crops_dir: Path, count: int) -> list:
    """Save crops from the clearest masks, one per view, preferring masks not cut by the frame."""

    def clarity(mask: dict) -> float:
        left, top, right, bottom = mask["box"]
        view = views[mask["view"]]
        cut = left <= 2 or top <= 2 or right >= view.width - 2 or bottom >= view.height - 2
        return mask["pixels"] * mask["score"] * (0.4 if cut else 1.0)

    crops, used = [], set()
    for mask in sorted(item["_masks"], key=clarity, reverse=True):
        if mask["view"] in used:
            continue
        used.add(mask["view"])
        path = crops_dir / f"{item['object_id']}_{len(crops)}.jpg"
        mask_pixels = claim_mask(files[mask["file"]], mask["index"])
        save_crop(views[mask["view"]].image_path, mask_pixels, mask["box"], path)
        crops.append(path.name)
        if len(crops) == count:
            break
    return crops
