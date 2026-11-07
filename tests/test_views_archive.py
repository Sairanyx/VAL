import json
import tarfile

import pytest

np = pytest.importorskip("numpy")

from scripts.views_archive import compress_depth, pack, unpack  # noqa: E402


def make_set(root, name):
    (root / name / "views").mkdir(parents=True)
    (root / name / "depth").mkdir()
    (root / name / "cameras.json").write_text(json.dumps({"views": 1}))
    (root / name / "views" / "view_00000.jpg").write_bytes(b"jpeg bytes")
    depth = np.array([[0.0, 1.2345], [5.4286, 0.0]], dtype=np.float32)
    np.save(root / name / "depth" / "view_00000.npy", depth)
    return depth


def test_pack_then_unpack_restores_files_within_a_millimetre(tmp_path):
    depth = make_set(tmp_path / "in", "render")
    make_set(tmp_path / "in", "render_detail")
    archive = tmp_path / "views.tar"
    pack(tmp_path / "in", archive, ["render", "render_detail"])
    unpack(archive, tmp_path / "out")

    for name in ["render", "render_detail"]:
        root = tmp_path / "out" / name
        restored = np.load(root / "depth" / "view_00000.npy")
        assert restored.dtype == np.float32
        np.testing.assert_allclose(restored, depth, atol=0.0006)
        assert restored[0, 0] == 0
        assert (root / "views" / "view_00000.jpg").read_bytes() == b"jpeg bytes"
        assert json.loads((root / "cameras.json").read_text()) == {"views": 1}
        assert not list(root.glob("depth/*.npz"))


def test_unpack_rejects_paths_outside_the_target(tmp_path):
    source = tmp_path / "evil.txt"
    source.write_text("x")
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as tar:
        tar.add(source, arcname="../evil.txt")
    with pytest.raises(ValueError, match="Unsafe path"):
        unpack(archive, tmp_path / "out")


def test_depth_too_large_to_store_is_rejected():
    with pytest.raises(ValueError, match="too large"):
        compress_depth(np.array([70.0], dtype=np.float32))
