"""Tiny local stdio MCP server used by test_external_mcp.py."""
from __future__ import annotations

import anyio
import os
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

server = Server("portage-test-fixture")


@server.list_tools()
async def list_tools():
    return [
        types.Tool(name="lookup", description="Read-only fixture lookup", inputSchema={
            "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                   annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False)),
        types.Tool(name="mutate", description="Write-capable fixture tool", inputSchema={
            "type": "object", "properties": {"value": {"type": "string"}}},
                   annotations=types.ToolAnnotations(readOnlyHint=False, destructiveHint=True)),
        types.Tool(name="unspecified", description="No safety annotation", inputSchema={
            "type": "object", "properties": {}}, annotations=None),
    ]


@server.call_tool(validate_input=False)
async def call_tool(name: str, arguments):
    if name == "lookup":
        return {"server": "fixture", "query": arguments.get("query", ""), "email": "external.person@example.com",
            "canary": os.environ.get("PORTAGE_TEST_SECRET_CANARY"), "configured": os.environ.get("FIXTURE_CONFIG")}
    return {"unexpected_write": True}


async def run():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    anyio.run(run)
