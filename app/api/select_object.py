"""Turn an operator's selection in the viewer into a proposed new object.

Code measures the object from the splats inside the selection. A vision model only suggests what it
might be, and the operator confirms or changes that before anything is saved.
"""

import base64
import io
import re
from typing import Any

import numpy as np
from scipy import ndimage

from app.scene.load import Splats

SOLID_OPACITY = 0.3
FLOOR_MARGIN = 0.05  # metres above the floor to ignore, so the floor isn't part of the object
NEAREST_DEPTH = 0.3  # metres from the camera, closer than this is the viewer's own surroundings
VOXEL = 0.04  # metres: solid splats closer than about this count as touching
MIN_SPLATS = 60
MIN_SHARE = 0.1  # a front cluster must hold this share of the selection, or it's stray splats
BOX_PERCENTILES = (1, 99)  # stray splats shouldn't stretch the box
MIN_SIDE = 0.05
CROP_MARGIN = 0.15
OVERLAP_ALREADY_KNOWN = 0.5
SPLIT_MIN_REST = 0.1  # share of an object that must remain, or it isn't really a split
SPLIT_GAP = 0.02  # metres around a selected part that still belong to it

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
    "light fixture",
    "door",
}
MOVABLE_LABELS = {"cart", "ladder", "box", "bucket", "barrel", "chair", "tool", "bag"}

LOOK_PROMPT = """This image is cropped from a view of an industrial equipment room. It shows one
object that an operator selected, near the middle. Choose the label that best fits, from: {labels}.

Use "unknown" if you can't tell or if it looks like several things. Only name equipment if you can
see its typical parts.

Reply with JSON only:
{{"label": "...", "confidence": 0.0, "reason": "evidence, under 12 words", "visible_text": ""}}
"visible_text" is text you can actually read on the object, exactly as written, or "" if none."""


class NothingSelected(ValueError):
    """The selection held no usable object. The message says why, for the operator."""


def inside_selection(
    positions: np.ndarray, origin: np.ndarray, corners: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return which points lie inside the pyramid of four corner rays, and each one's depth."""
    middle = corners.mean(axis=0)
    middle = middle / np.linalg.norm(middle)
    offsets = positions - origin
    inside = offsets @ middle > NEAREST_DEPTH
    for index in range(4):
        normal = np.cross(corners[index], corners[(index + 1) % 4])
        if normal @ middle < 0:
            normal = -normal
        inside &= offsets @ normal >= 0
    return inside, offsets @ middle


def box_summary(members: np.ndarray) -> dict[str, Any]:
    """Return the box around points, ignoring strays that would stretch it."""
    low = np.percentile(members, BOX_PERCENTILES[0], axis=0)
    high = np.percentile(members, BOX_PERCENTILES[1], axis=0)
    high = np.maximum(high, low + MIN_SIDE)
    return {
        "bbox_min": [round(float(v), 3) for v in low],
        "bbox_max": [round(float(v), 3) for v in high],
        "center": [round(float(v), 3) for v in (low + high) / 2],
        "splats": int(len(members)),
    }


def in_box(positions: np.ndarray, box: dict, margin: float = 0.0) -> np.ndarray:
    """Return which points lie in an object's box."""
    first, second = np.asarray(box["bbox_min"]), np.asarray(box["bbox_max"])
    low, high = np.minimum(first, second) - margin, np.maximum(first, second) + margin
    return ((positions >= low) & (positions <= high)).all(axis=1)


def pick_object(
    splats: Splats,
    origin: list[float],
    corners: list[list[float]],
    floor_y: float,
    up: tuple[float, float, float] = (0.0, -1.0, 0.0),
    within: dict | None = None,
) -> dict[str, Any]:
    """Return the box of the nearest solid thing in a selection, measured from the splats.

    `within` limits the search to an object's box, for picking out one part of it.
    """
    start = np.asarray(origin, dtype=np.float64)
    rays = np.asarray(corners, dtype=np.float64)
    direction = np.asarray(up, dtype=np.float64)
    positions = splats.positions.astype(np.float64)
    floor_height = floor_y * float(direction @ np.array([0.0, 1.0, 0.0]))
    solid = splats.opacities >= SOLID_OPACITY
    solid &= positions @ direction > floor_height + FLOOR_MARGIN
    inside, depths = inside_selection(positions, start, rays)
    if within is not None:
        inside &= in_box(positions, within)
    chosen = np.flatnonzero(inside & solid)
    if len(chosen) < MIN_SPLATS:
        raise NothingSelected("Nothing solid in that selection. Try a larger box.")

    points = positions[chosen]
    cells = np.floor((points - points.min(axis=0)) / VOXEL).astype(np.int64)
    grid = np.zeros(cells.max(axis=0) + 1, dtype=bool)
    grid[cells[:, 0], cells[:, 1], cells[:, 2]] = True
    regions, found = ndimage.label(grid, structure=np.ones((3, 3, 3)))
    groups = regions[cells[:, 0], cells[:, 1], cells[:, 2]]
    sizes = np.bincount(groups, minlength=found + 1)
    enough = max(MIN_SPLATS, MIN_SHARE * len(chosen))
    candidates = [group for group in range(1, found + 1) if sizes[group] >= enough]
    if not candidates:
        raise NothingSelected("That selection only holds scattered splats. Try a tighter box.")
    # The nearest sizeable thing is what the operator is looking at.
    best = min(candidates, key=lambda group: np.percentile(depths[chosen[groups == group]], 10))
    members = points[groups == best]
    return box_summary(members)


def largest_cluster(points: np.ndarray) -> np.ndarray:
    """Return the biggest group of touching points, so scraps don't stretch a box."""
    cells = np.floor((points - points.min(axis=0)) / VOXEL).astype(np.int64)
    grid = np.zeros(cells.max(axis=0) + 1, dtype=bool)
    grid[cells[:, 0], cells[:, 1], cells[:, 2]] = True
    regions, _ = ndimage.label(grid, structure=np.ones((3, 3, 3)))
    groups = regions[cells[:, 0], cells[:, 1], cells[:, 2]]
    return points[groups == np.argmax(np.bincount(groups)[1:]) + 1]


def split_object(
    splats: Splats,
    parent: dict,
    origin: list[float],
    corners: list[list[float]],
    floor_y: float,
    up: tuple[float, float, float] = (0.0, -1.0, 0.0),
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split an object into the part selected and the rest, each with its own measured box."""
    part = pick_object(splats, origin, corners, floor_y, up, within=parent)
    positions = splats.positions.astype(np.float64)
    direction = np.asarray(up, dtype=np.float64)
    floor_height = floor_y * float(direction @ np.array([0.0, 1.0, 0.0]))
    solid = splats.opacities >= SOLID_OPACITY
    solid &= positions @ direction > floor_height + FLOOR_MARGIN
    whole = solid & in_box(positions, parent)
    others = whole & ~in_box(positions, part, SPLIT_GAP)
    if others.sum() < max(MIN_SPLATS, SPLIT_MIN_REST * whole.sum()):
        raise NothingSelected("That selection covers nearly all of it. Select just one part.")
    return part, box_summary(largest_cluster(positions[others]))


def box_overlap(first: dict, second: dict) -> float:
    """Return how much of the smaller of two boxes lies inside the other."""
    low = np.maximum(first["bbox_min"], second["bbox_min"])
    high = np.minimum(first["bbox_max"], second["bbox_max"])
    shared = float(np.prod(np.clip(high - low, 0, None)))

    def volume(box: dict) -> float:
        return float(np.prod(np.asarray(box["bbox_max"]) - np.asarray(box["bbox_min"])))

    return shared / max(min(volume(first), volume(second)), 1e-9)


def already_known(box: dict, assets: list[dict]) -> list[str]:
    """Return objects that already cover most of this box, so the operator isn't duplicating."""
    return [
        asset["object_id"] for asset in assets if box_overlap(box, asset) >= OVERLAP_ALREADY_KNOWN
    ]


def crop_selection(data_url: str, rectangle: list[float]):
    """Return the operator's selection, with a margin, from a viewer screenshot."""
    from PIL import Image

    encoded = data_url.split(",", 1)[-1]
    image = Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")
    left, top, right, bottom = rectangle
    pad_x, pad_y = (right - left) * CROP_MARGIN, (bottom - top) * CROP_MARGIN
    return image.crop(
        (
            int(max(left - pad_x, 0) * image.width),
            int(max(top - pad_y, 0) * image.height),
            int(min(right + pad_x, 1) * image.width),
            int(min(bottom + pad_y, 1) * image.height),
        )
    )


def mobility_for(label: str) -> tuple[str, str]:
    """Return whether a label's objects can move, by rule, and why."""
    if label in FIXED_LABELS:
        return "fixed", f"{label} is fixed equipment"
    if label in MOVABLE_LABELS:
        return "movable", f"{label} can be moved"
    return "unsure", f"no rule for {label}"


def known_tag(text: str, tags: list[str]) -> str | None:
    """Return an equipment tag only if it's actually readable in the text."""
    for tag in tags:
        if re.search(rf"(?<![A-Z0-9]){re.escape(tag)}(?![A-Z0-9])", text.upper()):
            return tag
    return None


def suggest_config(writer: Any, crop: Any, tags: list[str]) -> dict[str, Any]:
    """Return the object's settings to confirm, with the model's guess where there is one."""
    from app.extract.label_vlm import LABELS, parse_answer

    config: dict[str, Any] = {
        "label": "object",
        "label_confidence": 0.0,
        "label_source": "not suggested",
        "reason": "",
        "visible_text": "",
        "possible_tag": None,
    }
    if writer is not None and crop is not None:
        try:
            reply = writer.look(crop, LOOK_PROMPT.format(labels=", ".join(LABELS)))
        except OSError:  # A small laptop model may not see images, so the operator just chooses.
            reply = ""
        answer = parse_answer(reply)
        if answer["label"] != "unknown":
            config["label"] = answer["label"]
            config["label_source"] = "vision model, unconfirmed"
        config["label_confidence"] = answer["confidence"]
        config["reason"] = answer["description"]
        config["visible_text"] = answer["visible_text"]
        config["possible_tag"] = known_tag(answer["visible_text"], tags)
    config["mobility"], config["mobility_reason"] = mobility_for(config["label"])
    return config
