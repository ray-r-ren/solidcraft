"""export_model: export CAD and print files and check the meshes are print-ready."""

from __future__ import annotations

import json
import shutil
from typing import Annotated, Any, Literal

from pydantic import Field
from skillnet_sdk import (FileConstraints, InputFile, OutputFile, ToolContext, ToolError, ToolInput, ToolOutput,
                          ToolResult, tool)

from ._engine import (ALL_INPUT_EXTS, EXPORT_EXT, check_input_ext, clean_stderr, eval_file, mesh_check, r, run_cli,
                      safe_name, staged_copy, total_volume, workdir)

ExportFormat = Literal["step", "iges", "stl", "3mf", "obj"]
_MESH = {"stl", "3mf", "obj"}
_QUALITY_CMD = {"stl": "file.export_stl", "3mf": "file.export_3mf", "obj": "file.export_obj"}


class ExportIn(ToolInput):
    file: Annotated[InputFile, FileConstraints(extensions=ALL_INPUT_EXTS)] = Field(
        description="The part to export: .sc design (best), STEP/IGES, or a mesh (STL/3MF/OBJ).")
    formats: list[ExportFormat] = Field(default_factory=lambda: ["step", "3mf", "stl"], min_length=1,
                                        description="Formats to write: step (CAD, 'STP'), iges, stl and 3mf (3D "
                                                    "printing / slicers), obj. Default step, 3mf, stl.")
    quality: Literal["standard", "fine", "finest"] = Field(
        default="standard", description="Mesh density for stl/3mf/obj: standard, fine, finest (smoother curves, "
                                        "bigger files).")
    name: str | None = Field(default=None, description="Base name for the files (default: the input's name).")


class FileInfo(ToolOutput):
    format: str
    file: str
    bytes: int


class ExportOut(ToolOutput):
    files: list[FileInfo]
    brep_volume_mm3: float | None = Field(description="Exact solid volume of the source (None for mesh inputs).")
    mesh_checks: list[dict[str, Any]]
    cad_checks: list[dict[str, Any]]
    print_ready: bool
    print_problems: list[str]


@tool(kind="export", title="Export CAD and print-ready files", timeout_s=300,
      examples=[{"arguments": {"file": "bracket.sc", "formats": ["3mf", "stl"]}},
                {"arguments": {"file": "bracket.sc", "formats": ["step"]}}])
def export_model(args: ExportIn, ctx: ToolContext) -> ToolResult[ExportOut]:
    """Use when the user wants a part in another format (STEP for CAD, STL or 3MF for 3D printing, OBJ, IGES) or asks whether it's print-ready. Exports the design, then checks every mesh (watertight, consistent winding, number of shells, mesh volume vs the exact solid volume, size in mm) and re-opens STEP/IGES to confirm the volume. print_ready is true only when the mesh is closed, consistent and within 0.5% of the solid's volume. Use as the final step; slicing to G-code is not included."""
    check_input_ext(args.file, set(ALL_INPUT_EXTS))
    work = workdir("export")
    src = staged_copy(args.file, work / "in")
    ctx.progress(5, "reading the part")
    ev = eval_file(ctx, src)
    bodies = ev.get("bodies", []) or []
    if not bodies:
        raise ToolError("nothing_to_export", f"'{args.file.name}' has no bodies to export.",
                        "Build the part first (build_part) or pass a file that contains a body.")
    failing = [t for t in ev.get("timeline", []) or [] if t.get("error")]
    is_mesh_src = all((b.get("face_types") or {}).get("mesh") for b in bodies)
    brep_vol = None if is_mesh_src else total_volume(ev)
    cad_wanted = [f for f in args.formats if f in ("step", "iges")]
    if is_mesh_src and cad_wanted:
        raise ToolError("mesh_to_cad", f"'{args.file.name}' is a triangle mesh, which can't be exported as "
                        f"{'/'.join(x.upper() for x in cad_wanted)} (those need an exact solid).",
                        "Export it as stl, 3mf or obj instead, or rebuild the part as a solid with build_part "
                        "(you can use the mesh's measured size from inspect_design as a reference).")
    name = safe_name(args.name or src.stem, "part")
    fmts = list(dict.fromkeys(args.formats))
    out_dir = work / "out"
    out_dir.mkdir()
    targets = {f: out_dir / f"{name}{EXPORT_EXT[f]}" for f in fmts}
    check_stl = None
    if not any(f in _MESH for f in fmts):
        check_stl = work / "check.stl"   # always check a mesh, even for CAD-only exports
    cli = ["run"]
    if args.quality != "standard":
        cmds = [{"command": _QUALITY_CMD[f], "params": {"path": str(p), "quality": args.quality}}
                for f, p in targets.items() if f in _MESH]
        if check_stl:
            cmds.append({"command": "file.export_stl", "params": {"path": str(check_stl), "quality": args.quality}})
        script = work / "export.json"
        script.write_text(json.dumps({"commands": cmds or [{"command": "inspect.measure", "params": {}}]}))
        cli += [str(script)]
    cli += ["--in", str(src)]
    for f, p in targets.items():
        if args.quality == "standard" or f not in _MESH:
            cli += ["--out", str(p)]
    if check_stl and args.quality == "standard":
        cli += ["--out", str(check_stl)]
    if failing:
        cli += ["--allow-errors"]
    ctx.progress(30, "exporting")
    rc, _, err = run_cli(ctx, cli)
    if rc != 0:
        raise ToolError("export_failed", f"The export failed: {clean_stderr(err) or 'no reason given'}",
                        "Check the file with inspect_design; if a feature fails, fix it first (change_parameters or "
                        "build_part), then export again.")
    outputs: list[OutputFile] = []
    files: list[FileInfo] = []
    meshes: list[dict[str, Any]] = []
    cads: list[dict[str, Any]] = []
    uncertain: list[str] = []
    missing: list[str] = []
    for f, p in targets.items():
        if not p.exists() or p.stat().st_size == 0:
            missing.append(f)
            continue
        ctx.progress(60, f"checking {f}")
        if f in _MESH:
            mc = mesh_check(p, brep_vol)
            mc["format"] = f
            meshes.append(mc)
        else:
            try:
                ev2 = eval_file(ctx, p)
                v2 = total_volume(ev2)
                d = round(abs(v2 - brep_vol) / brep_vol * 100, 4) if (v2 and brep_vol) else None
                cads.append({"format": f, "file": p.name, "reopens": True, "bodies": len(ev2.get("bodies") or []),
                             "volume_mm3": v2, "volume_diff_pct": d})
            except ToolError:
                cads.append({"format": f, "file": p.name, "reopens": False})
        dst = ctx.output_path(p.name)
        shutil.copyfile(p, dst)
        files.append(FileInfo(format=f, file=dst.name, bytes=dst.stat().st_size))
        outputs.append(OutputFile(dst, f"{f.upper()} export"))
    if check_stl is not None and check_stl.exists():
        mc = mesh_check(check_stl, brep_vol)
        mc["format"] = "stl (check only, not delivered)"
        meshes.append(mc)

    problems: list[str] = []
    if failing:
        problems.append("The design has failing features: " + ", ".join(str(t.get("name")) for t in failing))
    for mc in meshes:
        if not mc.get("readable"):
            problems.append(f"{mc['file']}: could not be read back as a mesh.")
            continue
        if not mc["watertight"]:
            problems.append(f"{mc['file']}: not watertight (has holes or gaps).")
        if not mc["winding_consistent"]:
            problems.append(f"{mc['file']}: inconsistent triangle winding (some faces point inward).")
        if mc["volume_mm3"] is not None and mc["volume_mm3"] <= 0:
            problems.append(f"{mc['file']}: zero or negative volume.")
        if mc.get("volume_diff_pct") is not None and mc["volume_diff_pct"] > 0.5:
            problems.append(f"{mc['file']}: mesh volume differs from the solid by {mc['volume_diff_pct']}% (> 0.5%); "
                            "try quality='fine'.")
    for cc in cads:
        if not cc.get("reopens"):
            problems.append(f"{cc['file']}: could not be re-opened.")
        elif cc.get("volume_diff_pct") is not None and cc["volume_diff_pct"] > 0.1:
            uncertain.append(f"{cc['file']}: re-opened volume differs from the design by {cc['volume_diff_pct']}%.")
    for mc in meshes:
        if mc.get("shells") and mc["shells"] > 1:
            uncertain.append(f"{mc['file']}: {mc['shells']} separate shells — they print as separate pieces (or "
                             "one is inside another).")
    if is_mesh_src:
        uncertain.append("The input is a mesh, so there is no exact solid volume to compare the export against.")
    print_ready = not problems and bool(meshes)
    status: Literal["ok", "partial"] = "ok"
    if missing:
        status = "partial"
        uncertain.append(f"Not written: {', '.join(missing)}.")
    mv = next((m for m in meshes if m.get("readable")), None)
    size = "×".join(f"{v:g}" for v in mv["bbox_mm"]["size"]) if mv else "?"
    return ToolResult(
        data=ExportOut(files=files, brep_volume_mm3=r(brep_vol) if brep_vol else None, mesh_checks=meshes,
                       cad_checks=cads, print_ready=print_ready, print_problems=problems),
        status=status, outputs=outputs, uncertain=uncertain,
        summary=f"Exported {', '.join(fi.format for fi in files)}; size {size} mm; "
                f"print-ready: {'yes' if print_ready else 'no'}" + (f" ({problems[0]})" if problems else "") + ".",
        next_step=None if print_ready else "Tell the user what blocks printing (print_problems) and fix the design "
                                            "before sending it to a slicer.")
