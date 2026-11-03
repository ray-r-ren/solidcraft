#!/bin/bash
set -e
set -euo pipefail
export XDG_RUNTIME_DIR=/tmp/xdg-solve; mkdir -p "$XDG_RUNTIME_DIR" /task/outputs
solidcraft-cli run --in /task/inputs/enclosure.sc --out /task/outputs/enclosure.3mf > /dev/null
python3 - <<'PY' > /task/answer.txt
import trimesh
m = trimesh.load("/task/outputs/enclosure.3mf", force="mesh")
e = " x ".join(f"{x:.1f}" for x in m.extents)
state = "print-ready: the mesh is watertight (closed)" if m.is_watertight else "NOT print-ready: the mesh has gaps"
print(f"enclosure.3mf is {state}; size {e} mm, volume {m.volume:.0f} mm3.")
PY
