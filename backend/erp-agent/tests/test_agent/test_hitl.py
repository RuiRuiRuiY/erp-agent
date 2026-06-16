"""
Task 5.1: HITL interrupt/resume 验证
Task 5.2: override_purchase_order 工具调用与全流程验证
Task 5.3: resume 后状态恢复 — 清理临时字段，保留业务数据

测试:
  1. budget_check → hitl_gate (interrupt) → resume 注入 override_token
  2. resume → override_po → transit_to_pending → resume_cleanup
  3. resume_cleanup 后临时字段被清除，业务字段保留
"""
import json
from unittest.mock import patch

import pytest
from langgraph.types import Command
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.state import AgentState
from app.agent.graph import build_graph
from tests.fixtures import make_mock_tools, make_mock_llm


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


def _make_budget_error_tools():
    draft_resp = json.dumps({
        "_error": True, "error_code": "BUDGET_INSUFFICIENT", "action": "request_override",
        "context": {"required": 6000.0, "remaining": 5000.0, "deficit": 1000.0},
    })
    return make_mock_tools(draft_response=draft_resp)


@pytest.mark.asyncio
async def test_hitl_interrupt_resume():
    """Task 5.1: 挂起 → resume 注入 override_token 的基础链路"""
    tools = _make_budget_error_tools()
    mock_llm = make_mock_llm([
        AIMessage(content=json.dumps({
            "intent": "new_request",
            "department_id": "dept_rd",
            "cart_items": [{"product_id": "p003", "product_name": "椅子", "quantity": 10}],
        })),
        AIMessage(content="", tool_calls=[{
            "id": "call_001", "name": "draft_purchase_order",
            "args": {"department_id": "dept_rd", "supplier_id": "sup_c",
                     "items": [{"product_id": "p003", "quantity": 10}]},
        }]),
    ])

    with patch("app.agent.graph._get_llm", return_value=mock_llm):
        graph = await build_graph(tools=tools)
        initial = AgentState(
            messages=[HumanMessage(content="为研发部买10把椅子")],
            department_id="dept_rd",
            selected_supplier_id="sup_c",
            cart_items=[{"product_id": "p003", "product_name": "椅子", "quantity": 10}],
        )
        config = {"configurable": {"thread_id": "test-hitl-1"}}

        async for event in graph.astream(initial, config, stream_mode="updates"):
            pass

        state = await graph.aget_state(config)
        assert state.values.get("pending_approval_type") == "budget", "应处于 budget 挂起状态"

        async for event in graph.astream(Command(resume={"override_token": "override-secret-2025"}), config, stream_mode="updates"):
            pass

    final = await graph.aget_state(config)
    assert final.values.get("override_token") == "override-secret-2025", "override_token 应已注入"
    assert final.values.get("pending_approval_type") is None, "pending_approval_type 应已清除"


async def test_hitl_override_full_flow():
    """Task 5.2 + Task 5.3: 完整 override 流程 → resume 后状态恢复

    验收标准:
      - 传入 override_token 成功建单 (Task 5.2)
      - resume_cleanup 后临时字段清除，业务字段保留 (Task 5.3)
    """
    tools = _make_budget_error_tools()
    mock_llm = make_mock_llm([
        AIMessage(content=json.dumps({
            "intent": "new_request",
            "department_id": "dept_rd",
            "cart_items": [{"product_id": "p003", "product_name": "椅子", "quantity": 10}],
        })),
        AIMessage(content="", tool_calls=[{
            "id": "call_001", "name": "draft_purchase_order",
            "args": {"department_id": "dept_rd", "supplier_id": "sup_c",
                     "items": [{"product_id": "p003", "quantity": 10}]},
        }]),
    ])

    with patch("app.agent.graph._get_llm", return_value=mock_llm):
        graph = await build_graph(tools=tools)
        initial = AgentState(
            messages=[HumanMessage(content="为研发部买10把椅子")],
            department_id="dept_rd",
            selected_supplier_id="sup_c",
            cart_items=[{"product_id": "p003", "product_name": "椅子", "quantity": 10}],
            tier_suggestion="旧的阶梯建议",
        )
        config = {"configurable": {"thread_id": "test-hitl-override"}}

        # ── Step 1: 触发中断 ──────────────────────────────────────────
        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass

        state = await graph.aget_state(config)
        assert state.values.get("pending_approval_type") == "budget", "应处于挂起状态"
        assert state.values.get("po_draft_id") is None, "挂起时不应有 PO"

        # ── Step 2: resume → 走完整 override 链路 + cleanup ───────────
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

    # ── Task 5.2 验收: 成功建单 ────────────────────────────────────
    assert final.values.get("po_draft_id") == "po-override-001", "应保存特批 PO ID"
    assert final.values.get("po_status") == "PENDING", "PO 应已流转到 PENDING"

    # ── Task 5.3 验收: 临时字段已清除 ──────────────────────────────
    assert final.values.get("override_token") is None, "override_token 应被消费"
    assert final.values.get("pending_approval_type") is None, "挂起类型应已清除"
    assert final.values.get("tier_suggestion") is None, "tier_suggestion 应已清除"

    # ── Task 5.3 验收: 业务字段保留 ────────────────────────────────
    assert final.values.get("department_id") == "dept_rd", "部门信息应保留"
    assert final.values.get("selected_supplier_id") == "sup_c", "供应商应保留"
    assert final.values.get("po_supplier_id") == "sup_c", "PO 供应商应保留"


async def test_hitl_override_missing_params():
    """缺少必要参数时 override_po_node 应报错而非崩溃"""
    tools = _make_budget_error_tools()
    mock_llm = make_mock_llm([
        AIMessage(content=json.dumps({
            "intent": "new_request",
            "department_id": "dept_rd",
            "cart_items": [{"product_id": "p003", "product_name": "椅子", "quantity": 10}],
        })),
        AIMessage(content="", tool_calls=[{
            "id": "call_001", "name": "draft_purchase_order",
            "args": {"department_id": "dept_rd", "supplier_id": "sup_c",
                     "items": [{"product_id": "p003", "quantity": 10}]},
        }]),
    ])

    with patch("app.agent.graph._get_llm", return_value=mock_llm):
        graph = await build_graph(tools=tools)
        config = {"configurable": {"thread_id": "test-hitl-missing-params"}}

        # 没有 department_id / selected_supplier_id / cart_items
        initial = AgentState(
            messages=[HumanMessage(content="为研发部买10把椅子")],
            department_id="dept_rd",
            selected_supplier_id="sup_c",
            cart_items=[{"product_id": "p003", "product_name": "椅子", "quantity": 10}],
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
