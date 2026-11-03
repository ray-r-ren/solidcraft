import pytest
from PIL import Image

import tools.render as render_mod
from conftest import assert_error, run
from tools.render import render_views


def test_iso_and_front_views_are_real_pictures(tmp_path, fx):
    env, outs = run(render_views, {"file": str(fx["block_sc"]), "views": ["iso", "front"],
                                   "width": 640, "height": 480}, tmp_path)
    assert env["status"] == "ok", env
    d = env["data"]
    assert [v["view"] for v in d["views"]] == ["iso", "front"]
    assert d["renderer_used"].startswith("solidcraft")
    for v in d["views"]:
        img = Image.open(outs[v["file"]])
        assert img.size == (640, 480)
        assert v["pixel_stddev"] > 5, v  # not a blank frame
    assert d["contact_sheet"] in outs


def test_iso_and_top_differ(tmp_path, fx):
    env, outs = run(render_views, {"file": str(fx["block_step"]), "views": ["iso", "top"], "grid": False,
                                   "width": 320, "height": 256}, tmp_path)
    assert env["status"] == "ok", env
    a = Image.open(outs[env["data"]["views"][0]["file"]]).convert("L").tobytes()
    b = Image.open(outs[env["data"]["views"][1]["file"]]).convert("L").tobytes()
    assert a != b


def test_mesh_files_render(tmp_path, fx):
    env, outs = run(render_views, {"file": str(fx["block_3mf"]), "views": ["iso"]}, tmp_path)
    assert env["status"] == "ok", env
    assert env["data"]["views"][0]["pixel_stddev"] > 5


def test_fallback_render_when_engine_renderer_fails(tmp_path, fx, monkeypatch):
    monkeypatch.setattr(render_mod, "_engine_snapshot", lambda *a, **k: None)
    env, outs = run(render_views, {"file": str(fx["block_sc"]), "views": ["iso", "top"],
                                   "width": 400, "height": 300}, tmp_path)
    assert env["status"] == "ok", env
    assert env["data"]["renderer_used"] == "fallback"
    assert any("simpler shaded mesh" in u for u in env["uncertain"])
    for v in env["data"]["views"]:
        img = Image.open(outs[v["file"]])
        assert img.size == (400, 300)
        assert v["pixel_stddev"] > 5


def test_unreadable_file(tmp_path, fx):
    env, _ = run(render_views, {"file": str(fx["garbage_step"])}, tmp_path)
    assert_error(env, "unreadable_file")


def test_size_limits(tmp_path, fx):
    env, _ = run(render_views, {"file": str(fx["block_sc"]), "width": 100}, tmp_path)
    assert_error(env, "invalid_arguments")
