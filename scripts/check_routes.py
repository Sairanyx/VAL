"""Check routes to every object against the scene's splats, not the floor map that planned them.

    python scripts/check_routes.py SCENE.ply ASSETS.json NAV_GRID.npz [--out report.json]

Walks each route in small steps with a body-sized cylinder, and counts solid splats inside it. The
map and this check share no thresholds, so a route the map wrongly allows shows up here. Stray
floaters can also touch a route, so counts are reported at several levels, not as one verdict.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.nav.grid import load_grid  # noqa: E402
from app.nav.route import NoRoute, plan_route  # noqa: E402
from app.scene.load import read_splats  # noqa: E402

BODY_RADIUS = 0.2  # metres: a person's torso, narrower than the 0.3 m the planner keeps clear
BODY_BOTTOM = 0.15  # metres above the floor: ignores what can be stepped over
BODY_TOP = 1.2  # metres above the floor: low pipes higher than this are handled by the walked path
SOLID_OPACITY = 0.5
STEP = 0.05
TOUCH_LEVELS = (10, 50, 200)  # splats inside the body at one point of the route


def along_route(path: np.ndarray, step: float = STEP) -> np.ndarray:
    """Return points every `step` metres along a route."""
    points = [path[0]]
    for start, end in zip(path, path[1:], strict=False):
        length = float(np.linalg.norm(end - start))
        count = max(int(length / step), 1)
        points += [start + (end - start) * (i + 1) / count for i in range(count)]
    return np.array(points)


def worst_touch(points: np.ndarray, tree: cKDTree, radius: float = BODY_RADIUS) -> int:
    """Return the most solid splats inside the body at any point on a route, seen from above."""
    return max((len(found) for found in tree.query_ball_point(points, radius)), default=0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("assets", type=Path)
    parser.add_argument("grid", type=Path)
    parser.add_argument("--width", type=float, default=0.6)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    document = json.loads(args.assets.read_text())
    assets = document["assets"]
    grid = load_grid(args.grid)
    up = np.asarray(grid.up, dtype=np.float64)
    axes = list(grid.axes)
    on_floor = np.zeros(3)
    on_floor[int(np.argmax(np.abs(up)))] = float(grid.floor_height) / float(up.max() + up.min())
    start = tuple(document.get("start") or on_floor)
    movable = [a for a in assets if a["mobility"] == "movable"]
    boxes = [(a["bbox_min"], a["bbox_max"]) for a in movable]

    splats = read_splats(args.scene)
    positions = splats.positions.astype(np.float64)
    heights = positions @ up - float(grid.floor_height)
    keep = (splats.opacities >= SOLID_OPACITY) & (heights > BODY_BOTTOM) & (heights < BODY_TOP)
    inside_movable = np.zeros(len(positions), dtype=bool)
    for low, high in boxes:
        low_side, high_side = np.minimum(low, high), np.maximum(low, high)
        inside_movable |= ((positions >= low_side) & (positions <= high_side)).all(axis=1)
    # Movable objects block routes as footprints, not splats, and some may belong elsewhere today.
    tree = cKDTree(positions[keep & ~inside_movable][:, axes])

    results = []
    for asset in assets:
        others = [box for box, a in zip(boxes, movable, strict=True) if a is not asset]
        try:
            route = plan_route(
                grid,
                start,
                tuple(asset["bbox_min"]),
                tuple(asset["bbox_max"]),
                width=args.width,
                footprints=others,
            )
        except NoRoute:
            results.append({"object_id": asset["object_id"], "route": False})
            continue
        path = np.array(route.path)[:, axes]
        results.append(
            {
                "object_id": asset["object_id"],
                "route": True,
                "length": round(route.length, 2),
                "stop_distance": round(route.stop_distance, 2),
                "worst_touch": worst_touch(along_route(path), tree),
            }
        )
    routed = [r for r in results if r["route"]]
    summary = {
        "objects": len(assets),
        "routes": len(routed),
        "within_reach": sum(r["stop_distance"] <= 0.8 for r in routed),
        "mean_length": round(float(np.mean([r["length"] for r in routed])), 2),
    }
    for level in TOUCH_LEVELS:
        summary[f"routes_touching_{level}_or_more"] = sum(r["worst_touch"] >= level for r in routed)
    print(json.dumps(summary))
    worst = sorted(routed, key=lambda r: -r["worst_touch"])[:10]
    print("worst", [(r["object_id"], r["worst_touch"]) for r in worst])
    if args.out:
        args.out.write_text(json.dumps({"summary": summary, "routes": results}, indent=1))


if __name__ == "__main__":
    main()
