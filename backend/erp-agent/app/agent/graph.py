"""LangGraph Agent 图构建模块。

混合架构：ToolNode 执行 MCP 工具 + 显式业务节点处理逻辑。

build_graph(tools) — 构建生产模式图：LLM + ToolNode + 业务节点 + 完整路由。
"""

from __future__ import annotations

from functools import partial
from typing import Any

from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.agent.nodes import (
    analyze_simulate,
    budget_check,
    confirm_and_submit,
    hitl_gate,
    override_po,
    parse_input,
    present_options,
    resume_cleanup,
    show_alternatives,
    stock_error,
    tier_suggest,
    transit_to_pending,
    user_resolve,
)
from app.agent.prompts import SYSTEM_PROMPT
from app.agent.routing import route_after_analysis, route_after_tools, route_after_user_choice
from app.agent.state import AgentState
from app.core.config import settings

import logging

logger = logging.getLogger(__name__)

# 全局缓存：chainlit run 为单进程 asyncio 模型，所有会话共享同一实例。
# 如果未来改为 Gunicorn + 多 Worker 部署，每个 Worker 进程会有独立副本，
# 这是正常行为（多连接 = 更高并发）。
_checkpointer: MemorySaver | None = None


async def aget_checkpointer() -> MemorySaver:
    """获取 checkpointer（异步，生产模式使用）。有 DATABASE_URL 时创建 AsyncPostgresSaver。"""
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    if not settings.DATABASE_URL:
        _checkpointer = MemorySaver()
        return _checkpointer
    try:
        from psycopg import AsyncConnection
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        conn = await AsyncConnection.connect(
            settings.DATABASE_URL,
            autocommit=True,
            prepare_threshold=0,
            connect_timeout=5,
        )
        cp = AsyncPostgresSaver(conn)
        await cp.setup()
        _checkpointer = cp
    except Exception as e:
        sanitized = settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else settings.DATABASE_URL
        logger.warning("PostgreSQL 不可达 (%s: %s), 降级为 MemorySaver", sanitized, e)
        _checkpointer = MemorySaver()
    return _checkpointer


# ── LLM 节点 ────────────────────────────────────────────────────────────


async def _call_model(state: AgentState, *, llm_with_tools: Any) -> dict:
    """LLM 调用节点：组装 system prompt，调用绑定工具的 LLM。"""
    context_parts = []
    if state.get("department_id"):
        context_parts.append(f"部门: {state['department_id']}")
    if state.get("cart_items"):
        names = [i.get("product_name", "") for i in state["cart_items"]]
        context_parts.append(f"商品: {', '.join(names)}")
    if state.get("selected_supplier_id"):
        context_parts.append(f"已选供应商: {state['selected_supplier_id']}")

    system = SYSTEM_PROMPT.format(
        po_status=state.get("po_status") or "新会话",
        context="; ".join(context_parts) or "新会话",
    )
    messages = [SystemMessage(content=system), *state["messages"]]
    response = await llm_with_tools.ainvoke(messages)
    return {"messages": [response]}


# ── 图构建 ──────────────────────────────────────────────────────────────


async def build_graph(tools: list, checkpointer: Any = None) -> CompiledStateGraph:
    """构建并编译 LangGraph（生产模式）。

    Args:
        tools: MCP 工具列表。
        checkpointer: 自定义 checkpointer。None = 自动获取。
    """
    if checkpointer is None:
        checkpointer = await aget_checkpointer()

    from app.agent.llm import _get_llm

    workflow = StateGraph(AgentState)

    llm = _get_llm()
    llm_with_tools = llm.bind_tools(tools)

    tool_node = ToolNode(tools, handle_tool_errors=True)

    # 入口：parse_input → call_model → ToolNode
    workflow.add_node("parse_input", parse_input)
    workflow.add_node("call_model", partial(_call_model, llm_with_tools=llm_with_tools))
    workflow.add_node("tools", tool_node)

    workflow.add_edge(START, "parse_input")
    workflow.add_edge("parse_input", "call_model")
    workflow.add_conditional_edges(
        "call_model", tools_condition, {"tools": "tools", "__end__": "__end__"}
    )
    workflow.add_conditional_edges(
        "tools",
        route_after_tools,
        {
            "call_model": "call_model",
            "analyze_simulate": "analyze_simulate",
            "stock_error": "stock_error",
            "budget_check": "budget_check",
        },
    )

    # 分析节点
    workflow.add_node("analyze_simulate", analyze_simulate)
    workflow.add_conditional_edges(
        "analyze_simulate",
        route_after_analysis,
        {
            "tier_suggest": "tier_suggest",
            "show_alternatives": "show_alternatives",
            "present_options": "present_options",
            "call_model": "call_model",
        },
    )

    # 展示 & 用户选择节点
    workflow.add_node("present_options", present_options)
    workflow.add_node("show_alternatives", show_alternatives)
    workflow.add_node("user_resolve", user_resolve)
    workflow.add_node("confirm_and_submit", confirm_and_submit)

    workflow.add_conditional_edges(
        "present_options",
        route_after_user_choice,
        {
            "confirm_and_submit": "confirm_and_submit",
            "call_model": "call_model",
        },
    )
    workflow.add_conditional_edges(
        "show_alternatives",
        route_after_user_choice,
        {
            "confirm_and_submit": "confirm_and_submit",
            "call_model": "call_model",
        },
    )
    workflow.add_edge("user_resolve", "call_model")
    workflow.add_edge("confirm_and_submit", END)

    # 业务节点
    workflow.add_node("stock_error", stock_error)
    workflow.add_node("tier_suggest", tier_suggest)
    workflow.add_node("budget_check", budget_check)
    workflow.add_node("hitl_gate", hitl_gate)
    workflow.add_node("override_po", override_po)
    workflow.add_node("transit_to_pending", transit_to_pending)
    workflow.add_node("resume_cleanup", resume_cleanup)

    workflow.add_edge("stock_error", END)
    workflow.add_edge("tier_suggest", END)
    workflow.add_conditional_edges(
        "budget_check",
        lambda s: "hitl_gate" if s.get("pending_approval_type") == "budget" else "__end__",
    )
    workflow.add_conditional_edges(
        "hitl_gate",
        lambda s: (
            "override_po"
            if s.get("override_token") and s.get("department_id") and s.get("selected_supplier_id")
            else "__end__"
        ),
    )
    workflow.add_conditional_edges(
        "override_po",
        lambda s: "transit_to_pending" if s.get("po_draft_id") else "__end__",
    )
    workflow.add_edge("transit_to_pending", "resume_cleanup")
    workflow.add_edge("resume_cleanup", "__end__")

    return workflow.compile(checkpointer=checkpointer, interrupt_before=["hitl_gate"])
