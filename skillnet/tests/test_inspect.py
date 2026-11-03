import json

import pytest

from conftest import BLOCK_VOLUME, assert_error, run
from tools.inspect import inspect_design, measure_features


def test_design_lists_parameters_features_and_bodies(tmp_path, fx):
    env, outs = run(inspect_design, {"file": str(fx["block_sc"])}, tmp_path)
    assert env["status"] == "ok", env
    d = env["data"]
    assert d["file_kind"] == "design"
    assert {p["name"]: p["value"] for p in d["parameters"]} == pytest.approx(
        {"width": 40, "depth": 30, "height": 20, "hole_d": 10})
    types = [f["type"] for f in d["features"]]
    assert "ExtrudeFeature" in types and "HoleFeature" in types
    assert d["failing_features"] == []
    assert d["total_volume_mm3"] == pytest.approx(BLOCK_VOLUME, rel=0.005)
    assert d["bodies"][0]["center_of_mass"] == pytest.approx([0, 0, 10], abs=1e-3)
    assert d["sketches"] and d["sketches"][0]["status"] == "solved"
    assert "inspect.json" in outs


def test_step_gives_bodies_and_volume(tmp_path, fx):
    env, _ = run(inspect_design, {"file": str(fx["block_step"])}, tmp_path)
    assert env["status"] == "ok", env
    d = env["data"]
    assert d["file_kind"] == "cad"
    assert d["body_count"] == 1
    assert d["total_volume_mm3"] == pytest.approx(BLOCK_VOLUME, rel=0.005)
    assert d["bbox_mm"]["size"] == pytest.approx([40, 30, 20], abs=1e-3)
    assert d["parameters"] == []


def test_mesh_input_is_marked_as_mesh(tmp_path, fx):
    env, _ = run(inspect_design, {"file": str(fx["block_stl"])}, tmp_path)
    assert env["status"] == "ok", env
    assert env["data"]["file_kind"] == "mesh"
    assert env["data"]["bbox_mm"]["size"] == pytest.approx([40, 30, 20], abs=0.01)


def test_topology_gives_face_points_and_edge_midpoints(tmp_path, fx):
    env, outs = run(inspect_design, {"file": str(fx["block_sc"]), "detail": "topology"}, tmp_path)
    assert env["status"] == "ok", env
    topo = json.loads(outs["topology.json"].read_text())
    body = next(iter(topo.values()))
    bores = [f for f in body["faces"] if f.get("cylinder")]
    assert bores and bores[0]["cylinder"]["radius"] == pytest.approx(5)
    mids = [tuple(round(c, 3) for c in e["mid"]) for e in body["edges"]]
    assert (20.0, 15.0, 10.0) in mids  # a vertical corner edge of the 40x30x20 block
    assert env["data"]["topology"] is not None


def test_garbage_file_is_unreadable(tmp_path, fx):
    env, _ = run(inspect_design, {"file": str(fx["garbage_step"])}, tmp_path)
    assert_error(env, "unreadable_file")


def test_measure_hole_diameter(tmp_path, fx):
    env, _ = run(measure_features, {"file": str(fx["block_sc"]),
                                    "items": [{"kind": "face", "point": [5, 0, 10]}]}, tmp_path)
    assert env["status"] == "ok", env
    item = env["data"]["items"][0]
    assert item["diameter"] == pytest.approx(10, abs=0.01)
    assert item["center"][:2] == pytest.approx([0, 0], abs=1e-3)


def test_measure_distance_between_opposite_faces(tmp_path, fx):
    env, _ = run(measure_features, {"file": str(fx["block_step"]),
                                    "items": [{"kind": "face", "point": [0, 15, 10]},
                                              {"kind": "face", "point": [0, -15, 10]}]}, tmp_path)
    assert env["status"] == "ok", env
    assert env["data"]["min_distance_mm"] == pytest.approx(30, abs=1e-3)
    assert env["data"]["angle_deg"] == pytest.approx(180, abs=1e-3)


def test_measure_face_by_name(tmp_path, fx):
    env, _ = run(measure_features, {"file": str(fx["block_sc"]),
                                    "items": [{"kind": "face", "name": "F3:bore:side:0"}]}, tmp_path)
    assert env["status"] == "ok", env
    assert env["data"]["items"][0]["radius"] == pytest.approx(5, abs=0.01)


def test_measure_unknown_name(tmp_path, fx):
    env, _ = run(measure_features, {"file": str(fx["block_sc"]),
                                    "items": [{"kind": "face", "name": "F9:nothing"}]}, tmp_path)
    assert_error(env, "unknown_name")


def test_measure_pick_without_point_or_name(tmp_path, fx):
    env, _ = run(measure_features, {"file": str(fx["block_sc"]), "items": [{"kind": "edge"}]}, tmp_path)
    assert_error(env, "invalid_input")


def test_measure_refuses_meshes(tmp_path, fx):
    env, _ = run(measure_features, {"file": str(fx["block_stl"]),
                                    "items": [{"kind": "face", "point": [0, 0, 20]}]}, tmp_path)
    assert_error(env, "invalid_arguments")


def test_measure_hole_spacing_reports_centre_distance(tmp_path, two_hole_step):
    env, _ = run(measure_features, {"file": str(two_hole_step),
                                    "items": [{"kind": "face", "point": [16.35, 28.25, 3]},
                                              {"kind": "face", "point": [63.65, 28.25, 3]}]}, tmp_path)
    assert env["status"] == "ok", env
    d = env["data"]
    assert d["center_distance_mm"] == pytest.approx(47.3, abs=1e-3)
    assert d["min_distance_mm"] == pytest.approx(47.3 - 6.5, abs=1e-3)
    assert all(it["diameter"] == pytest.approx(6.5, abs=1e-3) for it in d["items"])
    assert "centre-to-centre distance 47.3 mm" in env["summary"]
