import pytest

np = pytest.importorskip("numpy")

from app.scene.load import read_splats, write_splats  # noqa: E402
from app.scene.train_splat import drop_blurriest, split_frames, to_splats  # noqa: E402


def test_split_holds_out_every_eighth_frame_in_sorted_order():
    names = [f"f{index:02d}.jpg" for index in range(16)][::-1]
    train, test = split_frames(names)
    assert test == ["f00.jpg", "f08.jpg"]
    assert len(train) == 14
    assert not set(train) & set(test)


def test_drop_blurriest_removes_lowest_sharpness(tmp_path):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("file,source_frame,sharpness\na,0,10\nb,1,500\nc,2,50\nd,3,300\n")
    assert drop_blurriest(["a", "b", "c", "d"], manifest, 0.5) == ["b", "d"]


def test_trained_values_write_a_file_the_loader_reads(tmp_path):
    means = np.arange(6, dtype=np.float32).reshape(2, 3)
    scales = np.full((2, 3), -4.0)
    quats = np.array([[1.0, 0, 0, 0], [0, 1.0, 0, 0]])
    opacities = np.array([2.0, -2.0])
    sh0 = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
    shn = np.zeros((2, 15, 3))
    shn[0, 0] = [1.0, 2.0, 3.0]  # First coefficient for red, green, and blue.
    shn[0, 14, 2] = 9.0  # Last coefficient for blue.
    splats = to_splats(means, scales, quats, opacities, sh0, shn)
    write_splats(splats, tmp_path / "scene.ply")
    loaded = read_splats(tmp_path / "scene.ply")
    assert len(loaded) == 2
    np.testing.assert_allclose(loaded.positions, means)
    np.testing.assert_allclose(loaded.quaternions, quats)
    data = loaded.data
    assert (data["f_rest_0"][0], data["f_rest_15"][0], data["f_rest_30"][0]) == (1.0, 2.0, 3.0)
    assert data["f_rest_44"][0] == 9.0
    assert data["f_dc_2"][1] == pytest.approx(0.6)


def test_ssim_loss_is_near_zero_for_identical_images_and_higher_otherwise():
    torch = pytest.importorskip("torch")
    from app.scene.train_splat import ssim_loss

    image = torch.rand(32, 32, 3)
    assert ssim_loss(image, image) == pytest.approx(0.0, abs=1e-5)
    assert ssim_loss(image, torch.rand(32, 32, 3)) > 0.5
