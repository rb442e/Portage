# Sora: Web Search and Web Fetch examples

## 0:01 — Web Search + Web Fetch

Here are two real examples of Sora using Parallel MCP tools. Web Search finds information across the internet. Web Fetch reads the content at a specific URL. We will verify the tool used for each request.

## 0:15 — Enable both tools

In MCP settings, Parallel must be connected and available to Sora. Web Search and Web Fetch must both be enabled. Each switch controls one tool, and changes take effect on the next message.

## 0:27 — Find the official MCP documentation

First, ask Sora to search the web for the official Model Context Protocol documentation. This request supplies a topic. Parallel Web Search finds relevant pages and returns results that Sora can use in its answer.

## 0:57 — Look for the Web Search check mark

The completed activity names Parallel search MCP and Web Search. This confirms that Sora called the external search tool. The answer provides the official website and a short explanation.

## 1:09 — Read a specific URL

Next, start a new conversation and give Sora a specific page URL. Ask it to use Parallel Web Fetch and summarize the retrieved content. This request reads the selected page rather than searching for pages.

## 1:24 — Look for the Web Fetch check mark

The completed activity now names Web Fetch. Sora has retrieved the page through Parallel and used the returned content to write its summary. Both examples were executed live through Portage.

## 1:35 — Search to discover. Fetch to read.

Use Web Search when you have a question or topic. Use Web Fetch when you already have a URL. In both cases, check the completed tool activity, and control access using the individual tool switches in MCP settings.

## Copy these example prompts

**Web Search**

Search the web using Parallel for the official Model Context Protocol documentation. Return just the official URL and a one-sentence description.

**Web Fetch**

Use Parallel Web Fetch (web_fetch) to fetch https://modelcontextprotocol.org/docs/getting-started/intro . Summarize the page in two sentences based on the fetched content.

Both expected external tools returned successful tool results in the recorded Sora sessions.
