"""
S3 集成测试：HITL 审批流（预算超标 → 挂起 → 注入 Token → 恢复）

验收: interrupt 正确触发，resume 后 override_token 注入
"""
import json
from unittest.mock import patch

from langgraph.types import Command
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.state import AgentState
from app.agent.graph import build_graph
from tests.fixtures import make_mock_tools, make_mock_llm


async def _mock_override_po(**kwargs) -> str:
    return json.dumps({
        "id": "po-override-s3",
        "po_number": "PO-S3-001",
        "status": "DRAFT",
        "total_amount": 6000.0,
        "is_override": True,
    })


async def _mock_transit_po(**kwargs) -> str:
    return json.dumps({
        "po_id": "po-override-s3",
        "po_number": "PO-S3-001",
        "old_status": "DRAFT",
        "new_status": "PENDING",
    })


async def test_s3_hitl_approval():
    draft_resp = json.dumps({
        "_error": True, "error_code": "BUDGET_INSUFFICIENT", "action": "request_override",
        "context": {"required": 6000.0, "remaining": 5000.0, "deficit": 1000.0},
    })
    tools = make_mock_tools(draft_response=draft_resp)
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
        config = {"configurable": {"thread_id": "s3-int"}}

        # Step 1: budget_check → hitl_gate → interrupt
        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass
        state = await graph.aget_state(config)
        assert state.values.get("pending_approval_type") == "budget", "应挂起"

        # Step 2: resume → override_po → transit_to_pending → resume_cleanup
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
    assert final.values.get("po_draft_id") == "po-override-s3", "应创建特批 PO"
    assert final.values.get("po_status") == "PENDING", "应提交审批"
    assert final.values.get("override_token") is None, "token 应已消费"
