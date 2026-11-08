"""Merge per-view masks into 3D objects, and tag each splat with its object.

    python -m app.extract.lift SCENE.ply MASKS_DIR OUT_DIR RENDER_DIR [RENDER_DIR ...]

Each splat is projected into every view. If it's visible there, it's recorded against the mask it
lands in. Masks that cover mostly the same splats are the same object seen from different views, so
they merge. Each splat then joins the object that most of its views agree on.

Writes assets.json and splat_labels.npy. MASKS_DIR holds object_mask/
and object_mask_json/, and each RENDER_DIR holds depth/ and cameras.json. Units are metres.
"""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import sparse

from app.scene.load import Splats, estimate_floor, read_splats

STRUCTURE = {"wall", "floor", "ceiling"}


def project_to_masks(
    positions: np.ndarray,
    world_to_camera: np.ndarray,
    camera: np.ndarray,
    depth: np.ndarray,
    mask_ids: np.ndarray,
    depth_tolerance: float = 0.08,
) -> tuple[np.ndarray, np.ndarray]:
    """Return indices of splats visible in this view, and the mask ID each lands in (0 = none)."""
    in_camera = positions @ world_to_camera[:3, :3].T + world_to_camera[:3, 3]
    z = in_camera[:, 2]
    height, width = depth.shape
    ahead = np.flatnonzero(z > 0.05)
    u = (in_camera[ahead, 0] / z[ahead] * camera[0, 0] + camera[0, 2]).astype(np.int64)
    v = (in_camera[ahead, 1] / z[ahead] * camera[1, 1] + camera[1, 2]).astype(np.int64)
    inside = (u >= 0) & (u < width) & (v >= 0) & (v < height)
    ahead, u, v = ahead[inside], u[inside], v[inside]
    rendered = depth[v, u]
    visible = (rendered > 0) & (np.abs(z[ahead] - rendered) < depth_tolerance)
    return ahead[visible], mask_ids[v[visible], u[visible]]


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = np.arange(size)

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = int(self.parent[item])
        return int(item)

    def union(self, first: int, second: int) -> None:
        self.parent[self.find(first)] = self.find(second)


def merge_masks(
    membership: sparse.csr_matrix,
    min_iou: float = 0.3,
    max_extent: float = 3.0,
    positions: np.ndarray | None = None,
) -> np.ndarray:
    """Return a group number for each mask, given a splats-by-masks membership matrix.

    Merges the strongest overlaps first. A merge is refused if the result would be larger than
    `max_extent` metres, which stops chains of touching things becoming one room-sized object.
    """
    sizes = np.asarray(membership.sum(axis=0)).ravel()
    shared = sparse.triu(membership.T @ membership, k=1, format="coo")
    iou = shared.data / (sizes[shared.row] + sizes[shared.col] - shared.data)
    strong = np.flatnonzero(iou >= min_iou)
    order = strong[np.argsort(-iou[strong])]

    groups = UnionFind(membership.shape[1])
    low = high = None
    if positions is not None:
        as_csc = membership.tocsc()
        low, high = {}, {}
        for mask in range(membership.shape[1]):
            members = positions[as_csc[:, mask].indices]
            if len(members):
                low[mask], high[mask] = members.min(axis=0), members.max(axis=0)
    for index in order:
        first, second = groups.find(int(shared.row[index])), groups.find(int(shared.col[index]))
        if first == second:
            continue
        if low is not None and first in low and second in low:
            new_low = np.minimum(low[first], low[second])
            new_high = np.maximum(high[first], high[second])
            if (new_high - new_low).max() > max_extent:
                continue
            groups.union(first, second)
            root = groups.find(first)
            low[root], high[root] = new_low, new_high
        else:
            groups.union(first, second)
    return np.array([groups.find(mask) for mask in range(membership.shape[1])])


def vote_labels(
    membership: sparse.csr_matrix,
    groups: np.ndarray,
    min_votes: int = 2,
    min_share: float = 0.5,
) -> np.ndarray:
    """Return an object group for each splat, or -1 without enough agreement between its views."""
    votes = (
        membership
        @ sparse.csr_matrix(
            (np.ones(len(groups)), (np.arange(len(groups)), groups)),
            shape=(len(groups), int(groups.max()) + 1),
        )
    ).tocsr()
    labels = np.full(membership.shape[0], -1, dtype=np.int32)
    for splat in range(votes.shape[0]):
        start, stop = votes.indptr[splat], votes.indptr[splat + 1]
        if start == stop:
            continue
        counts = votes.data[start:stop]
        best = int(np.argmax(counts))
        if counts[best] >= min_votes and counts[best] / counts.sum() >= min_share:
            labels[splat] = votes.indices[start + best]
    return labels


def build_assets(
    positions: np.ndarray,
    raw_labels: np.ndarray,
    mask_records: list[dict],
    groups: np.ndarray,
    membership: sparse.csr_matrix,
    min_splats: int = 100,
    min_views: int = 3,
) -> tuple[list[dict], np.ndarray]:
    """Return asset dictionaries, largest first, and final per-splat labels indexing them."""
    masks_of_group: dict[int, list[int]] = {}
    for mask, group in enumerate(groups.tolist()):
        masks_of_group.setdefault(group, []).append(mask)
    mask_sizes = np.asarray(membership.sum(axis=0)).ravel()

    totals = np.bincount(raw_labels[raw_labels >= 0], minlength=int(groups.max()) + 1)
    final = np.full(len(raw_labels), -1, dtype=np.int32)
    assets = []
    for group in np.argsort(-totals).tolist():
        masks = masks_of_group.get(group, [])
        views = {mask_records[mask]["view"] for mask in masks}
        if totals[group] < min_splats or len(views) < min_views:
            continue
        members = positions[raw_labels == group]
        low, high = np.percentile(members, [1, 99], axis=0)
        names = Counter()
        for mask in masks:
            name = mask_records[mask]["label"]
            if name and name != "sam2":
                names[name] += mask_records[mask]["score"]
        label, weight = names.most_common(1)[0] if names else ("unknown", 0.0)
        confidence = weight / max(sum(names.values()), 1e-9) if names else 0.0
        largest = sorted(masks, key=lambda mask: -mask_sizes[mask])[:6]
        index = len(assets)
        final[raw_labels == group] = index
        assets.append(
            {
                "object_id": f"obj-{index + 1:04d}",
                "label": label,
                "label_confidence": round(float(confidence), 3),
                "center": ((low + high) / 2).round(3).tolist(),
                "bbox_min": low.round(3).tolist(),
                "bbox_max": high.round(3).tolist(),
                "splats": int(totals[group]),
                "views": len(views),
                "source_masks": [
                    {"view": mask_records[m]["view"], "mask_id": mask_records[m]["mask_id"]}
                    for m in largest
                ],
                "all_masks": [[mask_records[m]["view"], mask_records[m]["mask_id"]] for m in masks],
                "mapping": None,
            }
        )
    return assets, final


def collect_membership(
    positions: np.ndarray,
    masks_dir: Path,
    render_dirs: list[Path],
    max_area_share: float = 0.5,
) -> tuple[sparse.csr_matrix, list[dict]]:
    """Project splats into all views. Return a splats-by-masks matrix and a record for each mask."""
    rows, columns, records = [], [], []
    for render_dir in render_dirs:
        meta = json.loads((render_dir / "cameras.json").read_text())
        camera = np.array(meta["intrinsics"])
        for entry in meta["cameras"]:
            name = entry["name"]
            mask_path = masks_dir / "object_mask" / f"{name}.png"
            if not mask_path.exists():
                continue
            mask_ids = np.array(Image.open(mask_path))
            info = json.loads((masks_dir / "object_mask_json" / f"{name}.json").read_text())
            depth = np.load(render_dir / "depth" / f"{name}.npy")
            matrix = np.array(entry["world_to_camera"])
            splats, hits = project_to_masks(positions, matrix, camera, depth, mask_ids)
            values, counts = np.unique(mask_ids[mask_ids > 0], return_counts=True)
            for value, count in zip(values.tolist(), counts.tolist(), strict=True):
                detail = info.get(str(value), {})
                label = str(detail.get("label", ""))
                if label in STRUCTURE or count / mask_ids.size > max_area_share:
                    continue
                inside = splats[hits == value]
                if not len(inside):
                    continue
                rows.append(inside)
                columns.append(np.full(len(inside), len(records), dtype=np.int32))
                records.append(
                    {
                        "view": name,
                        "mask_id": value,
                        "label": label,
                        "score": float(detail.get("score", 0.0)),
                    }
                )
    row = np.concatenate(rows) if rows else np.zeros(0, dtype=np.int64)
    column = np.concatenate(columns) if columns else np.zeros(0, dtype=np.int32)
    shape = (len(positions), len(records))
    matrix = sparse.csr_matrix((np.ones(len(row), dtype=np.int32), (row, column)), shape=shape)
    return matrix, records


def run(
    splats: Splats,
    masks_dir: Path,
    render_dirs: list[Path],
    up: tuple[float, float, float] = (0.0, -1.0, 0.0),
    min_opacity: float = 0.2,
) -> tuple[list[dict], np.ndarray, dict]:
    """Return assets, one label per splat in the scene, and a summary."""
    start = time.perf_counter()
    solid = np.flatnonzero(splats.opacities >= min_opacity)
    positions = splats.positions[solid]
    membership, records = collect_membership(positions, masks_dir, render_dirs)
    project_seconds = time.perf_counter() - start

    start = time.perf_counter()
    groups = merge_masks(membership, positions=positions)
    raw = vote_labels(membership, groups)
    assets, final = build_assets(positions, raw, records, groups, membership)
    labels = np.full(len(splats), -1, dtype=np.int32)
    labels[solid] = final
    summary = {
        "objects": len(assets),
        "masks": len(records),
        "solid_splats": len(solid),
        "splats_in_objects": int((labels >= 0).sum()),
        "project_seconds": round(project_seconds),
        "merge_seconds": round(time.perf_counter() - start),
        "labels": Counter(asset["label"] for asset in assets).most_common(),
        "floor_height_along_up": round(estimate_floor(positions, up), 3),
    }
    return assets, labels, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("masks_dir", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("render_dirs", type=Path, nargs="+")
    parser.add_argument("--up", type=float, nargs=3, default=(0.0, -1.0, 0.0))
    parser.add_argument("--scene-id", default="equipment_room")
    args = parser.parse_args()

    splats = read_splats(args.scene)
    assets, labels, summary = run(splats, args.masks_dir, args.render_dirs, tuple(args.up))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    np.save(args.out_dir / "splat_labels.npy", labels)
    # Every object's masks go in their own file, as they would make assets.json much larger.
    masks_by_object = {asset["object_id"]: asset.pop("all_masks") for asset in assets}
    (args.out_dir / "object_masks.json").write_text(json.dumps(masks_by_object))
    document = {
        "scene_id": args.scene_id,
        "units": "metres",
        "up": list(args.up),
        "floor_height_along_up": summary["floor_height_along_up"],
        "assets": assets,
    }
    (args.out_dir / "assets.json").write_text(json.dumps(document, indent=1))
    (args.out_dir / "lift_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
