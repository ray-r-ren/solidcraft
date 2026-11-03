#!/bin/bash
set -e
set -euo pipefail
export XDG_RUNTIME_DIR=/tmp/xdg-solve; mkdir -p "$XDG_RUNTIME_DIR"
solidcraft-cli eval /task/inputs/bracket_rev3.step | python3 -c "
import sys, json
d = json.load(sys.stdin)
b = d['bodies'][0]['bbox']
size = [round(b['max'][i] - b['min'][i], 2) for i in range(3)]
v = d['total']['volume_mm3']
print(f'Overall size: {size[0]:g} x {size[1]:g} x {size[2]:g} mm. Volume: {v/1000:.2f} cm3 ({v:.0f} mm3).')
" > /task/answer.txt
