#!/bin/bash
set -uo pipefail
python3 - <<'PY'
import json, pathlib, re, sys

t = json.load(open("/task/truth/truth.json"))
V = t["volume_mm3"]
ans = pathlib.Path("/task/answer.txt")
text = ans.read_text(errors="ignore") if ans.exists() else ""
text = re.sub(r"(?<=\d)[,\u202f\u2009](?=\d{3}\b)", "", text)
nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]
def has(v, tol):
    return any(abs(n - v) <= tol for n in nums)
missing = [s for s in t["size_mm"] if not has(s, 0.5)]
if missing:
    print("FAIL: size numbers missing from the answer:", missing); sys.exit(1)
cm3 = V / 1000.0
if not (has(cm3, cm3 * 0.01) or has(V, V * 0.01)):
    print("FAIL: volume %.2f cm3 (%.0f mm3) not in the answer" % (cm3, V)); sys.exit(1)
print("PASS")
PY
