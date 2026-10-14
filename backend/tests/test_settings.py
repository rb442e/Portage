"""Product settings: precedence, validation, legacy compatibility, MCP policy and the API."""
import json

import pytest

from app import product_settings as ps
from app import store
from app.copilot import graph
from app.copilot.tools import REGISTRY, ToolContext, execute
from app.mcp_server import McpGateway


def sources(section):
    return {k: s for k, (_, s) in ps._resolve(ps._section(section)).items()}


def test_defaults_and_sections():
    assert [s.key for s in ps.SECTIONS] == ["sora", "mcp", "graph"]
    assert ps.get("mcp") == {"enabled": True, "read_only": False, "redact": True, "hidden_tools": []}
    assert ps.get("graph") == {"default_depth": 2, "max_nodes": 24}
    assert set(sources("sora").values()) == {"default"}


def test_precedence_saved_over_env_over_default_and_reset(monkeypatch):
    monkeypatch.setenv("PORTAGE_COPILOT_MODEL", "env-model")
    assert ps.get("sora")["model"] == "env-model" and sources("sora")["model"] == "env"
    ps.update("sora", {"model": "saved-model"})
    assert ps.get("sora")["model"] == "saved-model" and sources("sora")["model"] == "saved"
    ps.reset("sora", "model")
    assert ps.get("sora")["model"] == "env-model"
    monkeypatch.delenv("PORTAGE_COPILOT_MODEL")
    assert ps.get("sora")["model"] == "llama3.1:8b"


def test_unchanged_values_are_not_pinned(monkeypatch):
    ps.update("sora", {"max_steps": 6, "redact": True})                    # equal to the defaults
    assert set(sources("sora").values()) == {"default"}
    monkeypatch.setenv("PORTAGE_OLLAMA_URL", "http://gpu-box:11434/")
    assert ps.get("sora")["base_url"] == "http://gpu-box:11434"            # still follows the environment


@pytest.mark.parametrize("section,patch,message", [
    ("sora", {"mode": "yolo"}, "must be one of"),
    ("sora", {"max_steps": "many"}, "whole number"),
    ("sora", {"base_url": "  "}, "cannot be empty"),
    ("mcp", {"read_only": "maybe"}, "true or false"),
    ("mcp", {"hidden_tools": ["nope"]}, "unknown nope"),
    ("mcp", {"bogus": 1}, "Unknown setting"),
])
def test_invalid_values_are_rejected_and_nothing_is_saved(section, patch, message):
    with pytest.raises(ValueError, match=message):
        ps.update(section, patch)
    assert set(sources(section).values()) == {"default"}


def test_numbers_are_clamped_and_text_is_normalised():
    assert ps.update("sora", {"max_steps": 99})["max_steps"] == 12
    assert ps.update("graph", {"default_depth": 0})["default_depth"] == 1
    assert ps.update("sora", {"base_url": "http://h:1/"})["base_url"] == "http://h:1"
    assert ps.update("mcp", {"read_only": "yes"})["read_only"] is True


def test_settings_saved_by_the_previous_version_still_apply():
    store.set_setting("copilot_settings", json.dumps(
        {"enabled": True, "base_url": "http://old:11434/", "model": "old", "mode": "readonly", "redact": False, "max_steps": 3}))
    cfg = ps.get("sora")
    assert (cfg["mode"], cfg["redact"], cfg["max_steps"], cfg["base_url"]) == ("readonly", False, 3, "http://old:11434")
    store.set_setting("copilot_settings", json.dumps({"mode": "garbage"}))
    assert ps.get("sora")["mode"] == "propose"                              # invalid saved value is ignored


def test_changes_are_audited():
    ps.update("mcp", {"read_only": True})
    ps.reset("mcp", "read_only")
    events = [(a["event"], a["tool"]) for a in store.list_audit()]
    assert ("settings_changed", "mcp") in events and ("settings_reset", "mcp") in events


def test_mcp_is_never_more_permissive_than_sora():
    assert ps.mcp_policy()["read_only"] is False
    ps.update("sora", {"mode": "readonly"})
    assert ps.mcp_policy()["read_only"] is True                             # follows Sora
    ps.update("sora", {"mode": "propose"})
    ps.update("mcp", {"read_only": True})
    assert ps.mcp_policy()["read_only"] is True                             # stricter on its own


def test_mcp_settings_shape_what_the_gateway_exposes():
    gw = McpGateway()
    ps.update("mcp", {"hidden_tools": ["get_job", "propose_catalog_remove"]})
    names = {t.name for t in gw.tools()}
    assert "get_job" not in names and "propose_catalog_remove" not in names and "list_jobs" in names
    text, is_error = gw.call("get_job", {"job_id": "x"})
    assert is_error and "unavailable" in json.loads(text)["error"]

    ps.update("mcp", {"read_only": True})
    assert not any(n.startswith("propose_") for n in {t.name for t in gw.tools()})

    ps.update("mcp", {"enabled": False})
    assert gw.tools() == []
    text, is_error = gw.call("list_mappings", {})
    assert is_error and "turned off" in json.loads(text)["error"]
    assert store.list_proposals(gw.conv_id) == []


def test_mcp_redaction_is_its_own_setting():
    store.save_lookup({"name": "Users", "kind": "user", "entries": {"Jane": "jane.doe@example.com"}})
    ps.update("sora", {"redact": False})                                    # Sora's choice does not weaken MCP
    text, _ = McpGateway().call("get_catalog_entries", {"kind": "user"})
    assert "jane.doe@example.com" not in text
    ps.update("mcp", {"redact": False})
    text, _ = McpGateway().call("get_catalog_entries", {"kind": "user"})
    assert "jane.doe@example.com" in text


def test_graph_settings_drive_graph_search():
    ctx = ToolContext(conversation_id="s")
    ps.update("graph", {"max_nodes": 8, "default_depth": 1})
    res, _ = execute(REGISTRY["graph_search"], ctx, {"query": "sprint"})    # no depth: the setting applies
    assert "error" not in res
    assert res["stats"]["returned_nodes"] <= 8
    assert graph.search("sprint", depth=3)["stats"]["returned_nodes"] <= 8  # an explicit depth still honours the cap


def test_api_round_trip(client):
    body = client.get("/api/settings").json()
    assert [s["key"] for s in body["sections"]] == ["sora", "mcp", "graph"]
    mcp = next(s for s in body["sections"] if s["key"] == "mcp")
    hidden = next(f for f in mcp["fields"] if f["key"] == "hidden_tools")
    assert hidden["type"] == "multi" and "propose_mapping_edit" in hidden["choices"]
    assert any(i["label"] == "Data directory" for i in body["system"])

    out = client.put("/api/settings/mcp", json={"values": {"read_only": True, "hidden_tools": ["get_job"]}}).json()
    mcp = next(s for s in out["sections"] if s["key"] == "mcp")
    assert {f["key"]: (f["value"], f["source"]) for f in mcp["fields"]}["read_only"] == (True, "saved")
    assert out["effective_mcp"]["read_only"] is True and out["effective_mcp"]["hidden_tools"] == ["get_job"]

    assert client.put("/api/settings/mcp", json={"values": {"read_only": "x"}}).status_code == 400
    assert client.put("/api/settings/nope", json={"values": {}}).status_code == 404
    assert client.delete("/api/settings/mcp/read_only").json()["effective_mcp"]["read_only"] is False
    assert client.delete("/api/settings/mcp/zzz").status_code == 400
    client.delete("/api/settings/mcp")
    assert ps.get("mcp")["hidden_tools"] == []


def test_the_sora_panel_endpoint_and_the_settings_page_share_one_store(client):
    assert client.put("/api/copilot/settings", json={"mode": "readonly"}).json()["mode"] == "readonly"
    body = client.get("/api/settings").json()
    sora = next(s for s in body["sections"] if s["key"] == "sora")
    assert {f["key"]: f["value"] for f in sora["fields"]}["mode"] == "readonly" and body["effective_mcp"]["read_only"]
    assert client.put("/api/copilot/settings", json={"mode": "yolo"}).status_code == 400


def test_connection_snippets_are_valid_for_this_install(client):
    conn = client.get("/api/settings/mcp/connection").json()
    assert "app.mcp_server" in conn["shell"] and conn["transport"] == "stdio"
    vs, generic = json.loads(conn["vscode"]), json.loads(conn["generic"])
    assert vs["servers"]["portage"]["args"] == ["-m", "app.mcp_server"] == generic["mcpServers"]["portage"]["args"]
    assert "PORTAGE_DATA_DIR" in generic["mcpServers"]["portage"]["env"]
