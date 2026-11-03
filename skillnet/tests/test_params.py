import math

import pytest
import trimesh

from conftest import assert_error, evaluate, run
from tools.params import change_parameters


def test_width_change_rebuilds_with_before_after(tmp_path, fx):
    env, outs = run(change_parameters, {"design": str(fx["block_sc"]), "changes": {"width": 70},
                                        "formats": ["stl", "step"]}, tmp_path)
    assert env["status"] == "ok", env
    d = env["data"]
    assert d["changed"][0]["name"] == "width"
    assert d["changed"][0]["old_value"] == pytest.approx(40)
    assert d["changed"][0]["new_value"] == pytest.approx(70)
    assert d["before"]["bbox_mm"]["size"][0] == pytest.approx(40, abs=1e-3)
    assert d["after"]["bbox_mm"]["size"] == pytest.approx([70, 30, 20], abs=1e-3)
    expected = 70 * 30 * 20 - math.pi * 25 * 20
    assert d["after"]["volume_mm3"] == pytest.approx(expected, rel=0.005)
    assert d["failing_features"] == []
    sc = [p for n, p in outs.items() if n.endswith(".sc")][0]
    assert sc.name == "block_v2.sc"
    assert evaluate(sc)["total"]["volume_mm3"] == pytest.approx(expected, rel=0.005)
    stl = [p for n, p in outs.items() if n.endswith(".stl")][0]
    assert trimesh.load(stl).extents[0] == pytest.approx(70, abs=0.01)


def test_units_and_expressions(tmp_path, fx):
    env, _ = run(change_parameters, {"design": str(fx["block_sc"]),
                                     "changes": {"height": "1 in", "hole_d": "height/4"},
                                     "formats": ["step"], "name": "inch"}, tmp_path)
    assert env["status"] == "ok", env
    d = env["data"]
    assert d["after"]["bbox_mm"]["size"][2] == pytest.approx(25.4, abs=1e-3)
    expected = 40 * 30 * 25.4 - math.pi * (25.4 / 8) ** 2 * 25.4
    assert d["after"]["volume_mm3"] == pytest.approx(expected, rel=0.005)


def test_unknown_parameter_lists_existing_names(tmp_path, fx):
    env, outs = run(change_parameters, {"design": str(fx["block_sc"]), "changes": {"widht": 70}}, tmp_path)
    assert_error(env, "unknown_parameter")
    assert "width" in env["error"]["message"]
    assert "inspect_design" in env["next_step"] or "create_missing" in env["next_step"]
    assert outs == {}


def test_create_missing_adds_a_parameter(tmp_path, fx):
    env, _ = run(change_parameters, {"design": str(fx["block_sc"]), "changes": {"lid": "3 mm"},
                                     "create_missing": True, "formats": ["step"]}, tmp_path)
    assert env["status"] == "ok", env
    assert env["data"]["changed"][0]["created"] is True
    assert "lid" in {p["name"] for p in env["data"]["parameters"]}
    assert env["data"]["after"]["volume_mm3"] == pytest.approx(env["data"]["before"]["volume_mm3"], rel=1e-6)


def test_change_that_breaks_a_feature_is_reported(tmp_path, fx):
    env, outs = run(change_parameters, {"design": str(fx["plate_sc"]), "changes": {"t": 2}}, tmp_path)
    assert_error(env, "rebuild_failed")
    assert "TopRound" in env["error"]["message"]
    assert outs == {}


def test_non_design_input_is_refused(tmp_path, fx):
    env, _ = run(change_parameters, {"design": str(fx["block_step"]), "changes": {"width": 50}}, tmp_path)
    assert_error(env, "invalid_arguments")


def test_empty_changes_is_invalid(tmp_path, fx):
    env, _ = run(change_parameters, {"design": str(fx["block_sc"]), "changes": {}}, tmp_path)
    assert_error(env, "invalid_input")
