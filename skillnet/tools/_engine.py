"""Shared helpers: run solidcraft-cli headless, parse its JSON and errors, check meshes."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from skillnet_sdk import ToolContext, ToolError

CLI = "solidcraft-cli"
ENGINE = "solidcraft"

DESIGN_EXTS = {".sc", ".solidcraft"}
CAD_EXTS = {".step", ".stp", ".iges", ".igs"}
MESH_EXTS = {".stl", ".3mf", ".obj"}
ALL_INPUT_EXTS = sorted(DESIGN_EXTS | CAD_EXTS | MESH_EXTS)

EXPORT_EXT = {"step": ".step", "iges": ".iges", "stl": ".stl", "3mf": ".3mf", "obj": ".obj"}

# Commands that open, save, export, upload or read files by path, or touch app settings.
# The tools do all file input/output themselves, so build steps may not.
_BLOCKED_PREFIXES = ("file.", "doc.", "library.", "settings.", "ui.", "render.", "diagnostics.", "plugin")
_BLOCKED_IDS = {
    "component.insert_design", "component.relink", "component.extract", "component.replace_with_link",
    "component.edit_in_place", "component.paste_from_design", "canvas.insert", "canvas.decal",
    "pointcloud.insert", "inspect.compare_picture", "motion.export", "motion.export_animation",
}
_PATH_ARG_IDS = {
    "timeline.export_script", "parameters.export", "parameters.import", "sheet.export_dxf",
    "sheet.export_bend_table", "sketch.export_dxf", "sketch.insert_dxf", "sketch.insert_svg",
    "sketch.drawing_bounds",
}

_STEP_ERR = re.compile(r"error: step (\d+) \(([^)]*)\): (.*)")


def _env() -> dict[str, str]:
    xdg = Path(tempfile.gettempdir()) / "solidcraft-xdg"
    xdg.mkdir(mode=0o700, exist_ok=True)
    return {"XDG_RUNTIME_DIR": str(xdg)}


def engine_available() -> bool:
    return shutil.which(CLI) is not None


def run_cli(ctx: ToolContext, args: list[str], timeout_s: float | None = None,
            extra_env: dict[str, str] | None = None) -> tuple[int, str, str]:
    """Run solidcraft-cli; return (exit code, stdout, stderr) without raising on failure."""
    if not engine_available():
        raise ToolError("engine_missing", "The SolidCraft engine is not installed in this environment.",
                        "Report this to the skill owner; no CAD tool can run without it.")
    env = _env()
    if extra_env:
        env.update(extra_env)
    proc = ctx.run([CLI, *args], engine=ENGINE, timeout_s=timeout_s, env=env, check=False)
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    return proc.returncode, out, err


def clean_stderr(err: str, limit: int = 600) -> str:
    lines = [ln for ln in err.splitlines() if ln.strip() and "XDG_RUNTIME_DIR" not in ln]
    text = " ".join(re.sub(r"^(error|warning):\s*", "", ln.strip()) for ln in lines)
    # never leak sandbox paths
    text = re.sub(r"/(?:tmp|workspace|skill)[^\s:'\"]*/([^/\s:'\"]+)", r"\1", text)
    return text[:limit]


def parse_step_error(err: str) -> dict[str, Any] | None:
    """`error: step 2 (solid.fillet): msg` -> {index: 1 (0-based), command, error}."""
    for ln in err.splitlines():
        m = _STEP_ERR.search(ln)
        if m:
            return {"index": int(m.group(1)) - 1, "command": m.group(2), "error": clean_stderr(m.group(3), 400)}
    return None


def parse_failed_features(err: str) -> list[dict[str, str]]:
    """Lines after 'timeline feature(s) failed': '  Name: message'."""
    out: list[dict[str, str]] = []
    lines = err.splitlines()
    for i, ln in enumerate(lines):
        if "timeline feature(s) failed" in ln:
            for nxt in lines[i + 1:]:
                if not nxt.startswith("  "):
                    break
                name, _, msg = nxt.strip().partition(": ")
                out.append({"name": name, "error": clean_stderr(msg, 300)})
    return out


def parse_json(text: str, what: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolError("engine_failed", f"The engine returned unreadable output while {what}.",
                        "Try again once; if it repeats, simplify the input file.") from exc


def check_input_ext(path: Path, allowed: set[str] | list[str], role: str = "file") -> str:
    ext = path.suffix.lower()
    if ext not in allowed:
        raise ToolError(
            "unsupported_format",
            f"The {role} '{path.name}' has extension '{ext or '(none)'}', which this tool doesn't open.",
            f"Pass one of: {', '.join(sorted(allowed))}. Native SolidWorks/Fusion/Inventor/Onshape files must be "
            "exported to STEP in that program first.")
    return ext


def staged_copy(src: Path, work: Path, name: str | None = None) -> Path:
    """Copy an input to a work dir with a safe name, keeping its extension."""
    work.mkdir(parents=True, exist_ok=True)
    stem = safe_name(name or src.stem, "input")
    dst = work / f"{stem}{src.suffix.lower()}"
    shutil.copyfile(src, dst)
    return dst


def safe_name(name: str, default: str = "part") -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "").strip("._-")
    return (s or default)[:60]


def eval_file(ctx: ToolContext, path: Path, script: Path | None = None) -> dict[str, Any]:
    """Run `solidcraft-cli eval` on a design/CAD/mesh file and return the parsed JSON."""
    args = ["eval", str(script), "--in", str(path)] if script else ["eval", str(path)]
    rc, out, err = run_cli(ctx, args)
    if rc != 0:
        msg = clean_stderr(err) or "the engine could not read it"
        raise ToolError("unreadable_file", f"'{path.name}' could not be opened: {msg}",
                        "Check that the file is a complete SolidCraft design (.sc), STEP, IGES, STL, 3MF or OBJ; "
                        "re-export it from the program that made it and upload it again.")
    data = parse_json(out, "reading the design")
    if not isinstance(data, dict):
        raise ToolError("engine_failed", "The engine's measurement had an unexpected shape.",
                        "Try again once; if it repeats, report the file to the skill owner.")
    return data


def r(x: Any, nd: int = 3) -> Any:
    if isinstance(x, float):
        v = round(x, nd)
        return 0.0 if v == 0 else v
    if isinstance(x, list):
        return [r(v, nd) for v in x]
    return x


def bbox_of(b: dict[str, Any] | None) -> dict[str, Any] | None:
    if not b or "min" not in b or "max" not in b:
        return None
    mn, mx = b["min"], b["max"]
    return {"min": r(mn), "max": r(mx), "size": r([mx[i] - mn[i] for i in range(3)])}


def union_bbox(bodies: list[dict[str, Any]]) -> dict[str, Any] | None:
    boxes = [b.get("bbox") for b in bodies if b.get("bbox")]
    if not boxes:
        return None
    mn = [min(bx["min"][i] for bx in boxes) for i in range(3)]
    mx = [max(bx["max"][i] for bx in boxes) for i in range(3)]
    return bbox_of({"min": mn, "max": mx})


def body_summary(b: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": b.get("name"),
        "volume_mm3": r(b.get("volume_mm3")) if b.get("volume_mm3") is not None else None,
        "area_mm2": r(b.get("area_mm2")),
        "center_of_mass": r(b.get("center_of_mass")) if b.get("center_of_mass") else None,
        "bbox_mm": bbox_of(b.get("bbox")),
        "closed": b.get("closed"),
        "faces": b.get("faces"),
        "edges": b.get("edges"),
        "vertices": b.get("vertices"),
        "face_types": b.get("face_types"),
    }


def user_params(ev: dict[str, Any], include_model: bool = False) -> list[dict[str, Any]]:
    out = []
    for p in ev.get("params", []) or []:
        if p.get("model") and not include_model:
            continue
        out.append({"name": p.get("name"), "expression": p.get("expression"), "value": r(p.get("value")),
                    "unit": p.get("unit"), "error": p.get("error"),
                    **({"dimension": True} if p.get("model") else {})})
    return out


def feature_list(ev: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"name": t.get("name"), "type": t.get("type"), "error": t.get("error"), "warning": t.get("warning"),
             "suppressed": t.get("suppressed")} for t in ev.get("timeline", []) or []]


def total_volume(ev: dict[str, Any]) -> float | None:
    v = (ev.get("total") or {}).get("volume_mm3")
    return r(v) if v is not None else None


def validate_steps(raw: Any) -> list[dict[str, Any]]:
    """Accept a list, {"commands": [...]}, or a JSON string of either; return clean steps."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolError("invalid_input", f"The steps are not valid JSON: {exc.msg} at character {exc.pos}.",
                            "Pass steps as a JSON list of {\"command\": ..., \"params\": {...}} objects.") from exc
    if isinstance(raw, dict):
        if "commands" in raw:
            raw = raw["commands"]
        elif isinstance(raw.get("steps"), list):
            raw = raw["steps"]
        elif "command" in raw:
            raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise ToolError("invalid_input", "The steps must be a non-empty list of commands.",
                        "Pass steps like [{\"command\": \"solid.box\", \"params\": {\"length\": 40, \"width\": 30, "
                        "\"height\": 20}}].")
    if len(raw) > 2000:
        raise ToolError("invalid_input", f"{len(raw)} steps is more than the 2000 allowed in one call.",
                        "Build in stages: pass the .sc from one call as start_from of the next.")
    steps = []
    for i, st in enumerate(raw):
        if not isinstance(st, dict) or not isinstance(st.get("command"), str):
            raise ToolError("invalid_steps", f"steps[{i}] is not a {{command, params}} object.",
                            f"Fix step {i}: it needs a string 'command' and an object 'params'.")
        params = st.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ToolError("invalid_steps", f"steps[{i}] ({st['command']}): params must be an object.",
                            f"Fix step {i}: give params as a JSON object, e.g. {{\"distance\": 20}}.")
        cmd = st["command"].strip()
        blocked = cmd.startswith(_BLOCKED_PREFIXES) or cmd in _BLOCKED_IDS or (
            cmd in _PATH_ARG_IDS and any(k in params for k in ("path", "dir")))
        if blocked:
            raise ToolError("invalid_steps",
                            f"steps[{i}] ({cmd}) opens, saves, exports or sends files, which build steps can't do.",
                            f"Remove step {i}: the tool saves the design and exports files itself (use the `formats` "
                            "argument or export_model); pass existing geometry as start_from.")
        steps.append({"command": cmd, "params": params})
    return steps


def mesh_check(path: Path, brep_volume: float | None) -> dict[str, Any]:
    """Load a mesh with trimesh and check it's printable."""
    import trimesh  # noqa: PLC0415

    m = trimesh.load(str(path), force="mesh")
    if m is None or not hasattr(m, "faces") or len(m.faces) == 0:
        return {"file": path.name, "readable": False}
    if path.suffix.lower() == ".obj":
        m.merge_vertices(merge_norm=True, merge_tex=True)
    try:
        shells = len(m.split(only_watertight=False))
    except Exception:  # noqa: BLE001 - graph engine missing; count is optional
        shells = None
    vol = float(m.volume)
    diff = None
    if brep_volume:
        diff = round(abs(vol - brep_volume) / brep_volume * 100.0, 4)
    b = m.bounds
    return {
        "file": path.name,
        "readable": True,
        "watertight": bool(m.is_watertight),
        "winding_consistent": bool(m.is_winding_consistent),
        "shells": shells,
        "volume_mm3": r(vol),
        "brep_volume_mm3": r(brep_volume) if brep_volume else None,
        "volume_diff_pct": diff,
        "bbox_mm": bbox_of({"min": b[0].tolist(), "max": b[1].tolist()}),
        "triangles": int(len(m.faces)),
    }


def workdir(prefix: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=f"sc-{prefix}-"))


def env_cpu() -> dict[str, str]:
    return {"SOLIDCRAFT_GPU": "cpu"}


def is_design(path: Path) -> bool:
    return path.suffix.lower() in DESIGN_EXTS


def osenv(name: str) -> str | None:
    return os.environ.get(name)
