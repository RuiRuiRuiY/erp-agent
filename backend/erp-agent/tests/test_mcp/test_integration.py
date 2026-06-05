
import asyncio

from app.agent.graph import compile_graph_with_tools
from app.agent.mcp_client import get_mcp_tools


def test_mcp_integration():
    tools = asyncio.run(get_mcp_tools())
    assert len(tools) == 10
    graph = compile_graph_with_tools(tools)
    assert "call_model" in graph.nodes
    assert "tools" in graph.nodes
