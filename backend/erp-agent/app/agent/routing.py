import json

from app.agent.state import AgentState


def route_after_tools(state: AgentState) -> str:
    """检查工具返回结果，路由到对应节点：

    - 业务错误 → stock_error / 其他错误节点
    - simulate_purchase 有 all_quotes → tier_suggest（筛选价格阶梯）
    - check_budget available < 0 → budget_check_node
    - 默认 → call_model
    """
    msgs = state.get("messages", [])
    if not msgs:
        return "call_model"

    last = msgs[-1]
    content = getattr(last, "content", "")
    if isinstance(content, str) and content.strip().startswith("{"):
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                # 业务错误 → 按 action 路由
                if data.get("_error"):
                    action = data.get("action", "inform_user")
                    if action == "self_heal":
                        return "stock_error"
                    if action == "request_override":
                        return "budget_check"
                    return "call_model"

                # simulate_purchase 结果 → 检查阶梯差价
                if data.get("all_quotes"):
                    return "analyze_simulate"

                # check_budget 结果 → 检查预算透支
                if data.get("department_id") is not None and "available" in data:
                    if data["available"] < 0:
                        return "budget_check"
        except (json.JSONDecodeError, AttributeError):
            pass

    return "call_model"


def route_after_analysis(state: AgentState) -> str:
    """analyze_simulate 之后的路由：

    - 有阶梯建议 → tier_suggest
    - 有库存风险 → show_alternatives
    - 有供应商选项 → present_options
    - 默认 → call_model
    """
    analysis = state.get("analysis_result")
    if isinstance(analysis, dict):
        if analysis.get("has_tier_opportunity"):
            return "tier_suggest"
        if analysis.get("has_stock_risk"):
            return "show_alternatives"

    msgs = state.get("messages", [])
    for msg in reversed(msgs):
        content = getattr(msg, "content", "")
        if isinstance(content, str) and content.strip().startswith("{"):
            try:
                data = json.loads(content)
                if isinstance(data, dict) and data.get("all_quotes"):
                    return "present_options"
            except json.JSONDecodeError:
                pass

    return "call_model"


def route_after_user_choice(state: AgentState) -> str:
    """用户选择后的路由：

    - 选择了供应商 → confirm_and_submit
    - 要求重新试算 → call_model
    - 选择了替代商品 → call_model（更新 cart_items 后重新试算）
    - 默认 → call_model
    """
    intent = state.get("user_intent") or ""
    msgs = state.get("messages", [])

    for msg in reversed(msgs):
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            if "确认" in content or "提交" in content or "下单" in content:
                return "confirm_and_submit"
            if "重新" in content or "换" in content or "其他" in content:
                return "call_model"

    if state.get("selected_supplier_id") and state.get("cart_items"):
        return "confirm_and_submit"

    return "call_model"
