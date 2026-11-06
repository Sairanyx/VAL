"""Place virtual cameras through a scene. Cameras use OpenCV axes: x right, y down, z forward."""

import numpy as np


def world_to_camera(position: np.ndarray, forward: np.ndarray, up: np.ndarray) -> np.ndarray:
    """Return a 4x4 world-to-camera matrix for a camera at `position` looking along `forward`."""
    z = forward / np.linalg.norm(forward)
    x = np.cross(-up, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    rotation = np.stack([x, y, z])
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    matrix[:3, 3] = -rotation @ position
    return matrix


def intrinsics(width: int, height: int, horizontal_fov_degrees: float) -> np.ndarray:
    """Return a 3x3 pinhole camera matrix."""
    focal = width / (2 * np.tan(np.radians(horizontal_fov_degrees) / 2))
    return np.array([[focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1]])


def floor_fraction(
    depth: np.ndarray,
    camera: np.ndarray,
    matrix: np.ndarray,
    up: tuple[float, float, float],
    floor_height: float,
    tolerance: float = 0.1,
    stride: int = 4,
) -> float:
    """Return the share of rendered pixels that land on the floor. Depth is 0 where nothing was."""
    rows, columns = np.nonzero(depth[::stride, ::stride] > 0)
    if not len(rows):
        return 0.0
    rows, columns = rows * stride, columns * stride
    z = depth[rows, columns]
    x = (columns + 0.5 - camera[0, 2]) / camera[0, 0] * z
    y = (rows + 0.5 - camera[1, 2]) / camera[1, 1] * z
    rotation, translation = matrix[:3, :3], matrix[:3, 3]
    world = (np.stack([x, y, z], axis=1) - translation) @ rotation
    up_axis = np.asarray(up, dtype=np.float64)
    heights = world @ (up_axis / np.linalg.norm(up_axis))
    return float(np.mean(np.abs(heights - floor_height) < tolerance))


def is_clear(position: np.ndarray, obstacles: np.ndarray, radius: float) -> bool:
    """True if no obstacle point is within `radius` of `position`."""
    return bool(np.all(((obstacles - position) ** 2).sum(axis=1) > radius**2))


def grid_cameras(
    obstacles: np.ndarray,
    up: tuple[float, float, float],
    floor_height: float,
    heights: tuple[float, ...] = (0.7, 1.5),
    spacing: float = 0.75,
    yaws: int = 6,
    pitches_degrees: tuple[float, ...] = (-10.0,),
    clearance: float = 0.25,
) -> list[np.ndarray]:
    """Return world-to-camera matrices on a grid over the floor, skipping positions inside objects.

    `obstacles` are points from the solid part of the scene. `heights` are above the floor.
    """
    up_axis = np.asarray(up, dtype=np.float64)
    up_axis /= np.linalg.norm(up_axis)
    # Two floor directions perpendicular to up.
    helper = np.eye(3)[np.argmin(np.abs(up_axis))]
    side = np.cross(up_axis, helper)
    side /= np.linalg.norm(side)
    ahead = np.cross(side, up_axis)

    side_values, ahead_values = obstacles @ side, obstacles @ ahead
    side_low, side_high = np.percentile(side_values, [1, 99])
    ahead_low, ahead_high = np.percentile(ahead_values, [1, 99])

    cameras = []
    for along_side in np.arange(side_low, side_high, spacing):
        for along_ahead in np.arange(ahead_low, ahead_high, spacing):
            for height in heights:
                position = (
                    along_side * side + along_ahead * ahead + (floor_height + height) * up_axis
                )
                if not is_clear(position, obstacles, clearance):
                    continue
                for yaw in np.linspace(0, 2 * np.pi, yaws, endpoint=False):
                    level = np.cos(yaw) * ahead + np.sin(yaw) * side
                    for pitch in np.radians(pitches_degrees):
                        forward = np.cos(pitch) * level + np.sin(pitch) * up_axis
                        cameras.append(world_to_camera(position, forward, up_axis))
    return cameras
