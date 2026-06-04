"""
MCP Tool Interceptor: 参数校验与越权拦截

校验规则 (03-Agent-Technical-Arch §3.3):
  - draft_purchase_order.agent_reasoning:    非空且 > 20 字符
  - override_purchase_order.agent_reasoning: 同上
  - transit_po_status.operator_role:         Agent 调用固定 "agent"；
                                              HITL 回调固定 "finance_manager"（Sprint 2）
"""


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


def enforce_operator_role(role: str = "agent") -> str:
    """返回硬编码的 operator_role，LLM 无法操控此参数。
    
    Agent 直调 → "agent"；HITL 回调（Sprint 2）→ 调用方传入 "finance_manager"。
    """
    valid_roles = {"agent", "finance_manager"}
    if role not in valid_roles:
        raise ValueError(f"invalid operator_role '{role}', must be one of {valid_roles}")
    return role
