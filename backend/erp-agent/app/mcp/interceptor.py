"""
MCP Tool Interceptor: 参数校验与越权拦截 + 异常统一捕获 + 错误映射表

校验规则 (03-Agent-Technical-Arch §3.3):
  - draft_purchase_order.agent_reasoning:    非空且 > 20 字符
  - override_purchase_order.agent_reasoning: 同上
  - transit_po_status.operator_role:         Agent 调用固定 "purchaser"；
                                              HITL 回调固定 "finance_manager"（Sprint 2）
"""
import functools
import json

from app.mcp.erp_client import ErpApiError, ErpConnectionError

# ---------------------------------------------------------------------------
# 错误映射表
# ---------------------------------------------------------------------------
# action 含义:
#   self_heal        → 路由到自愈节点（如 stock_error）
#   request_override → 路由到 budget_check → 设 pending_approval_type（Day 5 升级为 HITL）
#   inform_user      → 路由回 call_model，由 Agent LLM 用 user_message 回复用户

ERROR_MAPPING: dict[str, dict] = {
    "BUDGET_INSUFFICIENT": {
        "action": "request_override",
        "template": "预算不足：部门剩余 ¥{remaining:.2f}，需要 ¥{required:.2f}，缺口 ¥{deficit:.2f}。{suggestion}",
    },
    "INSUFFICIENT_STOCK": {
        "action": "self_heal",
        "template": "库存不足：商品 {product_id} 需求 {requested} 件，当前可用 {available} 件。{suggestion}",
    },
    "INVALID_STATE_TRANSITION": {
        "action": "inform_user",
        "template": "状态流转错误：不允许从 {current_status} 跳转到 {target_status}。{suggestion}",
    },
    "RESOURCE_NOT_FOUND": {
        "action": "inform_user",
        "template": "资源不存在：{resource}（{resource_id}）未找到。请检查输入是否正确。",
    },
    "PERMISSION_DENIED": {
        "action": "inform_user",
        "template": "权限不足：需要 {required_role} 权限。请确认当前操作角色或切换到正确身份。",
    },
    "PRICING_TIER_NOT_FOUND": {
        "action": "inform_user",
        "template": "价格未匹配：商品 {product_id} 在数量 {quantity} 下无可用报价。{suggestion}",
    },
    "DB_INTEGRITY_ERROR": {
        "action": "inform_user",
        "template": "数据操作被拒绝：请检查数据完整性约束。{suggestion}",
    },
    "INTERNAL_ERROR": {
        "action": "inform_user",
        "template": "系统内部错误，{suggestion}",
    },
    "CONNECTION_ERROR": {
        "action": "inform_user",
        "template": "无法连接到 ERP 系统，请检查网络后重试。",
    },
    "UNKNOWN": {
        "action": "inform_user",
        "template": "发生未知错误（{message}），{suggestion}",
    },
}


def build_user_message(error_code: str, context: dict, suggestion: str | None, message: str) -> str:
    mapping = ERROR_MAPPING.get(error_code) or ERROR_MAPPING["UNKNOWN"]
    fmt_kwargs = {**context}
    if suggestion:
        fmt_kwargs["suggestion"] = suggestion
    else:
        fmt_kwargs["suggestion"] = ""
    fmt_kwargs["message"] = message
    try:
        return mapping["template"].format(**fmt_kwargs)
    except (KeyError, ValueError):
        return mapping["template"]


def get_error_action(error_code: str) -> str:
    mapping = ERROR_MAPPING.get(error_code)
    return mapping["action"] if mapping else "inform_user"


def catch_erp_error(func):
    """MCP 工具装饰器：统一捕获 ErpApiError / ErpConnectionError，返回结构化 JSON。"""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except ErpApiError as e:
            error_code = e.error_code or "UNKNOWN"
            context = dict(e.body.get("context", {}))
            suggestion = e.agent_suggestion
            # BUDGET_INSUFFICIENT error context 金额单位为分，转为元
            if error_code == "BUDGET_INSUFFICIENT":
                for k in ("required", "remaining", "deficit"):
                    if k in context and isinstance(context[k], (int, float)):
                        context[k] = context[k] / 100.0
            return json.dumps({
                "_error": True,
                "error_type": "business",
                "error_code": error_code,
                "context": context,
                "action": get_error_action(error_code),
                "user_message": build_user_message(error_code, context, suggestion, str(e)),
                "message": str(e),
            }, ensure_ascii=False)
        except ErpConnectionError as e:
            return json.dumps({
                "_error": True,
                "error_type": "infra",
                "error_code": "CONNECTION_ERROR",
                "action": "inform_user",
                "user_message": "无法连接到 ERP 系统，请检查网络后重试。",
                "message": e.message,
            }, ensure_ascii=False)
    return wrapper


def require_agent_reasoning(reasoning: str, tool_name: str = "") -> None:
    if not reasoning or not reasoning.strip():
        msg = f"agent_reasoning is required for {tool_name}"
        raise ValueError(msg)
    if len(reasoning.strip()) < 20:
        msg = (
            f"agent_reasoning too short ({len(reasoning.strip())} chars): "
            f"must be at least 20 characters for {tool_name}"
        )
        raise ValueError(msg)


def enforce_operator_role(role: str = "purchaser") -> str:
    """返回硬编码的 operator_role，LLM 无法操控此参数。
    
    Agent 直调 → "purchaser"；HITL 回调（Sprint 2）→ 调用方传入 "finance_manager"。
    """
    valid_roles = {"purchaser", "finance_manager"}
    if role not in valid_roles:
        raise ValueError(f"invalid operator_role '{role}', must be one of {valid_roles}")
    return role
