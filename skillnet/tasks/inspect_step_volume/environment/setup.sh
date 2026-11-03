#!/bin/bash
set -e
set -euo pipefail
export XDG_RUNTIME_DIR=/tmp/xdg-setup; mkdir -p "$XDG_RUNTIME_DIR" /task/inputs /task/truth
cat > /tmp/stepped.json <<'JSON'
{"commands":[
 {"command":"solid.box","params":{"length":60,"width":40,"height":10}},
 {"command":"solid.box","params":{"length":30,"width":40,"height":15,"corner":[30,0,10],"operation":"join"}},
 {"command":"solid.hole","params":{"position":[15,20,10],"diameter":8}}
]}
JSON
mkdir -p /tmp/stepgen
solidcraft-cli run /tmp/stepped.json --out /tmp/stepgen/bracket_rev3.step > /dev/null
cp /tmp/stepgen/bracket_rev3.step /task/inputs/bracket_rev3.step
python3 -c "import json,math; json.dump({'size_mm':[60,40,25],'volume_mm3':round(60*40*10+30*40*15-math.pi*16*10,3)}, open('/task/truth/truth.json','w'))"
