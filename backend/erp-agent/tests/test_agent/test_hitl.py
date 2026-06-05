
"""
Task 5.1: HITL interrupt/resume 验证
Task 5.2: override_purchase_order 工具调用与全流程验证

测试:
  1. budget_check → hitl_gate (interrupt) → resume 注入 override_token
  2. resume → override_po_node (调用 override_purchase_order) → transit_pending_node (DRAFT→PENDING)
"""
import json
from unittest.mock import patch

from langgraph.types import Command
from langchain_core.messages import ToolMessage

from app.agent.state import AgentState
from app.agent.graph import graph


async def _mock_override_po(**kwargs) -> str:
    return json.dumps({
        "id": "po-override-001",
        "po_number": "PO-20260605-OVERRIDE",
        "status": "DRAFT",
        "total_amount": 5000.0,
        "is_override": True,
        "supplier_name": "深圳宏达电子",
        "department_name": "研发部",
        "lines": [
            {"product_id": "p001", "product_name": "人体工学椅", "quantity": 10,
             "unit_price": 500.0, "line_total": 5000.0},
        ],
    })


async def _mock_transit_po(**kwargs) -> str:
    return json.dumps({
        "po_id": "po-override-001",
        "po_number": "PO-20260605-OVERRIDE",
        "old_status": "DRAFT",
        "new_status": "PENDING",
        "budget_impact": "特批跳过预算检查",
    })


def test_hitl_interrupt_resume():
    """Task 5.1: 挂起 → resume 注入 override_token 的基础链路"""
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


async def test_hitl_override_full_flow():
    """Task 5.2: 完整 override 流程 — override_po 建单 → transit PENDING

    验收标准: 传入 override_token 成功建单
    """
    initial = AgentState(
        pending_approval_type="budget",
        override_token=None,
        department_id="dept_rd",
        selected_supplier_id="sup_c",
        cart_items=[
            {"product_id": "p003", "product_name": "人体工学椅", "quantity": 10},
        ],
        messages=[ToolMessage(
            content=json.dumps({
                "_error": True,
                "error_code": "BUDGET_INSUFFICIENT",
                "context": {"required": 6000.0, "remaining": 5000.0, "deficit": 1000.0},
            }),
            tool_call_id="t1", name="draft_purchase_order",
        )],
    )
    config = {"configurable": {"thread_id": "test-hitl-override"}}

    # ── Step 1: 触发中断 ──────────────────────────────────────────
    async for _ in graph.astream(initial, config, stream_mode="updates"):
        pass

    state = await graph.aget_state(config)
    assert state.values.get("pending_approval_type") == "budget", "应处于挂起状态"
    assert state.values.get("po_draft_id") is None, "挂起时不应有 PO"

    # ── Step 2: resume → 走完整 override 链路 ──────────────────────
    with (
        patch("app.agent.nodes.override_purchase_order", _mock_override_po),
        patch("app.agent.nodes.transit_po_status", _mock_transit_po),
    ):
        async for _ in graph.astream(
            Command(resume={"override_token": "override-secret-2025"}),
            config,
            stream_mode="updates",
        ):
            pass

    final = await graph.aget_state(config)
    assert final.values.get("po_draft_id") == "po-override-001", "应保存特批 PO ID"
    assert final.values.get("po_status") == "PENDING", "PO 应已流转到 PENDING"
    assert final.values.get("override_token") == "override-secret-2025", "override_token 应保留"
    assert final.values.get("pending_approval_type") is None, "挂起类型应已清除"


async def test_hitl_override_missing_params():
    """缺少必要参数时 override_po_node 应报错而非崩溃"""
    config = {"configurable": {"thread_id": "test-hitl-missing-params"}}

    # 没有 department_id / selected_supplier_id / cart_items
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

    async for _ in graph.astream(initial, config, stream_mode="updates"):
        pass

    async for _ in graph.astream(
        Command(resume={"override_token": "override-secret-2025"}),
        config,
        stream_mode="updates",
    ):
        pass

    final = await graph.aget_state(config)
    assert final.values.get("override_token") == "override-secret-2025", "token 仍应注入"
    assert final.values.get("po_draft_id") is None, "缺少参数，不应创建 PO"
