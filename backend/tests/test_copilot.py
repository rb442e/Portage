import json

from app import store
from app.copilot import agent, tools
from app.copilot.redact import Redactor
from app.copilot.tools import REGISTRY, ToolContext, apply_proposal, execute

CTX = ToolContext(conversation_id="t1")


def run(name, args):
    return execute(REGISTRY[name], CTX, args)


def test_redactor_roundtrip_and_stream():
    r = Redactor(True)
    masked = r.to_model("ping a.b@corp.com and A.B@corp.com token=abc123")
    assert "corp.com" not in masked and "<redacted_secret>" in masked
    assert masked.count("<email_1>") == 2
    assert r.from_model("hi <email_1>") == "hi a.b@corp.com"
    s = r.stream()
    out = s.feed("hi <ema") + s.feed("il_1> bye") + s.flush()
    assert out == "hi a.b@corp.com bye"
    assert Redactor(False).to_model("x@y.com") == "x@y.com"


def test_lookup_versions_diff_restore(client):
    first = store.save_lookup({"name": "Sprints", "kind": "sprint", "entries": {"S1": "1"}})
    lid = first["id"]
    store.save_lookup({"id": lid, "name": "Sprints", "kind": "sprint", "entries": {"S1": "1", "S2": "2"}})
    versions = client.get(f"/api/lookups/{lid}/versions").json()
    assert [v["version"] for v in versions] == [2, 1]
    diff = client.get(f"/api/lookups/{lid}/diff", params={"from_version": 1}).json()
    assert diff["added"] == {"S2": "2"}
    restored = client.post(f"/api/lookups/{lid}/restore/1").json()
    assert restored["entries"] == {"S1": "1"}


def test_preexisting_lookup_gets_baseline():
    # simulate a row created before versioning existed
    from app.store import _conn, _lock
    with _lock, _conn() as conn:
        conn.execute("INSERT INTO lookups (id, name, kind, side, entries) VALUES (50,'Old','team','rally_to_jira','{\"A\":\"1\"}')")
    store.save_lookup({"id": 50, "name": "Old", "kind": "team", "entries": {"A": "1", "B": "2"}})
    assert [v["version"] for v in store.list_versions("lookup", 50)] == [2, 1]
    assert store.get_version("lookup", 50, 1)["payload"]["entries"] == {"A": "1"}


def test_catalog_upsert_proposal_requires_apply():
    result, proposal = run("propose_catalog_upsert", {
        "kind": "sprint", "entries": [{"source": "Sprint 24", "target": "1042"}], "note": "add"})
    assert result["status"] == "proposal_created" and proposal["status"] == "pending"
    assert store.list_lookups("sprint") == []  # nothing written yet
    applied = apply_proposal(proposal)
    assert applied["entries"] == 1
    assert store.list_lookups("sprint")[0]["entries"] == {"Sprint 24": "1042"}
    # same request again is a no-op and reported as such
    again, none = run("propose_catalog_upsert", {"kind": "sprint", "entries": [{"source": "Sprint 24", "target": "1042"}]})
    assert "error" in again and none is None


def test_nested_args_sent_as_json_strings_are_accepted():
    res, p = run("propose_catalog_upsert", {"kind": "sprint", "entries": '[{"source": "S9", "target": "9"}]'})
    assert p and p["preview"]["diff"]["added"] == {"S9": "9"}


def test_catalog_restore_via_tool():
    _, p = run("propose_catalog_upsert", {"kind": "team", "entries": [{"source": "A", "target": "1"}]})
    apply_proposal(p)
    _, p2 = run("propose_catalog_upsert", {"kind": "team", "entries": [{"source": "B", "target": "2"}]})
    apply_proposal(p2)
    _, p3 = run("propose_catalog_restore", {"kind": "team", "version": 1})
    apply_proposal(p3)
    assert store.list_lookups("team")[0]["entries"] == {"A": "1"}


def test_mapping_edit_creates_new_version_not_overwrite():
    res, p = run("propose_mapping_edit", {
        "artifact": "user story",
        "operations": [{"action": "set", "target": "Sprint", "sources": ["Iteration"]},
                       {"action": "remove", "target": "labels"}]})
    assert p and "sprint" in json.dumps(p["preview"]["diff"])
    first = apply_proposal(p)
    assert first["name"] == "jira_us_mapping_v1"
    _, p2 = run("propose_mapping_edit", {
        "artifact": "User Story", "base_mapping_id": first["id"],
        "operations": [{"action": "set", "target": "story_points", "sources": ["Plan Estimate", "Name"]}]})
    second = apply_proposal(p2)
    assert second["name"] == "jira_us_mapping_v2" and second["id"] != first["id"]
    saved = store.get_mapping(first["id"])
    assert [m for m in saved["profiles"]["User Story"] if m["target"] == "sprint"]  # v1 untouched


def test_mapping_edit_validation_errors_are_recoverable():
    res, p = run("propose_mapping_edit", {
        "artifact": "Epic", "operations": [{"action": "set", "target": "nope", "sources": ["Name"]}]})
    assert p is None and "Valid target fields" in res["error"]
    res, p = run("propose_mapping_edit", {"artifact": "Epic", "operations": []})
    assert "Invalid arguments" in res["error"]


def test_find_unmapped_values_and_source_id_guard():
    from app.config import settings
    sid = "a" * 32
    (settings.upload_dir / f"{sid}.csv").write_text("Iteration,Owner\nSprint 1,a@x.com\nSprint 2,b@x.com\nSprint 2,\n")
    _, p = run("propose_catalog_upsert", {"kind": "sprint", "entries": [{"source": "sprint 1", "target": "1"}]})
    apply_proposal(p)
    res, _ = run("find_unmapped_values", {"source_id": sid, "kind": "sprint"})
    assert res["unmapped"] == [{"value": "Sprint 2", "count": 2}]
    bad, _ = run("describe_source", {"source_id": "../../etc/passwd"})
    assert bad["source_id"] == sid  # malformed ids are ignored, never used as a path
    default, _ = run("find_unmapped_values", {"kind": "sprint"})  # omitted id -> latest upload
    assert default["source_id"] == sid
    nulls, _ = run("find_unmapped_values", {"kind": "sprint", "source_id": "null", "column": "null"})
    assert nulls["source_id"] == sid


class FakeLLM:
    """Scripted model: first turn calls a tool using a placeholder email, second turn answers."""
    turns = 0

    def __init__(self, *a, **k):
        pass

    def chat_stream(self, messages, tools_):
        FakeLLM.turns += 1
        if FakeLLM.turns == 1:
            assert not any("@" in str(m.get("content")) for m in messages)  # emails masked
            yield {"type": "tool_calls", "calls": [{"name": "propose_catalog_upsert", "arguments": {
                "kind": "user", "entries": [{"source": "Jane", "target": "<email_1>"}]}}]}
        else:
            yield {"type": "token", "text": "Proposed for <email_"}
            yield {"type": "token", "text": "1>."}


def test_agent_loop_redacts_and_creates_proposal(monkeypatch):
    monkeypatch.setattr(agent, "OllamaClient", FakeLLM)
    FakeLLM.turns = 0
    events = list(agent.run_chat("Add jane@corp.com as Jane to the user catalog", "", {"route": "/lookups"}))
    types = [e["type"] for e in events]
    assert types[0] == "meta" and "proposal" in types and types[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "token") == "Proposed for jane@corp.com."
    proposal = next(e for e in events if e["type"] == "proposal")["proposal"]
    assert proposal["args"]["entries"][0]["target"] == "jane@corp.com"
    assert store.list_lookups("user") == []  # still not applied


def test_apply_endpoint_and_readonly_mode(client):
    _, p = run("propose_catalog_upsert", {"kind": "version", "entries": [{"source": "R1", "target": "1.0"}]})
    client.put("/api/copilot/settings", json={"mode": "readonly"})
    assert client.post(f"/api/copilot/proposals/{p['id']}/apply").status_code == 403
    client.put("/api/copilot/settings", json={"mode": "propose"})
    ok = client.post(f"/api/copilot/proposals/{p['id']}/apply")
    assert ok.status_code == 200 and ok.json()["proposal"]["status"] == "applied"
    assert client.post(f"/api/copilot/proposals/{p['id']}/apply").status_code == 409


def test_docs_search(client):
    res, _ = run("search_docs", {"query": "mapping version naming"})
    assert res["results"] and "jira_" in json.dumps(res)


def test_schemas_are_flat_for_the_model():
    schema = tools.REGISTRY["propose_mapping_edit"].schema()["function"]["parameters"]
    assert "$ref" not in json.dumps(schema) and "title" not in json.dumps(schema)
