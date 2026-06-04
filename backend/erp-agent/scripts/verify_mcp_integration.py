"""
Task 2.5 验收脚本: 验证 MultiServerMCPClient → ToolNode 集成

验收标准:
1. client.get_tools() 返回 10 个 LangChain 兼容工具
2. 注入 ToolNode 后编译通过
"""
import asyncio
import sys

from app.agent.graph import compile_graph_with_tools
from app.agent.mcp_client import get_mcp_tools


async def main():
    print("=== Task 2.5 验收: MCP Client → ToolNode 集成 ===\n")

    # 1. 获取工具
    print("[1/3] 加载 MCP 工具...")
    tools = await get_mcp_tools()
    print(f"      工具数量: {len(tools)}")
    for t in tools:
        print(f"      - {t.name}")
    assert len(tools) == 10, f"预期 10 个工具, 实际 {len(tools)}"

    # 2. 注入 ToolNode 编译
    print("\n[2/3] 注入 ToolNode 编译...")
    graph = compile_graph_with_tools(tools)
    print(f"      编译成功: {type(graph).__name__}")

    # 3. 验证图结构
    print("\n[3/3] 验证图结构...")
    node_names = list(graph.nodes.keys())
    print(f"      节点: {node_names}")
    assert "call_model" in node_names, f"缺少 call_model 节点: {node_names}"
    assert "tools" in node_names, f"缺少 tools 节点: {node_names}"

    print("\n[PASS] Task 2.5 验收通过: MultiServerMCPClient 连接成功, ToolNode 编译通过")


if __name__ == "__main__":
    asyncio.run(main())
