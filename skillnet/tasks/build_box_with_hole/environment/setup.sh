#!/bin/bash
set -e
set -euo pipefail
mkdir -p /task/inputs /task/truth
python3 - <<'PY'
import json, math
vol = 40 * 30 * 20 - math.pi * 5 ** 2 * 20
json.dump({"volume_mm3": round(vol, 3), "extents_mm": [20, 30, 40]}, open("/task/truth/truth.json", "w"))
PY
