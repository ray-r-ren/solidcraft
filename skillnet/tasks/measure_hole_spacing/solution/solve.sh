#!/bin/bash
set -e
set -euo pipefail
export XDG_RUNTIME_DIR=/tmp/xdg-solve; mkdir -p "$XDG_RUNTIME_DIR"
BODY=$(solidcraft-cli eval /task/inputs/mount_plate.step | python3 -c "import sys,json;print(json.load(sys.stdin)['bodies'][0]['name'])")
cat > /tmp/m.json <<JSON
{"commands":[{"command":"inspect.measure","params":{"items":[
 {"type":"face","body":"$BODY","point":[16.35,28.25,3]},
 {"type":"face","body":"$BODY","point":[63.65,28.25,3]}]}}]}
JSON
solidcraft-cli run /tmp/m.json --in /task/inputs/mount_plate.step --results | python3 -c "
import sys, json
r = json.load(sys.stdin)[0]
r = r.get('result', r)
items = r.get('items') or []
d = items[0].get('diameter') if items else None
c = r.get('center_distance')
print(f'Hole diameter: {d:.2f} mm. Centre-to-centre distance: {c:.2f} mm.')
" > /task/answer.txt
