import json

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")

from app.nav.carve import carved_splats, load_views  # noqa: E402
from app.nav.grid import build_nav_grid  # noqa: E402

UP = (0.0, 1.0, 0.0)
BAND = (0.15, 1.9)
INTRINSICS = np.array([[100.0, 0, 50], [0, 100.0, 50], [0, 0, 1]])


def facing_wall(camera_z=-2.0, wall_z=2.0):
    """A camera 1 m above the floor, looking along +z at a wall."""
    world_to_camera = np.eye(4)
    world_to_camera[1, 1] = -1  # The camera's y points down, and world y points up.
    world_to_camera[2, 2] = 1
    world_to_camera[:3, 3] = [0, 1, -camera_z]
    return INTRINSICS, world_to_camera, np.full((100, 100), wall_z - camera_z)


def test_floater_is_carved_but_wall_and_unseen_splats_are_not():
    points = np.array(
        [
            [0.0, 1.0, 0.0],  # In front of the wall, seen through.
            [0.0, 1.0, 2.0],  # On the wall.
            [0.0, 1.0, 2.5],  # Behind the wall, so never reached.
            [0.0, 0.0, 0.0],  # On the floor, below the band.
        ]
    )
    carved = carved_splats(points, [facing_wall()], UP, 0.0, BAND, pixel_step=2)
    assert carved.tolist() == [True, False, False, False]


def test_views_load_from_a_render_folder(tmp_path):
    (tmp_path / "depth").mkdir()
    np.save(tmp_path / "depth" / "a.npy", np.ones((4, 4)))
    meta = {
        "intrinsics": INTRINSICS.tolist(),
        "cameras": [{"name": "a", "world_to_camera": np.eye(4).tolist()}],
    }
    (tmp_path / "cameras.json").write_text(json.dumps(meta))
    intrinsics, world_to_camera, depth = next(load_views(tmp_path))
    assert intrinsics[0, 0] == 100 and world_to_camera[0, 0] == 1 and depth.shape == (4, 4)


def test_walked_path_opens_a_way_under_a_low_pipe():
    xs, zs = np.meshgrid(np.arange(0, 4, 0.02), np.arange(0, 2, 0.02))
    floor = np.stack([xs.ravel(), np.zeros(xs.size), zs.ravel()], axis=1)
    wall = floor[np.abs(floor[:, 0] - 2) < 0.1] + [0, 1.6, 0]  # A pipe overhead, in the body band.
    points = np.concatenate([floor, wall])
    opacities = np.ones(len(points))
    closed = build_nav_grid(points, opacities, UP, floor_height=0.0)
    walked = np.array([[x, 1.3, 1.0] for x in np.arange(1, 3, 0.05)])
    opened = build_nav_grid(points, opacities, UP, floor_height=0.0, walked=walked)
    cell = np.floor((np.array([2.0, 1.0]) - opened.origin) / opened.cell).astype(int)
    assert not closed.free[cell[0], cell[1]]
    assert opened.free[cell[0], cell[1]]
    assert opened.clearance[cell[0], cell[1]] >= 0.3


def test_walked_path_does_not_clear_objects_at_waist_height():
    xs, zs = np.meshgrid(np.arange(0, 4, 0.02), np.arange(0, 2, 0.02))
    floor = np.stack([xs.ravel(), np.zeros(xs.size), zs.ravel()], axis=1)
    chair = floor[np.abs(floor[:, 0] - 2) < 0.1] + [0, 0.5, 0]
    points = np.concatenate([floor, chair])
    walked = np.array([[x, 1.3, 1.0] for x in np.arange(1, 3, 0.05)])
    grid = build_nav_grid(points, np.ones(len(points)), UP, floor_height=0.0, walked=walked)
    cell = np.floor((np.array([2.0, 1.0]) - grid.origin) / grid.cell).astype(int)
    assert not grid.free[cell[0], cell[1]]
