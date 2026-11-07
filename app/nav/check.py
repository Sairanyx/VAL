"""Check the floor map, routes, mapping and API together, and draw the result.

    make nav-check

Runs the real API code without a server or database. Writes `runs/nav_check.png` and exits with an
error if a check fails. It compares routes with our own map, so it can't prove the map is right.
Check the route in the 3D viewer for that.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

from app.nav.grid import LOW_BAND, NavGrid, load_grid
from app.nav.route import BODIES, to_cell

STATE_COLORS = {
    "healthy": "limegreen",
    "watch": "gold",
    "degraded": "darkorange",
    "attention_required": "red",
}


def route_clear(grid: NavGrid, path: list[list[float]], profile: str, samples: int = 60) -> bool:
    """True if a body fits along the whole path, allowing one cell for rounding."""
    width, band = BODIES[profile]
    clearance = grid.clearance_low if band == LOW_BAND else grid.clearance
    needed = width / 2 - grid.cell
    points = np.asarray(path, dtype=float)
    for start, end in zip(points, points[1:], strict=False):
        for point in np.linspace(start, end, samples):
            cell = to_cell(grid, tuple(point))
            inside = all(0 <= c < limit for c, limit in zip(cell, clearance.shape, strict=True))
            if not inside or clearance[cell] < needed:
                return False
    return True


def draw(grid: NavGrid, assets: list[dict], routes: dict[str, dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    first, second = grid.axes
    extent = [
        grid.origin[1],
        grid.origin[1] + grid.free.shape[1] * grid.cell,
        grid.origin[0] + grid.free.shape[0] * grid.cell,
        grid.origin[0],
    ]
    fig, axes = plt.subplots(1, len(routes), figsize=(7 * len(routes), 7))
    for axis, (profile, route) in zip(np.atleast_1d(axes), routes.items(), strict=True):
        width, band = BODIES[profile]
        clearance = grid.clearance_low if band == LOW_BAND else grid.clearance
        axis.imshow(clearance >= width / 2, cmap="gray", extent=extent, alpha=0.6)
        for asset in assets:
            if not asset.get("condition"):
                continue
            low, high = asset["bbox_min"], asset["bbox_max"]
            box = plt.Rectangle(
                (min(low[second], high[second]), min(low[first], high[first])),
                abs(high[second] - low[second]),
                abs(high[first] - low[first]),
                fill=False,
                ec=STATE_COLORS.get(asset["condition"]["condition_state"], "white"),
                lw=1.5,
            )
            axis.add_patch(box)
        points = np.asarray(route["path"])
        axis.plot(points[:, second], points[:, first], c="red", lw=2.5)
        axis.plot(points[0, second], points[0, first], "bo")
        axis.plot(points[-1, second], points[-1, first], "m*", ms=14)
        axis.set_title(f"{profile}: {route['length']} m, stops {route['stop_distance']} m away")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=80)


def main() -> None:
    from fastapi.testclient import TestClient

    from app.api.main import create_app

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path)
    parser.add_argument("--assets", default="assets_mapped.json")
    parser.add_argument("--target", default="P-005")
    parser.add_argument("--out", type=Path, default=Path("runs/nav_check.png"))
    args = parser.parse_args()
    os.environ.pop("DATABASE_URL", None)  # This check never touches saved scene changes.
    grid_path = args.scene / "nav_grid.npz"
    grid = load_grid(grid_path)
    client = TestClient(create_app(args.scene / args.assets, grid_path))
    results: list[tuple[str, bool, str]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        results.append((name, bool(passed), detail))

    health = client.get("/api/health").json()
    check("copilot and Excel pack loaded", health["copilot"])
    scene = client.get("/api/assets").json()
    assets = scene["assets"]
    linked = [asset for asset in assets if asset.get("mapping")]
    check("objects linked to Excel", linked, f"{len(linked)} of {len(assets)}")
    check(
        "linked objects show status",
        all(asset.get("condition") for asset in linked),
        f"{sum(bool(asset.get('condition')) for asset in linked)} of {len(linked)}",
    )
    target = next((a for a in linked if a["mapping"].get("tag") == args.target), None)
    check(f"{args.target} has an object", target, target["object_id"] if target else "")
    routes: dict[str, dict] = {}
    if target:
        walked = args.scene / "walked.npy"
        start = [float(v) for v in np.load(walked)[0]] if walked.exists() else scene["start"]
        request = {"start": start, "object_id": target["object_id"]}
        for profile in BODIES:
            reply = client.post("/api/route", json={**request, "profile": profile})
            route = reply.json()
            good = reply.status_code == 200 and not route.get("placeholder")
            check(f"{profile} route found", good, str(route.get("length", route)))
            if good:
                routes[profile] = route
                check(f"{profile} route stays clear", route_clear(grid, route["path"], profile))
        answer = client.post(
            "/api/copilot/query",
            json={"question": "What's wrong?", "object_id": request["object_id"]},
        ).json()
        check(
            "copilot answers with citations",
            answer.get("citations") and not answer.get("placeholder"),
            str(answer.get("citations", []))[:60],
        )
        if routes:
            point = next(iter(routes.values()))["path"][-1]
            query = {"x": point[0], "y": point[1], "z": point[2], "radius": 3}
            near = client.get("/api/nearby", params=query).json()["assets"]
            found = any(asset["object_id"] == target["object_id"] for asset in near)
            check("nearby finds the target at the route's end", found, f"{len(near)} objects")
    fixed = next((a for a in assets if a["mobility"] != "movable"), None)
    if fixed:
        move = {"op": "move", "object_id": fixed["object_id"], "position": fixed["center"]}
        check(
            "fixed objects can't be moved",
            client.post("/api/changes", json=move).status_code == 409,
        )
    movable = next((a for a in assets if a["mobility"] == "movable"), None)
    if movable:
        move = {"op": "move", "object_id": movable["object_id"], "position": movable["center"]}
        check(
            "movable objects can be moved",
            client.post("/api/changes", json=move).status_code == 200,
        )
        client.post("/api/changes/reset")
    if routes:
        draw(grid, assets, routes, args.out)
        print(f"Picture: {args.out}")
    for name, passed, detail in results:
        print(f"{'ok  ' if passed else 'FAIL'}  {name}{f': {detail}' if detail else ''}")
    print(
        json.dumps({"passed": sum(r[1] for r in results), "failed": sum(not r[1] for r in results)})
    )
    sys.exit(0 if all(r[1] for r in results) else 1)


if __name__ == "__main__":
    main()
