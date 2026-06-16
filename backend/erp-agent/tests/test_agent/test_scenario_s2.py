"""
S2 集成测试：库存不足协商

check_inventory 返回库存不足 → stock_error → 生成替代方案
图正常结束，recovery 字段正确

验收: recovery_attempted=True, recovery_path 有值
"""
import json
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.state import AgentState
from app.agent.schemas import Intent, ParseResult
from app.agent.graph import build_graph
from tests.fixtures import make_mock_tools, make_structured_mock_llm


async def test_s2_insufficient_stock():
    inventory_resp = json.dumps({
        "_error": True, "error_code": "INSUFFICIENT_STOCK", "action": "self_heal",
        "context": {"product_id": "p003", "requested": 10, "available": 5},
    })
    tools = make_mock_tools(inventory_response=inventory_resp)
    mock_llm = make_structured_mock_llm([
        ParseResult(intent=Intent.NEW_REQUEST, department_id="dept_it",
                    cart_items=[{"product_id": "p003", "product_name": "椅子", "quantity": 10}]),
        AIMessage(content="", tool_calls=[{
            "id": "call_001", "name": "check_inventory",
            "args": {"product_id": "p003"},
        }]),
    ])

    with patch("app.agent.llm._get_llm", return_value=mock_llm):
        graph = await build_graph(tools=tools)
        initial = AgentState(
            messages=[HumanMessage(content="买10把椅子")],
            department_id="dept_it",
            cart_items=[{"product_id": "p003", "product_name": "椅子", "quantity": 10}],
        )
        config = {"configurable": {"thread_id": "s2-int"}}

        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass

    final = await graph.aget_state(config)
    assert final.values.get("recovery_attempted") is True
    assert final.values.get("recovery_path") == "reduce_qty"
