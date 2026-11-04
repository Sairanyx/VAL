import pytest

torch = pytest.importorskip("torch")


def test_torch_works():
    assert torch.ones(2, 2).sum().item() == 4
