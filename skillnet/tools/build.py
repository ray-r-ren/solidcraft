"""build_part: run a list of CAD commands into an editable design plus CAD/print files."""

from __future__ import annotations

import json
import shutil
from typing import Annotated, Any, Literal

from pydantic import Field
from skillnet_sdk import (FileConstraints, InputFile, OutputFile, ToolContext, ToolError, ToolInput, ToolOutput,
                          ToolResult, tool)

from ._engine import (ALL_INPUT_EXTS, EXPORT_EXT, body_summary, check_input_ext, clean_stderr, eval_file,
                      feature_list, parse_failed_features, parse_json, parse_step_error, run_cli, safe_name,
                      staged_copy, total_volume, union_bbox, user_params, validate_steps, workdir)

BuildFormat = Literal["step", "stl", "3mf", "obj", "iges"]


class BuildIn(ToolInput):
    steps: list[dict[str, Any]] | dict[str, Any] | str = Field(
        description="The CAD commands to run, in order: a list of {\"command\": id, \"params\": {...}} (or "
                    "{\"commands\": [...]}, or the same as a JSON string). Lengths in mm; any numeric field can be an "
                    "expression naming parameters (\"width/2 - 6\"). Get ids and params from find_cad_commands.")
    start_from: Annotated[InputFile, FileConstraints(extensions=ALL_INPUT_EXTS)] | None = Field(
        default=None, description="Optional design to build on: a .sc design from an earlier build_part call (keeps "
                                  "its parameters and timeline), or a STEP/IGES/STL/3MF/OBJ to use as the base body.")
    name: str = Field(default="part", description="Base name for the output files, e.g. 'bracket'.")
    formats: list[BuildFormat] = Field(
        default_factory=lambda: ["step", "stl", "3mf"],
        description="Files to export besides the editable .sc design: step (CAD), stl and 3mf (3D printing), obj, "
                    "iges. Default step, stl, 3mf.")


class FailedFeature(ToolOutput):
    name: str
    error: str


class BuildOut(ToolOutput):
    design_file: str = Field(description="The editable design (.sc) to pass to change_parameters, inspect_design, "
                                         "render_views, export_model or build_part start_from.")
    files: list[str]
    step_count: int
    bodies: list[dict[str, Any]]
    body_count: int
    total_volume_mm3: float | None
    bbox_mm: dict[str, Any] | None = Field(description="Overall {min, max, size} in mm.")
    parameters: list[dict[str, Any]]
    feature_count: int
    features: list[dict[str, Any]]
    sketches: list[dict[str, Any]]


@tool(kind="create", title="Build a parametric part from CAD steps", timeout_s=300,
      examples=[{"arguments": {"name": "block", "steps": [
          {"command": "parameters.add", "params": {"name": "width", "expression": "40 mm"}},
          {"command": "solid.box", "params": {"length": "width", "width": 30, "height": 20, "center": [0, 0, 10]}},
          {"command": "solid.hole", "params": {"position": [0, 0, 20], "diameter": 10, "name": "Hole"}}]}}])
def build_part(args: BuildIn, ctx: ToolContext) -> ToolResult[BuildOut]:
    """Use when the user describes a part to model (bracket, box, enclosure, plate, spacer…) or wants features added to an existing design. Runs your list of CAD commands (parameters.add, sketch.create, sketch.rectangle.center, sketch.finish, solid.extrude, solid.fillet, solid.hole…) headless, optionally on top of a design from start_from, and returns the editable .sc design plus STEP/STL/3MF with measured volume, bounding box, bodies, parameters and timeline. If any step fails nothing is written and the error names the step index and the engine's reason. Verify after with measure_features or render_views."""
    steps = validate_steps(args.steps)
    name = safe_name(args.name, "part")
    work = workdir("build")
    script = work / "script.json"
    script.write_text(json.dumps({"commands": steps}))
    base_args: list[str] = []
    if args.start_from is not None:
        check_input_ext(args.start_from, set(ALL_INPUT_EXTS), "start_from file")
        base = staged_copy(args.start_from, work / "in")
        base_args = ["--in", str(base)]
    fmts = list(dict.fromkeys(args.formats))
    out_dir = work / "out"
    out_dir.mkdir()
    sc_path = out_dir / f"{name}.sc"
    cli = ["run", str(script), *base_args, "--save", str(sc_path), "--results", "--param-check", "strict"]
    for f in fmts:
        cli += ["--out", str(out_dir / f"{name}{EXPORT_EXT[f]}")]
    ctx.progress(10, f"running {len(steps)} CAD steps")
    rc, out, err = run_cli(ctx, cli)
    if rc != 0:
        step_err = parse_step_error(err)
        if step_err:
            i = step_err["index"]
            raise ToolError(
                "step_failed",
                f"steps[{i}] ({step_err['command']}) failed: {step_err['error']}. Nothing was written.",
                f"Fix steps[{i}] (0-based index) using the engine's reason, then call build_part again with the "
                "whole list. Check its parameter names with find_cad_commands; for edge/face picks get exact points "
                "from inspect_design detail='topology'.")
        failed = parse_failed_features(err)
        if failed:
            lst = "; ".join(f"{f['name']}: {f['error']}" for f in failed)
            raise ToolError("feature_failed", f"{len(failed)} timeline feature(s) failed: {lst}. Nothing was written.",
                            "Change the failing feature's step (e.g. a smaller fillet radius or a pick on an existing "
                            "edge) and call build_part again.")
        raise ToolError("engine_failed", f"The build failed: {clean_stderr(err) or 'no reason given'}",
                        "Check the steps against find_cad_commands and try again; build in smaller stages to find "
                        "the step that breaks.")
    results = parse_json(out, "running the steps") if out.strip() else []
    ctx.progress(70, "measuring the result")
    ev = eval_file(ctx, sc_path)
    bodies = ev.get("bodies", []) or []
    feats = feature_list(ev)
    sketches = [{"name": s.get("name"), "dof": s.get("dof"), "status": s.get("status"), "profiles": s.get("profiles")}
                for s in ev.get("sketches", []) or []]

    outputs: list[OutputFile] = []
    files: list[str] = []
    final_sc = ctx.output_path(sc_path.name)
    shutil.copyfile(sc_path, final_sc)
    outputs.append(OutputFile(final_sc, "Editable parametric design (.sc): pass it to change_parameters, "
                                        "inspect_design, export_model or build_part start_from."))
    files.append(final_sc.name)
    missing: list[str] = []
    for f in fmts:
        p = out_dir / f"{name}{EXPORT_EXT[f]}"
        if p.exists() and p.stat().st_size > 0:
            dst = ctx.output_path(p.name)
            shutil.copyfile(p, dst)
            outputs.append(OutputFile(dst, f"{f.upper()} export of the part"))
            files.append(dst.name)
        else:
            missing.append(f)
    res_path = ctx.output_path("results.json")
    res_path.write_text(json.dumps(results, indent=1))
    outputs.append(OutputFile(res_path, "The engine's result for every step (created sketch ids, bodies, features)."))

    uncertain: list[str] = []
    status: Literal["ok", "partial"] = "ok"
    if missing:
        status = "partial"
        uncertain.append(f"These exports were not written: {', '.join(missing)}.")
    if not bodies:
        status = "partial"
        uncertain.append("The steps ran but the design has no bodies (e.g. only sketches, or a cut removed "
                         "everything).")
    for b in bodies:
        if b.get("closed") is False:
            uncertain.append(f"Body {b.get('name')} is not a closed solid, so it has no volume.")
    for ft in feats:
        if ft.get("warning"):
            uncertain.append(f"Feature {ft['name']} warns: {str(ft['warning'])[:200]} — check the volume matches "
                             "your hand calculation.")
    for s in sketches:
        if s.get("dof") and s["dof"] > 0:
            uncertain.append(f"Sketch {s['name']} has {s['dof']} free degree(s) of freedom; geometry not tied to "
                             "a dimension won't follow parameter changes.")
    vol = total_volume(ev)
    bb = union_bbox(bodies)
    size = "×".join(f"{v:g}" for v in bb["size"]) if bb else "?"
    params = user_params(ev)
    data = BuildOut(
        design_file=final_sc.name, files=files, step_count=len(steps),
        bodies=[body_summary(b) for b in bodies], body_count=len(bodies), total_volume_mm3=vol, bbox_mm=bb,
        parameters=params, feature_count=len(feats), features=feats, sketches=sketches)
    return ToolResult(
        data=data, status=status, outputs=outputs, uncertain=uncertain,
        summary=f"Built {name}: {len(bodies)} body(ies), volume {vol if vol is not None else '?'} mm³, size {size} "
                f"mm, {len(params)} parameter(s), {len(feats)} timeline feature(s).",
        next_step="Compare total_volume_mm3 and bbox_mm with your own numbers for the intended part before telling "
                  "the user it's done; check key dimensions with measure_features and look with render_views.")
