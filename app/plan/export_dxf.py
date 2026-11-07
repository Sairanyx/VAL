"""Write a floor layout as a DXF that CAD tools open: walls, object footprints, and tags.

Uses the plain R12 text format, so it needs no extra library. Coordinates are the scan's, in metres,
with the first floor axis as X and the second as Y.
"""

import re

from app.bim.model import identity_confirmed
from app.plan.layout import plan_axes

TEXT_HEIGHT = 0.08
NOTE = "GENERATED FROM A SCAN, NOT SURVEYED"
COLORS = {"WALLS": 7, "FAULT": 1, "LINKED": 5, "TAGS": 2, "NOTES": 8}


def layer_for(asset: dict, fault_tag: str | None) -> str:
    """Return the DXF layer for an object, by its link or type."""
    tag = (asset.get("mapping") or {}).get("tag")
    if tag and tag == fault_tag:
        return "FAULT"
    if tag:
        return "LINKED"
    label = re.sub(r"[^A-Z0-9]+", "_", str(asset.get("label", "OBJECT")).upper()).strip("_")
    return f"OBJECT_{label or 'OTHER'}"


def _pairs(*items: tuple[int, object]) -> list[str]:
    return [f"{code}\n{value}" for code, value in items]


def _line(layer: str, a: tuple[float, float], b: tuple[float, float]) -> list[str]:
    return _pairs(
        (0, "LINE"), (8, layer), (10, f"{a[0]:.3f}"), (20, f"{a[1]:.3f}"), (30, 0.0),
        (11, f"{b[0]:.3f}"), (21, f"{b[1]:.3f}"), (31, 0.0),
    )  # fmt: skip


def _text(layer: str, at: tuple[float, float], value: str) -> list[str]:
    clean = re.sub(r"[^\x20-\x7e]", "?", value)
    return _pairs(
        (0, "TEXT"), (8, layer), (10, f"{at[0]:.3f}"), (20, f"{at[1]:.3f}"), (30, 0.0),
        (40, TEXT_HEIGHT), (1, clean),
    )  # fmt: skip


def write_dxf(
    description: dict,
    assets: list[dict],
    fault_tag: str | None = None,
    up: tuple[float, float, float] = (0.0, -1.0, 0.0),
) -> str:
    """Return a DXF of the layout. Objects in the list are drawn where they stand now."""
    first, second, _, _ = plan_axes(up)
    body: list[str] = []
    layers = set(COLORS)
    for wall in description["walls"]:
        body += _line("WALLS", tuple(wall["start"]), tuple(wall["end"]))
    for asset in assets:
        layer = layer_for(asset, fault_tag)
        layers.add(layer)
        low_x, high_x = sorted((asset["bbox_min"][first], asset["bbox_max"][first]))
        low_y, high_y = sorted((asset["bbox_min"][second], asset["bbox_max"][second]))
        corners = [(low_x, low_y), (high_x, low_y), (high_x, high_y), (low_x, high_y)]
        for a, b in zip(corners, corners[1:] + corners[:1], strict=True):
            body += _line(layer, a, b)
        tag = (asset.get("mapping") or {}).get("tag")
        if tag:
            shown = tag if identity_confirmed(asset["mapping"]) else f"{tag}?"
            body += _text("TAGS", (low_x, high_y + 0.02), shown)
    if description["walls"]:
        x = min(p[0] for w in description["walls"] for p in (w["start"], w["end"]))
        y = min(p[1] for w in description["walls"] for p in (w["start"], w["end"]))
        body += _text("NOTES", (x, y - 0.2), NOTE)

    table = _pairs((0, "SECTION"), (2, "TABLES"), (0, "TABLE"), (2, "LAYER"), (70, len(layers)))
    for layer in sorted(layers):
        color = COLORS.get(layer, 3)
        table += _pairs((0, "LAYER"), (2, layer), (70, 0), (62, color), (6, "CONTINUOUS"))
    table += _pairs((0, "ENDTAB"), (0, "ENDSEC"))
    entities = _pairs((0, "SECTION"), (2, "ENTITIES")) + body + _pairs((0, "ENDSEC"), (0, "EOF"))
    return "\n".join(table + entities) + "\n"
