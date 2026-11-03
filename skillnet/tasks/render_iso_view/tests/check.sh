#!/bin/bash
set -uo pipefail
python3 - <<'PY'
import pathlib, re, sys
from PIL import Image, ImageStat

out = pathlib.Path("/task/outputs")
good = []
for p in out.rglob("*.png"):
    try:
        im = Image.open(p).convert("L")
    except Exception:
        continue
    w, h = im.size
    sd = ImageStat.Stat(im).stddev[0]
    if w >= 256 and h >= 256 and sd > 5:
        good.append(p.name)
if not good:
    print("FAIL: no non-blank PNG picture of at least 256x256 px in the outputs"); sys.exit(1)
ans = pathlib.Path("/task/answer.txt")
text = ans.read_text(errors="ignore").lower() if ans.exists() else ""
if not re.search(r"hole|bore|disc|disk|ring|round|circular|flange", text):
    print("FAIL: the answer does not describe the part"); sys.exit(1)
print("PASS", good)
PY
