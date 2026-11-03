#!/bin/bash
set -uo pipefail
export XDG_RUNTIME_DIR=/tmp/xdg-check; mkdir -p "$XDG_RUNTIME_DIR"
python3 - <<'PY'
import json, pathlib, re, subprocess, sys
import trimesh

truth = json.load(open("/task/truth/truth.json"))
V = truth["volume_mm3"]
out = pathlib.Path("/task/outputs")
def files(*exts):
    return [p for p in out.rglob("*") if p.is_file() and p.suffix.lower() in exts]
def fail(msg):
    print("FAIL:", msg); sys.exit(1)
def ev(p):
    r = subprocess.run(["solidcraft-cli", "eval", str(p)], capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout) if r.returncode == 0 else None

# STL: closed mesh, right size and volume (the hole must be there)
ok_stl = False
for p in files(".stl"):
    m = trimesh.load(str(p), force="mesh")
    ext = sorted(float(x) for x in m.extents)
    if m.is_watertight and all(abs(a - b) <= 0.2 for a, b in zip(ext, truth["extents_mm"])) \
            and abs(m.volume - V) / V <= 0.01:
        ok_stl = True
if not ok_stl:
    fail("no watertight STL of 40x30x20 mm with volume within 1%% of %.1f mm3" % V)

# STEP: a real solid with the same volume
ok_step = False
for p in files(".step", ".stp"):
    d = ev(p)
    if d and d.get("total", {}).get("volume_mm3") and abs(d["total"]["volume_mm3"] - V) / V <= 0.01:
        ok_step = True
if not ok_step:
    fail("no STEP file that opens as a solid with the expected volume")

# Editable design with named parameters
ok_sc = False
for p in files(".sc", ".solidcraft"):
    d = ev(p)
    if d and abs((d.get("total", {}).get("volume_mm3") or 0) - V) / V <= 0.01:
        user = [q for q in d.get("params", []) if not q.get("model")]
        if user:
            ok_sc = True
if not ok_sc:
    fail("no editable design (.sc) with named parameters and the expected volume")

# The answer states the volume (mm3 or cm3)
ans = pathlib.Path("/task/answer.txt")
text = ans.read_text(errors="ignore") if ans.exists() else ""
nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", re.sub(r"(?<=\d)[,\u202f\u2009 ](?=\d{3}\b)", "", text))]
if not any(abs(n - V) / V <= 0.01 or abs(n - V / 1000) / (V / 1000) <= 0.01 for n in nums):
    fail("the answer does not state the volume (about %.0f mm3 / %.2f cm3)" % (V, V / 1000))
print("PASS")
PY
