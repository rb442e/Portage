"""Admin-managed external MCP servers are namespaced, opt-in and read-only in Sora."""
import json
import os
import sys
from pathlib import Path

import pytest

from app import product_settings, store
from app.copilot import agent, external_mcp

FIXTURE = Path(__file__).parent / "fixtures" / "external_mcp_server.py"


def server(name):
    return {"name": name, "command": sys.executable, "args": [str(FIXTURE)], "env": {}, "cwd": str(FIXTURE.parent)}


def configure(monkeypatch, *names):
    monkeypatch.setenv("PORTAGE_EXTERNAL_MCP_SERVERS", json.dumps([server(n) for n in names]))


def test_multiple_admin_servers_are_listed_without_exposing_commands(monkeypatch):
    configure(monkeypatch, "docs", "jira")
    assert external_mcp.names() == ["docs", "jira"]
    status = external_mcp.configured()
    assert [s["name"] for s in status] == ["docs", "jira"]
    assert all(s["status"] == "available" and s["tool_count"] == 1 and s["blocked_count"] == 2 for s in status)
    assert all("command" not in s and "cwd" not in s and "env" not in s for s in status)


def test_only_opted_in_readonly_tools_are_discovered_and_namespaced(monkeypatch):
    configure(monkeypatch, "docs", "jira")
    tools = external_mcp.discover(["docs"])
    assert [t.name for t in tools] == ["ext_docs__lookup"]
    assert tools[0].server == "docs" and tools[0].remote_name == "lookup"
    assert tools[0].schema["required"] == ["query"]


def test_external_read_tool_runs_through_stdio_and_bounds_result(monkeypatch):
    configure(monkeypatch, "docs")
    tool = external_mcp.discover(["docs"])[0]
    result = external_mcp.call(tool, {"query": "sprint catalog"})
    assert result["structured_content"] == {
        "server": "fixture", "query": "sprint catalog", "email": "external.person@example.com",
        "canary": None, "configured": None}
    assert result["summary"]


def test_child_only_receives_basic_environment_and_admin_overrides(monkeypatch):
    monkeypatch.setenv("PORTAGE_TEST_SECRET_CANARY", "do-not-forward")
    definition = server("docs")
    definition["env"] = {"FIXTURE_CONFIG": "explicit-admin-value"}
    monkeypatch.setenv("PORTAGE_EXTERNAL_MCP_SERVERS", json.dumps([definition]))
    tool = external_mcp.discover(["docs"])[0]
    result = external_mcp.call(tool, {"query": "test"})["structured_content"]
    assert result["canary"] is None
    assert result["configured"] == "explicit-admin-value"


def test_invalid_admin_config_fails_closed(monkeypatch):
    monkeypatch.setenv("PORTAGE_EXTERNAL_MCP_SERVERS", "not json")
    with pytest.raises(external_mcp.ExternalMcpError, match="not valid JSON"):
        external_mcp.names()
    monkeypatch.setenv("PORTAGE_EXTERNAL_MCP_SERVERS", json.dumps([server("../unsafe")]))
    with pytest.raises(external_mcp.ExternalMcpError, match="Server names"):
        external_mcp.names()
    duplicate = [server("docs"), server("docs")]
    monkeypatch.setenv("PORTAGE_EXTERNAL_MCP_SERVERS", json.dumps(duplicate))
    with pytest.raises(external_mcp.ExternalMcpError, match="unique"):
        external_mcp.names()


def test_invalid_admin_config_does_not_break_settings_api(client, monkeypatch):
    monkeypatch.setenv("PORTAGE_EXTERNAL_MCP_SERVERS", "not json")
    assert client.get("/api/settings").status_code == 200
    response = client.get("/api/settings/mcp/external-servers").json()
    assert response["servers"][0]["status"] == "invalid configuration"


def test_settings_api_lists_definitions_and_selected_servers(client, monkeypatch):
    configure(monkeypatch, "docs", "jira")
    body = client.get("/api/settings").json()
    mcp = next(s for s in body["sections"] if s["key"] == "mcp")
    field = next(f for f in mcp["fields"] if f["key"] == "external_servers")
    assert field["choices"] == ["docs", "jira"]
    assert client.get("/api/settings/mcp/external-servers").status_code == 200
    assert [s["name"] for s in client.get("/api/settings/mcp/external-servers").json()["servers"]] == ["docs", "jira"]
    saved = client.put("/api/settings/mcp", json={"values": {"external_servers": ["docs", "jira"]}})
    assert saved.status_code == 200
    assert saved.json()["effective_mcp"]["external_servers"] == ["docs", "jira"]
    assert client.put("/api/settings/mcp", json={"values": {"external_servers": ["unknown"]}}).status_code == 400


def test_agent_can_call_selected_external_tool_and_redacts_its_result(monkeypatch):
    configure(monkeypatch, "docs", "other")
    product_settings.update("mcp", {"external_servers": ["docs"]})

    class FakeLLM:
        turn = 0
        seen = []

        def __init__(self, *args, **kwargs):
            pass

        def chat_stream(self, messages, tools):
            FakeLLM.turn += 1
            FakeLLM.seen.append((messages, tools))
            if FakeLLM.turn == 1:
                names = [t["function"]["name"] for t in tools]
                assert "ext_docs__lookup" in names and "ext_other__lookup" not in names
                assert "ext_docs__mutate" not in names
                yield {"type": "tool_calls", "calls": [{"name": "ext_docs__lookup", "arguments": {"query": "sprint"}}]}
            else:
                assert "<email_1>" in messages[-1]["content"]
                assert "external.person@example.com" not in messages[-1]["content"]
                yield {"type": "token", "text": "I found the read-only result."}

    monkeypatch.setattr(agent, "OllamaClient", FakeLLM)
    events = list(agent.run_chat("Search the docs for sprint information", "", {"route": "/connections"}))
    assert any(e["type"] == "tool_result" and e["name"] == "ext_docs__lookup" and e["ok"] for e in events)
    assert any(e["type"] == "token" and "read-only result" in e["text"] for e in events)
    assert store.list_proposals("") == []
    audit = [a for a in store.list_audit() if a["event"] == "external_tool"]
    assert audit and audit[0]["tool"] == "ext_docs__lookup"


def test_external_server_write_tool_cannot_be_called_even_if_requested(monkeypatch):
    configure(monkeypatch, "docs")
    assert [t.name for t in external_mcp.discover(["docs"])] == ["ext_docs__lookup"]
    assert "mutate" not in json.dumps([t.llm_schema() for t in external_mcp.discover(["docs"])])
