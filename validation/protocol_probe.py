"""Real stdio MCP discovery/calls without model inference or external credentials."""
import asyncio
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def main():
    async with Client(StdioServerParameters(command=sys.executable,
                                            args=['/app/mcp_server.py'])) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} == {
            'validation_list_targets', 'validation_validate_pascode'}
        result = await client.call_tool('validation_validate_pascode',
                                        {'target': 'cdt', 'family': 'jira-as-code'})
        report = result.structured_content
        assert report['conforms'] and report['files'] == 10, report
        print('PASS real stdio MCP: discovered 2 read-only tools; CDT Jira 10 files passed')


if __name__ == '__main__':
    asyncio.run(main())
