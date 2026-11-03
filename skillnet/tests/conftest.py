"""Shared fixtures: every input is generated at test time with the real SolidCraft engine."""
import json
import math
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from skillnet_sdk import call_tool  # noqa: E402

BLOCK_VOLUME = 40 * 30 * 20 - math.pi * 5 ** 2 * 20  # 22429.2 (exact solid: 22429.465)

BLOCK_STEPS = [
    {"command": "parameters.add", "params": {"name": "width", "expression": "40 mm"}},
    {"command": "parameters.add", "params": {"name": "depth", "expression": "30 mm"}},
    {"command": "parameters.add", "params": {"name": "height", "expression": "20 mm"}},
    {"command": "parameters.add", "params": {"name": "hole_d", "expression": "10 mm"}},
    {"command": "sketch.create", "params": {"plane": "XY"}},
    {"command": "sketch.rectangle.center", "params": {"center": [0, 0], "corner": ["width/2", "depth/2"]}},
    {"command": "sketch.finish", "params": {}},
    {"command": "solid.extrude", "params": {"distance": "height"}},
    {"command": "solid.hole", "params": {"position": [0, 0, "height"], "diameter": "hole_d"}},
]

# 40x40 plate of thickness t (corner at origin) with a 4 mm round on one top edge: t=2 breaks the fillet.
PLATE_STEPS = [
    {"command": "parameters.add", "params": {"name": "t", "expression": "10 mm"}},
    {"command": "solid.box", "params": {"length": 40, "width": 40, "height": "t"}},
    {"command": "solid.fillet", "params": {"edges": [[20, 0, 10]], "radius": 4, "name": "TopRound"}},
]


def _env():
    env = dict(os.environ)
    env.setdefault("XDG_RUNTIME_DIR", "/tmp/xdg-tests")
    os.makedirs(env["XDG_RUNTIME_DIR"], exist_ok=True)
    return env


def cli(*args, check=True):
    p = subprocess.run(["solidcraft-cli", *map(str, args)], capture_output=True, text=True, timeout=120, env=_env())
    if check and p.returncode != 0:
        raise RuntimeError(f"solidcraft-cli {args} failed: {p.stderr[-800:]}")
    return p


def make(tmp: pathlib.Path, name: str, steps, *outs):
    script = tmp / f"{name}.json"
    script.write_text(json.dumps({"commands": steps}))
    args = ["run", script, "--save", tmp / f"{name}.sc"]
    for o in outs:
        args += ["--out", tmp / f"{name}{o}"]
    cli(*args)
    return tmp / f"{name}.sc"


def evaluate(path):
    return json.loads(cli("eval", path).stdout)


@pytest.fixture(scope="session")
def fx(tmp_path_factory):
    """Generated input files (built once per session)."""
    d = tmp_path_factory.mktemp("fx")
    files = {}
    files["block_sc"] = make(d, "block", BLOCK_STEPS, ".step", ".stl", ".3mf")
    files["block_step"] = d / "block.step"
    files["block_stl"] = d / "block.stl"
    files["block_3mf"] = d / "block.3mf"
    files["plate_sc"] = make(d, "plate", PLATE_STEPS)
    garbage = d / "broken.step"
    garbage.write_text("this is not a CAD file\n" * 20)
    files["garbage_step"] = garbage
    notes = d / "notes.txt"
    notes.write_text("hello")
    files["txt"] = notes
    return files


def run(fn, args, tmp_path, **kw):
    """Call a tool in-process and return (envelope dict, {output name: path})."""
    env = call_tool(fn, args, output_root=tmp_path, **kw).model_dump()
    outs = {o["name"]: pathlib.Path(o["path"]) for o in env.get("outputs") or []}
    return env, outs


def assert_error(env, code):
    assert env["status"] == "error", env
    assert env["error"]["code"] == code, env["error"]
    assert env.get("next_step"), "every expected failure must say what to do next"


PLATE2_STEPS = [
    {"command": "solid.box", "params": {"length": 80, "width": 50, "height": 6}},
    {"command": "solid.hole", "params": {"position": [16.35, 25, 6], "diameter": 6.5}},
    {"command": "solid.hole", "params": {"position": [63.65, 25, 6], "diameter": 6.5}},
]


@pytest.fixture(scope="session")
def two_hole_step(tmp_path_factory):
    d = tmp_path_factory.mktemp("plate2")
    script = d / "p.json"
    script.write_text(json.dumps({"commands": PLATE2_STEPS}))
    cli("run", script, "--out", d / "mount_plate.step")
    return d / "mount_plate.step"
