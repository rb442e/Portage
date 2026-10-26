#!/usr/bin/env python3
"""Deterministic local MCP boundary fixture. Never contacts an external provider."""
import argparse
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, required=True)
args = parser.parse_args()
server = FastMCP('portage-verification-fixture', host='127.0.0.1', port=args.port,
                 stateless_http=True, json_response=True)


@server.tool(annotations=ToolAnnotations(readOnlyHint=True))
def lookup(query: str) -> str:
    """Return the verification query unchanged."""
    return 'VERIFIED_LOOKUP: ' + query


@server.tool(annotations=ToolAnnotations(readOnlyHint=True))
def failing_fetch(url: str) -> str:
    """Return an intentional retrieval failure for error-path verification."""
    raise ValueError('VERIFICATION_FETCH_FAILED: no page content was retrieved')


@server.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
def write_blocked(value: str) -> str:
    """This tool must never be exposed to Sora."""
    raise RuntimeError('Write-capable fixture must never run')


server.run(transport='streamable-http')
