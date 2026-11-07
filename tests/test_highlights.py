import json

import pytest

np = pytest.importorskip("numpy")

from app.scene.highlights import export_highlights  # noqa: E402
from app.scene.load import Splats, read_splats  # noqa: E402


def scene():
    names = ["x", "y", "z", "opacity", "rot_0", "rot_1", "rot_2", "rot_3"]
    names += [f"scale_{i}" for i in range(3)] + [f"f_dc_{i}" for i in range(3)]
    data = np.zeros(4, dtype=[(name, "<f4") for name in names])
    data["x"] = [0, 1, 2, 3]
    data["rot_0"] = 1
    return Splats(data)


def test_exports_only_segmented_surface_preserving_source(tmp_path):
    original = scene()
    before = original.data.copy()
    assets = [{"object_id": "obj-1", "splats": 2}, {"object_id": "obj-2", "splats": 1}]
    result = export_highlights(original, assets, np.array([0, -1, 1, 0]), tmp_path)
    assert len(result) == 2
    subset = read_splats(tmp_path / "obj-1.ply")
    assert subset.positions[:, 0].tolist() == [0, 3]
    np.testing.assert_allclose(subset.base_colors, [[0.05, 0.9, 1]] * 2, atol=1e-6)
    np.testing.assert_array_equal(original.data, before)
    assert json.loads((tmp_path / "highlights.json").read_text()) == result


@pytest.mark.parametrize(
    "labels",
    [np.array([0]), np.array([0, 2, 0, 0]), np.array([0.0, 0.0, 0.0, 0.0])],
)
def test_rejects_mismatched_labels(tmp_path, labels):
    with pytest.raises(ValueError):
        export_highlights(scene(), [{"object_id": "obj-1", "splats": 4}], labels, tmp_path)


def test_rejects_wrong_asset_order_counts(tmp_path):
    with pytest.raises(ValueError, match="counts differ"):
        export_highlights(
            scene(), [{"object_id": "obj-1", "splats": 4}], np.array([0, 0, -1, 0]), tmp_path
        )
