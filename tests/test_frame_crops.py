import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("PIL")

from app.extract.frame_crops import (  # noqa: E402
    choose_frames,
    frame_score,
    moved_camera,
    seen_points,
)

CAMERA = np.array([[100.0, 0, 50], [0, 100.0, 50], [0, 0, 1]])


def test_points_on_the_video_surface_count_and_others_do_not():
    depth = np.full((100, 100), 2.0)
    points = np.array(
        [
            [0.0, 0.0, 2.0],  # On the surface.
            [0.0, 0.0, 1.0],  # In front of it: the video shows nothing there, so it had moved.
            [0.0, 0.0, 3.0],  # Behind it, so hidden.
            [50.0, 0.0, 2.0],  # Outside the image.
            [0.0, 0.0, -2.0],  # Behind the camera.
        ]
    )
    _, seen = seen_points(points, np.eye(4), CAMERA, depth)
    assert seen.tolist() == [True, False, False, False, False]


def test_large_whole_objects_score_above_small_or_cut_off_ones():
    whole = np.array([[20.0, 20.0], [70.0, 70.0]])
    small = np.array([[50.0, 50.0], [52.0, 52.0]])
    cut_off = np.array([[0.0, 20.0], [50.0, 70.0]])
    shape = (100, 100)
    assert frame_score(whole, shape, 1.0) > frame_score(small, shape, 1.0)
    assert frame_score(whole, shape, 1.0) > frame_score(cut_off, shape, 1.0)


def test_chosen_frames_are_the_best_ones_kept_apart():
    scores = [(0.9, 10), (0.8, 11), (0.7, 30), (0.6, 50)]
    assert choose_frames(scores, 2, 5) == [10, 30]


def test_moved_camera_sees_a_moved_point_where_it_saw_the_original():
    turn = np.array([[0.0, 0, 1], [0, 1, 0], [-1, 0, 0]])
    align = {"scale": 2.0, "R": turn.tolist(), "t": [1.0, 2.0, 3.0]}
    camera = np.eye(4)
    camera[:3, 3] = [0.5, 0.0, 4.0]
    point = np.array([1.0, 2.0, 3.0])
    moved = 2.0 * turn @ point + np.array([1.0, 2.0, 3.0])
    before = camera[:3, :3] @ point + camera[:3, 3]
    new = moved_camera(camera, align)
    after = new[:3, :3] @ moved + new[:3, 3]
    np.testing.assert_allclose(after, before * 2.0, atol=1e-9)  # Same direction, scaled depth.
