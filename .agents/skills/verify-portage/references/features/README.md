# Portage verification feature map

Select the smallest applicable group. For a local regression sweep, run `local`, then run the two explicit live groups if Sora behavior changed and Ollama/provider access is available.

| Feature | Driver group | Evidence |
|---|---|---|
| [Portage MCP server](mcp-server.md) | `mcp` | Initialization, tool discovery, real read call |
| [External MCP settings](mcp-settings.md) | `tool-access` | Browser trace, screenshots, persisted settings |
| [Sora external tools](sora-tools.md) | `sora-web`, `failed-fetch` | Real streamed tool events and generated answers |

Initial coverage excludes authentication, migrations, catalogs, uploads, and proposal approval. A successful sweep is not a claim that those features passed.
