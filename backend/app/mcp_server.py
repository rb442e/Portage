"""MCP server: exposes Portage's governed tool registry to external agents over stdio.

Run (from the repo root):
    PYTHONPATH=backend PORTAGE_DATA_DIR=backend/data .venv/bin/python -m app.mcp_server

Same guarantees as Sora, because it is the same registry:
- read tools run immediately; write tools only create a *proposal* that a human applies inside
  Portage. No apply tool is exposed, so an external agent can never change data on its own;
- Sora's read-only mode, or the MCP read-only setting, hides write tools; MCP redaction masks emails and
  secrets; the MCP settings can also switch access off or hide individual tools (Settings > MCP server);
- every call is audited and proposals appear in Ask Sora > History under an "MCP agent session".
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from typing import Any, Dict, List, Optional, Tuple

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from . import __version__, product_settings, store
from .copilot import knowledge
from .copilot.redact import Redactor
from .copilot.tools import REGISTRY, Tool, ToolContext, execute

INSTRUCTIONS = (
    "Portage is a Rally-to-Jira migration platform. Read tools return live data about mappings, catalogs, "
    "uploads and migration jobs; use graph_search to trace relationships and graph_overview for a summary. "
    "propose_* tools never change data: they create a proposal that a person must review and apply in Portage. "
    "Never claim a proposed change has been applied. Emails appear as <email_N> placeholders; use them as written."
)


class McpGateway:
    """Transport-independent logic: which tools are visible, and how a call is governed and audited."""

    def __init__(self) -> None:
        self.conv_id = f"mcp-{uuid.uuid4().hex[:8]}"
        self._redactor = Redactor(True)
        self._started = False

    def _visible(self) -> Dict[str, Tool]:
        policy = product_settings.mcp_policy()
        if not policy["enabled"]:
            return {}
        return {n: t for n, t in REGISTRY.items()
                if n not in policy["hidden_tools"] and (not policy["read_only"] or t.risk == "read")}

    def tools(self) -> List[types.Tool]:
        return [types.Tool(
            name=t.name, description=t.description, inputSchema=t.schema()["function"]["parameters"],
            annotations=types.ToolAnnotations(readOnlyHint=t.risk == "read", destructiveHint=False,
                                              openWorldHint=False)) for t in self._visible().values()]

    def _start(self) -> None:
        if self._started:
            return
        self._started = True
        store.ensure_conversation(self.conv_id, "MCP agent session")
        store.add_message(self.conv_id, "user", "External agent connected over MCP.")
        store.audit(self.conv_id, "chat", "", {"via": "mcp"})

    def call(self, name: str, arguments: Optional[Dict[str, Any]]) -> Tuple[str, bool]:
        """Run one tool call. Returns (text for the agent, is_error)."""
        tool = self._visible().get(name)
        if tool is None:
            disabled = not product_settings.mcp_policy()["enabled"]
            return json.dumps({"error": "MCP access is turned off in Portage settings" if disabled
                               else f"Unknown or unavailable tool '{name}'"}), True
        self._start()
        self._redactor.enabled = product_settings.mcp_policy()["redact"]
        args = self._redactor.obj_from_model(arguments or {})
        result, proposal = execute(tool, ToolContext(conversation_id=self.conv_id), args)
        ok = "error" not in result
        store.audit(self.conv_id, "tool", name, {"args": args, "ok": ok, "via": "mcp"})
        if proposal:
            store.add_message(self.conv_id, "assistant",
                              f"An external agent proposed: {proposal['preview'].get('title', name)}. "
                              f"{proposal['preview'].get('summary', '')}".strip(),
                              {"skill": "mcp", "tools": [name], "proposals": [proposal["id"]]})
            result = {**result, "review": "A person must review and apply this proposal in Portage "
                                          "(Ask Sora > History). It cannot be applied through MCP."}
        return self._redactor.to_model(json.dumps(result, default=str)), not ok


def create_server(gateway: Optional[McpGateway] = None) -> Server:
    gw = gateway or McpGateway()
    server: Server = Server("portage", version=__version__, instructions=INSTRUCTIONS)

    @server.list_tools()
    async def _list_tools() -> List[types.Tool]:
        return gw.tools()

    # Arguments are validated by the registry's Pydantic models, which also tolerate model quirks and
    # return corrective errors, so the SDK's strict JSON-schema pre-check is turned off.
    @server.call_tool(validate_input=False)
    async def _call_tool(name: str, arguments: Dict[str, Any]) -> types.CallToolResult:
        text, is_error = await anyio.to_thread.run_sync(gw.call, name, arguments)
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)], isError=is_error)

    return server


async def serve() -> None:
    store.init_db()
    knowledge.rebuild()
    server = create_server()
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)   # stdout is the protocol channel
    anyio.run(serve)


if __name__ == "__main__":
    main()
