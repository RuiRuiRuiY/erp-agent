
"""
Task 5.1: HITL interrupt/resume 验证

测试 budget_check → hitl_gate (interrupt) → resume 注入 override_token 的全链路。
"""
import json

from langgraph.types import Command
from langchain_core.messages import ToolMessage

from app.agent.state import AgentState
from app.agent.graph import graph


def test_hitl_interrupt_resume():
    initial = AgentState(
        messages=[ToolMessage(
            content=json.dumps({
                "_error": True,
                "error_code": "BUDGET_INSUFFICIENT",
                "context": {"required": 6000.0, "remaining": 5000.0, "deficit": 1000.0},
            }),
            tool_call_id="t1", name="draft_purchase_order",
        )],
        pending_approval_type="budget",
    )
    config = {"configurable": {"thread_id": "test-hitl-1"}}

    for event in graph.stream(initial, config, stream_mode="updates"):
        pass

    state = graph.get_state(config)
    assert state.values.get("pending_approval_type") == "budget", "应处于 budget 挂起状态"

    for event in graph.stream(Command(resume={"override_token": "override-secret-2025"}), config, stream_mode="updates"):
        pass

    final = graph.get_state(config)
    assert final.values.get("override_token") == "override-secret-2025", "override_token 应已注入"
    assert final.values.get("pending_approval_type") is None, "pending_approval_type 应已清除"
