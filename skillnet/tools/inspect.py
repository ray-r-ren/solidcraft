"""inspect_design and measure_features."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field
from skillnet_sdk import (FileConstraints, InputFile, OutputFile, ToolContext, ToolError, ToolInput, ToolOutput,
                          ToolResult, tool)

from ._engine import (ALL_INPUT_EXTS, body_summary, check_input_ext, clean_stderr, eval_file, feature_list,
                      is_design, parse_json, parse_step_error, r, run_cli, staged_copy, total_volume, union_bbox,
                      user_params, workdir)


def _is_mesh_body(b: dict[str, Any]) -> bool:
    ft = b.get("face_types") or {}
    return bool(ft.get("mesh"))


def topology(ctx: ToolContext, src: Path, bodies: list[str], work: Path) -> dict[str, dict[str, Any]]:
    """Faces and edges of each body, compacted."""
    cmds = []
    for b in bodies:
        cmds.append({"command": "model.faces", "params": {"body": b}})
        cmds.append({"command": "model.edges", "params": {"body": b}})
    script = work / "topo.json"
    script.write_text(json.dumps({"commands": cmds}))
    rc, out, err = run_cli(ctx, ["run", str(script), "--in", str(src), "--results"])
    if rc != 0:
        raise ToolError("engine_failed", f"Could not list faces and edges: {clean_stderr(err)}",
                        "Topology needs solid (B-rep) bodies; mesh files (STL/3MF/OBJ) have none.")
    res = parse_json(out, "listing faces and edges")
    topo: dict[str, dict[str, Any]] = {}
    for i, b in enumerate(bodies):
        faces = res[2 * i].get("faces", []) if isinstance(res[2 * i], dict) else []
        edges = res[2 * i + 1].get("edges", []) if isinstance(res[2 * i + 1], dict) else []
        cf = []
        for f in faces:
            item: dict[str, Any] = {"index": f.get("index"), "name": f.get("name"), "point": r(f.get("point")),
                                    "area_mm2": r(f.get("area"), 2)}
            if f.get("plane_normal"):
                item["normal"] = r(f["plane_normal"])
            if f.get("cylinder"):
                c = f["cylinder"]
                item["cylinder"] = {"radius": r(c.get("radius")), "axis": r(c.get("axis")), "origin": r(c.get("origin"))}
            cf.append(item)
        ce = [{"index": e.get("index"), "name": e.get("name"), "mid": r(e.get("mid")), "length_mm": r(e.get("length")),
               "start": r(e.get("start")), "end": r(e.get("end"))} for e in edges]
        topo[b] = {"faces": cf, "edges": ce}
    return topo


Detail = Literal["summary", "full", "topology"]


class InspectIn(ToolInput):
    file: Annotated[InputFile, FileConstraints(extensions=ALL_INPUT_EXTS)] = Field(
        description="The design or model: SolidCraft .sc/.solidcraft, STEP/STP, IGES, STL, 3MF or OBJ.")
    detail: Detail = Field(default="summary", description="summary: parameters, features, bodies, sketches. full: "
                           "also sketch-dimension parameters and (for .sc) the design's full history as a command "
                           "script file. topology: also every face and edge (names, a point on each face, edge "
                           "midpoints, cylinder radii) — the picks fillet, chamfer, shell and measure_features take.")


class InspectOut(ToolOutput):
    file_kind: Literal["design", "cad", "mesh"]
    body_count: int
    total_volume_mm3: float | None
    total_area_mm2: float | None
    bbox_mm: dict[str, Any] | None
    bodies: list[dict[str, Any]]
    parameters: list[dict[str, Any]]
    features: list[dict[str, Any]]
    failing_features: list[dict[str, Any]]
    sketches: list[dict[str, Any]]
    topology: dict[str, Any] | None = Field(default=None, description="Per body faces/edges (only with detail="
                                            "'topology' and when small enough; always in topology.json).")


@tool(kind="inspect", title="Inspect a design, STEP or mesh file", timeout_s=180,
      examples=[{"arguments": {"file": "part.step"}}, {"arguments": {"file": "box.sc", "detail": "topology"}}])
def inspect_design(args: InspectIn, ctx: ToolContext) -> ToolResult[InspectOut]:
    """Use when the user gives a CAD or mesh file and asks what's in it (size, volume, weight, parameters), or after build_part/change_parameters to verify. Returns parameters, timeline features with errors and warnings, bodies with volume, area, centre of mass, bounding box and face/edge counts, and sketches with their free degrees of freedom. detail='topology' adds every face and edge (a point on each face, edge midpoints, cylinder radii) — the exact picks fillet, chamfer, shell and measure_features need."""
    ext = check_input_ext(args.file, set(ALL_INPUT_EXTS))
    kind: Literal["design", "cad", "mesh"] = "design" if is_design(args.file) else (
        "mesh" if ext in (".stl", ".3mf", ".obj") else "cad")
    work = workdir("inspect")
    src = staged_copy(args.file, work / "in")
    ctx.progress(10, "reading the file")
    ev = eval_file(ctx, src)
    bodies = ev.get("bodies", []) or []
    feats = feature_list(ev)
    sketches = [{"name": s.get("name"), "dof": s.get("dof"), "status": s.get("status"), "profiles": s.get("profiles")}
                for s in ev.get("sketches", []) or []]
    outputs: list[OutputFile] = []
    uncertain: list[str] = []
    full = ctx.output_path("inspect.json")
    full.write_text(json.dumps(ev, indent=1))
    outputs.append(OutputFile(full, "The engine's full measurement and timeline report."))
    if args.detail in ("full", "topology") and kind == "design":
        rc, out, err = run_cli(ctx, ["script", str(src)])
        if rc == 0 and out.strip():
            sp = ctx.output_path("design_script.json")
            sp.write_text(out)
            outputs.append(OutputFile(sp, "The design's history as a command script (replayable steps)."))
        else:
            uncertain.append("The design's history could not be written as a script.")
    topo_inline = None
    if args.detail == "topology":
        solid = [b["name"] for b in bodies if not _is_mesh_body(b)]
        if not solid:
            uncertain.append("No solid (B-rep) bodies: mesh files have no faces or edges to pick.")
        else:
            ctx.progress(50, "listing faces and edges")
            topo = topology(ctx, src, solid, work)
            tp = ctx.output_path("topology.json")
            tp.write_text(json.dumps(topo, indent=1))
            outputs.append(OutputFile(tp, "Every face (name, point on it, normal or cylinder) and edge (midpoint, "
                                          "length) per body."))
            compact = {b: {"faces": t["faces"],
                           "edges": [{k: e[k] for k in ("index", "name", "mid", "length_mm")} for e in t["edges"]]}
                       for b, t in topo.items()}
            if len(json.dumps(compact)) <= 9000:
                topo_inline = compact
            else:
                uncertain.append("Topology is large; read it from topology.json.")
    if kind == "mesh":
        uncertain.append("Mesh file: volumes come from triangles, there are no parameters, features or exact faces.")
    for b in bodies:
        if b.get("closed") is False:
            uncertain.append(f"Body {b.get('name')} is open (not watertight), so it has no volume.")
    failing = [f for f in feats if f.get("error")]
    data = InspectOut(
        file_kind=kind, body_count=len(bodies), total_volume_mm3=total_volume(ev),
        total_area_mm2=r((ev.get("total") or {}).get("area_mm2")), bbox_mm=union_bbox(bodies),
        bodies=[body_summary(b) for b in bodies],
        parameters=user_params(ev, include_model=args.detail != "summary"),
        features=feats if len(feats) <= 60 else feats[:60], failing_features=failing, sketches=sketches[:60],
        topology=topo_inline)
    if len(feats) > 60:
        uncertain.append(f"Only the first 60 of {len(feats)} features are listed inline; all are in inspect.json.")
    bb = data.bbox_mm
    size = "×".join(f"{v:g}" for v in bb["size"]) if bb else "?"
    return ToolResult(
        data=data, outputs=outputs, uncertain=uncertain,
        status="partial" if failing else "ok",
        summary=f"{args.file.name}: {len(bodies)} body(ies), volume {data.total_volume_mm3} mm³, size {size} mm, "
                f"{len(data.parameters)} parameter(s), {len(feats)} feature(s), {len(failing)} failing.")


# ---------------------------------------------------------------------------------------------------------------


class Pick(ToolInput):
    kind: Literal["face", "edge", "vertex"] = Field(description="What to measure: face (a hole's wall, a flat "
                                                    "side), edge, or vertex (a corner).")
    point: list[float] | None = Field(default=None, min_length=3, max_length=3,
                                      description="[x, y, z] in mm on or near the item (from inspect_design "
                                                  "detail='topology': a face's point, an edge's mid).")
    name: str | None = Field(default=None, description="Instead of point: the face or edge name from "
                             "inspect_design detail='topology', e.g. 'F2:top' or 'F3:bore:side:0'.")
    body: str | None = Field(default=None, description="Body name; needed only when the file has several bodies.")


class MeasureIn(ToolInput):
    file: Annotated[InputFile, FileConstraints(extensions=[".sc", ".solidcraft", ".step", ".stp", ".iges", ".igs"])] = (
        Field(description="The design (.sc) or STEP/IGES file to measure."))
    items: list[Pick] = Field(min_length=1, max_length=2, description="One pick (its size: diameter, length, area) "
                              "or two (distance and angle between them).")


class MeasureOut(ToolOutput):
    items: list[dict[str, Any]]
    min_distance_mm: float | None = Field(default=None, description="Closest distance between the two picks "
                                          "(wall-to-wall for two holes; the thickness for two parallel faces).")
    max_distance_mm: float | None = Field(default=None, description="Farthest distance between the two picks.")
    center_distance_mm: float | None = Field(default=None, description="Axis-to-axis distance between two round "
                                             "items (hole spacing); None when either pick isn't round.")
    angle_deg: float | None = None


_KEEP = ("type", "length_mm", "area_mm2", "diameter", "radius", "center", "axis", "planar", "round", "position",
         "arc_length", "angle_deg", "circumference", "slot")


@tool(kind="measure", title="Measure holes, faces, edges and distances", timeout_s=120,
      examples=[{"arguments": {"file": "box.sc", "items": [{"kind": "face", "point": [5, 0, 10]}]}},
                {"arguments": {"file": "box.sc", "items": [{"kind": "face", "point": [0, 15, 10]},
                                                           {"kind": "face", "point": [0, -15, 10]}]}}])
def measure_features(args: MeasureIn, ctx: ToolContext) -> ToolResult[MeasureOut]:
    """Use to check one exact dimension: a hole's diameter, an edge's length, a wall's thickness, the distance or angle between two faces. Takes one or two picks, each a point on the item ([x,y,z] mm, from inspect_design detail='topology') or a face/edge name, and returns length, area, diameter/radius/centre/axis for round items, and min/max/centre distance and angle for two picks. Works on exact solids (.sc, STEP, IGES), not meshes."""
    check_input_ext(args.file, {".sc", ".solidcraft", ".step", ".stp", ".iges", ".igs"})
    work = workdir("measure")
    src = staged_copy(args.file, work / "in")
    ev = eval_file(ctx, src)
    bodies = [b["name"] for b in ev.get("bodies", []) or [] if not _is_mesh_body(b)]
    if not bodies:
        raise ToolError("no_solid", "The file has no solid bodies to measure.",
                        "Use inspect_design for mesh files (volume and size only), or pass a .sc or STEP file.")
    picks: list[dict[str, Any]] = []
    topo: dict[str, Any] | None = None
    for i, p in enumerate(args.items):
        body = p.body
        if body is None:
            if len(bodies) > 1:
                raise ToolError("ambiguous_body", f"Pick {i} names no body and the file has {len(bodies)}: "
                                f"{', '.join(bodies[:20])}.", "Add \"body\" to each pick with one of these names.")
            body = bodies[0]
        elif body not in bodies:
            raise ToolError("unknown_body", f"Pick {i}: there is no solid body named '{body}'. Bodies: "
                            f"{', '.join(bodies[:20])}.", "Use one of the listed body names.")
        point = p.point
        if point is None:
            if not p.name:
                raise ToolError("invalid_input", f"Pick {i} has neither point nor name.",
                                "Give each pick a point [x,y,z] on the item, or a face/edge name from "
                                "inspect_design detail='topology'.")
            if topo is None:
                topo = topology(ctx, src, bodies, work)
            if p.kind == "face":
                hit = next((f for f in topo[body]["faces"] if f["name"] == p.name), None)
                point = hit["point"] if hit else None
            elif p.kind == "edge":
                hit = next((e for e in topo[body]["edges"] if e["name"] == p.name), None)
                point = hit["mid"] if hit else None
            else:
                raise ToolError("invalid_input", f"Pick {i}: a vertex is picked by point, not by name.",
                                "Give the vertex as point [x,y,z] (an edge's start or end from topology).")
            if point is None:
                raise ToolError("unknown_name", f"Pick {i}: body {body} has no {p.kind} named '{p.name}'.",
                                "Call inspect_design detail='topology' and copy a name from its faces or edges.")
        picks.append({"type": p.kind, "body": body, "point": [float(v) for v in point]})
    script = work / "measure.json"
    script.write_text(json.dumps({"commands": [{"command": "inspect.measure", "params": {"items": picks}}]}))
    rc, out, err = run_cli(ctx, ["run", str(script), "--in", str(src), "--results"])
    if rc != 0:
        se = parse_step_error(err)
        reason = se["error"] if se else clean_stderr(err)
        raise ToolError("pick_failed", f"The measurement failed: {reason}",
                        "Move the point onto the item: use a face's 'point' or an edge's 'mid' from inspect_design "
                        "detail='topology' (a face's centroid can fall inside a hole).")
    res = parse_json(out, "measuring")
    m = res[0] if isinstance(res, list) and res else {}
    items = []
    for it in m.get("items", []) or []:
        items.append({k: r(v, 4) for k, v in it.items() if k in _KEEP})
    data = MeasureOut(items=items)
    parts = []
    if len(picks) == 2:
        data.min_distance_mm = r(m.get("min", m.get("distance_mm")), 4)
        data.max_distance_mm = r(m.get("max"), 4)
        cd = m.get("center_distance")
        data.center_distance_mm = r(cd.get("distance_mm") if isinstance(cd, dict) else cd, 4)
        data.angle_deg = r(m.get("angle_deg"), 4)
        if data.center_distance_mm is not None:
            parts.append(f"centre-to-centre distance {data.center_distance_mm} mm")
        parts.append(f"min distance {data.min_distance_mm} mm (closest points)")
        if data.angle_deg is not None:
            parts.append(f"angle {data.angle_deg}°")
    for i, it in enumerate(items):
        if it.get("diameter") is not None:
            parts.append(f"item {i} Ø{it['diameter']} mm")
        elif it.get("length_mm") is not None:
            parts.append(f"item {i} length {it['length_mm']} mm")
        elif it.get("area_mm2") is not None:
            parts.append(f"item {i} area {it['area_mm2']} mm²")
    uncertain = []
    if any(it.get("type") != p["type"] for it, p in zip(items, picks)):
        uncertain.append("The engine measured a different kind of item than requested at one pick.")
    return ToolResult(data=data, uncertain=uncertain,
                      summary="Measured: " + ("; ".join(parts) if parts else "see items") + ".",
                      next_step="Points snap to the nearest face/edge/vertex: confirm each measured item is the one "
                                "you meant (its centre, axis or area) before reporting the number.")
