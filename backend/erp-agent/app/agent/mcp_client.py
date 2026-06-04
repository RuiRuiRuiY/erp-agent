from __future__ import annotations

from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

_tools: list[Any] | None = None
_client: MultiServerMCPClient | None = None


async def get_mcp_tools() -> list[Any]:
    global _tools, _client
    if _tools is None:
        _client = MultiServerMCPClient(
            {
                "mcp-erp-server": {
                    "command": "python",
                    "args": ["-m", "app.mcp.server"],
                    "transport": "stdio",
                },
            }
        )
        _tools = await _client.get_tools()
    return _tools
