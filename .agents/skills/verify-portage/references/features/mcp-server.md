# Portage MCP server

## Sub-features

Initialization, tool discovery, and a read-only invocation.

## How to get to it (user POV)

External assistants launch `python -m app.mcp_server` over stdio. Connection configuration is available under Settings → MCP server → Connect an MCP client.

## Driving it with verify_portage.py

Run `run mcp`. The driver launches the actual server with a fresh data directory, initializes an MCP session, discovers tools, and calls `list_mappings`.

**Required evidence**

`stdio-result.json` must identify Portage, contain `list_mappings`, and show a successful empty mapping result for the fresh workspace. Tool count is recorded, not hard-coded. `stdio-stderr.log` captures failures.

## Gotchas

A paid-model quota failure is not a failed MCP handshake. Discovery alone does not prove invocation; this group performs both. This check intentionally uses empty workspace data and never reads the user's saved mappings.
