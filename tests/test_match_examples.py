import pytest

np = pytest.importorskip("numpy")

from app.extract.match_examples import cross_validate, knn_predict  # noqa: E402


def blobs():
    random = np.random.default_rng(0)
    pumps = random.normal([1, 0, 0], 0.05, (20, 3))
    pipes = random.normal([0, 1, 0], 0.05, (20, 3))
    return np.vstack([pumps, pipes]), ["pump"] * 20 + ["pipe"] * 20


def test_knn_returns_the_nearest_label_and_a_share():
    features, labels = blobs()
    guessed, shares = knn_predict(features, labels, np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]))
    assert guessed == ["pump", "pipe"]
    assert shares.min() > 0.9


def test_cross_validation_predicts_every_object_from_other_objects():
    features, labels = blobs()
    predictions, _ = cross_validate(features, labels)
    assert predictions == labels


def test_cross_validation_never_trains_on_unknown():
    features, labels = blobs()
    labels[:5] = ["unknown"] * 5
    predictions, _ = cross_validate(features, labels)
    assert "unknown" not in predictions
