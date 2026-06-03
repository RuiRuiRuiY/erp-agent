from langgraph.graph import START, StateGraph

from app.agent.state import AgentState


def dummy_node(state: AgentState) -> dict:
    return {}


workflow = StateGraph(AgentState)
workflow.add_node("entry", dummy_node)
workflow.add_edge(START, "entry")

graph = workflow.compile()
