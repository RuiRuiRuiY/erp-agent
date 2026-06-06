"""
S2 集成测试：库存不足协商

error_context 设入 → entry → stock_error → 生成替代方案
图正常结束，recovery 字段正确

验收: recovery_attempted=True, recovery_path 有值
"""
import json

from langchain_core.messages import ToolMessage

from app.agent.state import AgentState
from app.agent.graph import graph


async def test_s2_insufficient_stock():
    initial = AgentState(
        error_context={"product_id": "p003", "requested": 10, "available": 5},
        messages=[ToolMessage(
            content=json.dumps({
                "_error": True,
                "error_code": "INSUFFICIENT_STOCK",
                "context": {"product_id": "p003", "requested": 10, "available": 5},
            }),
            tool_call_id="t1", name="draft_purchase_order",
        )],
    )
    config = {"configurable": {"thread_id": "s2-int"}}

    async for _ in graph.astream(initial, config, stream_mode="updates"):
        pass

    final = await graph.aget_state(config)
    assert final.values.get("recovery_attempted") is True
    assert final.values.get("recovery_path") == "reduce_qty"
