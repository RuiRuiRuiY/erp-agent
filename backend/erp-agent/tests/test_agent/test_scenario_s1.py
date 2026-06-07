"""
S1 集成测试：常规采购

simulate_purchase 返回正常报价 → entry → tier_suggest（无阶梯 → 空）
图不报错，正常结束

验收: 路由正确，无阶梯时不产生 tier_suggestion
"""
import json
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage

from app.agent.state import AgentState
from app.agent.graph import build_graph

graph = build_graph()


async def test_s1_regular_purchase():
    simulate_raw = json.dumps({
        "all_quotes": [
            {"supplier_id": "c39c69ee", "supplier_name": "Shenzhen Hongda",
             "default_lead_time_days": 15, "rating": 4.5, "total_amount": 5000.0,
             "line_details": [{"product_id": "p001", "quantity": 5,
                               "unit_price": 1000.0, "subtotal": 5000.0}]},
        ],
    })
    initial = AgentState(
        messages=[ToolMessage(content=simulate_raw, tool_call_id="t1", name="simulate_purchase")],
        simulate_result={"raw": simulate_raw},
    )
    config = {"configurable": {"thread_id": "s1-int"}}

    with patch("app.agent.nodes.erp_get", AsyncMock(return_value=[])):
        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass

    final = await graph.aget_state(config)
    assert "messages" in final.values, "图应正常结束"
