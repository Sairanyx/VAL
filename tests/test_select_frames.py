import pytest

from scripts.select_frames import pick_sharpest


def test_picks_best_frame_from_each_window():
    assert pick_sharpest([1, 9, 2, 8, 3, 7], 3) == [1, 3, 5]


def test_returns_exact_count_of_unique_frames():
    picked = pick_sharpest(list(range(3352)), 1500)
    assert len(set(picked)) == 1500


def test_rejects_count_above_frame_total():
    with pytest.raises(ValueError):
        pick_sharpest([1, 2], 3)
