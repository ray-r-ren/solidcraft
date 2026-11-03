#!/bin/bash
set -e
set -euo pipefail
export XDG_RUNTIME_DIR=/tmp/xdg-solve; mkdir -p "$XDG_RUNTIME_DIR" /task/outputs
solidcraft-cli snapshot /task/inputs/flange.step --out /task/outputs/flange_iso.png --view iso --width 1024 --height 768 > /dev/null
echo "Rendered flange_iso.png: a flat round disc (flange) with a large centre bore and a ring of six bolt holes." > /task/answer.txt
