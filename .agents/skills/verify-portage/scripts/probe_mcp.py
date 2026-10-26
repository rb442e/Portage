#!/usr/bin/env python3
"""Use the real MCP SDK to initialize Portage, list tools, and read mappings."""
import json
import os
import sys
import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    with anyio.fail_after(20):
        params = StdioServerParameters(command=sys.executable, args=['-m', 'app.mcp_server'], env=dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                names = [tool.name for tool in tools.tools]
                if 'list_mappings' not in names:
                    raise RuntimeError('Portage did not expose list_mappings')
                result = await session.call_tool('list_mappings', {})
                if result.isError:
                    raise RuntimeError('list_mappings returned an MCP error')
                payload = json.loads(''.join(c.text for c in result.content if c.type == 'text'))
                if not isinstance(payload.get('mappings'), list) or payload.get('count') != 0:
                    raise RuntimeError('Expected the isolated workspace to contain no saved mappings')
                print(json.dumps({'server': init.serverInfo.name, 'tools': names, 'read_result': payload}))


anyio.run(main)
