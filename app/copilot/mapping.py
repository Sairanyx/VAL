"""Link Excel records to scanned objects by class, as Valmet's brief allows.

    uv run python -m app.copilot.mapping data/scene/splat_v2

Reads `assets_viewer.json`, and uses `nav_grid.npz`, plus the scene's `start` or `walked.npy`.
Writes
`mapping.json` and `assets_mapped.json`, the same objects with `mapping` filled in, for the API and
viewer.

These links are procedural, not real identities, and are marked that way. Each record goes to one
object of a fitting type, or to none: a pump record never lands on a light. Hand-made links, such as
the picked target, are kept, and earlier procedural ones are made again. Healthy records go nearest
the route to the target, so a walk passes normal devices and ends at the fault.

Types corrected by eye come from `scenes/<scene>.labels.json`, matched by object ID and position.
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np

from app.copilot.store import DataStore

EXACT_CONFIDENCE = 0.3
SIMILAR_CONFIDENCE = 0.15
CLOSE_STOP = 1.0  # metres: prefer objects a person can get this close to
# For each record class: exact types, then similar ones. A pump comes with its motor, and a
# transmitter often looks like a gauge. Nothing else is close enough to stand in.
LABELS = {
    "CONTROL_VALVE": (["valve"], ["pipe fitting"]),
    "PROCESS_PUMP": (["pump"], ["motor"]),
    "ELECTRIC_MOTOR": (["motor"], ["pump"]),
    "PRESSURE_TRANSMITTER": (["sensor"], ["gauge"]),
    "VIBRATION_SENSOR": (["sensor"], ["gauge"]),
}
SAME_OBJECT_M = 0.3  # a fix only applies to an object this close to where it was reviewed
REVIEWED = "reviewed from screenshots"  # by a coding agent, see the labels file's "method"


def object_labels(asset: dict) -> set[str]:
    if asset.get("label_source") == REVIEWED:
        return {asset["label"]}  # Checked by looking, so the model's guesses don't count.
    return {asset.get(key) for key in ("label", "suggested_label", "sam_label")} - {None}


def apply_label_fixes(assets: list[dict], fixes: list[dict]) -> int:
    """Set types corrected by eye, for the same objects only. Returns how many applied."""
    by_id = {asset["object_id"]: asset for asset in assets}
    applied = 0
    for fix in fixes:
        asset = by_id.get(fix["object_id"])
        if asset is None or math.dist(asset["center"], fix["center"]) > SAME_OBJECT_M:
            continue  # Another extraction: the same ID can be a different object.
        asset["label_was"] = asset["label"]
        asset["label"] = fix["label"]
        asset["label_source"] = REVIEWED
        asset["label_evidence"] = fix.get("evidence", "")
        if fix.get("mobility"):
            asset["mobility"] = fix["mobility"]
        # A reason that names the old type would now be wrong.
        if asset.get("mobility_reason", "").startswith(f"{asset['label_was']} "):
            asset["mobility_reason"] = f"{fix['label']}: type checked from screenshots"
        applied += 1
    return applied


def rank(asset: dict, asset_class: str) -> int | None:
    """Return 0 for a matching label, 1 for a similar one, and None if it doesn't fit."""
    exact, similar = LABELS[asset_class]
    labels = object_labels(asset)
    if labels & set(exact):
        return 0
    return 1 if labels & set(similar) else None


def route_distance(center: list[float], route: list[list[float]], axes: tuple[int, int]) -> float:
    """Distance across the floor from a point to the nearest point on a route."""
    if not route:
        return 0.0
    point = np.asarray(center, dtype=float)[list(axes)]
    best = math.inf
    for start, end in zip(route, route[1:] or route, strict=False):
        a = np.asarray(start, dtype=float)[list(axes)]
        b = np.asarray(end, dtype=float)[list(axes)]
        span = b - a
        length = float(span @ span)
        share = 0.0 if length == 0 else min(max(float((point - a) @ span) / length, 0.0), 1.0)
        best = min(best, float(np.linalg.norm(point - (a + share * span))))
    return best


def build_mapping(
    assets: list[dict],
    records: list[dict],
    route: list[list[float]] | None = None,
    stop_distance=None,
    axes: tuple[int, int] = (0, 2),
) -> list[dict]:
    """Return one link per record that has a suitable object.

    `records` hold `asset_id`, `tag`, `asset_class`, and `condition_state`. `stop_distance` is an
    optional function giving how close a person can get to an object, or None if they can't reach
    it. Objects within CLOSE_STOP come first, ahead of a better label further away.
    """
    links = [
        {**asset["mapping"], "object_id": asset["object_id"]}
        for asset in assets
        if asset.get("mapping") and not asset["mapping"].get("method", "").startswith("procedural")
    ]
    used_objects = {link["object_id"] for link in links}
    used_records = {link["asset_id"] for link in links}
    route = route or []
    candidates = sorted(
        (a for a in assets if a.get("mobility") != "movable"), key=lambda a: a["object_id"]
    )

    def healthy_first(record: dict) -> tuple[bool, str]:
        return record["condition_state"] != "healthy", record["asset_id"]

    for record in sorted(records, key=healthy_first):
        if record["asset_id"] in used_records:
            continue
        options = []
        for asset in candidates:
            fit = rank(asset, record["asset_class"])
            if fit is None or asset["object_id"] in used_objects:
                continue
            gap = stop_distance(asset) if stop_distance else 0.0
            if gap is None:
                continue
            route_gap = route_distance(asset["center"], route, axes)
            options.append((gap > CLOSE_STOP, fit, route_gap, asset["object_id"]))
        for _, fit, _, object_id in sorted(options)[:1]:
            used_objects.add(object_id)
            links.append(
                {
                    "object_id": object_id,
                    "asset_id": record["asset_id"],
                    "tag": record["tag"],
                    "method": "procedural_class" if fit == 0 else "procedural_similar_class",
                    "confidence": EXACT_CONFIDENCE if fit == 0 else SIMILAR_CONFIDENCE,
                    "note": "Assigned by class for the demo, not a confirmed identity.",
                }
            )
    return links


def load_records(store: DataStore) -> list[dict]:
    records = []
    for asset in store.list_assets():
        state = store.get_current_state(asset.asset_id)
        records.append(
            {
                "asset_id": asset.asset_id,
                "tag": asset.tag,
                "asset_class": asset.asset_class,
                "condition_state": state.condition_state if state else "unknown",
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("--assets", default="assets_viewer.json")
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--labels", type=Path, help="types corrected by eye")
    args = parser.parse_args()
    scene = json.loads((args.scene / args.assets).read_text())
    assets = scene["assets"]
    labels = args.labels or Path("scenes") / f"{scene.get('scene_id', args.scene.name)}.labels.json"
    fixed = 0
    if labels.exists():
        fixed = apply_label_fixes(assets, json.loads(labels.read_text())["fixes"])
    route, stop_distance, axes = [], None, (0, 2)
    grid_file, walked_file = args.scene / "nav_grid.npz", args.scene / "walked.npy"
    if grid_file.exists() and (walked_file.exists() or scene.get("start")):
        from app.nav.grid import load_grid
        from app.nav.route import NoRoute, plan_route

        grid = load_grid(grid_file)
        axes = grid.axes
        first = np.load(walked_file)[0] if walked_file.exists() else scene["start"]
        start = tuple(float(v) for v in first)

        def stop_distance(asset: dict) -> float | None:
            try:
                low, high = tuple(asset["bbox_min"]), tuple(asset["bbox_max"])
                return plan_route(grid, start, low, high).stop_distance
            except NoRoute:
                return None

        target = next((a for a in assets if a.get("mapping")), None)
        if target is not None:
            found = plan_route(grid, start, tuple(target["bbox_min"]), tuple(target["bbox_max"]))
            route = [list(point) for point in found.path]
    store = DataStore.load(args.workbook)
    links = build_mapping(assets, load_records(store), route, stop_distance, axes)
    (args.scene / "mapping.json").write_text(json.dumps({"mappings": links}, indent=2))
    by_object = {link["object_id"]: link for link in links}
    for asset in assets:
        link = by_object.get(asset["object_id"])
        asset["mapping"] = (
            {key: value for key, value in link.items() if key != "object_id"} if link else None
        )
    (args.scene / "assets_mapped.json").write_text(json.dumps(scene))
    methods: dict[str, int] = {}
    for link in links:
        methods[link["method"]] = methods.get(link["method"], 0) + 1
    summary = {
        "objects": len(assets),
        "types fixed": fixed,
        "linked": len(links),
        "methods": methods,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
