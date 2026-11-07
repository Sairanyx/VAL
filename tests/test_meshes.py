import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("PIL")

from app.extract.meshes import keep_largest_parts, voxel_size_for  # noqa: E402


def test_voxel_size_scales_with_the_object_but_has_a_floor():
    assert voxel_size_for(1.28) == pytest.approx(0.01)
    assert voxel_size_for(0.01) == 0.004


def test_keep_largest_parts_drops_small_floating_pieces():
    clusters = np.array([0, 0, 1, 2])
    areas = np.array([10.0, 0.1, 2.0])
    assert keep_largest_parts(clusters, areas, 0.05).tolist() == [True, True, False, True]


def test_keep_largest_parts_handles_an_empty_mesh():
    assert len(keep_largest_parts(np.zeros(0, dtype=int), np.zeros(0), 0.05)) == 0
