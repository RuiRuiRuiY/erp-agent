"""
S4 集成测试：阶梯凑单

simulate_result 含未命中高阶阶梯 → entry → tier_suggest → 生成建议
图正常结束，tier_suggestion 有值

验收: tier_suggestion 包含阶梯价信息
"""
import json
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage

from app.agent.state import AgentState
from app.agent.graph import build_graph

graph = build_graph()


async def test_s4_tiered_pricing():
    simulate_raw = json.dumps({
        "all_quotes": [
            {"supplier_id": "sup_c", "supplier_name": "Guangzhou Wantong",
             "default_lead_time_days": 7, "rating": 4.8, "total_amount": 8000.0,
             "line_details": [{"product_id": "p004", "product_name": "Logitech Mouse",
                               "quantity": 80, "unit_price": 100.0, "subtotal": 8000.0}]},
        ],
    })
    # Patch erp_get to return tiered pricing data (1-99:100, 100+:80)
    pricelist = [
        {"min_qty": 1, "unit_price": 100.0},
        {"min_qty": 100, "unit_price": 80.0},
    ]

    initial = AgentState(
        messages=[ToolMessage(content=simulate_raw, tool_call_id="t1", name="simulate_purchase")],
        simulate_result={"raw": simulate_raw},
    )
    config = {"configurable": {"thread_id": "s4-int"}}

    with patch("app.agent.nodes.erp_get", AsyncMock(return_value=pricelist)):
        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass

    final = await graph.aget_state(config)
    ts = final.values.get("tier_suggestion", "")
    assert ts, "应生成凑单建议"
    assert "100" in ts, "建议应提及 100 个阶梯"
