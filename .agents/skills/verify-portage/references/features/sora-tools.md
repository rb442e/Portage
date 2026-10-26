# Sora external tool calls

## Sub-features

Live search, live URL fetch, disabled tools, and retrieval failures.

## How to get to it (user POV)

Enable the external server and its tools in MCP settings. Open Sora and ask for a web search or fetch a specific URL. The conversation shows tool activity and an answer.

## Driving it with verify_portage.py

Run `run sora-web` for real Ollama → Sora → Parallel calls. It verifies search, URL fetch, then disables Web Search and confirms that the next turn does not invoke it. Settings changes in this group use the API; the separate `tool-access` group verifies the UI.

Run `run failed-fetch` for a local MCP retrieval failure and a real Sora response. This group always returns review-required if the failure was exercised; inspect the response before accepting its behavior.

**Required evidence**

For search and fetch, saved SSE events must contain the exact namespaced tool and `ok: true`. For disabled search, the next turn must not invoke that tool. A generated answer without tool evidence is insufficient.

For failure, verify the intentional failing tool executed with `ok: false`, then review whether the answer explains that retrieval failed and avoids unsupported claims about the page. Record the conclusion alongside the events. Absence of a successful result does not, by itself, prove truthful failure handling.

## Gotchas

Ollama availability, installed models, Parallel availability, argument formats, and rate limits can affect results. Provider/transport failure is distinct from a model choosing the wrong tool. Use the saved events to locate the boundary. These public prompts do not validate unrelated factual answers or all possible user phrasings.
