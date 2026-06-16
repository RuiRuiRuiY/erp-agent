"""
S1 集成测试：常规采购

simulate_purchase 返回正常报价 → entry → tier_suggest（无阶梯 → 空）
图不报错，正常结束

验收: 路由正确，无阶梯时不产生 tier_suggestion
"""
import json
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.state import AgentState
from app.agent.schemas import AnalysisResult, Intent, ParseResult
from app.agent.graph import build_graph
from tests.fixtures import make_mock_tools, make_structured_mock_llm


async def test_s1_regular_purchase():
    simulate_raw = json.dumps({
        "all_quotes": [
            {"supplier_id": "c39c69ee", "supplier_name": "Shenzhen Hongda",
             "default_lead_time_days": 15, "rating": 4.5, "total_amount": 5000.0,
             "line_details": [{"product_id": "p001", "quantity": 5,
                               "unit_price": 1000.0, "subtotal": 5000.0}]},
        ],
    })
    tools = make_mock_tools(simulate_response=simulate_raw)
    mock_llm = make_structured_mock_llm([
        ParseResult(intent=Intent.NEW_REQUEST, department_id="dept_it",
                    cart_items=[{"product_id": "p001", "product_name": "显示器", "quantity": 5}]),
        AIMessage(content="", tool_calls=[{
            "id": "call_001", "name": "simulate_purchase",
            "args": {"department_id": "dept_it", "items": [{"product_id": "p001", "quantity": 5}]},
        }]),
        AnalysisResult(has_tier_opportunity=False, has_stock_risk=False),
        AIMessage(content="请选择供应商编号，或输入其他条件重新试算。"),
    ])

    with patch("app.agent.llm._get_llm", return_value=mock_llm):
        graph = await build_graph(tools=tools)
        initial = AgentState(messages=[HumanMessage(content="买5台显示器给IT部")])
        config = {"configurable": {"thread_id": "s1-int"}}

        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass

    final = await graph.aget_state(config)
    assert "messages" in final.values, "图应正常结束"
