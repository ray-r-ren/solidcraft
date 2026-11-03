# Parametric CAD Studio

Describe a part. Get an editable parametric 3D model with print-ready and CAD files.

You (the agent) write the modelling steps; the tools run them in a headless parametric CAD engine,
measure the result exactly, render it and export STEP, STL, 3MF, OBJ or IGES. Units are millimetres.

## Where to start

Call `find_cad_commands` for the operations you need (e.g. `rectangle`, `extrude`, `hole`, `fillet`) and copy the parameter shapes it returns, then write the steps for `build_part`; when the user gives you a file, call `inspect_design` on it first.

Files: local files go in with `upload_file` (pass the returned file_id) or as an https URL. Every result's
`outputs` are download links: give the user the `.sc` design and the requested exports, or download them
for the user's own tools.

## Stages

1. **Plan** — turn the description into numbers in mm and decide the origin (centre the part on X/Y,
   bottom face on Z=0 unless the user says otherwise). Hand-compute the expected volume and bounding
   box for anything simple: you need them to verify. Pick the sizes the user is likely to change
   (width, depth, height, wall, hole diameter) and make them named parameters.
2. **Look up** — `find_cad_commands` with one plain word per operation (`rectangle`, `circle`, `extrude`,
   `hole`, `fillet`, `chamfer`, `shell`, `pattern`, `mirror`, `revolve`, `parameter`). Copy key names
   exactly (`center`, not `centre`): unknown keys are rejected. Worked, verified scripts are in
   [references/examples.md](references/examples.md).
3. **Build** — `build_part` with `steps` as a list of `{"command": id, "params": {...}}`:
   - `parameters.add {name, expression:"40 mm"}` for each key size, first.
   - `sketch.create {plane:"XY"}` → profile (`sketch.rectangle.center {center:[0,0], corner:["width/2","depth/2"]}`,
     `sketch.circle.center {center, diameter}`) → `sketch.finish {}` → `solid.extrude {distance:"height"}`.
   - Then features: `solid.hole {position:[x,y,z on a face], diameter}`, `solid.fillet {edges:[[x,y,z]…], radius}`,
     `solid.chamfer {edges, distance}`, `solid.shell {faces:[[x,y,z]], thickness}`,
     `solid.pattern.circular {features:[name], axis:"Z", count}`. Give features a `name` so patterns,
     mirrors and later edits can refer to them.
   - If it fails, the error says `steps[i] (command) failed: <reason>` (i counts from 0) or names the
     timeline feature that failed. Nothing is written. Fix that step and call again.
   - For long parts, build in stages: build the base, then pass its `.sc` as `start_from` with only the new
     steps. The earlier parameters and timeline are kept.
4. **Verify** — compare `total_volume_mm3` and `bbox_mm.size` with your hand numbers (within ~0.5% for
   prismatic parts). If they differ, the part is wrong even though the build succeeded. Then:
   - `measure_features` for the dimensions that matter: a hole's `diameter` (and `radius`, `center`, `axis`), a wall's `min_distance_mm`
     between two faces, `center_distance_mm` between two holes. Picks are points from
     `inspect_design` detail=`topology` (a face's `point`, an edge's `mid`) or face/edge names such as `F3:bore:side:0`.
   - `render_views` (default iso, front, top, right) and look at the pictures yourself: hole positions,
     which edges got rounded, which side is open.
   - Check `uncertain`: sketches with free degrees of freedom won't follow parameter changes.
5. **Change** — when the user asks to resize or tweak ("make it 80 wide", "wall 2.5"): `inspect_design`
   for the parameter names, then `change_parameters` with `changes` (`{"width": 80}` keeps the unit;
   `"1 in"` and expressions like `"height/4"` work). Check `after.bbox_mm` moved by what the change implies.
   If the name doesn't exist you get `unknown_parameter` with the names that do; `create_missing: true`
   only adds a parameter, it changes nothing until a feature uses it.
6. **Export** — `export_model` on the `.sc` with the formats the user wants (`step` for CAD, `3mf`/`stl`
   for printing, `quality: "fine"` for smoother curves). For print requests report `print_ready`; if it
   is false, read `print_problems`, fix the design and export again.

## Decisions, by example

- *"A 40×30×20 mm block with a 10 mm hole through the middle, for printing."* Parameters width/depth/height/hole_d,
  centre rectangle, extrude `height`, `solid.hole {position:[0,0,"height"], diameter:"hole_d"}` (through
  all by default). Expected 40·30·20 − π·5²·20 = 22429.2 mm³; the engine reports 22429.465. Then
  `export_model` formats `["3mf","stl"]` and report `print_ready`.
- *"Here's my STEP; how big is it and how much material?"* `inspect_design` only: report `bbox_mm.size`,
  `total_volume_mm3` (and convert: cm³ = mm³/1000). STEP files have no parameters: to resize, rebuild it
  with `build_part` (`start_from` the STEP gives a base body you can add features to, not parameters).
- *"Make the enclosure 80 long instead of 60."* `change_parameters {"changes":{"L":80}}` on the `.sc`;
  fillets and shells picked by points follow the new size (verified: 60→80 kept all four corner fillets).
  If the user only has an STL, say it can't be resized parametrically.

## Pitfalls

- **Origin and orientation.** `solid.box` puts its corner at the origin (min 0,0,0) unless you give
  `center`. Sketch on `XY` maps sketch x,y to world +X,+Y; on `YZ` to +Y,+Z; on `XZ` to +X and **−Z**
  (a rectangle drawn at positive sketch y ends up below Z=0, and the extrude goes along +Y). Prefer `XY`
  and `YZ`, or check `bbox_mm` after building.
- **Numbers don't follow parameters.** Only expressions that name a parameter (`"width/2"`, `"height"`)
  update on `change_parameters`; a literal `20` stays 20. Use expressions for every size the user may change.
- **A cut that misses still succeeds.** A cut extrude placed off the body builds without error and leaves the
  volume unchanged. Always compare volume against your expectation. (`solid.hole` off a face does fail:
  "position … is not on a face of a body".)
- **Edge and face picks are points.** Fillet/chamfer `edges` and shell `faces` are `[x,y,z]` points on the
  item. Get them from `inspect_design` detail=`topology`: use an edge's `mid`, and a face's `point`, not its
  centroid (a face centroid can fall inside a hole).
- **Too-large fillets fail the build**, e.g. "largest radius that fits is 2 mm". Shrink the radius or use
  `fit: "reduce"` from the fillet docs.
- **Mesh inputs are dumb solids.** STL/3MF/OBJ come in as mesh bodies: no edges to fillet, no STEP/IGES export
  (`mesh_to_cad`), no `measure_features`. They can still be inspected, rendered, exported to other mesh formats
  and used as a `start_from` base.
- **Renders.** If `renderer_used` is `fallback`, the pictures are a simpler shaded mesh view (colours and edges
  differ). Parts that sit below Z=0 look cut by the ground grid: pass `grid: false`.
- **Measure picks snap** to the nearest face/edge/vertex. Confirm the returned centre, axis or area is the
  item you meant before quoting the number. For hole spacing quote `center_distance_mm` (axis to axis), not
  `min_distance_mm` (wall to wall: 40.8 vs 47.3 mm for two 6.5 mm holes).
- **Restricted commands.** Steps that touch files, the app UI or settings (`file.*`, `ui.*`, `settings.*`,
  `render.*` …) are refused with `invalid_steps`; exports are done by the tools' `formats`.

## Evidence

- Size and material: `bbox_mm.size` (X×Y×Z mm), `total_volume_mm3`, per-body `area_mm2` and `center_of_mass`.
- Editability: the `parameters` list (name, expression, value) and `features` with no `error`.
- Exact dimensions: `measure_features` numbers (`diameter`, `min_distance_mm`, `center_distance_mm`, `angle_deg`).
- Appearance: the iso PNG and the views sheet from `render_views`.
- Print readiness: `export_model` → `print_ready` (and `print_problems`), and in each `mesh_checks` entry `watertight`, `shells`,
  `volume_diff_pct` against `brep_volume_mm3`.
- Changes: `change_parameters` → `changed` (old → new) and `before`/`after` volume and bbox.
Attach the `.sc` design plus the requested exports; say plainly when something is inferred (listed in `uncertain`).

## Done when

- The last build or change has no failed step and no feature with an `error`.
- Volume and bounding box match your hand numbers, and the key dimensions are confirmed with
  `measure_features` (or by the bbox for plain blocks).
- You looked at at least the iso render.
- For print requests, `export_model` reports `print_ready: true`.
- The user has download links for the `.sc` design and every format they asked for.

## Can't do

- Slice to G-code or estimate print time: give the user the STL/3MF for their slicer (PrusaSlicer, Cura, Bambu Studio).
- Open native SolidWorks, Fusion, Inventor or Onshape files: ask for a STEP export from that app, then `inspect_design`.
- Turn a photo or drawing into a model automatically: read the dimensions from it yourself and write the steps.
- Drive the CAD desktop app live on the user's computer: everything runs headless; the user can open the `.sc` in it.
- Stress, thermal or other simulation (FEA): export STEP for a simulation tool.
- CAM toolpaths or CNC programs: export STEP for CAM software.
- Photorealistic product renders: the pictures are viewport-style; use a renderer on the exported STEP/OBJ.
