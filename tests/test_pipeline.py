import importlib.util
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parent.parent
SPEC = importlib.util.spec_from_file_location("pipeline", ROOT / "scripts" / "pipeline.py")
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)
CONFIG_PATH = ROOT / "scenes" / "equipment_room.toml"
CONFIG = tomllib.loads(CONFIG_PATH.read_text())


def test_steps_run_in_an_order_where_each_has_its_inputs():
    names = [step.name for step in pipeline.plan(CONFIG, CONFIG_PATH)]
    for earlier, later in [("render", "masks"), ("masks", "objects"), ("objects", "labels")]:
        assert names.index(earlier) < names.index(later)
    assert names.index("grades") < names.index("floor") < names.index("route_check")


def test_every_step_uses_the_uncleaned_source_and_its_up_direction():
    steps = {step.name: step for step in pipeline.plan(CONFIG, CONFIG_PATH)}
    source = str(ROOT / CONFIG["source"])
    assert source in steps["render"].command
    assert "clean" not in " ".join(steps["floor"].command).lower()
    for name in ("render", "objects", "floor"):
        assert "--up" in steps[name].command


def test_a_different_scene_needs_only_a_different_config():
    other = {**CONFIG, "source": "rooms/other.ply", "output": "out/other", "up": [0.0, 0.0, 1.0]}
    step = pipeline.plan(other, CONFIG_PATH)[0]
    assert str(ROOT / "rooms/other.ply") in step.command
    assert step.command[-4:-2] != ["0.0", "-1.0"]
    assert "1.0" in step.command


def test_report_says_what_still_needs_a_person(tmp_path):
    objects = tmp_path / "objects"
    objects.mkdir()
    assets = [{"label_grade": "likely"}, {"label_grade": "unsure"}]
    (objects / "assets_final.json").write_text(json.dumps({"assets": assets}))
    summary = pipeline.report(CONFIG, tmp_path, {"render": 1.0})
    assert summary["objects"] == 2 and summary["grades"]["unsure"] == 1
    assert any("P-005" in need for need in summary["needs_a_person"])


def test_viewer_file_gets_floor_start_and_fault_tag(tmp_path):
    objects = tmp_path / "objects"
    objects.mkdir()
    document = {"floor_height_along_up": -1.2, "assets": []}
    (objects / "assets_final.json").write_text(json.dumps(document))
    written = pipeline.write_viewer_file(CONFIG, tmp_path)
    assert written["floor_y"] == 1.2  # This scene's up is -y, so y = 1.2 is below the origin.
    assert written["start"] == [0.0, 1.2, 0.0]
    assert written["fault_tag"] == "P-005"
    assert json.loads((tmp_path / "assets_viewer.json").read_text())["up"] == CONFIG["up"]


def test_viewer_file_works_for_a_scene_with_z_up(tmp_path):
    objects = tmp_path / "objects"
    objects.mkdir()
    (objects / "assets_final.json").write_text(
        json.dumps({"floor_height_along_up": 0.5, "assets": []})
    )
    written = pipeline.write_viewer_file({**CONFIG, "up": [0.0, 0.0, 1.0]}, tmp_path)
    assert written["floor_y"] == 0.5 and written["start"] == [0.0, 0.0, 0.5]
