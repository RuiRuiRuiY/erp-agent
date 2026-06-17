"""Chainlit 入口：ERP-Agent 对话式 UI。

启动方式:
    cd backend/erp-agent
    chainlit run app/chainlit_app.py --port 8001
"""

from __future__ import annotations

import logging
from uuid import uuid4

import chainlit as cl
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from app.agent.graph import build_graph
from app.core.langfuse import make_langfuse_config

logger = logging.getLogger(__name__)

_graph = None
_RECURSION_LIMIT = 25


def _build_config(thread_id: str) -> dict:
    """构建 graph.ainvoke 的 config dict，统一 recursion_limit 和 Langfuse 回调。"""
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": _RECURSION_LIMIT,
        **make_langfuse_config(),
    }


async def _get_graph():
    """懒加载 LangGraph 实例（避免启动时连接 MCP Server）。"""
    global _graph
    if _graph is not None:
        return _graph

    from app.mcp.client import get_mcp_tools

    tools = cl.user_session.get("mcp_tools")
    if tools is None:
        try:
            tools = await get_mcp_tools()
        except Exception:
            tools = []
        cl.user_session.set("mcp_tools", tools)

    _graph = await build_graph(tools=tools or [])
    return _graph


@cl.on_chat_start
async def on_chat_start():
    """初始化会话：生成 thread_id。"""
    thread_id = str(uuid4())
    cl.user_session.set("thread_id", thread_id)
    logger.info("新会话: thread_id=%s", thread_id)


_ROLE_MAP = {
    "采购员": "purchaser",
    "财务经理": "finance_manager",
}


@cl.on_message
async def on_message(message: cl.Message):
    """处理用户消息：支持 /role、/reset 命令，其余消息调用 LangGraph Agent。"""
    # ── 角色切换命令 ──
    if message.content.startswith("/role"):
        parts = message.content.split(maxsplit=1)
        if len(parts) < 2:
            await cl.Message(content="用法: /role 采购员 或 /role 财务经理").send()
            return
        role_name = parts[1].strip()
        role_value = _ROLE_MAP.get(role_name)
        if not role_value:
            await cl.Message(content=f"未知角色: {role_name}。可用角色: {', '.join(_ROLE_MAP.keys())}").send()
            return
        cl.user_session.set("operator_role", role_value)
        await cl.Message(content=f"已切换到角色: {role_name}（{role_value}）").send()
        return

    # ── 重置命令 ──
    if message.content.strip() in ("/reset", "重置"):
        new_thread_id = str(uuid4())
        cl.user_session.set("thread_id", new_thread_id)
        logger.info("会话重置: new_thread_id=%s", new_thread_id)
        await cl.Message(content="会话已重置，开始新的对话。").send()
        return

    thread_id = cl.user_session.get("thread_id")
    if not thread_id:
        thread_id = str(uuid4())
        cl.user_session.set("thread_id", thread_id)

    graph = await _get_graph()
    config = _build_config(thread_id)

    operator_role = cl.user_session.get("operator_role", "purchaser")

    try:
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=message.content)], "operator_role": operator_role, "action_source": "ai"},
            config,
        )
    except Exception as e:
        logger.exception("Agent 执行失败")
        await cl.Message(content=f"抱歉，处理您的请求时出现错误：{e}").send()
        return

    # 检查是否被 interrupt() 暂停（HITL 审批场景）
    interrupts = result.get("__interrupt__")
    if interrupts:
        await _handle_interrupts(graph, config, interrupts)
        return

    # 正常流程：提取最后一条 assistant 消息
    reply = _extract_reply(result)
    await cl.Message(content=reply).send()


async def _handle_interrupts(graph, config, interrupts):
    """处理 interrupt：弹出审批框，用户批准后 resume。"""
    interrupt_obj = interrupts[0] if isinstance(interrupts, list) else interrupts
    interrupt_value = getattr(interrupt_obj, "value", interrupt_obj)

    # 提取审批信息
    pending_type = "unknown"
    request_msg = "需要您的审批"
    if isinstance(interrupt_value, dict):
        pending_type = interrupt_value.get("pending_type", "unknown")
        request_msg = interrupt_value.get("message", request_msg)

    # 弹出 Chainlit 审批确认框
    approve_action = cl.Action(
        name="approve_override",
        label="批准",
        payload={"approve": True},
        description="批准特批采购",
    )
    reject_action = cl.Action(
        name="reject_override",
        label="拒绝",
        payload={"approve": False},
        description="拒绝特批采购",
    )

    await cl.Message(
        content=f"**HITL 审批请求**\n\n类型: {pending_type}\n{request_msg}\n\n请点击「批准」或「拒绝」：",
        actions=[approve_action, reject_action],
    ).send()


@cl.action_callback("approve_override")
async def on_approve(action: cl.Action):
    """用户点击「批准」：resume 图执行。"""
    thread_id = cl.user_session.get("thread_id")
    graph = await _get_graph()
    config = _build_config(thread_id)

    try:
        result = await graph.ainvoke(Command(resume=True), config)
    except Exception as e:
        logger.exception("Resume 失败")
        await cl.Message(content=f"恢复执行失败：{e}").send()
        return

    # 检查是否还有后续 interrupt
    interrupts = result.get("__interrupt__")
    if interrupts:
        await _handle_interrupts(graph, config, interrupts)
        return

    reply = _extract_reply(result)
    await cl.Message(content=reply).send()


@cl.action_callback("reject_override")
async def on_reject(action: cl.Action):
    """用户点击「拒绝」：resume 图但传入拒绝信号。"""
    thread_id = cl.user_session.get("thread_id")
    graph = await _get_graph()
    config = _build_config(thread_id)

    try:
        result = await graph.ainvoke(Command(resume=False), config)
    except Exception as e:
        logger.exception("Resume 失败")
        await cl.Message(content=f"恢复执行失败：{e}").send()
        return

    reply = _extract_reply(result)
    if not reply:
        reply = "采购已取消。"
    await cl.Message(content=reply).send()


def _extract_reply(result: dict) -> str:
    """从 graph result 提取最后一条 assistant 消息。"""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if getattr(msg, "type", "") == "ai" and getattr(msg, "content", ""):
            return msg.content
    return ""
