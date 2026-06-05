import json

from app.agent.state import AgentState


def route_after_tools(state: AgentState) -> str:
    """检查工具返回结果是否含业务错误，路由到对应节点。"""
    msgs = state.get("messages", [])
    if not msgs:
        return "call_model"

    last = msgs[-1]
    content = getattr(last, "content", "")
    if isinstance(content, str) and content.strip().startswith("{"):
        try:
            data = json.loads(content)
            if isinstance(data, dict) and data.get("_error"):
                error_code = data.get("error_code", "")
                if error_code == "INSUFFICIENT_STOCK":
                    return "stock_error"
        except (json.JSONDecodeError, AttributeError):
            pass

    return "call_model"
