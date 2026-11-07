"""Make a top-down floor layout from a scan: a floor image, walls, and object footprints.

It's generated from the scan, not surveyed. The walls are the same room estimate the BIM model uses,
and the scale is the scan's own, which hasn't been checked on site.
"""

from typing import Any

import numpy as np
from scipy import ndimage

from app.bim.room import estimate_room
from app.scene.load import Splats

CELL = 0.025  # metres per pixel of the floor image
FLOOR_BAND = 0.06  # metres either side of the floor that count as floor
BODY_BAND = (0.15, 1.9)  # metres above the floor where things stand
SOLID_OPACITY = 0.3
SH_ZERO = 0.28209479177387814
EDGE_MARGIN = 0.3  # metres of image around the room
SHADE = 0.55  # how much standing things darken the floor image
OUTSIDE = (22, 26, 32)
UNSEEN = (58, 60, 64)  # floor inside the room that the scan didn't see
BLEND_CELLS = 2.0
NO_FLOOR = 0.002  # blended splat opacity per cell, below which there's no evidence of floor


def plan_axes(up: tuple[float, float, float]) -> tuple[int, int, int, float]:
    """Return the two floor axes, the up axis, and the sign of up along it."""
    direction = np.asarray(up, dtype=np.float64)
    axis = int(np.argmax(np.abs(direction)))
    first, second = [i for i in range(3) if i != axis]
    return first, second, axis, float(np.sign(direction[axis]))


def build_layout(
    splats: Splats, floor_y: float, up: tuple[float, float, float] = (0.0, -1.0, 0.0)
) -> tuple[Any, dict]:
    """Return the floor image and a description: its extent in scene coordinates, and the room."""
    from PIL import Image

    first, second, axis, sign = plan_axes(up)
    positions = splats.positions.astype(np.float64)
    heights = (positions[:, axis] - floor_y) * sign
    flat = positions[:, [first, second]]
    solid = splats.opacities >= SOLID_OPACITY

    standing = solid & (heights > BODY_BAND[0]) & (heights < BODY_BAND[1])

    room = estimate_room(positions, splats.opacities, list(up), floor_y * sign)
    faces, support = room["faces"], room["wall_support"]
    room_low = np.array([faces["first_min"], faces["second_min"]])
    room_high = np.array([faces["first_max"], faces["second_max"]])
    origin = room_low - EDGE_MARGIN
    top = room_high + EDGE_MARGIN
    columns, rows = np.ceil((top - origin) / CELL).astype(int)

    def to_cells(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        cells = np.floor((flat[mask] - origin) / CELL).astype(int)
        inside = (cells[:, 0] >= 0) & (cells[:, 0] < columns)
        inside &= (cells[:, 1] >= 0) & (cells[:, 1] < rows)
        return cells[inside, 0], cells[inside, 1], np.flatnonzero(mask)[inside]

    # Faint splats count too, as they build up floors. Blending fills the gaps between splats.
    on_floor = np.abs(heights) <= FLOOR_BAND
    x, z, chosen = to_cells(on_floor)
    colors = np.stack([splats.data[f"f_dc_{i}"][chosen] for i in range(3)], axis=1)
    colors = np.clip(colors * SH_ZERO + 0.5, 0, 1)
    weights = splats.opacities[chosen]
    total = np.zeros((rows, columns))
    np.add.at(total, (z, x), weights)
    blended_total = ndimage.gaussian_filter(total, BLEND_CELLS)
    image = np.zeros((rows, columns, 3))
    for channel in range(3):
        sums = np.zeros((rows, columns))
        np.add.at(sums, (z, x), colors[:, channel] * weights)
        image[..., channel] = ndimage.gaussian_filter(sums, BLEND_CELLS) / np.maximum(
            blended_total, 1e-6
        )
    image[blended_total < NO_FLOOR] = np.array(UNSEEN) / 255

    x, z, _ = to_cells(standing)
    shade = np.zeros((rows, columns))
    np.add.at(shade, (z, x), 1.0)
    shade = ndimage.gaussian_filter(np.minimum(shade, 4.0) / 4.0, 1.0)
    image = image * (1 - SHADE * np.clip(shade * 2, 0, 1)[..., None])

    xs = origin[0] + (np.arange(columns) + 0.5) * CELL
    zs = origin[1] + (np.arange(rows) + 0.5) * CELL
    inside_x = (xs >= room_low[0]) & (xs <= room_high[0])
    inside_z = (zs >= room_low[1]) & (zs <= room_high[1])
    outside = ~(inside_z[:, None] & inside_x[None, :])
    pixels = (image * 255).astype(np.uint8)
    pixels[outside] = OUTSIDE
    # Row 0 is the far side, so that +z points up the page.
    picture = Image.fromarray(pixels[::-1])
    x0, z0 = room_low.tolist()
    x1, z1 = room_high.tolist()
    description = {
        "x_min": float(origin[0]),
        "x_max": float(origin[0] + columns * CELL),
        "z_min": float(origin[1]),
        "z_max": float(origin[1] + rows * CELL),
        "axes": [first, second],
        "room": room,
        "walls": [
            {"start": [x0, z0], "end": [x1, z0], "support": support["second_min"]},
            {"start": [x1, z0], "end": [x1, z1], "support": support["first_max"]},
            {"start": [x1, z1], "end": [x0, z1], "support": support["second_max"]},
            {"start": [x0, z1], "end": [x0, z0], "support": support["first_min"]},
        ],
        "generated_from": "scan, not surveyed",
    }
    return picture, description
