"""find_cad_commands: search the engine's live command registry."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import Field
from skillnet_sdk import OutputFile, ToolContext, ToolError, ToolInput, ToolOutput, ToolResult, tool

from ._engine import parse_json, run_cli

_CACHE: dict[str, Any] = {}

# Words people use -> words in the registry.
_SYNONYMS = {
    "round": ["fillet"], "bevel": ["chamfer"], "hollow": ["shell"], "drill": ["hole"], "bore": ["hole"],
    "array": ["pattern"], "copy": ["pattern", "mirror"], "variable": ["parameters"], "param": ["parameters"],
    "parameter": ["parameters"], "dimension": ["dimension"], "pad": ["extrude"], "pocket": ["extrude", "cut"],
    "cut": ["cut", "extrude"], "revolve": ["revolve"], "lathe": ["revolve"], "cylinder": ["cylinder"],
    "rectangle": ["rectangle"], "square": ["rectangle"], "circle": ["circle"], "slot": ["slot"],
    "thread": ["thread"], "screw": ["thread", "hole"], "text": ["text"], "emboss": ["text", "emboss"],
}


class FindIn(ToolInput):
    query: str = Field(default="", description="Words matched against each command's id, label, toolbar tab and "
                       "panel, e.g. 'fillet', 'hole', 'sketch circle', 'pattern circular', 'parameter'. Empty lists "
                       "every command id and writes the full registry to a file.")
    limit: int = Field(default=12, ge=1, le=200, description="Most matches to return (1-200, default 12).")


class CommandInfo(ToolOutput):
    id: str
    label: str
    tab: str | None = None
    panel: str | None = None
    params_doc: str = Field(description="The engine's own parameter documentation for this command.")


class FindOut(ToolOutput):
    version: str
    total_commands: int
    match_count: int
    matches: list[CommandInfo]
    all_ids: list[str] | None = Field(default=None, description="Every command id (only when query is empty).")


def _registry(ctx: ToolContext) -> tuple[list[dict[str, Any]], str]:
    if "reg" not in _CACHE:
        rc, out, _ = run_cli(ctx, ["commands"], timeout_s=60)
        if rc != 0:
            raise ToolError("engine_failed", "The engine could not list its commands.",
                            "Try again once; if it repeats, report it to the skill owner.")
        reg = parse_json(out, "listing commands")
        rc2, ver, _ = run_cli(ctx, ["--version"], timeout_s=30)
        _CACHE["reg"] = reg
        _CACHE["ver"] = ver.strip() if rc2 == 0 else "unknown"
    return _CACHE["reg"], _CACHE["ver"]


def _score(cmd: dict[str, Any], words: list[str]) -> float:
    cid = cmd.get("id", "").lower()
    label = (cmd.get("label") or "").lower()
    where = f"{cmd.get('tab') or ''} {cmd.get('panel') or ''}".lower()
    params = str(cmd.get("params") or "").lower()
    total = 0.0
    for w in words:
        alts = [w, *_SYNONYMS.get(w, [])]
        best = 0
        for a in alts:
            if a == cid or cid.endswith("." + a):
                best = max(best, 12)
            elif re.search(rf"(^|[._]){re.escape(a)}($|[._])", cid):
                best = max(best, 8)
            elif re.search(rf"(^|[._]){re.escape(a)}", cid):
                best = max(best, 7)
            elif a in cid:
                best = max(best, 6)
            if a in label:
                best = max(best, 5)
            if a in where:
                best = max(best, 2)
            if best == 0 and a in params:
                best = 1
        if best == 0:
            return 0
        total += best
    # prefer modelling commands over view/render/ui ones
    top = cid.split(".")[0]
    if top == "solid":
        total += 2.5   # 'fillet' means the solid fillet before the sketch one
    elif top in ("sketch", "parameters"):
        total += 2
    return total


@tool(kind="inspect", title="Find CAD commands and their parameters", timeout_s=60,
      examples=[{"arguments": {"query": "fillet"}}, {"arguments": {"query": "sketch circle", "limit": 5}}])
def find_cad_commands(args: FindIn, ctx: ToolContext) -> ToolResult[FindOut]:
    """Use before writing build steps, when you need the exact command id and parameters for a CAD operation (sketch rectangle/circle, extrude, fillet, chamfer, hole, shell, pattern, mirror, parameters). Searches the CAD engine's live command registry and returns each match's id, label and the engine's own parameter docs. Start here if unsure how to express a feature, then call build_part."""
    reg, ver = _registry(ctx)
    words = [w for w in re.split(r"[\s,;/]+", args.query.lower().strip()) if w]
    outputs: list[OutputFile] = []
    if not words:
        path = ctx.output_path("command_registry.json")
        path.write_text(json.dumps(reg, indent=1, ensure_ascii=False))
        outputs.append(OutputFile(path, "The full command registry: every command id, label and parameter doc."))
        ids = sorted(c.get("id", "") for c in reg)
        return ToolResult(
            data=FindOut(version=ver, total_commands=len(reg), match_count=0, matches=[], all_ids=ids),
            summary=f"Listed all {len(reg)} CAD commands (full parameter docs in the registry file).",
            outputs=outputs,
            next_step="Search with a query (e.g. 'extrude', 'hole') to get a command's parameter docs inline.")
    scored = sorted(((s, c) for c in reg if (s := _score(c, words)) > 0),
                    key=lambda sc: (-sc[0], sc[1].get("id", "")))
    picked = scored[: args.limit]
    matches: list[CommandInfo] = []
    budget = 13000
    truncated = False
    for _, c in picked:
        doc = str(c.get("params") or "")
        if len(doc) > budget:
            doc = doc[: max(200, budget)] + " …(truncated; see command_matches.json)"
            truncated = True
        budget -= len(doc)
        matches.append(CommandInfo(id=c.get("id", ""), label=c.get("label") or "", tab=c.get("tab"),
                                   panel=c.get("panel"), params_doc=doc))
        if budget <= 0:
            break
    if truncated or len(matches) < len(picked):
        path = ctx.output_path("command_matches.json")
        path.write_text(json.dumps([c for _, c in picked], indent=1, ensure_ascii=False))
        outputs.append(OutputFile(path, "Full registry entries for every match."))
    if not matches:
        return ToolResult(
            data=FindOut(version=ver, total_commands=len(reg), match_count=0, matches=[]),
            summary=f"No CAD command matches '{args.query}'.",
            next_step="Try one plain word for the operation (e.g. 'extrude', 'fillet', 'hole', 'pattern', 'shell', "
                      "'rectangle', 'circle', 'parameters'), or an empty query to list every command id.")
    uncertain = []
    if len(matches) < len(picked):
        uncertain.append(f"Only the first {len(matches)} of {len(picked)} matches are inline (size limit); "
                         "the rest are in command_matches.json.")
    return ToolResult(
        data=FindOut(version=ver, total_commands=len(reg), match_count=len(scored), matches=matches),
        summary=f"{len(scored)} CAD command(s) match '{args.query}'; best: {matches[0].id}.",
        outputs=outputs, uncertain=uncertain)
