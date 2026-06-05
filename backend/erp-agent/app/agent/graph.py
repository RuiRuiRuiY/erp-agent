from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.agent.state import AgentState
from app.agent.nodes import stock_error, tier_suggest, budget_check
from app.agent.routing import route_after_tools


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
    workflow.add_edge("budget_check", "__end__")

    return workflow.compile()


workflow = StateGraph(AgentState)
workflow.add_node("entry", call_model)
workflow.add_node("stock_error", stock_error)
workflow.add_node("tier_suggest", tier_suggest)
workflow.add_node("budget_check", budget_check)
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

graph = workflow.compile()
