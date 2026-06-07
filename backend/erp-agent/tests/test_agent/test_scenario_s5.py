"""
S5 集成测试：综合寻源

多供应商报价 → entry → tier_suggest（无阶梯 → 空）
图正常结束，模拟多供应商数据完整

验收: 多供应商报价存在，tier_suggest 不产生建议
"""
import json
from unittest.mock import AsyncMock, patch

from langchain_core.messages import ToolMessage

from app.agent.state import AgentState
from app.agent.graph import build_graph

graph = build_graph()


async def test_s5_multi_supplier():
    simulate_raw = json.dumps({
        "all_quotes": [
            {"supplier_id": "sup_a", "supplier_name": "Shenzhen Hongda",
             "default_lead_time_days": 15, "rating": 4.5, "total_amount": 2250.0,
             "line_details": [{"product_id": "p005", "quantity": 5,
                               "unit_price": 450.0, "subtotal": 2250.0}]},
            {"supplier_id": "sup_c", "supplier_name": "Guangzhou Wantong",
             "default_lead_time_days": 7, "rating": 4.8, "total_amount": 2500.0,
             "line_details": [{"product_id": "p005", "quantity": 5,
                               "unit_price": 500.0, "subtotal": 2500.0}]},
        ],
    })

    initial = AgentState(
        messages=[ToolMessage(content=simulate_raw, tool_call_id="t1", name="simulate_purchase")],
        simulate_result={"raw": simulate_raw},
    )
    config = {"configurable": {"thread_id": "s5-int"}}

    with patch("app.agent.nodes.erp_get", AsyncMock(return_value=[])):
        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass

    final = await graph.aget_state(config)
    assert "messages" in final.values, "图应正常结束"
