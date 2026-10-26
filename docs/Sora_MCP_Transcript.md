# Portage MCP walkthrough — narration

## 0:00 — Portage + MCP

This walkthrough shows how Portage uses the Model Context Protocol. We will connect Sora to Parallel web search, inspect a real tool call, and control which external tools Sora can use.

## 0:12 — 01 / Two MCP roles

Portage has two MCP roles. As a client, it calls external MCP servers for Sora. As a server, it exposes Portage tools to external assistants, using standard input and output. These are separate connections.

## 0:27 — 02 / External servers

In Settings, select MCP server. The external server named parallel search MCP connects to search dot parallel dot A I, over Streamable HTTP. Connected means Portage successfully discovered its tools.

## 0:42 — 03 / Tool discovery

Click Web Search to inspect its description. Parallel provides Web Search for internet queries and Web Fetch for retrieving pages. Portage exposes tools that pass its read only policy. A connection test discovers tools; it does not run a search.

## 0:59 — 04 / Live web search

Now ask Sora to search the web. Portage selects the available search tool, sends the arguments to Parallel, and passes the returned results back to the model. The tool activity in the conversation identifies the server and tool used.

## 1:22 — 05 / Results and trace

The check mark records the completed external tool call. The response below is generated from the live search results. Use this activity trace to distinguish an actual search from a model answering from memory.

## 1:36 — 06 / Disable a tool

Turn off Web Search to remove it from Sora on its next message. The setting is saved immediately. Web Fetch stays enabled, so you can control each tool independently without deleting the server.

## 1:48 — 07 / Restore access

Turn Web Search back on to make it available again. The server level Available to Sora switch controls every tool from this server. The individual tool switches give you finer control.

## 2:00 — 08 / Connect an MCP client

The Connect an MCP client section shows configuration for Visual Studio Code and other clients. The client starts the Portage MCP server as a local process. Portage tools support your migration workflow, and proposed changes still require approval in Portage.

## 2:17 — Portage + Sora

You have seen live Parallel tool discovery, a real web search through Sora, individual tool controls, and configuration for connecting external MCP clients to Portage. Choose your servers, inspect their tools, and enable only what your team needs.

## Additional live examples

See [Web Search and Web Fetch examples](Sora_MCP_Search_and_Fetch.md) for a companion video transcript, exact prompts, and successful tool validation.
