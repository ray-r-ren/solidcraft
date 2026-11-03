#!/bin/bash
set -uo pipefail
python3 - <<'PY'
import json, pathlib, re, sys
import trimesh

t = json.load(open("/task/truth/truth.json"))
V = t["volume_mm3"]
out = pathlib.Path("/task/outputs")
ok = False
for p in out.rglob("*.3mf"):
    try:
        m = trimesh.load(str(p), force="mesh")
    except Exception as exc:
        print("cannot read", p.name, exc); continue
    ext = sorted(float(x) for x in m.extents)
    if m.is_watertight and all(abs(a - b) <= 0.2 for a, b in zip(ext, sorted(t["size_mm"]))) \
            and abs(m.volume - V) / V <= 0.01:
        ok = True
if not ok:
    print("FAIL: no watertight 3MF of 60x40x25 mm with volume within 1%% of %.0f mm3" % V); sys.exit(1)
ans = pathlib.Path("/task/answer.txt")
text = ans.read_text(errors="ignore").lower() if ans.exists() else ""
neg = re.search(r"(not|n't)\s+(yet\s+)?(print[- ]?ready|ready (to|for) print)", text)
pos = re.search(r"print[- ]?ready|ready to print|watertight|closed", text)
if not pos or neg:
    print("FAIL: the answer does not say the part is print-ready"); sys.exit(1)
print("PASS")
PY
