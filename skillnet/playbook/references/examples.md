# Verified build scripts

Each script below was run through `build_part` with the engine's strict parameter check. Pass the
`commands` list as `steps`. The volumes are what the engine measured; the hand formula is there so you
can see how to check your own parts.

## Block with a through hole (parametric)

```json
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
```

- Result: volume 22429.465 mm³ (40·30·20 − π·5²·20 = 22429.2), bbox X −20…20, Y −15…15, Z 0…20.
- `change_parameters {"width": 70}` → bbox X 70, the hole stays centred.
- `solid.hole` drills through all by default, into the face at `position`; `depth` makes it blind.

## Flange with a bolt circle (circular pattern)

```json
{"commands":[
 {"command":"parameters.add","params":{"name":"od","expression":"80 mm"}},
 {"command":"parameters.add","params":{"name":"thk","expression":"8 mm"}},
 {"command":"parameters.add","params":{"name":"bolt_d","expression":"6 mm"}},
 {"command":"parameters.add","params":{"name":"pcd","expression":"60 mm"}},
 {"command":"sketch.create","params":{"plane":"XY"}},
 {"command":"sketch.circle.center","params":{"center":[0,0],"diameter":"od"}},
 {"command":"sketch.circle.center","params":{"center":[0,0],"diameter":30}},
 {"command":"sketch.finish","params":{}},
 {"command":"solid.extrude","params":{"distance":"thk","name":"Disc"}},
 {"command":"solid.hole","params":{"position":["pcd/2",0,"thk"],"diameter":"bolt_d","name":"Bolt"}},
 {"command":"solid.pattern.circular","params":{"features":["Bolt"],"axis":"Z","count":6}}
]}
```

- Result: volume 33200.247 mm³ (π/4·(80² − 30² − 6·6²)·8 = 33200.35), bbox 80×80×8.
- A circle inside another circle in one sketch becomes its hole when extruded.
- The pattern refers to the hole by its `name`. `count` includes the original.
- The inner 30 mm bore is a literal number, so it does not follow any parameter. `uncertain` reports
  the sketch's free degree of freedom.

## Rounded open enclosure (fillet + shell)

```json
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
```

- Result: volume 13273.104 mm³, bbox 60×40×25. Hand check: outer rounded rectangle (60·40 − (4−π)·5²)·25
  minus the inner one (56·36 − (4−π)·3²)·23 = 13273.19. The shell keeps a 3 mm inner corner radius.
- Edges are picked by their midpoints (the vertical corner edges at z = H/2). Faces are picked by a
  point on them (the top face at z = 25 is removed, so the box is open on top).
- `change_parameters {"L": 80}` → bbox 80×40×25, volume 16713.104 mm³, all four fillets kept.

## Fillet that doesn't fit

`solid.fillet {edges:[[20,0,4]], radius:6}` on a 4 mm plate fails with "the largest radius that fits is
4 mm". With `"fit":"reduce"` it builds and the timeline warning says "the radius is reduced to 4 mm".
`build_part` lists that warning in `uncertain`.
