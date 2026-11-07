"""Run a scene through the whole pipeline, from one splat file to objects, floor map, and report.

    python scripts/pipeline.py scenes/equipment_room.toml
    python scripts/pipeline.py scenes/equipment_room.toml --dry-run
    python scripts/pipeline.py scenes/equipment_room.toml --force floor

Steps already done are skipped, so a failed run can continue. Each output says how it was made.
Uncleaned splats are used throughout: cleaning leaves black holes in anything rendered from it.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Step:
    name: str
    command: list[str]
    output: Path
    python: str = "python"  # Which environment from the config's [python] table runs it.
    cwd: Path | None = None
    env: dict[str, str] | None = None


def plan(config: dict, config_path: Path) -> list[Step]:
    """Return the steps for a scene, in order."""
    out = ROOT / config["output"]
    scene = str(ROOT / config["source"])
    up = [str(value) for value in config["up"]]
    renders, details = out / "render", out / "render_detail"
    masks, objects = out / "masks", out / "objects"
    assets = objects / "assets.json"
    labels = objects / "splat_labels.npy"
    final = objects / "assets_final.json"
    qwen = objects / "qwen_labels.jsonl"
    numbers = config.get("renders", {})
    vision = config.get("objects", {})
    tool = ROOT / config.get("masks", {}).get("tool", "vlsplat")
    views_flag = ["--views", str(renders), str(details)]
    return [
        Step(
            "render",
            ["-m", "app.scene.render", scene, str(renders), "--up", *up]
            + ["--max-views", str(numbers.get("views", 400))],
            renders / "cameras.json",
            "render",
        ),
        Step(
            "render_detail",
            ["-m", "app.scene.render", scene, str(details), "--up", *up, "--prefix", "detail"]
            + ["--max-views", str(numbers.get("detail_views", 300)), "--fov", "50"]
            + ["--spacing", "0.5", "--heights", "0.4", "1.0", "1.6", "--pitches", "-30", "0", "30"]
            + ["--yaws", "8", "--min-median-depth", "0.7", "--max-median-depth", "2.5"],
            details / "cameras.json",
            "render",
        ),
        Step(
            "masks",
            ["bash", "preprocess/run_masks.sh"],
            masks / "object_mask",
            "shell",
            cwd=tool,
            env={"IMAGE_DIR": str(masks / "images")},
        ),
        Step(
            "objects",
            ["-m", "app.extract.lift", scene, str(masks), str(objects), str(renders), str(details)]
            + ["--up", *up, "--scene-id", config["name"]],
            assets,
        ),
        Step(
            "labels",
            ["-m", "app.extract.label_objects", str(assets), str(masks), str(qwen)]
            + ["--model", str(ROOT / vision.get("vision_model", "")), "--views"]
            + [str(vision.get("views", 5))],
            qwen,
            "vision",
        ),
        Step("grades", ["-m", "app.extract.finalize", str(assets), str(qwen), str(final)], final),
        Step(
            "shapes",
            ["-m", "app.extract.primitives", str(final), scene, str(labels)]
            + [str(objects / "shapes.json")],
            objects / "shapes.json",
        ),
        Step(
            "light_full",
            ["-m", "app.scene.lighten", scene, str(out / "light_full.ply")],
            out / "light_full.ply",
        ),
        Step(
            "light_400k",
            ["-m", "app.scene.lighten", scene, str(out / "light_400k.ply"), "--splats", "400000"],
            out / "light_400k.ply",
        ),
        Step(
            "floor",
            ["-m", "app.nav.grid", scene, "--out", str(out / "nav_grid.npz"), "--up", *up]
            + ["--labels", str(labels), "--assets", str(final), *views_flag],
            out / "nav_grid.npz",
        ),
        Step(
            "route_check",
            [str(ROOT / "scripts" / "check_routes.py"), scene, str(final)]
            + [str(out / "nav_grid.npz"), "--out", str(out / "route_check.json")],
            out / "route_check.json",
        ),
    ]


def write_viewer_file(config: dict, out: Path) -> dict:
    """Add what the viewer and API need to the graded objects: floor, start, and fault tag."""
    document = json.loads((out / "objects" / "assets_final.json").read_text())
    up = config["up"]
    axis = max(range(3), key=lambda i: abs(up[i]))
    floor = document["floor_height_along_up"] / up[axis]
    start = [0.0, 0.0, 0.0]
    start[axis] = floor
    grid_file = out / "nav_grid.npz"
    if grid_file.exists():
        import numpy as np

        # Start at the middle of the floor that the map found, not the file's origin.
        with np.load(grid_file) as grid:
            free = np.argwhere(grid["clearance"] > 0)
            middle = grid["origin"] + (np.median(free, axis=0) + 0.5) * float(grid["cell"])
            for index, value in zip(grid["axes"], middle, strict=True):
                start[int(index)] = round(float(value), 3)
    document.update(
        floor_y=round(float(floor), 3),
        start=start,
        up=up,
        fault_tag=config.get("fault_tag"),
    )
    (out / "assets_viewer.json").write_text(json.dumps(document))
    return document


def link_views(out: Path) -> None:
    """Gather rendered views into the folder the mask tool reads."""
    images = out / "masks" / "images"
    images.mkdir(parents=True, exist_ok=True)
    for folder in ("render", "render_detail"):
        for view in (out / folder / "views").glob("*.jpg"):
            link = images / view.name
            if not link.exists():
                link.symlink_to(view)


def report(config: dict, out: Path, timings: dict[str, float]) -> dict:
    """Summarize a run, and say what still needs a person."""
    summary: dict = {"scene": config["name"], "step_seconds": timings}
    final = out / "objects" / "assets_final.json"
    if final.exists():
        assets = json.loads(final.read_text())["assets"]
        grades: dict[str, int] = {}
        for asset in assets:
            grade = asset.get("label_grade", "?")
            grades[grade] = grades.get(grade, 0) + 1
        summary["objects"] = len(assets)
        summary["grades"] = grades
    check = out / "route_check.json"
    if check.exists():
        summary["routes"] = json.loads(check.read_text())["summary"]
    summary["needs_a_person"] = [
        f"Link {config.get('fault_tag', 'the faulty device')} to its object in the overrides",
        "Review objects graded unsure or unknown",
        "Check moving objects by eye before listing them in PIECES_OBJECTS",
    ]
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="print the steps without running")
    parser.add_argument("--force", nargs="*", default=[], help="steps to run again")
    args = parser.parse_args()
    config = tomllib.loads(args.config.read_text())
    out = ROOT / config["output"]
    pythons = config.get("python", {})
    timings: dict[str, float] = {}
    for step in plan(config, args.config):
        program = [pythons.get(step.python) or sys.executable]
        if step.python == "shell":
            program = []
        command = program + step.command
        done = step.output.exists() and step.name not in args.force
        print(f"{'skip' if done else 'run '} {step.name}: {' '.join(command)}", flush=True)
        if done or args.dry_run:
            continue
        if step.name == "masks":
            link_views(out)
        started = time.perf_counter()
        environment = {**os.environ, "PYTHONPATH": str(ROOT), **(step.env or {})}
        out.mkdir(parents=True, exist_ok=True)
        subprocess.run(command, check=True, cwd=step.cwd or ROOT, env=environment)
        timings[step.name] = round(time.perf_counter() - started, 1)
    if not args.dry_run:
        write_viewer_file(config, out)
        summary = report(config, out, timings)
        (out / "report.json").write_text(json.dumps(summary, indent=1))
        print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
