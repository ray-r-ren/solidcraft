#!/bin/bash
set -e
set -euo pipefail
export XDG_RUNTIME_DIR=/tmp/xdg-setup; mkdir -p "$XDG_RUNTIME_DIR" /task/inputs /task/truth
cat > /tmp/plate.json <<'JSON'
{"commands":[
 {"command":"solid.box","params":{"length":80,"width":50,"height":6}},
 {"command":"solid.hole","params":{"position":[16.35,25,6],"diameter":6.5}},
 {"command":"solid.hole","params":{"position":[63.65,25,6],"diameter":6.5}}
]}
JSON
mkdir -p /tmp/plategen
solidcraft-cli run /tmp/plate.json --out /tmp/plategen/mount_plate.step > /dev/null
cp /tmp/plategen/mount_plate.step /task/inputs/mount_plate.step
echo '{"diameter_mm": 6.5, "center_distance_mm": 47.3}' > /task/truth/truth.json
