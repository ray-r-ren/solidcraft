#!/bin/bash
set -e
set -euo pipefail
export XDG_RUNTIME_DIR=/tmp/xdg-solve; mkdir -p "$XDG_RUNTIME_DIR" /task/outputs
cat > /tmp/block.json <<'JSON'
{"commands":[
 {"command":"parameters.add","params":{"name":"width","expression":"40 mm"}},
 {"command":"parameters.add","params":{"name":"depth","expression":"30 mm"}},
 {"command":"parameters.add","params":{"name":"height","expression":"20 mm"}},
 {"command":"parameters.add","params":{"name":"hole_d","expression":"10 mm"}},
 {"command":"sketch.create","params":{"plane":"XY"}},
 {"command":"sketch.rectangle.center","params":{"center":[0,0],"corner":["width/2","depth/2"]}},
 {"command":"sketch.finish","params":{}},
 {"command":"solid.extrude","params":{"distance":"height"}},
 {"command":"solid.hole","params":{"position":[0,0,"height"],"diameter":"hole_d"}}
]}
JSON
solidcraft-cli run /tmp/block.json --save /task/outputs/block.sc --out /task/outputs/block.step --out /task/outputs/block.stl > /dev/null
VOL=$(solidcraft-cli eval /task/outputs/block.sc | python3 -c "import sys,json;print(round(json.load(sys.stdin)['total']['volume_mm3'],1))")
echo "The block's volume is ${VOL} mm³ (about 22.43 cm³)." > /task/answer.txt
