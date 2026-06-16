"""
S4 集成测试：阶梯凑单

simulate_result 含未命中高阶阶梯 → entry → tier_suggest → 生成建议
图正常结束，tier_suggestion 有值

验收: tier_suggestion 包含阶梯价信息
"""
import json
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.state import AgentState
from app.agent.graph import build_graph
from tests.fixtures import make_mock_tools, make_mock_llm


async def test_s4_tiered_pricing():
    simulate_resp = json.dumps({
        "all_quotes": [{
            "supplier_id": "sup_c", "supplier_name": "Guangzhou Wantong",
            "default_lead_time_days": 7, "rating": 4.8, "total_amount": 8000.0,
            "line_details": [{"product_id": "p004", "product_name": "Logitech Mouse",
                              "quantity": 80, "unit_price": 100.0, "subtotal": 8000.0}],
        }],
    })
    tools = make_mock_tools(simulate_response=simulate_resp)
    mock_llm = make_mock_llm([
        AIMessage(content=json.dumps({
            "intent": "new_request",
            "department_id": "dept_it",
            "cart_items": [{"product_id": "p004", "product_name": "鼠标", "quantity": 80}],
        })),
        AIMessage(content="", tool_calls=[{
            "id": "call_001", "name": "simulate_purchase",
            "args": {"department_id": "dept_it", "items": [{"product_id": "p004", "quantity": 80}]},
        }]),
        AIMessage(content='{"has_tier_opportunity": true, "has_stock_risk": false}\n有阶梯价机会：80个×100元 vs 100个×80元'),
    ])
    pricelist = [
        {"min_qty": 1, "unit_price": 100.0},
        {"min_qty": 100, "unit_price": 80.0},
    ]

    async def mock_erp_get(path, params=None):
        if "/pricelists" in path:
            return pricelist
        return []

    with patch("app.agent.graph._get_llm", return_value=mock_llm), \
         patch("app.agent.nodes.erp_get", side_effect=mock_erp_get):
        graph = await build_graph(tools=tools)
        initial = AgentState(
            messages=[HumanMessage(content="买80个鼠标给IT部")],
            department_id="dept_it",
            cart_items=[{"product_id": "p004", "product_name": "鼠标", "quantity": 80}],
        )
        config = {"configurable": {"thread_id": "s4-int"}}

        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass

    final = await graph.aget_state(config)
    ts = final.values.get("tier_suggestion", "")
    assert ts, "应生成凑单建议"
    assert "100" in ts, "建议应提及 100 个阶梯"
