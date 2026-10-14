"""MCP server: tool exposure, governance (propose-only, read-only mode, redaction, audit) and a real stdio session."""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app import product_settings, store
from app.copilot import settings as cfg_mod
from app.copilot.tools import REGISTRY
from app.mcp_server import McpGateway

BACKEND = Path(__file__).resolve().parents[1]
STORY_EDIT = {"artifact": "User Story", "version_name": "v1",
              "operations": [{"action": "set", "target": "sprint", "sources": ["Iteration"]}]}


def test_every_registry_tool_is_exposed_with_schema_and_hints():
    tools = {t.name: t for t in McpGateway().tools()}
    assert set(tools) == set(REGISTRY)
    assert "graph_search" in tools and not any("apply" in n for n in tools)      # approval is never an MCP action
    assert tools["graph_search"].inputSchema["required"] == ["query"]
    assert tools["list_mappings"].annotations.readOnlyHint is True
    assert tools["propose_mapping_edit"].annotations.readOnlyHint is False
    assert tools["propose_mapping_edit"].annotations.destructiveHint is False


def test_write_tool_only_proposes_and_a_person_applies_it_in_portage(client):
    gw = McpGateway()
    text, is_error = gw.call("propose_mapping_edit", STORY_EDIT)
    out = json.loads(text)
    assert not is_error and out["status"] == "proposal_created" and "cannot be applied through MCP" in out["review"]
    assert store.list_mappings() == []                                         # nothing written by the agent

    (proposal,) = store.list_proposals(gw.conv_id)
    assert proposal["status"] == "pending"
    conv = client.get(f"/api/copilot/conversations/{gw.conv_id}").json()       # visible in Ask Sora > History
    assert conv["messages"][-1]["meta"]["proposals"] == [proposal["id"]]

    assert client.post(f"/api/copilot/proposals/{proposal['id']}/apply").status_code == 200
    assert [m["name"] for m in store.list_mappings()] == ["jira_us_mapping_v1"]


def test_readonly_mode_hides_and_refuses_write_tools():
    cfg_mod.update({"mode": "readonly"})
    gw = McpGateway()
    assert not any(t.name.startswith("propose_") for t in gw.tools())
    text, is_error = gw.call("propose_mapping_edit", STORY_EDIT)
    assert is_error and "unavailable" in json.loads(text)["error"]
    assert store.list_proposals(gw.conv_id) == []


def test_errors_are_returned_to_the_agent_not_raised():
    gw = McpGateway()
    text, is_error = gw.call("get_job", {"job_id": "nope"})
    assert is_error and "not found" in json.loads(text)["error"]
    text, is_error = gw.call("propose_mapping_edit", {"artifact": "Epic", "operations": []})
    assert is_error and "Invalid arguments" in json.loads(text)["error"]
    text, is_error = gw.call("does_not_exist", {})
    assert is_error


def test_emails_are_masked_for_the_agent_and_restored_in_arguments():
    store.save_lookup({"name": "Users", "kind": "user", "entries": {"Jane": "jane.doe@example.com"}})
    gw = McpGateway()
    text, _ = gw.call("get_catalog_entries", {"kind": "user"})
    assert "jane.doe@example.com" not in text
    placeholder = re.search(r"<email_\d+>", text).group(0)

    text, is_error = gw.call("propose_catalog_upsert", {"kind": "user", "entries": [{"source": "Bob", "target": placeholder}]})
    assert not is_error
    (proposal,) = store.list_proposals(gw.conv_id)
    assert proposal["args"]["entries"][0]["target"] == "jane.doe@example.com"  # real value reaches the reviewer

    product_settings.update("mcp", {"redact": False})
    text, _ = gw.call("get_catalog_entries", {"kind": "user"})
    assert "jane.doe@example.com" in text


def test_every_call_is_audited_under_the_mcp_session():
    gw = McpGateway()
    gw.call("list_mappings", {})
    gw.call("graph_overview", {})
    events = [(a["event"], a["tool"]) for a in store.list_audit() if a["conversation_id"] == gw.conv_id]
    assert ("tool", "list_mappings") in events and ("tool", "graph_overview") in events and ("chat", "") in events


def test_real_stdio_session_lists_and_calls_tools():
    data_dir = tempfile.mkdtemp(prefix="portage-mcp-")
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "app.mcp_server"], cwd=str(BACKEND),
        env={**os.environ, "PORTAGE_DATA_DIR": data_dir, "PYTHONPATH": str(BACKEND)})

    async def run():
        with anyio.fail_after(60):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    tools = await session.list_tools()
                    overview = await session.call_tool("graph_overview", {})
                    bad = await session.call_tool("get_job", {"job_id": "nope"})
                    return init, tools, overview, bad

    init, tools, overview, bad = anyio.run(run)
    assert init.serverInfo.name == "portage" and "propose_*" in init.instructions
    assert {"graph_search", "propose_catalog_upsert"} <= {t.name for t in tools.tools}
    assert not overview.isError and "artifacts" in json.loads(overview.content[0].text)
    assert bad.isError
