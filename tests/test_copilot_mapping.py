import pytest

pytest.importorskip("numpy")

from app.copilot.mapping import build_mapping, route_distance  # noqa: E402


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
