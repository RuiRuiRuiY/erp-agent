
import pytest

from app.agent.graph import build_graph
from app.mcp.client import get_mcp_tools


@pytest.mark.asyncio
async def test_mcp_integration():
    tools = await get_mcp_tools()
    assert len(tools) == 10
    graph = await build_graph(tools=tools)
    assert "call_model" in graph.nodes
    assert "tools" in graph.nodes
