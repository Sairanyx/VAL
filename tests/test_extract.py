import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("sklearn")

from app.extract.geometry import View, lift, project, upright_box, visible_points  # noqa: E402
from app.extract.label import parse_answer  # noqa: E402
from app.extract.masks import claim_mask, load_claims, save_claims  # noqa: E402
from app.extract.merge import link_masks, main_cluster, vote_splats  # noqa: E402


def make_view() -> View:
    # Camera at the origin looking along +z, so camera axes equal world axes.
    return View(
        name="test",
        image_path=None,
        depth_path=None,
        world_to_camera=np.eye(4),
        intrinsics=np.array([[100.0, 0, 50], [0, 100.0, 40], [0, 0, 1]]),
        width=100,
        height=80,
    )


def test_lift_then_project_returns_the_same_pixels():
    view = make_view()
    depth = np.full((80, 100), 2.0)
    rows, columns = np.array([0, 40, 79]), np.array([0, 50, 99])
    points = lift(rows, columns, depth, view)
    projected_columns, projected_rows, z = project(points, view)
    np.testing.assert_allclose(projected_columns, columns + 0.5)
    np.testing.assert_allclose(projected_rows, rows + 0.5)
    np.testing.assert_allclose(z, 2.0)


def test_visible_points_skips_points_behind_the_surface_and_outside_the_image():
    view = make_view()
    depth = np.full((80, 100), 2.0)
    points = np.array([[0, 0, 2.0], [0, 0, 3.0], [0, 0, -1.0], [50.0, 0, 2.0]])
    index, _, _ = visible_points(points, view, depth)
    assert index.tolist() == [0]


def test_upright_box_finds_a_turned_box():
    random = np.random.default_rng(0)
    local = random.uniform([-1, 0, -0.25], [1, 0.6, 0.25], (4000, 3))
    angle = 0.5
    points = local.copy()
    points[:, 0] = np.cos(angle) * local[:, 0] - np.sin(angle) * local[:, 2] + 3
    points[:, 2] = np.sin(angle) * local[:, 0] + np.cos(angle) * local[:, 2]
    box = upright_box(points, low=0, high=100)
    np.testing.assert_allclose(sorted(box["size"]), [0.5, 0.6, 2.0], atol=0.02)
    np.testing.assert_allclose(box["center"], [3, 0.3, 0], atol=0.02)
    assert box["size"][1] == pytest.approx(0.6, abs=0.02)


def test_masks_of_the_same_object_link_but_a_valve_stays_apart_from_its_pipe():
    masks = [
        np.arange(0, 80),  # object A from one view
        np.arange(20, 100),  # object A from another view
        np.arange(100, 200),  # object B
        np.arange(200, 1000),  # pipe
        np.arange(200, 220),  # valve on the pipe
    ]
    groups = link_masks(masks, splat_voxels=np.arange(1000))
    assert groups[0] == groups[1]
    assert len({groups[0], groups[2], groups[3], groups[4]}) == 4


def test_splats_need_two_votes_and_a_clear_winner():
    masks = [np.array([0, 1, 2]), np.array([1, 2]), np.array([2, 3]), np.array([2])]
    groups = np.array([0, 0, 1, 1])
    labels = vote_splats(masks, groups, splat_count=5)
    # 0: one vote. 1: two votes for group 0. 2: two each, a tie. 3: one vote. 4: unseen.
    assert labels.tolist() == [-1, 0, -1, -1, -1]


def test_main_cluster_drops_a_distant_patch():
    random = np.random.default_rng(0)
    body = random.normal(0, 0.03, (500, 3))
    patch = random.normal(0, 0.01, (20, 3)) + [2.0, 0, 0]
    keep = main_cluster(np.vstack([body, patch]))
    assert keep[:500].mean() > 0.95
    assert not keep[500:].any()


def test_claims_round_trip(tmp_path):
    mask = np.zeros((5, 7), dtype=bool)
    mask[1:4, 2:6] = True
    claims = [
        {
            "prompt": 3,
            "score": 0.8,
            "pixels": int(mask.sum()),
            "box": (10, 20, 17, 25),
            "splats": np.array([4, 5, 6], dtype=np.int32),
            "mask": mask,
        }
    ]
    save_claims(tmp_path / "view.npz", claims, {"view": "view_1"})
    loaded = load_claims(tmp_path / "view.npz")
    assert loaded["meta"] == {"view": "view_1"}
    assert loaded["splats"].tolist() == [4, 5, 6]
    np.testing.assert_array_equal(claim_mask(loaded, 0), mask)


def test_parse_answer_accepts_json_inside_text_and_rejects_unknown_labels():
    text = 'Sure:\n```json\n{"label": "Pump", "single_object": "true", "confidence": 1.4}\n```'
    answer = parse_answer(text, labels=["pump", "valve"])
    assert answer["label"] == "pump"
    assert answer["single_object"] is True
    assert answer["confidence"] == 1.0
    assert parse_answer('{"label": "spaceship"}', labels=["pump"])["label"] == "unknown"
    broken = parse_answer("no json here", labels=["pump"])
    assert broken["parsed"] is False and broken["single_object"] is False
