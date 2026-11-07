import pytest

pytest.importorskip("numpy")

from app.extract.finalize import decide_mobility, finalize, geometry_problem, grade_label  # noqa: E402

TALL = {"height": 2.0, "bottom": 0.0, "top": 2.0, "longest": 2.0, "middle": 0.8, "shortest": 0.1}
SMALL = {"height": 0.3, "bottom": 0.0, "top": 0.3, "longest": 0.3, "middle": 0.3, "shortest": 0.3}


def asset(object_id, label, low, high):
    return {"object_id": object_id, "label": label, "bbox_min": low, "bbox_max": high}


def document(*assets):
    return {"up": [0, 1, 0], "floor_height_along_up": 0.0, "assets": list(assets)}


# A ceiling-height object and far walls, so room limits are predictable in these tests.
ROOM = [
    asset("room-a", "pipe", [-9, 0, -9], [-8, 3, -8]),
    asset("room-b", "pipe", [8, 0, 8], [9, 3, 9]),
]


def by_id(result, object_id):
    return next(item for item in result["assets"] if item["object_id"] == object_id)


def test_geometry_rejects_shapes_that_cannot_fit_the_label():
    assert "too small" in geometry_problem("tank", SMALL, 3.0)
    assert "long and thin" in geometry_problem("pipe", SMALL, 3.0)
    assert "too large" in geometry_problem("pump", TALL, 3.0)
    assert "too short" in geometry_problem("door", SMALL, 3.0)
    assert "ceiling" in geometry_problem("light fixture", SMALL, 3.0)
    assert geometry_problem("door", TALL, 3.0) is None
    assert geometry_problem("box", SMALL, 3.0) is None


def test_agreement_is_likely_and_disagreement_is_unsure():
    assert grade_label("box", "box", SMALL, 3.0)[1] == "likely"
    assert grade_label("pipe", "box", SMALL, 3.0)[1] == "unsure"
    assert grade_label("cabinet", "electrical cabinet", SMALL, 3.0)[1] == "likely"
    assert grade_label("box", "unknown", SMALL, 3.0)[1] == "unknown"
    assert grade_label("tank", "tank", SMALL, 3.0)[1] == "unsure"


def test_mobility_needs_both_label_and_geometry():
    assert decide_mobility("cart", "likely", SMALL, 0.0, 3.0, False)[0] == "movable"
    assert decide_mobility("cart", "unsure", SMALL, 0.0, 3.0, False)[0] == "unsure"
    assert decide_mobility("pipe", "likely", SMALL, 0.0, 3.0, False)[0] == "fixed"
    assert decide_mobility("cart", "likely", SMALL, 0.0, 3.0, True)[0] == "unsure"
    assert decide_mobility("cart", "likely", SMALL, 0.0, 0.35, False)[0] == "unsure"
    floating = {**SMALL, "bottom": 1.0, "top": 1.3}
    assert decide_mobility("cart", "likely", floating, 0.0, 3.0, False)[0] == "unsure"
    assert decide_mobility("other", "likely", SMALL, 0.0, 3.0, False)[0] == "unsure"


def test_unconfirmed_objects_show_as_object_and_keep_the_guess():
    item = asset("obj-1", "pipe", [0, 0, 0], [0.5, 0.5, 0.5])
    result = finalize(document(item, *ROOM), {"obj-1": {"label": "pump"}}, {})
    final = by_id(result, "obj-1")
    assert final["label"] == "object"
    assert final["suggested_label"] == "pump"
    assert final["label_grade"] == "unsure"
    assert final["sam_label"] == "pipe"
    assert final["mobility"] == "unsure"


def test_agreed_cart_in_open_floor_is_movable():
    item = asset("obj-1", "cart", [0, 0, 0], [0.5, 0.5, 0.5])
    final = by_id(finalize(document(item, *ROOM), {"obj-1": {"label": "cart"}}, {}), "obj-1")
    assert final["label"] == "cart"
    assert final["mobility"] == "movable"


def test_person_overrides_always_win():
    item = asset("obj-1", "pipe", [0, 0, 0], [0.5, 0.5, 0.5])
    overrides = {"obj-1": {"label": "pump", "mobility": "movable"}}
    final = by_id(finalize(document(item, *ROOM), {"obj-1": {"label": "box"}}, overrides), "obj-1")
    assert final["label"] == "pump"
    assert final["label_grade"] == "verified"
    assert final["mobility"] == "movable"


def test_ai_review_beats_models_but_not_a_person():
    item = asset("obj-1", "pipe", [0, 0, 0], [0.5, 0.5, 0.5])
    qwen = {"obj-1": {"label": "box"}}
    final = by_id(finalize(document(item, *ROOM), qwen, {}, ai_review={"obj-1": "pump"}), "obj-1")
    assert final["label"] == "pump"
    assert final["label_grade"] == "ai_reviewed"
    person = {"obj-1": {"label": "valve"}}
    final = by_id(
        finalize(document(item, *ROOM), qwen, person, ai_review={"obj-1": "pump"}), "obj-1"
    )
    assert final["label"] == "valve"
    assert final["label_grade"] == "verified"


def test_other_shows_as_object_and_unknown_review_is_ignored():
    item = asset("obj-1", "pipe", [0, 0, 0], [0.5, 0.5, 0.5])
    final = by_id(finalize(document(item, *ROOM), {}, {}, ai_review={"obj-1": "other"}), "obj-1")
    assert final["label"] == "object"
    assert final["suggested_label"] == "other"
    final = by_id(finalize(document(item, *ROOM), {}, {}, ai_review={"obj-1": "unknown"}), "obj-1")
    assert final["label_grade"] == "unknown"


def test_object_with_no_vision_reply_stays_unknown():
    item = asset("obj-1", "box", [0, 0, 0], [0.5, 0.5, 0.5])
    final = by_id(finalize(document(item, *ROOM), {}, {}), "obj-1")
    assert final["label"] == "object"
    assert final["label_grade"] == "unknown"
