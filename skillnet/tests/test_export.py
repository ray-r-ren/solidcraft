import pytest
import trimesh

from conftest import BLOCK_VOLUME, assert_error, evaluate, run
from tools.export import export_model


def test_design_exports_print_ready_meshes_and_cad(tmp_path, fx):
    env, outs = run(export_model, {"file": str(fx["block_sc"]), "formats": ["3mf", "stl", "step"],
                                   "name": "bracket"}, tmp_path)
    assert env["status"] == "ok", env
    d = env["data"]
    assert d["print_ready"] is True and d["print_problems"] == []
    assert d["brep_volume_mm3"] == pytest.approx(BLOCK_VOLUME, rel=0.005)
    assert {f["file"] for f in d["files"]} == {"bracket.3mf", "bracket.stl", "bracket.step"}
    for mc in d["mesh_checks"]:
        assert mc["watertight"] and mc["winding_consistent"] and mc["shells"] == 1
        assert mc["volume_diff_pct"] < 0.5
        assert mc["bbox_mm"]["size"] == pytest.approx([40, 30, 20], abs=0.01)
    assert d["cad_checks"][0]["reopens"] is True
    m = trimesh.load(outs["bracket.3mf"], force="mesh")
    assert m.is_watertight and m.volume == pytest.approx(BLOCK_VOLUME, rel=0.005)
    assert evaluate(outs["bracket.step"])["total"]["volume_mm3"] == pytest.approx(BLOCK_VOLUME, rel=0.005)


def test_fine_quality_is_closer_to_the_solid(tmp_path, fx):
    std, _ = run(export_model, {"file": str(fx["block_sc"]), "formats": ["stl"], "name": "std"}, tmp_path)
    fine, outs = run(export_model, {"file": str(fx["block_sc"]), "formats": ["stl", "obj"], "quality": "finest",
                                    "name": "fine"}, tmp_path)
    assert fine["status"] == "ok", fine
    d_std = std["data"]["mesh_checks"][0]["volume_diff_pct"]
    d_fine = [m for m in fine["data"]["mesh_checks"] if m["format"] == "stl"][0]["volume_diff_pct"]
    assert d_fine <= d_std
    assert fine["data"]["print_ready"] is True
    assert "fine.obj" in outs


def test_iges_and_step_only_still_checks_a_mesh(tmp_path, fx):
    env, outs = run(export_model, {"file": str(fx["block_sc"]), "formats": ["iges", "step"]}, tmp_path)
    assert env["status"] == "ok", env
    assert {"block.iges", "block.step"} <= set(outs)
    assert env["data"]["mesh_checks"], "a check mesh is always made"
    assert all(c["reopens"] for c in env["data"]["cad_checks"])
    assert not any(n.endswith(".stl") for n in outs)


def test_mesh_input_converts_between_mesh_formats(tmp_path, fx):
    env, outs = run(export_model, {"file": str(fx["block_stl"]), "formats": ["3mf"]}, tmp_path)
    assert env["status"] == "ok", env
    assert env["data"]["brep_volume_mm3"] is None
    assert env["data"]["mesh_checks"][0]["watertight"]
    assert any("mesh" in u for u in env["uncertain"])


def test_mesh_to_step_is_refused(tmp_path, fx):
    env, outs = run(export_model, {"file": str(fx["block_stl"]), "formats": ["step"]}, tmp_path)
    assert_error(env, "mesh_to_cad")
    assert "stl" in env["next_step"] and outs == {}


def test_non_cad_file_is_refused(tmp_path, fx):
    env, _ = run(export_model, {"file": str(fx["txt"])}, tmp_path)
    assert_error(env, "invalid_arguments")


def test_garbage_cad_file_is_unreadable(tmp_path, fx):
    env, _ = run(export_model, {"file": str(fx["garbage_step"])}, tmp_path)
    assert_error(env, "unreadable_file")
