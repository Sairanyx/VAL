import json

import pytest

np = pytest.importorskip("numpy")
pil = pytest.importorskip("PIL.Image")

from app.extract.label_vlm import (  # noqa: E402
    focus_crop,
    list_crops,
    mask_box,
    parse_answer,
    sample_evenly,
)


def test_parse_answer_reads_json_inside_other_text():
    reply = (
        '<think>hmm</think>```json\n{"label": "Pump", "confidence": 0.8, "description": "x"}\n```'
    )
    answer = parse_answer(reply)
    assert answer["label"] == "pump"
    assert answer["confidence"] == 0.8
    assert answer["visible_text"] == ""


@pytest.mark.parametrize(
    "reply",
    ["not json", '{"label": "spaceship", "confidence": 1}', "{broken", "[1, 2]", ""],
)
def test_parse_answer_never_accepts_unusable_replies(reply):
    answer = parse_answer(reply)
    assert answer["label"] == "unknown"
    assert answer["confidence"] == 0.0


def test_parse_answer_clamps_and_tolerates_bad_confidence():
    assert parse_answer('{"label": "valve", "confidence": 7}')["confidence"] == 1.0
    assert parse_answer('{"label": "valve", "confidence": "high"}')["confidence"] == 0.0


def test_mask_box_adds_margin_and_stays_inside_the_image():
    mask = np.zeros((100, 100), dtype=bool)
    mask[0:10, 90:100] = True
    left, top, right, bottom = mask_box(mask)
    assert (top, right) == (0, 100)
    assert left < 90 and bottom > 10


def test_focus_crop_dims_only_the_surroundings_and_enlarges_small_crops():
    image = np.full((100, 100, 3), 200, dtype=np.uint8)
    mask = np.zeros((100, 100), dtype=bool)
    mask[40:60, 40:60] = True
    crop = focus_crop(image, mask, (30, 30, 70, 70))
    assert max(crop.size) == 448
    pixels = np.array(crop)
    assert pixels[224, 224, 0] == 200
    assert pixels[5, 5, 0] < 100


def write_scene(root, ids, info):
    for name in ("images", "object_mask", "object_mask_json"):
        (root / name).mkdir()
    pil.fromarray(ids.astype(np.uint16)).save(root / "object_mask" / "v.png")
    (root / "object_mask_json" / "v.json").write_text(json.dumps(info))


def test_list_crops_skips_structure_and_small_or_huge_masks(tmp_path):
    ids = np.zeros((100, 100), dtype=np.uint16)
    ids[:60, :] = 1  # 60% of the image: too large.
    ids[60:70, :] = 2  # 10%: a wall.
    ids[70:80, :] = 3  # 10%: kept.
    ids[99, 99] = 4  # One pixel: too small.
    info = {
        "1": {"label": "pipe", "score": 0.5},
        "2": {"label": "wall", "score": 0.9},
        "3": {"label": "sam2", "score": 0.4},
        "4": {"label": "pipe", "score": 0.5},
    }
    write_scene(tmp_path, ids, info)
    crops = list_crops(tmp_path)
    assert [crop.mask_id for crop in crops] == [3]
    assert crops[0].sam_label == "sam2"


def test_object_crops_uses_one_crop_per_view_up_to_the_limit(tmp_path):
    from app.extract.label_objects import object_crops

    (tmp_path / "images").mkdir()
    (tmp_path / "object_mask").mkdir()
    for name in ("a", "b", "c"):
        pil.fromarray(np.zeros((50, 50, 3), dtype=np.uint8)).save(
            tmp_path / "images" / f"{name}.jpg"
        )
        ids = np.zeros((50, 50), dtype=np.uint16)
        ids[10:20, 10:20] = 1
        pil.fromarray(ids).save(tmp_path / "object_mask" / f"{name}.png")
    sources = [
        {"view": "a", "mask_id": 1},
        {"view": "a", "mask_id": 1},
        {"view": "b", "mask_id": 1},
        {"view": "c", "mask_id": 1},
    ]
    assert len(object_crops({"source_masks": sources}, tmp_path, views=2)) == 2
    assert len(object_crops({"source_masks": sources}, tmp_path, views=9)) == 3


def test_object_prompt_formats_with_real_json_braces():
    from app.extract.label_objects import PROMPT

    text = PROMPT.format(count=3)
    assert "from 3 different" in text
    assert '{"label": "..."' in text


def test_sample_evenly_spans_the_list():
    assert sample_evenly([1, 2, 3, 4, 5], 2) == [1, 5]
    assert sample_evenly([1, 2], None) == [1, 2]
