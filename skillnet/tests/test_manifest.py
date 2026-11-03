import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLANNED = {"find_cad_commands", "build_part", "change_parameters", "inspect_design", "measure_features",
           "render_views", "export_model"}


def _manifest():
    p = subprocess.run([sys.executable, "-m", "skillnet_sdk", "manifest", "--package", "tools"], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_every_planned_tool_is_declared_with_a_description():
    tools = {t["name"]: t for t in _manifest()}
    assert set(tools) == PLANNED
    for t in tools.values():
        assert t["description"].startswith("Use "), t["name"]
        assert len(t["title"]) <= 60


def test_skill_yaml_matches_manifest_when_present():
    y = ROOT / "skill.yaml"
    if not y.exists():
        return
    import yaml
    data = yaml.safe_load(y.read_text())
    names = {t["name"] if isinstance(t, dict) else t for t in data.get("tools", [])}
    assert names == PLANNED


def test_playbook_names_only_real_tools():
    text = (ROOT / "playbook" / "SKILL.md").read_text()
    for name in PLANNED:
        assert f"`{name}`" in text, name
