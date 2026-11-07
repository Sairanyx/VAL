import json

import pytest

np = pytest.importorskip("numpy")
sparse = pytest.importorskip("scipy.sparse")
pil = pytest.importorskip("PIL.Image")

from app.extract.lift import (  # noqa: E402
    build_assets,
    collect_membership,
    merge_masks,
    project_to_masks,
    vote_labels,
)
from app.scene.cameras import intrinsics, world_to_camera  # noqa: E402

UP = np.array([0.0, -1.0, 0.0])


def membership_from(mask_splats, splat_count):
    rows, columns = [], []
    for mask, splats in enumerate(mask_splats):
        rows += list(splats)
        columns += [mask] * len(splats)
    data = np.ones(len(rows), dtype=np.int32)
    return sparse.csr_matrix((data, (rows, columns)), shape=(splat_count, len(mask_splats)))


def test_projection_finds_the_mask_and_skips_hidden_splats():
    camera = intrinsics(100, 100, 90.0)
    matrix = world_to_camera(np.zeros(3), np.array([0.0, 0.0, 1.0]), UP)
    positions = np.array([[0.0, 0.0, 2.0], [0.0, 0.0, 5.0], [0.0, 0.0, -2.0], [50.0, 0.0, 2.0]])
    depth = np.full((100, 100), 2.0, dtype=np.float32)
    ids = np.zeros((100, 100), dtype=np.uint16)
    ids[50, 50] = 7
    splats, hits = project_to_masks(positions, matrix, camera, depth, ids)
    assert splats.tolist() == [0]
    assert hits.tolist() == [7]


def test_overlapping_masks_merge_and_distant_ones_do_not():
    masks = [range(0, 100), range(10, 110), range(500, 600)]
    groups = merge_masks(membership_from(masks, 700))
    assert groups[0] == groups[1]
    assert groups[0] != groups[2]


def test_merge_refuses_to_grow_beyond_the_size_limit():
    positions = np.zeros((300, 3))
    positions[:, 0] = np.linspace(0, 10, 300)
    masks = [range(0, 150), range(100, 300)]
    membership = membership_from(masks, 300)
    groups = merge_masks(membership, min_iou=0.1, max_extent=3.0, positions=positions)
    assert groups[0] != groups[1]


def test_splats_join_the_object_their_views_agree_on():
    membership = membership_from([[0, 1], [0, 1], [1, 2], [3]], 4)
    labels = vote_labels(membership, np.array([0, 0, 1, 2]), min_votes=2, min_share=0.6)
    assert labels[0] == 0
    assert labels[1] == 0
    assert labels[2] == -1  # Only one vote.
    assert labels[3] == -1


def test_assets_keep_big_multi_view_objects_and_use_labels():
    positions = np.random.default_rng(0).normal(size=(400, 3))
    masks = [range(0, 300), range(0, 300), range(0, 300), range(300, 310)]
    membership = membership_from(masks, 400)
    records = [
        {"view": "a", "mask_id": 1, "label": "sam2", "score": 0.9},
        {"view": "b", "mask_id": 1, "label": "pump", "score": 0.6},
        {"view": "c", "mask_id": 2, "label": "pipe", "score": 0.2},
        {"view": "d", "mask_id": 1, "label": "box", "score": 0.5},
    ]
    groups = np.array([0, 0, 0, 3])
    raw = np.full(400, -1)
    raw[:300], raw[300:310] = 0, 3
    assets, final = build_assets(positions, raw, records, groups, membership)
    assert len(assets) == 1
    asset = assets[0]
    assert asset["object_id"] == "obj-0001"
    assert asset["label"] == "pump"
    assert asset["label_confidence"] == 0.75
    assert asset["mapping"] is None
    assert asset["views"] == 3
    assert (final[:300] == 0).all() and (final[300:] == -1).all()
    assert all(a <= b for a, b in zip(asset["bbox_min"], asset["bbox_max"], strict=True))


def test_collect_membership_skips_structure_from_files(tmp_path):
    render = tmp_path / "render"
    (render / "depth").mkdir(parents=True)
    (tmp_path / "object_mask").mkdir()
    (tmp_path / "object_mask_json").mkdir()
    camera = intrinsics(20, 20, 90.0)
    matrix = world_to_camera(np.zeros(3), np.array([0.0, 0.0, 1.0]), UP)
    (render / "cameras.json").write_text(
        json.dumps(
            {
                "intrinsics": camera.tolist(),
                "cameras": [{"name": "v", "world_to_camera": matrix.tolist()}],
            }
        )
    )
    np.save(render / "depth" / "v.npy", np.full((20, 20), 2.0, dtype=np.float32))
    ids = np.zeros((20, 20), dtype=np.uint16)
    ids[8:12, 8:12] = 1
    ids[0:3, 0:3] = 2
    pil.fromarray(ids).save(tmp_path / "object_mask" / "v.png")
    info = {"1": {"label": "pump", "score": 0.5}, "2": {"label": "wall", "score": 0.9}}
    (tmp_path / "object_mask_json" / "v.json").write_text(json.dumps(info))
    positions = np.array([[0.0, 0.0, 2.0], [-2.0, -2.0, 2.0]])
    membership, records = collect_membership(positions, tmp_path, [render])
    assert [record["label"] for record in records] == ["pump"]
    assert membership.shape == (2, 1)
    assert membership[0, 0] == 1 and membership[1, 0] == 0
