import pytest


def test_app_package_imports():
    import app  # noqa: F401


def test_torch_works():
    torch = pytest.importorskip("torch")
    assert torch.ones(2, 2).sum().item() == 4
