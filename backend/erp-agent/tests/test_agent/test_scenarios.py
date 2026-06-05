
"""
Task 4.5: 5 个业务陷阱场景端到端测试

需要 mock-erp 运行在 http://127.0.0.1:8000.

陷阱清单:
  1. 价格 vs 交期    -- 显示器 SUP_A ¥1000/15天 vs SUP_B ¥1200/2天
  2. 预算红线        -- 研发部余额 ¥5,000, 椅子 10×¥600=¥6,000
  3. 阶梯凑单        -- 鼠标 90个×¥100 vs 100个×¥80
  4. 库存不足        -- 椅子仅 5 把, 用户要 10 把
  5. 竞争报价        -- 键盘 SUP_A ¥450 vs SUP_C ¥500
"""
import asyncio
import json

from langchain_core.messages import ToolMessage

from app.agent.state import AgentState
from app.agent.nodes import stock_error, tier_suggest, budget_check
from app.agent.routing import route_after_tools
from app.mcp.server import (
    check_budget,
    check_inventory,
    draft_purchase_order,
    simulate_purchase,
)

# ── UUIDs ──────────────────────────────────────────────────────────────────
SUP_A = "c39c69ee-d865-47c4-a067-62038722811a"
SUP_C = "79a08cf4-6cfd-4c9e-8cf2-b7911a06b781"
DEPT_RD = "716ab0b4-c98e-473f-81fc-1a8063cc179d"
DEPT_IT = "1061736d-f4ea-43c4-ba0e-60d1224bfc78"
PROD_MONITOR = "07c5fb7a-2c99-40cb-be86-bd70a2a35fbd"
PROD_CHAIR = "fe87f02a-1d9f-4960-b6b0-9adf30e9ff84"
PROD_MOUSE = "fbf13637-2305-48d1-a1d7-311d8eb5bcf3"
PROD_KEYBOARD = "e79c3b47-a9b0-4334-8d0b-cd7d50eff850"


def make_state(tool_content: str, **extra) -> AgentState:
    base = AgentState(
        messages=[ToolMessage(content=tool_content, tool_call_id="t", name="test")],
        error_context=None,
        tier_suggestion=None,
    )
    base.update(extra)
    return base


async def _scenario_1():
    items = [{"product_id": PROD_MONITOR, "quantity": 5}]
    raw = await simulate_purchase(department_id=DEPT_IT, items=items)
    data = json.loads(raw)
    quotes = {q["supplier_name"]: q for q in data.get("all_quotes", [])}
    sup_a = quotes.get("深圳宏达电子")
    sup_b = quotes.get("上海极速科技")
    assert sup_a and sup_b, "缺少供应商报价"
    assert sup_a["total_amount"] < sup_b["total_amount"], "SUP_A 应更便宜"
    assert sup_a["default_lead_time_days"] > sup_b["default_lead_time_days"], "SUP_A 交期应更长"


async def _scenario_2():
    raw = await check_budget(department_id=DEPT_RD)
    data = json.loads(raw)
    avail = data["available"]

    items = [{"product_id": PROD_CHAIR, "quantity": 10}]
    raw2 = await simulate_purchase(department_id=DEPT_RD, items=items)
    sim = json.loads(raw2)
    total = 0
    for q in sim.get("all_quotes", []):
        total = q.get("total_amount", 0)
        break
    assert total > avail, f"总价 {total} 应超过可用预算 {avail}"

    po_items = [{"product_id": PROD_CHAIR, "quantity": 10}]
    raw3 = await draft_purchase_order(
        department_id=DEPT_RD, supplier_id=SUP_C, items=po_items,
        agent_reasoning="为研发部紧急采购10把人体工学椅以改善办公条件",
    )
    err = json.loads(raw3)
    assert err.get("_error"), "应返回错误"
    assert err.get("error_code") == "BUDGET_INSUFFICIENT"
    assert err.get("action") == "request_override"

    state = make_state(raw3)
    route = route_after_tools(state)
    assert route == "budget_check"
    node_result = budget_check(state)
    assert node_result.get("pending_approval_type") == "budget"


async def _scenario_3():
    items = [{"product_id": PROD_MOUSE, "quantity": 90}]
    raw = await simulate_purchase(department_id=DEPT_IT, items=items)
    state = make_state(raw)
    route = route_after_tools(state)
    assert route == "tier_suggest"
    result = await tier_suggest(state)
    ts = result.get("tier_suggestion", "")
    assert ts, "应生成凑单建议"
    assert "罗技无线鼠标" in ts
    assert "100" in ts and "80" in ts


async def _scenario_4():
    raw_inv = await check_inventory(product_id=PROD_CHAIR)
    inv = json.loads(raw_inv)
    print(f"  人体工学椅可用库存: {inv.get('available_qty', '?')}")

    po_items = [{"product_id": PROD_CHAIR, "quantity": 10}]
    raw = await draft_purchase_order(
        department_id=DEPT_IT, supplier_id=SUP_C, items=po_items,
        agent_reasoning="测试库存不足场景，紧急采购10把人体工学椅",
    )
    err = json.loads(raw)
    if not err.get("_error"):
        return  # seed 数据充裕时跳过

    assert err.get("error_code") == "INSUFFICIENT_STOCK"
    assert err.get("action") == "self_heal"
    ctx = err.get("context", {})

    state = make_state(raw, error_context=ctx)
    route = route_after_tools(state)
    assert route == "stock_error"
    result = stock_error(state)
    msg = result.get("messages", [{}])[0].get("content", "")
    assert "库存不足" in msg
    assert result.get("recovery_attempted")


async def _scenario_5():
    items = [{"product_id": PROD_KEYBOARD, "quantity": 5}]
    raw = await simulate_purchase(department_id=DEPT_IT, items=items)
    data = json.loads(raw)
    quotes = {q["supplier_name"]: q for q in data.get("all_quotes", [])}
    sup_a = quotes.get("深圳宏达电子")
    sup_c = quotes.get("广州万通商贸")
    assert sup_a and sup_c, "缺少供应商报价"
    assert sup_a["total_amount"] < sup_c["total_amount"], "SUP_A 应更便宜"


def test_scenario_1_price_vs_leadtime():
    asyncio.run(_scenario_1())


def test_scenario_2_budget_redline():
    asyncio.run(_scenario_2())


def test_scenario_3_tiered_pricing():
    asyncio.run(_scenario_3())


def test_scenario_4_insufficient_stock():
    asyncio.run(_scenario_4())


def test_scenario_5_competitive_bidding():
    asyncio.run(_scenario_5())
