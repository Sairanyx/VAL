"""Combine label sources, grade them, check them against geometry, and set each object's mobility.

    python -m app.extract.finalize ASSETS.json QWEN.jsonl OUT.json [--overrides OVERRIDES.json]

Overrides are hand corrections, {"obj-0001": {"label": "pump", "mobility": "fixed"}}. They always
win and survive re-running the pipeline. Grades: verified (a person confirmed it), likely (SAM and
the vision model agree and geometry allows it), unsure, and unknown. Users only see a name for
verified and likely objects. Others show as "object", with the guess kept in `suggested_label`.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

FIXED_LABELS = {
    "pipe",
    "pipe fitting",
    "tank",
    "pump",
    "valve",
    "motor",
    "gauge",
    "sensor",
    "electrical cabinet",
    "control panel",
    "door",
    "light fixture",
    "wall",
    "floor",
    "ceiling",
}
MOVABLE_LABELS = {"cart", "ladder", "box", "bucket", "barrel", "chair", "tool", "bag"}
SAM_TO_QWEN = {"cabinet": "electrical cabinet"}
TRUSTED_GRADES = {"verified", "likely"}


def box_measures(asset: dict, up: np.ndarray) -> dict:
    """Return height along `up`, and the longest and shortest box sides, in metres."""
    low, high = np.array(asset["bbox_min"]), np.array(asset["bbox_max"])
    sides = np.sort(high - low)[::-1]
    corners = np.array([low, high]) @ up
    return {
        "height": float(abs(corners[1] - corners[0])),
        "bottom": float(corners.min()),
        "top": float(corners.max()),
        "longest": float(sides[0]),
        "middle": float(sides[1]),
        "shortest": float(sides[2]),
    }


def geometry_problem(label: str, measures: dict, room_top: float) -> str | None:
    """Return why a label can't fit this object's shape, or None if it can."""
    longest, middle = measures["longest"], measures["middle"]
    if label == "tank" and longest < 0.4:
        return f"too small for a tank ({longest:.2f} m)"
    if label == "pipe" and longest < 1.5 * max(middle, 0.01):
        return "not long and thin enough for a pipe"
    if label in {"pump", "motor"} and longest > 1.6:
        return f"too large for a {label} ({longest:.2f} m)"
    if label == "door" and measures["height"] < 1.2:
        return f"too short for a door ({measures['height']:.2f} m)"
    if label == "light fixture" and room_top - measures["top"] > 0.5:
        return "too far below the ceiling for a light fixture"
    return None


def grade_label(
    sam_label: str, qwen_label: str, measures: dict, room_top: float
) -> tuple[str, str, str]:
    """Return the label to show, its grade, and the reason for that grade."""
    sam = SAM_TO_QWEN.get(sam_label, sam_label)
    if qwen_label in ("", "unknown"):
        return "unknown", "unknown", "the vision model couldn't tell"
    problem = geometry_problem(qwen_label, measures, room_top)
    if problem:
        return qwen_label, "unsure", problem
    if qwen_label == sam:
        return qwen_label, "likely", "SAM and the vision model agree"
    return qwen_label, "unsure", f"SAM said {sam_label or 'nothing'}"


def decide_mobility(
    label: str,
    grade: str,
    measures: dict,
    floor: float,
    room_top: float,
    touches_wall: bool,
) -> tuple[str, str]:
    """Return mobility and its reason. It's movable only if label and geometry both agree."""
    if grade not in TRUSTED_GRADES:
        return "unsure", "label isn't confirmed"
    if label in FIXED_LABELS:
        return "fixed", f"{label} is fixed equipment"
    if label not in MOVABLE_LABELS:
        return "unsure", f"no rule for {label}"
    if room_top - measures["top"] < 0.15:
        return "unsure", "reaches the ceiling"
    if measures["bottom"] - floor > 0.4:
        return "unsure", "isn't resting on the floor"
    if touches_wall:
        return "unsure", "touches a wall"
    return "movable", f"{label} resting on the floor, clear of walls"


def finalize(
    document: dict,
    qwen: dict[str, dict],
    overrides: dict[str, dict],
    wall_margin: float = 0.1,
) -> dict:
    """Return a copy of the assets document with labels, grades, and mobility filled in."""
    up = np.asarray(document.get("up", (0.0, -1.0, 0.0)), dtype=np.float64)
    up /= np.linalg.norm(up)
    assets = document["assets"]
    floor = float(document["floor_height_along_up"])
    all_measures = [box_measures(asset, up) for asset in assets]
    room_top = max((m["top"] for m in all_measures), default=floor + 2.5)
    lows = np.array([asset["bbox_min"] for asset in assets]) if assets else np.zeros((0, 3))
    highs = np.array([asset["bbox_max"] for asset in assets]) if assets else np.zeros((0, 3))
    room_low = lows.min(axis=0) if assets else np.zeros(3)
    room_high = highs.max(axis=0) if assets else np.zeros(3)
    horizontal = np.abs(up) < 0.5

    result = []
    for asset, measures in zip(assets, all_measures, strict=True):
        object_id = asset["object_id"]
        reply = qwen.get(object_id, {})
        sam_label = asset["label"]
        suggestion, grade, grade_reason = grade_label(
            sam_label, reply.get("label", ""), measures, room_top
        )
        low, high = np.array(asset["bbox_min"]), np.array(asset["bbox_max"])
        near_low = (low - room_low)[horizontal] < wall_margin
        near_high = (room_high - high)[horizontal] < wall_margin
        touches_wall = bool(near_low.any() or near_high.any())

        override = overrides.get(object_id, {})
        if "label" in override:
            suggestion, grade, grade_reason = override["label"], "verified", "confirmed by a person"
        mobility, mobility_reason = decide_mobility(
            suggestion, grade, measures, floor, room_top, touches_wall
        )
        if "mobility" in override:
            mobility, mobility_reason = override["mobility"], "set by a person"

        result.append(
            {
                **asset,
                "label": suggestion if grade in TRUSTED_GRADES else "object",
                "label_grade": grade,
                "label_reason": grade_reason,
                "suggested_label": suggestion,
                "sam_label": sam_label,
                "description": reply.get("description", ""),
                "visible_text": reply.get("visible_text", ""),
                "mobility": mobility,
                "mobility_reason": mobility_reason,
            }
        )
    return {**document, "assets": result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", type=Path)
    parser.add_argument("qwen", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--overrides", type=Path)
    args = parser.parse_args()

    document = json.loads(args.assets.read_text())
    replies = [json.loads(line) for line in args.qwen.read_text().splitlines() if line]
    qwen = {reply["object_id"]: reply for reply in replies}
    overrides = json.loads(args.overrides.read_text()) if args.overrides else {}
    final = finalize(document, qwen, overrides)
    args.out.write_text(json.dumps(final, indent=1))
    assets = final["assets"]
    print(
        json.dumps(
            {
                "objects": len(assets),
                "grades": Counter(a["label_grade"] for a in assets).most_common(),
                "mobility": Counter(a["mobility"] for a in assets).most_common(),
                "shown_labels": Counter(a["label"] for a in assets).most_common(),
                "movable": [a["object_id"] for a in assets if a["mobility"] == "movable"][:40],
            }
        )
    )


if __name__ == "__main__":
    main()
