import json

from conftest import assert_error, run
from tools.commands import find_cad_commands


def test_fillet_query_returns_solid_fillet_with_docs(tmp_path):
    env, _ = run(find_cad_commands, {"query": "fillet"}, tmp_path)
    assert env["status"] == "ok"
    data = env["data"]
    assert data["total_commands"] > 300
    ids = [m["id"] for m in data["matches"]]
    assert ids[0] == "solid.fillet", ids
    doc = data["matches"][0]["params_doc"]
    assert "edges" in doc and "radius" in doc


def test_multiword_and_synonym_queries(tmp_path):
    env, _ = run(find_cad_commands, {"query": "sketch circle", "limit": 5}, tmp_path)
    ids = [m["id"] for m in env["data"]["matches"]]
    assert "sketch.circle.center" in ids
    assert len(ids) <= 5
    env, _ = run(find_cad_commands, {"query": "parameter"}, tmp_path)
    ids = [m["id"] for m in env["data"]["matches"]]
    assert "parameters.add" in ids and "parameters.change" in ids


def test_empty_query_lists_all_ids_and_writes_registry(tmp_path):
    env, outs = run(find_cad_commands, {"query": ""}, tmp_path)
    assert env["status"] == "ok"
    all_ids = env["data"]["all_ids"]
    assert {"solid.extrude", "solid.fillet", "sketch.create", "solid.hole"} <= set(all_ids)
    reg = [p for n, p in outs.items() if n.endswith(".json")]
    assert reg, outs
    content = json.loads(reg[0].read_text())
    assert len(content) == env["data"]["total_commands"]


def test_nonsense_query_has_no_matches_and_a_next_step(tmp_path):
    env, _ = run(find_cad_commands, {"query": "zzqxv flurble"}, tmp_path)
    assert env["status"] == "ok"
    assert env["data"]["match_count"] == 0
    assert "extrude" in env["next_step"]


def test_limit_out_of_range_is_rejected(tmp_path):
    env, _ = run(find_cad_commands, {"query": "hole", "limit": 0}, tmp_path)
    assert env["status"] == "error"
