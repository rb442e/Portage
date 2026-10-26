# External MCP settings

## Sub-features

Remote connection testing, tool details, individual access, and server access.

## How to get to it (user POV)

Settings → MCP server → External MCP servers → Add server. Choose Remote server (Streamable HTTP), supply a name and URL, test, and save. Click a tool name for details; use its switch to change access.

## Driving it with verify_portage.py

Run `run tool-access` with Playwright available. The driver builds the current frontend, launches Portage and a real local HTTP MCP fixture, and follows this path through the browser.

**Required evidence**

Capture draft entry, completed connection test, expanded description, disabled state after reload, and the server availability switch. `remote-discovery.json` must show only the fixture's read-only tools and block its write-capable tool. `browser-trace.zip` records actions and snapshots. The server disable must persist in the API. HTTP process cleanup is recorded in `cleanup.json`.

## Gotchas

A checking spinner is not a completed test. One tool's switch must not disable another tool. This fixture group does not involve an LLM and cannot prove how Sora selects tools; run `sora-web` for that next-message check. Do not substitute API setters for the browser toggle journey.
