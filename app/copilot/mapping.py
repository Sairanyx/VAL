"""Link Excel records to scanned objects by class, as Valmet's brief allows.

    uv run python -m app.copilot.mapping data/scene/splat_v2

Reads `assets_viewer.json`, and uses `nav_grid.npz`, plus the scene's `start` or `walked.npy`.
Writes
`mapping.json` and `assets_mapped.json`, the same objects with `mapping` filled in, for the API and
viewer.

These links are procedural, not real identities, and are marked that way. Each record goes to one
object. Links already in the file, such as the hand-picked target, are kept. Healthy records go
nearest the route to the target, so a walk passes normal devices and ends at the fault.
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
LABELS = {
    "CONTROL_VALVE": (["valve"], ["pipe fitting"]),
    "PROCESS_PUMP": (["pump"], ["motor", "appliance"]),
    "ELECTRIC_MOTOR": (["motor"], ["pump", "appliance"]),
    "PRESSURE_TRANSMITTER": (["sensor"], ["control panel", "pipe fitting"]),
    "VIBRATION_SENSOR": (["sensor"], ["control panel", "pipe fitting"]),
}


def object_labels(asset: dict) -> set[str]:
    return {asset.get(key) for key in ("label", "suggested_label", "sam_label")} - {None}


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
        if asset.get("mapping")
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
    args = parser.parse_args()
    scene = json.loads((args.scene / args.assets).read_text())
    assets = scene["assets"]
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
    print(json.dumps({"objects": len(assets), "linked": len(links), "methods": methods}, indent=2))


if __name__ == "__main__":
    main()
