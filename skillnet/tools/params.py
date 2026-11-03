"""change_parameters: set named parameters on a design and rebuild its timeline."""

from __future__ import annotations

import json
import shutil
from typing import Annotated, Any, Literal

from pydantic import Field
from skillnet_sdk import (FileConstraints, InputFile, OutputFile, ToolContext, ToolError, ToolInput, ToolOutput,
                          ToolResult, tool)

from ._engine import (DESIGN_EXTS, EXPORT_EXT, body_summary, clean_stderr, eval_file, feature_list, parse_failed_features,
                      parse_json, parse_step_error, r, run_cli, safe_name, staged_copy, total_volume, union_bbox,
                      user_params, workdir)

ParamFormat = Literal["step", "stl", "3mf", "obj", "iges"]


class ChangeIn(ToolInput):
    design: Annotated[InputFile, FileConstraints(extensions=sorted(DESIGN_EXTS))] = Field(
        description="The editable SolidCraft design (.sc) from build_part or the user.")
    changes: dict[str, float | int | str] = Field(
        description="Parameter name → new value. A number keeps the parameter's unit (mm for lengths); a string can "
                    "carry a unit or be an expression: {\"width\": 80, \"wall\": \"2.5 mm\", \"depth\": \"1 in\", "
                    "\"lid\": \"height/4\"}.")
    create_missing: bool = Field(default=False, description="Create parameters that don't exist yet instead of "
                                 "failing (a new parameter changes nothing until a feature uses it).")
    formats: list[ParamFormat] = Field(default_factory=lambda: ["step", "stl", "3mf"],
                                       description="Files to export from the updated design: step, stl, 3mf, obj, "
                                                   "iges. Default step, stl, 3mf.")
    name: str | None = Field(default=None, description="Base name for the output files (default: the design's name "
                                                        "with '_v2').")


class Change(ToolOutput):
    name: str
    old: str | None
    new: str
    old_value: float | None
    new_value: float | None
    created: bool = False


class Snapshot(ToolOutput):
    volume_mm3: float | None
    bbox_mm: dict[str, Any] | None


class ChangeOut(ToolOutput):
    design_file: str
    files: list[str]
    changed: list[Change]
    recomputed_features: int | None
    failing_features: list[dict[str, Any]]
    before: Snapshot
    after: Snapshot
    bodies: list[dict[str, Any]]
    parameters: list[dict[str, Any]]


def _expr(v: float | int | str) -> str:
    if isinstance(v, bool):
        raise ToolError("invalid_value", "A parameter value can't be true/false.",
                        "Give a number (e.g. 80) or a string with a unit or expression (e.g. \"80 mm\").")
    if isinstance(v, (int, float)):
        return f"{v:g}" if isinstance(v, float) else str(v)
    s = str(v).strip()
    if not s:
        raise ToolError("invalid_value", "A parameter value is empty.", "Give each parameter a number or expression.")
    return s


@tool(kind="edit", title="Change a design's parameters and rebuild", timeout_s=300,
      examples=[{"arguments": {"design": "box.sc", "changes": {"width": 80, "wall": "2.5 mm"}}}])
def change_parameters(args: ChangeIn, ctx: ToolContext) -> ToolResult[ChangeOut]:
    """Use when the user wants an existing parametric design resized or tweaked by name ('make it 80 wide', 'wall 2.5 mm', 'hole 6 mm'). Sets each named parameter (number or expression with unit), rebuilds the whole timeline, and returns the updated .sc design and STEP/STL/3MF with before/after volume and bounding box. If the new values make a feature fail, nothing is written and the error names the feature and why. Call inspect_design first to see the parameter names."""
    if not args.changes:
        raise ToolError("invalid_input", "No parameter changes were given.",
                        "Pass changes like {\"width\": 80}; call inspect_design to see the design's parameters.")
    work = workdir("params")
    src = staged_copy(args.design, work / "in")
    ctx.progress(5, "reading the design")
    ev0 = eval_file(ctx, src)
    params0 = {p["name"]: p for p in user_params(ev0, include_model=True)}
    exprs = {}
    for k, v in args.changes.items():
        e = _expr(v)
        unit = (params0.get(k.strip()) or {}).get("unit")
        if isinstance(v, (int, float)) and unit and unit not in ("text",):
            e = f"{e} {unit}"
        exprs[k.strip()] = e
    missing = [k for k in exprs if k not in params0]
    if missing and not args.create_missing:
        names = ", ".join(p for p, d in params0.items() if not d.get("dimension")) or "(none)"
        raise ToolError("unknown_parameter",
                        f"The design has no parameter named {', '.join(repr(m) for m in missing)}. "
                        f"Its parameters: {names}.",
                        "Use one of the listed names (call inspect_design detail='full' to also see sketch dimension "
                        "parameters d1, d2…), or set create_missing=true to add it as a new parameter.")
    commands: list[dict[str, Any]] = []
    for k in missing:
        commands.append({"command": "parameters.add", "params": {"name": k, "expression": exprs[k]}})
    existing = {k: v for k, v in exprs.items() if k not in missing}
    if existing:
        commands.append({"command": "parameters.change", "params": {"changes": existing}})
    script = work / "change.json"
    script.write_text(json.dumps({"commands": commands}))
    name = safe_name(args.name or f"{args.design.stem}_v2", "design")
    out_dir = work / "out"
    out_dir.mkdir()
    sc_path = out_dir / f"{name}.sc"
    fmts = list(dict.fromkeys(args.formats))
    cli = ["run", str(script), "--in", str(src), "--save", str(sc_path), "--results"]
    for f in fmts:
        cli += ["--out", str(out_dir / f"{name}{EXPORT_EXT[f]}")]
    ctx.progress(30, "rebuilding the timeline")
    rc, out, err = run_cli(ctx, cli)
    if rc != 0:
        failed = parse_failed_features(err)
        if failed:
            lst = "; ".join(f"{f['name']}: {f['error']}" for f in failed)
            raise ToolError("rebuild_failed",
                            f"With these values {len(failed)} feature(s) fail: {lst}. Nothing was written.",
                            "Tell the user which feature breaks and why; pick values the engine's reason allows, or "
                            "first change the failing feature (e.g. a smaller fillet radius) with build_part "
                            "start_from, then try again.")
        se = parse_step_error(err)
        reason = se["error"] if se else (clean_stderr(err) or "no reason given")
        raise ToolError("invalid_value", f"The engine refused the change: {reason}. Nothing was written.",
                        "Fix the value (a number, a number with a unit like '80 mm', or an expression using existing "
                        "parameter names) and try again.")
    results = parse_json(out, "changing parameters") if out.strip() else []
    recomputed = None
    for res in results if isinstance(results, list) else []:
        if isinstance(res, dict) and isinstance(res.get("recomputed"), int):
            recomputed = (recomputed or 0) + res["recomputed"]
    ctx.progress(70, "measuring the result")
    ev1 = eval_file(ctx, sc_path)
    params1 = {p["name"]: p for p in user_params(ev1, include_model=True)}
    failing = [f for f in feature_list(ev1) if f.get("error")]
    changed = []
    for k in exprs:
        o, n = params0.get(k), params1.get(k)
        changed.append(Change(name=k, old=o.get("expression") if o else None,
                              new=(n or {}).get("expression") or exprs[k],
                              old_value=o.get("value") if o else None, new_value=(n or {}).get("value"),
                              created=k in missing))
    outputs: list[OutputFile] = []
    files: list[str] = []
    final_sc = ctx.output_path(sc_path.name)
    shutil.copyfile(sc_path, final_sc)
    outputs.append(OutputFile(final_sc, "The updated editable design (.sc)."))
    files.append(final_sc.name)
    not_written = []
    for f in fmts:
        p = out_dir / f"{name}{EXPORT_EXT[f]}"
        if p.exists() and p.stat().st_size > 0:
            dst = ctx.output_path(p.name)
            shutil.copyfile(p, dst)
            outputs.append(OutputFile(dst, f"{f.upper()} export of the updated part"))
            files.append(dst.name)
        else:
            not_written.append(f)
    b0, b1 = ev0.get("bodies", []) or [], ev1.get("bodies", []) or []
    before = Snapshot(volume_mm3=total_volume(ev0), bbox_mm=union_bbox(b0))
    after = Snapshot(volume_mm3=total_volume(ev1), bbox_mm=union_bbox(b1))
    uncertain = []
    status: Literal["ok", "partial"] = "ok"
    if not_written:
        status = "partial"
        uncertain.append(f"These exports were not written: {', '.join(not_written)}.")
    if failing:
        status = "partial"
        uncertain.append("Some features report errors after the rebuild: "
                         + "; ".join(f"{f['name']}: {f['error']}" for f in failing))
    if before.volume_mm3 == after.volume_mm3 and before.bbox_mm == after.bbox_mm and not missing:
        uncertain.append("Volume and size did not change: the parameter may not drive any feature (e.g. a sketch "
                         "drawn with plain numbers instead of the parameter).")
    for c in changed:
        if c.created:
            uncertain.append(f"Parameter {c.name} was created; no feature uses it yet.")
    for ft in feature_list(ev1):
        if ft.get("warning"):
            uncertain.append(f"Feature {ft['name']} warns: {str(ft['warning'])[:200]}")
    desc = ", ".join(f"{c.name} {c.old or '(new)'} → {c.new}" for c in changed)
    vb, va = before.volume_mm3, after.volume_mm3
    return ToolResult(
        data=ChangeOut(design_file=final_sc.name, files=files, changed=changed, recomputed_features=recomputed,
                       failing_features=failing, before=before, after=after,
                       bodies=[body_summary(b) for b in b1], parameters=user_params(ev1)),
        status=status, outputs=outputs, uncertain=uncertain,
        summary=f"Set {desc}; volume {r(vb, 1) if vb is not None else '?'} → {r(va, 1) if va is not None else '?'} mm³, "
                f"size {'×'.join(f'{v:g}' for v in after.bbox_mm['size']) if after.bbox_mm else '?'} mm.",
        next_step="Check that after.bbox_mm moved by the amount the change implies, then give the user the new .sc "
                  "and exports.")
