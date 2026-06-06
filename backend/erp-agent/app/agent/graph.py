from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from psycopg import Connection

from app.agent.state import AgentState
from app.agent.nodes import budget_check, hitl_gate, override_po, resume_cleanup, stock_error, tier_suggest, transit_to_pending
from app.agent.routing import route_after_tools
from app.core.config import settings

_checkpointer = None


def get_checkpointer() -> MemorySaver | PostgresSaver:
    """创建持久化 checkpointer（PostgreSQL），无配置或连接失败时降级为 MemorySaver。"""
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer
    if not settings.DATABASE_URL:
        _checkpointer = MemorySaver()
        return _checkpointer
    try:
        conn = Connection.connect(
            settings.DATABASE_URL,
            autocommit=True,
            prepare_threshold=0,
        )
        cp = PostgresSaver(conn)
        cp.setup()
        # PostgresSaver(sync conn) 不实现 aget_tuple → astream 崩溃
        # 检测到未覆盖基类方法时降级为 MemorySaver
        if type(cp).aget_tuple is BaseCheckpointSaver.aget_tuple:
            conn.close()
            _checkpointer = MemorySaver()
        else:
            _checkpointer = cp
    except Exception:
        _checkpointer = MemorySaver()
    return _checkpointer


def call_model(state: AgentState) -> dict:
    return {}


def compile_graph_with_tools(tools: list) -> StateGraph:
    tool_node = ToolNode(tools)

    workflow = StateGraph(AgentState)
    workflow.add_node("call_model", call_model)
    workflow.add_node("tools", tool_node)
    workflow.add_node("stock_error", stock_error)
    workflow.add_node("tier_suggest", tier_suggest)
    workflow.add_node("budget_check", budget_check)
    workflow.add_node("hitl_gate", hitl_gate)
    workflow.add_node("override_po", override_po)
    workflow.add_node("transit_to_pending", transit_to_pending)
    workflow.add_node("resume_cleanup", resume_cleanup)
    workflow.add_edge(START, "call_model")
    workflow.add_conditional_edges("call_model", tools_condition, {"tools": "tools", "__end__": "__end__"})
    workflow.add_conditional_edges(
        "tools",
        route_after_tools,
        {
            "call_model": "call_model",
            "stock_error": "stock_error",
            "tier_suggest": "tier_suggest",
            "budget_check": "budget_check",
        },
    )
    workflow.add_edge("stock_error", "__end__")
    workflow.add_edge("tier_suggest", "__end__")
    workflow.add_conditional_edges(
        "budget_check",
        lambda s: "hitl_gate" if s.get("pending_approval_type") == "budget" else "__end__",
    )
    workflow.add_conditional_edges(
        "hitl_gate",
        lambda s: (
            "override_po"
            if s.get("override_token") and s.get("department_id") and s.get("selected_supplier_id")
            else "call_model"
        ),
    )
    workflow.add_conditional_edges(
        "override_po",
        lambda s: "transit_to_pending" if s.get("po_draft_id") else "__end__",
    )
    workflow.add_edge("transit_to_pending", "resume_cleanup")
    workflow.add_edge("resume_cleanup", "__end__")

    return workflow.compile(checkpointer=get_checkpointer())


workflow = StateGraph(AgentState)
workflow.add_node("entry", call_model)
workflow.add_node("stock_error", stock_error)
workflow.add_node("tier_suggest", tier_suggest)
workflow.add_node("budget_check", budget_check)
workflow.add_node("hitl_gate", hitl_gate)
workflow.add_node("override_po", override_po)
workflow.add_node("transit_to_pending", transit_to_pending)
workflow.add_node("resume_cleanup", resume_cleanup)
workflow.add_edge(START, "entry")
workflow.add_conditional_edges(
    "entry",
    lambda s: (
        "stock_error" if s.get("error_context") else
        "tier_suggest" if s.get("simulate_result") else
        "budget_check" if s.get("pending_approval_type") == "budget" else
        "__end__"
    ),
)
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

graph = workflow.compile(checkpointer=get_checkpointer())

if settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY:
    try:
        from app.core.langfuse import setup_langfuse
        setup_langfuse()
        from app.core.langfuse import langfuse_client as lf
        if lf:
            from langfuse.langchain import CallbackHandler
            _lf_handler = CallbackHandler()

            # 包装 astream：自动在 config 中注入 Langfuse callback
            _orig_astream = graph.astream

            async def _astream_with_lf(*args, **kwargs):
                if len(args) > 1 and args[1] is not None:
                    _cfg = args[1]
                    if "callbacks" not in _cfg:
                        _cfg = {**_cfg, "callbacks": [_lf_handler]}
                        args = (args[0], _cfg) + args[2:]
                elif "config" in kwargs:
                    _cfg = kwargs["config"]
                    if "callbacks" not in _cfg:
                        kwargs["config"] = {**_cfg, "callbacks": [_lf_handler]}
                async for chunk in _orig_astream(*args, **kwargs):
                    yield chunk

            graph.astream = _astream_with_lf

            # 包装 invoke
            _orig_invoke = graph.invoke

            def _invoke_with_lf(*args, **kwargs):
                if len(args) > 1 and args[1] is not None:
                    _cfg = args[1]
                    if "callbacks" not in _cfg:
                        _cfg = {**_cfg, "callbacks": [_lf_handler]}
                        args = (args[0], _cfg) + args[2:]
                elif "config" in kwargs:
                    _cfg = kwargs["config"]
                    if "callbacks" not in _cfg:
                        kwargs["config"] = {**_cfg, "callbacks": [_lf_handler]}
                return _orig_invoke(*args, **kwargs)

            graph.invoke = _invoke_with_lf

            # 进程退出前确保数据发送
            import atexit
            atexit.register(lambda: lf.flush())
    except Exception:
        pass
