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
cat > /tmp/enclosure.json <<'JSON'
{"commands":[
 {"command":"parameters.add","params":{"name":"L","expression":"60 mm"}},
 {"command":"parameters.add","params":{"name":"W","expression":"40 mm"}},
 {"command":"parameters.add","params":{"name":"H","expression":"25 mm"}},
 {"command":"parameters.add","params":{"name":"wall","expression":"2 mm"}},
 {"command":"sketch.create","params":{"plane":"XY"}},
 {"command":"sketch.rectangle.center","params":{"center":[0,0],"corner":["L/2","W/2"]}},
 {"command":"sketch.finish","params":{}},
 {"command":"solid.extrude","params":{"distance":"H","name":"Body"}},
 {"command":"solid.fillet","params":{"edges":[[30,20,12.5],[-30,20,12.5],[30,-20,12.5],[-30,-20,12.5]],"radius":5,"name":"Corners"}},
 {"command":"solid.shell","params":{"faces":[[0,0,25]],"thickness":"wall","name":"Shell"}}
]}
JSON
solidcraft-cli run /tmp/enclosure.json --save /task/inputs/enclosure.sc > /dev/null
normalise /task/inputs/enclosure.sc
python3 -c "import json,math; r=lambda l,w,q: l*w-(4-math.pi)*q*q; json.dump({'size_mm':[60,40,25],'volume_mm3':round(r(60,40,5)*25-r(56,36,3)*23,3)}, open('/task/truth/truth.json','w'))"
