import pytest

np = pytest.importorskip("numpy")

from app.scene.cameras import (  # noqa: E402
    floor_fraction,
    grid_cameras,
    intrinsics,
    world_to_camera,
)

Y_DOWN_UP = np.array([0.0, -1.0, 0.0])


def to_camera(matrix, point):
    return matrix[:3, :3] @ np.asarray(point, dtype=float) + matrix[:3, 3]


def test_point_ahead_has_positive_depth_and_matrix_is_a_proper_rotation():
    matrix = world_to_camera(np.zeros(3), np.array([0.0, 0.0, 1.0]), Y_DOWN_UP)
    assert to_camera(matrix, [0, 0, 2])[2] == pytest.approx(2)
    np.testing.assert_allclose(matrix[:3, :3] @ matrix[:3, :3].T, np.eye(3), atol=1e-9)
    assert np.linalg.det(matrix[:3, :3]) == pytest.approx(1)


def test_scene_up_appears_above_the_image_center():
    # OpenCV image y grows downward, so a point above the camera has negative camera y.
    matrix = world_to_camera(np.zeros(3), np.array([1.0, 0.0, 0.0]), Y_DOWN_UP)
    assert to_camera(matrix, 2 * Y_DOWN_UP + [3, 0, 0])[1] < 0


def test_intrinsics_center_the_principal_point():
    camera = intrinsics(1280, 720, 90.0)
    assert camera[0, 0] == pytest.approx(640)
    assert (camera[0, 2], camera[1, 2]) == (640, 360)


def test_floor_fraction_separates_floor_views_from_wall_views():
    camera = intrinsics(64, 64, 60.0)
    # With +y down and the floor 1.2 below the camera, floor height along up is -1.2.
    position = np.zeros(3)
    down = world_to_camera(position, np.array([0.0, 1.0, 1e-6]), np.array([0.0, 0.0, -1.0]))
    assert floor_fraction(np.full((64, 64), 1.2), camera, down, (0, -1, 0), -1.2) == 1.0
    level = world_to_camera(position, np.array([0.0, 0.0, 1.0]), Y_DOWN_UP)
    assert floor_fraction(np.full((64, 64), 2.0), camera, level, (0, -1, 0), -1.2) == 0.0
    assert floor_fraction(np.zeros((64, 64)), camera, level, (0, -1, 0), -1.2) == 0.0


def test_grid_skips_positions_inside_obstacles_and_sits_above_the_floor():
    random = np.random.default_rng(0)
    room = random.uniform([-3, -1.3, -3], [3, 1.2, 3], (2000, 3))
    room[:, 1] = 1.2  # A flat floor with +y down, so the only obstacles are far below the cameras.
    wall = np.column_stack(
        [np.zeros(500), random.uniform(-1.3, 1.2, 500), random.uniform(-3, 3, 500)]
    )
    cameras = grid_cameras(
        np.vstack([room, wall]), up=(0, -1, 0), floor_height=-1.2, heights=(1.5,), yaws=2
    )
    assert cameras
    positions = np.array([-m[:3, :3].T @ m[:3, 3] for m in cameras])
    np.testing.assert_allclose(positions[:, 1], -0.3, atol=1e-6)
    assert np.abs(positions[:, 0]).min() > 0.2
