"""Chainlit 入口：ERP-Agent 对话式 UI。

启动方式:
    cd backend/erp-agent
    chainlit run app/chainlit_app.py
"""

from __future__ import annotations

import logging
from uuid import uuid4

import chainlit as cl
from langchain_core.messages import HumanMessage

from app.agent.graph import build_graph, make_langfuse_config

logger = logging.getLogger(__name__)

_graph = None


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

    _graph = build_graph(tools=tools or [])
    return _graph


@cl.on_chat_start
async def on_chat_start():
    """初始化会话：生成 thread_id。"""
    thread_id = str(uuid4())
    cl.user_session.set("thread_id", thread_id)
    logger.info("新会话: thread_id=%s", thread_id)


@cl.on_message
async def on_message(message: cl.Message):
    """处理用户消息：调用 LangGraph Agent。"""
    thread_id = cl.user_session.get("thread_id")
    if not thread_id:
        thread_id = str(uuid4())
        cl.user_session.set("thread_id", thread_id)

    graph = await _get_graph()
    config = {
        "configurable": {"thread_id": thread_id},
        **make_langfuse_config(),
    }

    try:
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=message.content)]},
            config,
        )
    except Exception as e:
        logger.exception("Agent 执行失败")
        await cl.Message(content=f"抱歉，处理您的请求时出现错误：{e}").send()
        return

    # 提取最后一条 assistant 消息
    messages = result.get("messages", [])
    reply = ""
    for msg in reversed(messages):
        if getattr(msg, "type", "") == "ai" and getattr(msg, "content", ""):
            reply = msg.content
            break

    if not reply:
        reply = "抱歉，我无法处理您的请求。"

    await cl.Message(content=reply).send()
