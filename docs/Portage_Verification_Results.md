# Portage verification — 2026-10-23

The official `pstack@cursor-plugins` plugin, version **0.15.30**, is installed and enabled in the local Codex configuration. The source is `https://github.com/cursor/plugins.git`; Codex installed its Claude-compatible package. Cursor-specific capabilities are not guaranteed to work in Codex. No model-role configuration or autonomous merge workflow was enabled.

The project-local skill is [.agents/skills/verify-portage/SKILL.md](../.agents/skills/verify-portage/SKILL.md). It follows pstack's verification workflow with executable drivers and a focused feature map. It is separate from Sora's application skill files.

## Results

| Check | Result | Evidence directory |
|---|---|---|
| Portage stdio initialization, discovery, and real read call | Passed; 23 tools discovered and `list_mappings` executed against a fresh workspace | `/tmp/portage-proof-local-passed/mcp/` |
| Browser-driven external MCP settings | Passed; draft test, discovery, details, read-only policy, individual toggle persistence, re-enable, and server availability | `/tmp/portage-proof-local-passed/tool-access/` |
| Live Sora → Parallel search and fetch | Passed; both expected tools returned successful results | `/tmp/portage-proof-sora-web/sora-web/` |
| Disabled Web Search on the next Sora request | Passed; no call to the disabled tool | `/tmp/portage-proof-sora-web/sora-web/disabled-search-events.json` |
| Intentional fetch failure through Sora | **Failed**; Sora selected the internal `search_docs` tool rather than the external `failing_fetch` tool | `/tmp/portage-proof-failed-fetch/failed-fetch/failed-fetch-events.json` |
| Unavailable Ollama handling | Passed; the driver returns exit 2 and `blocked` instead of passing | `/tmp/portage-proof-unavailable-provider/` |
| Frontend navigation regression tests | 5 passed | `backend/tests/test_frontend_navigation.py` |
| Skill metadata validation | Passed | Skill Creator `quick_validate.py` |

Temporary evidence is local to this machine and can be removed by the owner later. Each HTTP run records owned-process termination in `cleanup.json`. Browser runs preserve `browser-trace.zip`, screenshots, backend logs, and discovery responses.

## Defect corrected during verification

Refreshing `/settings` with the built frontend served by the backend returned 404. The backend now serves `index.html` for browser navigation to extensionless frontend routes. Missing APIs, asset paths, and non-navigation requests remain errors. The browser's reload/persistence journey passed after this fix.

The driver also needed to launch macOS Node in the architecture matching the installed Rollup native dependency. An Intel browser-Python environment otherwise selected the Intel Node slice despite an Apple Silicon frontend dependency installation. No dependencies or lockfiles were replaced.

## Open Sora issue

The failed-fetch prompt was:

> Use the failing_fetch tool to retrieve https://example.com and summarize its content. If retrieval fails, explain the failure.

The saved events show a successful internal documentation search followed by an answer describing Portage. The intended failed-retrieval path was never exercised. This is a failed check, not evidence that Sora handles failed retrieval correctly. The isolated fixture was discovered successfully and its HTTP logs are preserved. Investigate routing/model selection using that evidence; do not change the test to accept the unrelated tool call.

When a future run actually invokes the failing tool and receives an error, the driver returns `review_required` until its answer is assessed for truthful failure handling. It does not automatically infer answer correctness from text keywords.

## Scope

These checks do not establish correctness of unrelated migrations, catalog edits, authentication, approval flows, all model phrasings, or the factual accuracy of generated web answers. Live provider availability and model behavior can vary between runs. See the skill for the exact commands and feature coverage.
