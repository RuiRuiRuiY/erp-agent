
import asyncio

from app.agent.graph import build_graph
from app.agent.mcp_client import get_mcp_tools


def test_mcp_integration():
    tools = asyncio.run(get_mcp_tools())
    assert len(tools) == 10
    graph = build_graph(tools=tools)
    assert "call_model" in graph.nodes
    assert "tools" in graph.nodes
