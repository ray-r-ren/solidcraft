#!/bin/bash
set -uo pipefail
export XDG_RUNTIME_DIR=/tmp/xdg-check; mkdir -p "$XDG_RUNTIME_DIR"
python3 - <<'PY'
import json, pathlib, subprocess, sys
import trimesh

t = json.load(open("/task/truth/truth.json"))
V = t["volume_mm3"]
out = pathlib.Path("/task/outputs")
def files(*exts):
    return [p for p in out.rglob("*") if p.is_file() and p.suffix.lower() in exts]
def fail(msg):
    print("FAIL:", msg); sys.exit(1)

ok_stl = False
for p in files(".stl"):
    m = trimesh.load(str(p), force="mesh")
    if m.is_watertight and all(abs(a - b) <= 0.1 for a, b in zip(m.extents, t["size_mm"])) \
            and abs(m.volume - V) / V <= 0.01:
        ok_stl = True
if not ok_stl:
    fail("no watertight STL of 70x30x20 mm (X x Y x Z) with volume within 1%% of %.1f" % V)

ok_sc = False
for p in files(".sc", ".solidcraft"):
    r = subprocess.run(["solidcraft-cli", "eval", str(p)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        continue
    d = json.loads(r.stdout)
    width = [q for q in d.get("params", []) if q.get("name") == "width"]
    b = d["bodies"][0]["bbox"] if d.get("bodies") else None
    if width and abs(width[0]["value"] - 70) <= 1e-6 and b and abs((b["max"][0] - b["min"][0]) - 70) <= 0.1 \
            and abs(d["total"]["volume_mm3"] - V) / V <= 0.01:
        ok_sc = True
if not ok_sc:
    fail("no updated design whose width parameter is 70 mm and whose body is 70 mm wide")
print("PASS")
PY
