"""LangGraph Agent 图构建模块。

混合架构：ToolNode 执行 MCP 工具 + 显式业务节点处理逻辑。

提供两种模式：
- build_graph(tools=[]) — 生产模式：LLM + ToolNode + 业务节点 + 完整路由
- build_graph(tools=None) — 测试模式：跳过 LLM，直接按 state 路由（用于单元测试）
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, END, StateGraph
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
from app.agent.routing import route_after_analysis, route_after_tools, route_after_user_choice
from app.agent.state import AgentState
from app.core.config import settings

import logging

logger = logging.getLogger(__name__)

_checkpointer: MemorySaver | None = None
_llm_instance: Any = None


def get_checkpointer() -> MemorySaver:
    """创建持久化 checkpointer（PostgreSQL），无配置或连接失败时降级为 MemorySaver。"""
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    if not settings.DATABASE_URL:
        _checkpointer = MemorySaver()
        return _checkpointer
    try:
        from langgraph.checkpoint.base import BaseCheckpointSaver
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import Connection

        conn = Connection.connect(
            settings.DATABASE_URL,
            autocommit=True,
            prepare_threshold=0,
            connect_timeout=5,
        )
        cp = PostgresSaver(conn)
        cp.setup()
        if type(cp).aget_tuple is BaseCheckpointSaver.aget_tuple:
            conn.close()
            _checkpointer = MemorySaver()
        else:
            _checkpointer = cp
    except Exception as e:
        sanitized = settings.DATABASE_URL.split("@")[-1] if "@" in settings.DATABASE_URL else settings.DATABASE_URL
        logger.warning("PostgreSQL 不可达 (%s: %s), 降级为 MemorySaver", sanitized, e)
        _checkpointer = MemorySaver()
    return _checkpointer


def _get_llm():
    """获取或创建缓存的 LLM 实例。"""
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance
    from langchain_openai import ChatOpenAI

    _llm_instance = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=0,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
    )
    return _llm_instance


# ── 测试模式路由 ────────────────────────────────────────────────────────


def _test_route(state: AgentState) -> str:
    """测试模式路由：优先按 state 字段路由，回退到 route_after_tools。"""
    if state.get("error_context"):
        return "stock_error"
    if state.get("simulate_result"):
        return "tier_suggest"
    if state.get("pending_approval_type") == "budget":
        return "budget_check"
    return route_after_tools(state)


# ── 图构建 ──────────────────────────────────────────────────────────────


def build_graph(tools: list | None = None, checkpointer: Any = None) -> Any:
    """构建并编译 LangGraph。

    Args:
        tools: MCP 工具列表。None = 测试模式（无 LLM/ToolNode），[] = 生产模式但无工具。
        checkpointer: 自定义 checkpointer。None = 使用 get_checkpointer()。
    """
    if checkpointer is None:
        checkpointer = get_checkpointer()

    workflow = StateGraph(AgentState)

    if tools is not None:
        # ── 生产模式：LLM + ToolNode + 业务节点 ──
        from langchain_core.messages import SystemMessage
        from app.agent.prompts import SYSTEM_PROMPT

        llm = _get_llm()
        llm_with_tools = llm.bind_tools(tools)
        tools_desc = "\n".join(f"- {t.name}: {t.description}" for t in tools if t.description)

        async def _call_model(state: AgentState) -> dict:
            context_parts = []
            if state.get("department_id"):
                context_parts.append(f"部门: {state['department_id']}")
            if state.get("cart_items"):
                names = [i.get("product_name", "") for i in state["cart_items"]]
                context_parts.append(f"商品: {', '.join(names)}")
            if state.get("selected_supplier_id"):
                context_parts.append(f"已选供应商: {state['selected_supplier_id']}")

            system = SYSTEM_PROMPT.format(
                tools=tools_desc,
                po_status=state.get("po_status") or "新会话",
                context="; ".join(context_parts) or "新会话",
            )
            messages = [SystemMessage(content=system), *state["messages"]]
            response = await llm_with_tools.ainvoke(messages)
            return {"messages": [response]}

        tool_node = ToolNode(tools)

        # 入口：parse_input → call_model → ToolNode
        workflow.add_node("parse_input", parse_input)
        workflow.add_node("call_model", _call_model)
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

    else:
        # ── 测试模式：按 state 直接路由，跳过 LLM ──
        workflow.add_node("entry", lambda s: {})
        workflow.add_edge(START, "entry")
        workflow.add_conditional_edges(
            "entry",
            _test_route,
            {
                "stock_error": "stock_error",
                "tier_suggest": "tier_suggest",
                "budget_check": "budget_check",
            },
        )

    # ── 共享节点（两种模式一致） ──
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


# ── Langfuse 辅助 ──────────────────────────────────────────────────────


def get_langfuse_callback():
    """获取 Langfuse CallbackHandler，未配置时返回 None。"""
    if not (settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY):
        return None
    try:
        from app.core.langfuse import setup_langfuse, langfuse_client as lf
        setup_langfuse()
        if not lf:
            return None
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except Exception:
        return None


def make_langfuse_config(callback=None):
    """构建包含 Langfuse 回调的 config dict。"""
    if callback is None:
        callback = get_langfuse_callback()
    if callback is None:
        return {}
    return {"callbacks": [callback]}
