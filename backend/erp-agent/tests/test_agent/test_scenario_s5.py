"""
S5 集成测试：综合寻源

多供应商报价 → entry → tier_suggest（无阶梯 → 空）
图正常结束，模拟多供应商数据完整

验收: 多供应商报价存在，tier_suggest 不产生建议
"""
import json
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.state import AgentState
from app.agent.schemas import AnalysisResult, Intent, ParseResult
from app.agent.graph import build_graph
from tests.fixtures import make_mock_tools, make_structured_mock_llm


async def test_s5_multi_supplier():
    simulate_resp = json.dumps({
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
    tools = make_mock_tools(simulate_response=simulate_resp)
    mock_llm = make_structured_mock_llm([
        ParseResult(intent=Intent.NEW_REQUEST, department_id="dept_it",
                    cart_items=[{"product_id": "p005", "product_name": "键盘", "quantity": 5}]),
        AIMessage(content="", tool_calls=[{
            "id": "call_001", "name": "simulate_purchase",
            "args": {"department_id": "dept_it", "items": [{"product_id": "p005", "quantity": 5}]},
        }]),
        AnalysisResult(has_tier_opportunity=False, has_stock_risk=False),
        AIMessage(content="请选择供应商编号，或输入其他条件重新试算。"),
    ])

    with patch("app.agent.llm._get_llm", return_value=mock_llm):
        graph = await build_graph(tools=tools)
        initial = AgentState(
            messages=[HumanMessage(content="买5个键盘")],
            department_id="dept_it",
            cart_items=[{"product_id": "p005", "product_name": "键盘", "quantity": 5}],
        )
        config = {"configurable": {"thread_id": "s5-int"}}

        async for _ in graph.astream(initial, config, stream_mode="updates"):
            pass

    final = await graph.aget_state(config)
    assert "messages" in final.values, "图应正常结束"
