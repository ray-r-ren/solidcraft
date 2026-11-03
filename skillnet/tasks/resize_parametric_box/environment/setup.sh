#!/bin/bash
set -e
set -euo pipefail
export XDG_RUNTIME_DIR=/tmp/xdg-setup; mkdir -p "$XDG_RUNTIME_DIR" /task/inputs /task/truth
normalise() {
python3 - "$1" <<'PY'
import json, sys, zipfile
p = sys.argv[1]
zin = zipfile.ZipFile(p); items = [(i.filename, zin.read(i.filename)) for i in zin.infolist()]; zin.close()
def strip(o):
    if isinstance(o, dict): return {k: (0 if k == "ms" else strip(v)) for k, v in o.items()}
    if isinstance(o, list): return [strip(v) for v in o]
    return o
with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
    for name, data in items:
        if name == "cache/model.json":
            data = json.dumps(strip(json.loads(data)), separators=(",", ":")).encode()
        info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        z.writestr(info, data)
PY
}
cat > /tmp/mount_block.json <<'JSON'
{"commands":[
 {"command":"parameters.add","params":{"name":"width","expression":"40 mm"}},
 {"command":"parameters.add","params":{"name":"depth","expression":"30 mm"}},
 {"command":"parameters.add","params":{"name":"height","expression":"20 mm"}},
 {"command":"parameters.add","params":{"name":"hole_d","expression":"10 mm"}},
 {"command":"sketch.create","params":{"plane":"XY"}},
 {"command":"sketch.rectangle.center","params":{"center":[0,0],"corner":["width/2","depth/2"]}},
 {"command":"sketch.finish","params":{}},
 {"command":"solid.extrude","params":{"distance":"height","name":"Block"}},
 {"command":"solid.hole","params":{"position":[0,0,"height"],"diameter":"hole_d","name":"ThroughHole"}}
]}
JSON
solidcraft-cli run /tmp/mount_block.json --save /task/inputs/mount_block.sc > /dev/null
normalise /task/inputs/mount_block.sc
python3 -c "import json,math; json.dump({'size_mm':[70,30,20],'volume_mm3':round(70*30*20-math.pi*25*20,3),'width':70}, open('/task/truth/truth.json','w'))"
