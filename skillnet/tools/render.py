"""render_views: PNG pictures of a part from standard views."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field
from skillnet_sdk import (FileConstraints, InputFile, OutputFile, ToolContext, ToolError, ToolInput, ToolOutput,
                          ToolResult, tool)

from ._engine import ALL_INPUT_EXTS, check_input_ext, clean_stderr, env_cpu, eval_file, run_cli, staged_copy, workdir

View = Literal["iso", "front", "back", "top", "bottom", "left", "right"]

# matplotlib (elev, azim) for the fallback; SolidCraft: front looks from -Y, right from +X, top from +Z.
_MPL_VIEWS = {"iso": (30, -60), "front": (0, -90), "back": (0, 90), "top": (90, -90), "bottom": (-90, -90),
              "left": (0, 180), "right": (0, 0)}


class RenderIn(ToolInput):
    file: Annotated[InputFile, FileConstraints(extensions=ALL_INPUT_EXTS)] = Field(
        description="The part to draw: .sc design, STEP, IGES, STL, 3MF or OBJ.")
    views: list[View] = Field(default_factory=lambda: ["iso", "front", "top", "right"], min_length=1, max_length=7,
                              description="Views to draw: iso, front, back, top, bottom, left, right "
                                          "(default iso, front, top, right).")
    width: int = Field(default=1024, ge=256, le=2560, description="Picture width in pixels (256-2560).")
    height: int = Field(default=768, ge=256, le=2560, description="Picture height in pixels (256-2560).")
    grid: bool = Field(default=True, description="Draw the ground grid at Z=0 (turn off for clean pictures).")


class ViewInfo(ToolOutput):
    view: str
    file: str
    renderer: str
    pixel_stddev: float


class RenderOut(ToolOutput):
    views: list[ViewInfo]
    renderer_used: str
    contact_sheet: str | None


def _stddev(path: Path) -> float:
    from PIL import Image, ImageStat  # noqa: PLC0415

    with Image.open(path) as im:
        st = ImageStat.Stat(im.convert("L"))
        return round(float(st.stddev[0]), 2)


def _engine_snapshot(ctx: ToolContext, src: Path, out: Path, view: str, w: int, h: int, grid: bool,
                     cpu: bool) -> str | None:
    cli = ["snapshot", str(src), "--out", str(out), "--view", view, "--width", str(w), "--height", str(h)]
    if not grid:
        cli += ["--no-grid", "--no-axes"]
    try:
        rc, so, _ = run_cli(ctx, cli, timeout_s=120, extra_env=env_cpu() if cpu else None)
    except ToolError as exc:
        if exc.code == "engine_missing":
            raise
        return None
    if rc != 0 or not out.exists() or out.stat().st_size == 0:
        return None
    try:
        info = json.loads(so)
        return str(info.get("renderer") or ("cpu" if cpu else "solidcraft"))
    except json.JSONDecodeError:
        return "cpu" if cpu else "solidcraft"


def _fallback_render(mesh_path: Path, out: Path, view: str, w: int, h: int) -> None:
    import matplotlib  # noqa: PLC0415

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    import trimesh  # noqa: PLC0415
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: PLC0415

    m = trimesh.load(str(mesh_path), force="mesh")
    tris = m.triangles
    if len(tris) > 200000:
        tris = tris[:: math.ceil(len(tris) / 200000)]
    normals = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = normals / np.where(n == 0, 1, n)
    light = np.array([0.4, -0.6, 0.7])
    light = light / np.linalg.norm(light)
    shade = 0.35 + 0.65 * np.clip(normals @ light, 0, 1)
    colors = np.stack([shade * 0.62, shade * 0.66, shade * 0.72, np.ones_like(shade)], axis=1)
    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
    ax = fig.add_axes((-0.15, -0.15, 1.3, 1.3), projection="3d")
    ax.add_collection3d(Poly3DCollection(tris, facecolors=colors, edgecolors="none"))
    lo, hi = m.bounds
    c = (lo + hi) / 2
    span = float(max(hi - lo)) / 2 or 1.0
    ax.set_xlim(c[0] - span, c[0] + span)
    ax.set_ylim(c[1] - span, c[1] + span)
    ax.set_zlim(c[2] - span, c[2] + span)
    ax.set_box_aspect((1, 1, 1))
    elev, azim = _MPL_VIEWS[view]
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    ax.set_title(view, fontsize=10)
    fig.savefig(out, dpi=100, facecolor="white")
    plt.close(fig)


def _contact_sheet(paths: list[tuple[str, Path]], out: Path) -> None:
    from PIL import Image, ImageDraw  # noqa: PLC0415

    ims = [(v, Image.open(p).convert("RGB")) for v, p in paths]
    tw = 512
    thumbs = []
    for v, im in ims:
        th = im.resize((tw, max(1, int(im.height * tw / im.width))))
        ImageDraw.Draw(th).text((8, 6), v, fill=(20, 20, 20))
        thumbs.append(th)
    cols = 2 if len(thumbs) > 1 else 1
    rows = math.ceil(len(thumbs) / cols)
    hmax = max(t.height for t in thumbs)
    sheet = Image.new("RGB", (cols * tw, rows * hmax), "white")
    for i, t in enumerate(thumbs):
        sheet.paste(t, ((i % cols) * tw, (i // cols) * hmax))
    sheet.save(out)


@tool(kind="export", title="Render pictures of a part", timeout_s=300,
      examples=[{"arguments": {"file": "bracket.sc", "views": ["iso", "top"]}}])
def render_views(args: RenderIn, ctx: ToolContext) -> ToolResult[RenderOut]:
    """Use when the user wants to see the part or you need to visually check a build (a hole in the right place, a fillet on the right edge). Renders viewport-style PNGs of a design, CAD or mesh file from standard views (iso, front, back, top, bottom, left, right), headless, plus a contact sheet of all views. If the CAD renderer fails it falls back to a simpler shaded mesh picture and says so in uncertain. Not for photorealistic product renders."""
    check_input_ext(args.file, set(ALL_INPUT_EXTS))
    work = workdir("render")
    src = staged_copy(args.file, work / "in")
    ev = eval_file(ctx, src)
    if not (ev.get("bodies") or []):
        raise ToolError("nothing_to_draw", f"'{args.file.name}' has no bodies to draw.",
                        "Build or pass a file that contains a solid or mesh body.")
    views = list(dict.fromkeys(args.views))
    infos: list[ViewInfo] = []
    outputs: list[OutputFile] = []
    uncertain: list[str] = []
    mesh_for_fallback: Path | None = None
    stem = src.stem
    for k, v in enumerate(views):
        ctx.progress(10 + 80 * k / len(views), f"drawing {v}")
        out = ctx.output_path(f"{stem}_{v}.png")
        renderer = _engine_snapshot(ctx, src, out, v, args.width, args.height, args.grid, cpu=False)
        if renderer is None:
            renderer = _engine_snapshot(ctx, src, out, v, args.width, args.height, args.grid, cpu=True)
            if renderer is not None:
                uncertain.append(f"{v}: drawn by the engine's CPU rasterizer (simpler shading).")
        if renderer is None:
            if mesh_for_fallback is None:
                mesh_for_fallback = work / "fallback.stl"
                rc, _, err = run_cli(ctx, ["run", "--in", str(src), "--out", str(mesh_for_fallback)])
                if rc != 0 or not mesh_for_fallback.exists():
                    raise ToolError("render_failed", f"The part could not be drawn: {clean_stderr(err)}",
                                    "Check the file with inspect_design; if it reads fine, use export_model and view "
                                    "the STL in another viewer.")
            _fallback_render(mesh_for_fallback, out, v, args.width, args.height)
            renderer = "fallback"
            uncertain.append(f"{v}: the CAD renderer failed here; this is a simpler shaded mesh picture.")
        sd = _stddev(out)
        if sd < 3.0:
            uncertain.append(f"{v}: the picture is almost uniform (pixel stddev {sd}); the part may be out of view.")
        infos.append(ViewInfo(view=v, file=out.name, renderer=renderer, pixel_stddev=sd))
        outputs.append(OutputFile(out, f"{v} view"))
    sheet_name = None
    if len(infos) > 1:
        sheet = ctx.output_path(f"{stem}_views_sheet.png")
        _contact_sheet([(i.view, ctx.output_path(i.file)) for i in infos], sheet)
        outputs.append(OutputFile(sheet, "All views on one sheet"))
        sheet_name = sheet.name
    used = sorted({i.renderer for i in infos})
    renderer_used = "fallback" if "fallback" in used else ("solidcraft-cpu" if "cpu" in used else "solidcraft")
    return ToolResult(
        data=RenderOut(views=infos, renderer_used=renderer_used, contact_sheet=sheet_name),
        outputs=outputs, uncertain=uncertain,
        summary=f"Rendered {len(infos)} view(s) of {args.file.name} ({', '.join(views)}) with {renderer_used}.",
        next_step="Look at the pictures yourself before describing them to the user (holes, fillets, orientation).")
