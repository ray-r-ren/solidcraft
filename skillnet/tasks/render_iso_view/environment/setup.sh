#!/bin/bash
set -e
set -euo pipefail
export XDG_RUNTIME_DIR=/tmp/xdg-setup; mkdir -p "$XDG_RUNTIME_DIR" /task/inputs /task/truth
cat > /tmp/flange.json <<'JSON'
{"commands":[
 {"command":"sketch.create","params":{"plane":"XY"}},
 {"command":"sketch.circle.center","params":{"center":[0,0],"diameter":80}},
 {"command":"sketch.circle.center","params":{"center":[0,0],"diameter":30}},
 {"command":"sketch.finish","params":{}},
 {"command":"solid.extrude","params":{"distance":8,"name":"Disc"}},
 {"command":"solid.hole","params":{"position":[30,0,8],"diameter":6,"name":"Bolt"}},
 {"command":"solid.pattern.circular","params":{"features":["Bolt"],"axis":"Z","count":6}}
]}
JSON
mkdir -p /tmp/flangegen
solidcraft-cli run /tmp/flange.json --out /tmp/flangegen/flange.step > /dev/null
cp /tmp/flangegen/flange.step /task/inputs/flange.step
echo '{"holes": 6, "size_mm": [80, 80, 8]}' > /task/truth/truth.json
