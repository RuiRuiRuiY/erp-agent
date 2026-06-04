from langgraph.graph import START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.agent.state import AgentState


def call_model(state: AgentState) -> dict:
    return {}


def compile_graph_with_tools(tools: list) -> StateGraph:
    tool_node = ToolNode(tools)

    workflow = StateGraph(AgentState)
    workflow.add_node("call_model", call_model)
    workflow.add_node("tools", tool_node)
    workflow.add_edge(START, "call_model")
    workflow.add_conditional_edges("call_model", tools_condition, {"tools": "tools", "__end__": "__end__"})
    workflow.add_edge("tools", "call_model")

    return workflow.compile()


workflow = StateGraph(AgentState)
workflow.add_node("entry", call_model)
workflow.add_edge(START, "entry")

graph = workflow.compile()
