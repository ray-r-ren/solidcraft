import json

import pytest
import trimesh

from conftest import BLOCK_STEPS, BLOCK_VOLUME, assert_error, evaluate, run
from tools.build import build_part


def test_block_with_hole_measures_and_exports(tmp_path):
    env, outs = run(build_part, {"steps": BLOCK_STEPS, "name": "block"}, tmp_path)
    assert env["status"] == "ok", env
    d = env["data"]
    assert d["total_volume_mm3"] == pytest.approx(BLOCK_VOLUME, rel=0.005)
    assert d["bbox_mm"]["size"] == pytest.approx([40, 30, 20], abs=1e-3)
    assert {p["name"] for p in d["parameters"]} == {"width", "depth", "height", "hole_d"}
    assert all(f["error"] is None for f in d["features"])
    assert {"block.sc", "block.step", "block.stl", "block.3mf", "results.json"} <= set(outs)
    # the design and the STEP re-open in the engine with the same volume
    for f in ("block.sc", "block.step"):
        ev = evaluate(outs[f])
        assert ev["total"]["volume_mm3"] == pytest.approx(d["total_volume_mm3"], rel=1e-4)
    # the STL is a closed printable mesh of the same size
    m = trimesh.load(outs["block.stl"])
    assert m.is_watertight
    assert m.volume == pytest.approx(BLOCK_VOLUME, rel=0.005)
    m3 = trimesh.load(outs["block.3mf"], force="mesh")
    assert m3.extents == pytest.approx([40, 30, 20], abs=0.01)
    results = json.loads(outs["results.json"].read_text())
    assert len(results) == len(BLOCK_STEPS)


def test_steps_accept_json_string_and_commands_wrapper(tmp_path):
    steps = json.dumps({"commands": [{"command": "solid.box", "params": {"length": 20, "width": 10, "height": 5}}]})
    env, outs = run(build_part, {"steps": steps, "name": "small", "formats": ["obj"]}, tmp_path)
    assert env["status"] == "ok", env
    assert env["data"]["total_volume_mm3"] == pytest.approx(1000, rel=1e-6)
    # solid.box puts its corner at the origin
    assert env["data"]["bbox_mm"]["min"] == pytest.approx([0, 0, 0], abs=1e-6)
    assert "small.obj" in outs and "small.step" not in outs


def test_start_from_adds_a_fillet_to_an_earlier_design(tmp_path, fx):
    before = evaluate(fx["block_sc"])["total"]["volume_mm3"]
    steps = [{"command": "solid.fillet",
              "params": {"edges": [[20, 15, 10], [-20, 15, 10], [20, -15, 10], [-20, -15, 10]], "radius": 3}}]
    env, outs = run(build_part, {"steps": steps, "start_from": str(fx["block_sc"]), "name": "rounded"}, tmp_path)
    assert env["status"] == "ok", env
    d = env["data"]
    # four vertical edges rounded with r=3: removes 4*(1-pi/4)*9*20 mm^3
    assert before - d["total_volume_mm3"] == pytest.approx(4 * (1 - 3.14159265 / 4) * 9 * 20, rel=0.01)
    # earlier parameters survive
    assert "width" in {p["name"] for p in d["parameters"]}


def test_unknown_command_names_the_step(tmp_path):
    steps = BLOCK_STEPS[:4] + [{"command": "solid.boxx", "params": {"length": 1, "width": 1, "height": 1}}]
    env, outs = run(build_part, {"steps": steps}, tmp_path)
    assert_error(env, "step_failed")
    assert "steps[4]" in env["error"]["message"] and "solid.boxx" in env["error"]["message"]
    assert "find_cad_commands" in env["next_step"]
    assert outs == {}


def test_misspelled_parameter_key_is_rejected(tmp_path):
    steps = [{"command": "sketch.create", "params": {"plane": "XY"}},
             {"command": "sketch.circle.center", "params": {"centre": [0, 0], "diameter": 10}}]
    env, _ = run(build_part, {"steps": steps}, tmp_path)
    assert_error(env, "step_failed")
    assert "steps[1]" in env["error"]["message"]


def test_too_large_fillet_reports_largest_radius(tmp_path):
    steps = [{"command": "solid.box", "params": {"length": 40, "width": 40, "height": 4}},
             {"command": "solid.fillet", "params": {"edges": [[20, 0, 4]], "radius": 6}}]
    env, _ = run(build_part, {"steps": steps}, tmp_path)
    assert_error(env, "step_failed")
    assert "largest radius that fits is 4 mm" in env["error"]["message"]


def test_reduced_fillet_warning_goes_to_uncertain(tmp_path):
    steps = [{"command": "solid.box", "params": {"length": 40, "width": 40, "height": 4}},
             {"command": "solid.fillet", "params": {"edges": [[20, 0, 4]], "radius": 6, "fit": "reduce"}}]
    env, _ = run(build_part, {"steps": steps, "formats": ["step"]}, tmp_path)
    assert env["status"] == "ok"
    assert any("reduced to 4 mm" in u for u in env["uncertain"]), env["uncertain"]


def test_malformed_json_is_invalid_input(tmp_path):
    env, _ = run(build_part, {"steps": "[{\"command\": \"solid.box\", "}, tmp_path)
    assert_error(env, "invalid_input")


def test_file_commands_are_refused(tmp_path):
    steps = [{"command": "file.export_stl", "params": {"path": "/etc/passwd"}}]
    env, _ = run(build_part, {"steps": steps}, tmp_path)
    assert_error(env, "invalid_steps")


def test_wrong_start_from_type_is_refused(tmp_path, fx):
    env, _ = run(build_part, {"steps": BLOCK_STEPS, "start_from": str(fx["txt"])}, tmp_path)
    assert env["status"] == "error"
