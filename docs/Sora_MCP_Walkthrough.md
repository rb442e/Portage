# Portage MCP walkthrough

The narrated video, `Sora_MCP_Walkthrough.mp4` (approximately 2 minutes 35 seconds, 1600 × 900), explains Portage's two MCP roles using the product UI and a live Parallel MCP connection.

## Chapters

1. **Two MCP roles:** Sora uses Portage's MCP client to call external servers. External assistants can connect to Portage's own MCP server over stdio.
2. **External server connection:** `parallel_search_mcp` connects to `https://search.parallel.ai/mcp` using Streamable HTTP.
3. **Tool discovery:** connection validation discovers `web_search` and `web_fetch`. Clicking a tool name reveals its description.
4. **Live search:** Sora sends a real search request to Parallel and displays the completed external tool activity and its answer.
5. **Tool access:** turn Web Search off and on independently of Web Fetch. Changes apply to Sora's next message. The server's **Available to Sora** switch controls access to the server as a whole.
6. **MCP client configuration:** copy the configuration for VS Code or another MCP client to connect that assistant to Portage's tools.

## How to interpret the demonstration

A **Connected** status confirms successful MCP initialization and tool discovery. It does not mean a web search has run. The Sora conversation's completed tool activity identifies the actual external tool invoked.

Individual tool settings and the server availability setting both affect which tools Sora can access. Portage also filters external tools according to its read-only policy. A server's read-only annotations are supplied by that server.

The demonstration uses a separate local data directory. Product responses and Parallel search results are live; explanatory title cards, chapter captions, and synthetic narration are added for the recording.

## Recording source

`demo/record_mcp.py` captures the browser, checks the completed Parallel search activity, verifies the saved disabled-tool setting, and assembles the narrated MP4. It requires an isolated Portage instance at `127.0.0.1:8132`, local Ollama, Playwright Chromium, `imageio-ffmpeg`, and macOS `say`.

## Accessibility and supporting files

The MP4 includes an optional English subtitle track. `Sora_MCP_Walkthrough.srt` provides the same captions separately, and `Sora_MCP_Transcript.md` includes the narration with chapter timestamps. Subtitle timings are generated from narration segments.

## Live Web Search and Web Fetch examples

Watch `Sora_MCP_Search_and_Fetch.mp4` for two additional Sora examples: search for the official MCP documentation by topic, then fetch a specific documentation page by URL. Both recorded requests produced successful results from their expected Parallel tools. `Sora_MCP_Search_and_Fetch.md` contains the transcript and exact prompts. `Sora_MCP_Examples_Validation.json` preserves the corresponding streamed tool-call and tool-result events.

The live validation exposed a local model encoding boolean arguments as strings. Portage now normalizes literal `true` and `false` strings when the external tool schema requires booleans. Restart your running backend to load this fix.
