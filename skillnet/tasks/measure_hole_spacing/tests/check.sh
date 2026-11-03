#!/bin/bash
set -uo pipefail
python3 - <<'PY'
import json, pathlib, re, sys

t = json.load(open("/task/truth/truth.json"))
ans = pathlib.Path("/task/answer.txt")
text = ans.read_text(errors="ignore") if ans.exists() else ""
nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]
if not any(abs(n - t["diameter_mm"]) <= 0.02 for n in nums):
    print("FAIL: hole diameter %.2f mm not in the answer" % t["diameter_mm"]); sys.exit(1)
if not any(abs(n - t["center_distance_mm"]) <= 0.02 for n in nums):
    print("FAIL: centre distance %.2f mm not in the answer" % t["center_distance_mm"]); sys.exit(1)
print("PASS")
PY
