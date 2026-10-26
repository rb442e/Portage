---
name: verify-portage
description: Verify Portage runtime behavior after changes to MCP settings, Sora tool calling, or related UI. Runs isolated checks and preserves browser traces, protocol events, and results for regression investigations.
---

# Verify Portage

Use the executable driver in this skill to prove behavior against the current checkout. This is a developer skill; Sora's application skills live separately in `backend/app/copilot/skills/`.

From the repository root:

```bash
backend/.venv/bin/python .agents/skills/verify-portage/scripts/verify_portage.py doctor
backend/.venv/bin/python .agents/skills/verify-portage/scripts/verify_portage.py run mcp
uv run --with playwright python .agents/skills/verify-portage/scripts/verify_portage.py run local
```

`local` runs stdio verification plus browser-driven MCP settings checks. Playwright and its Chromium runtime must be installed in the driver environment; the driver always launches Portage with `backend/.venv/bin/python`. It builds the current frontend into the evidence directory instead of using a potentially stale `frontend/dist`. On macOS, when only one Rollup native package architecture is installed, the driver launches Node in that architecture to avoid Rosetta inheritance from the browser Python environment.

Read [the feature index](references/features/README.md), then the relevant feature file. Use `--help` for options; global options go before `run`, for example `--output /tmp/portage-proof-unique run mcp`. The output path must be new. Without `--output`, a unique directory is created under the system temporary directory.

## Live Sora verification

Run these when the change concerns model-driven behavior and local Ollama is available:

```bash
backend/.venv/bin/python .agents/skills/verify-portage/scripts/verify_portage.py run sora-web
backend/.venv/bin/python .agents/skills/verify-portage/scripts/verify_portage.py run failed-fetch
```

`sora-web` sends public sample prompts through the real Sora API, calls the live Parallel endpoint, and checks successful search/fetch events and disabled-search behavior. It requires internet access and an installed Ollama model supporting tool calls (`llama3.1:8b` by default). It can consume external provider allowance. `failed-fetch` uses a local HTTP fixture that always fails retrieval and the real local model; inspect the resulting answer for unsupported page claims.

## Interpret results

- Exit 0: the selected automated checks passed. Only claim the behaviors listed in `report.json`.
- Exit 1: a behavior assertion or runtime operation failed; inspect the case artifacts.
- Exit 2: a prerequisite was unavailable. This is blocked, not a pass.
- Exit 3: tool failure was observed but the generated explanation requires review. Inspect `failed-fetch-events.json`; record whether it clearly explains the failure without claiming page contents. A review-required run is not an automated pass.

A server connection/discovery result is not proof of tool execution. For Sora, inspect `tool_call` and successful `tool_result` events for the exact expected tool. A local fixture proves protocol and product behavior against that fixture; it does not establish live provider availability. Generated answer accuracy remains a separate assessment.

## Isolation and evidence

The driver creates fresh Portage data, binds owned processes to loopback on ephemeral ports, and removes inherited Portage overrides. Authentication is disabled only for that private disposable instance. It never connects to the user's running Portage or applies migration proposals. Do not redirect it to production data.

Each run writes `report.json`; individual checks retain protocol results, HTTP/MCP discovery responses, screenshots, browser traces, and process logs as applicable. Launched HTTP processes stop in `finally`; `cleanup.json` records their exit state. The stdio client closes its child process through the MCP SDK context manager. Evidence survives cleanup. Temporary directories persist for inspection and can later be removed by their owner.

When a check fails, reproduce it with the same group, fix only the demonstrated cause, and rerun that group. Keep feature instructions aligned with changed UI labels and routes. Broader migration and catalog journeys are outside this initial feature map.

The verification structure is informed by Lauren Tan's [pstack verification approach](https://github.com/cursor/plugins/blob/main/pstack/skills/create-verification-skill/SKILL.md). This skill is implemented for Portage and does not install pstack or require Cursor.
