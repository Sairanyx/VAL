import pytest

pytest.importorskip("numpy")

from app.copilot.mapping import apply_label_fixes, build_mapping, route_distance  # noqa: E402


def obj(object_id, label, x=0.0, mobility="fixed", mapping=None):
    return {
        "object_id": object_id,
        "label": "object",
        "suggested_label": label,
        "center": [x, 0.0, 0.0],
        "mobility": mobility,
        "mapping": mapping,
    }


def record(asset_id, asset_class, state="healthy"):
    return {
        "asset_id": asset_id,
        "tag": asset_id,
        "asset_class": asset_class,
        "condition_state": state,
    }


def test_each_record_gets_one_matching_object():
    assets = [obj("a", "valve"), obj("b", "valve"), obj("c", "pump")]
    records = [record("V1", "CONTROL_VALVE"), record("V2", "CONTROL_VALVE")]
    links = build_mapping(assets, records)
    assert {link["object_id"] for link in links} == {"a", "b"}
    assert all(link["method"] == "procedural_class" for link in links)


def test_existing_link_is_kept():
    target = {"asset_id": "P5", "tag": "P-005", "method": "manual", "confidence": 0.3}
    links = build_mapping(
        [obj("a", "pump", mapping=target), obj("b", "pump")], [record("P5", "PROCESS_PUMP")]
    )
    assert links == [{**target, "object_id": "a"}]


def test_healthy_record_goes_nearest_the_route():
    assets = [obj("far", "valve", x=9.0), obj("near", "valve", x=1.0)]
    records = [record("BAD", "CONTROL_VALVE", "degraded"), record("OK", "CONTROL_VALVE")]
    links = build_mapping(assets, records, route=[[0, 0, 0], [2, 0, 0]])
    assert {link["asset_id"]: link["object_id"] for link in links} == {"OK": "near", "BAD": "far"}


def test_exact_label_beats_similar_and_similar_is_marked():
    links = build_mapping([obj("fit", "pipe fitting")], [record("V1", "CONTROL_VALVE")])
    assert links[0]["method"] == "procedural_similar_class"
    assert links[0]["confidence"] == 0.15
    links = build_mapping(
        [obj("fit", "pipe fitting"), obj("valve", "valve", x=9.0)],
        [record("V1", "CONTROL_VALVE")],
        route=[[0, 0, 0]],
    )
    assert links[0]["object_id"] == "valve"


def test_movable_and_unreachable_objects_are_skipped():
    assets = [obj("cart", "valve", mobility="movable"), obj("high", "valve"), obj("ok", "valve")]
    stops = {"high": None, "ok": 1.5}
    links = build_mapping(
        assets, [record("V1", "CONTROL_VALVE")], stop_distance=lambda a: stops[a["object_id"]]
    )
    assert links[0]["object_id"] == "ok"


def test_close_object_beats_better_label_further_away():
    assets = [obj("far", "valve"), obj("near", "pipe fitting")]
    stops = {"far": 1.8, "near": 0.5}
    links = build_mapping(
        assets, [record("V1", "CONTROL_VALVE")], stop_distance=lambda a: stops[a["object_id"]]
    )
    assert links[0]["object_id"] == "near"


def test_no_suitable_object_means_no_link():
    assert build_mapping([obj("a", "pipe")], [record("V1", "CONTROL_VALVE")]) == []


def test_route_distance_measures_across_floor():
    assert route_distance([1, 5, 3], [[0, 0, 0], [2, 0, 0]], (0, 2)) == 3


def test_a_pump_record_never_lands_on_an_unrelated_type():
    links = build_mapping(
        [obj("w", "appliance"), obj("l", "light fixture")], [record("P1", "PROCESS_PUMP")]
    )
    assert links == []


def test_a_pump_record_can_go_on_a_motor():
    links = build_mapping([obj("m", "motor")], [record("P1", "PROCESS_PUMP")])
    assert links[0]["object_id"] == "m" and links[0]["method"] == "procedural_similar_class"


def test_earlier_procedural_links_are_made_again():
    old = {"asset_id": "P1", "tag": "P1", "method": "procedural_similar_class", "confidence": 0.15}
    links = build_mapping(
        [obj("wrong", "appliance", mapping=old), obj("right", "pump")],
        [record("P1", "PROCESS_PUMP")],
    )
    assert [link["object_id"] for link in links] == ["right"]


def test_a_type_fixed_by_eye_wins_over_model_guesses():
    asset = obj("a", "pump")  # the model said pump
    fixes = [{"object_id": "a", "center": [0.0, 0.0, 0.0], "label": "washing machine"}]
    assert apply_label_fixes([asset], fixes) == 1
    assert asset["label"] == "washing machine" and asset["label_was"] == "object"
    assert build_mapping([asset], [record("P1", "PROCESS_PUMP")]) == []


def test_a_fix_for_a_different_object_with_the_same_id_is_ignored():
    asset = obj("a", "pump", x=5.0)
    fixes = [{"object_id": "a", "center": [0.0, 0.0, 0.0], "label": "door"}]
    assert apply_label_fixes([asset], fixes) == 0
    assert asset["label"] == "object"


def test_a_reason_naming_the_old_type_is_replaced():
    asset = {**obj("a", "pipe"), "label": "pipe", "mobility_reason": "pipe is fixed equipment"}
    apply_label_fixes([asset], [{"object_id": "a", "center": [0.0, 0.0, 0.0], "label": "pump"}])
    assert "pipe" not in asset["mobility_reason"]


def test_a_specific_type_wins_over_other_model_guesses():
    pipe = {**obj("p", "valve"), "label": "pipe"}  # labelled pipe, but SAM said valve
    assert build_mapping([pipe], [record("V1", "CONTROL_VALVE")]) == []


def test_sam_labels_alone_never_link_a_record():
    fragment = {**obj("f", None), "sam_label": "valve"}
    del fragment["suggested_label"]
    assert build_mapping([fragment], [record("V1", "CONTROL_VALVE")]) == []
