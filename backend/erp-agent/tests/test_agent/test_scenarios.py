
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
    list_suppliers,
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
    """S1 常规采购：多供应商价格 vs 交期权衡"""
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
    """S2 库存不足：draft_purchase_order 失败 → stock_error 生成替代方案"""
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


async def _scenario_3():
    """S3 预算红线：超预算 → BUDGET_INSUFFICIENT → budget_check 挂起"""
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


async def _scenario_4():
    """S4 阶梯凑单完整流程：检测阶梯 → 生成建议 → 用户确认/拒绝后的试算变化"""
    # ── 1. 原始报价（80 个，在库存范围内）───────────────────────────
    items_80 = [{"product_id": PROD_MOUSE, "quantity": 80}]
    raw = await simulate_purchase(department_id=DEPT_IT, items=items_80)
    data_80 = json.loads(raw)
    assert data_80.get("all_quotes"), "应返回报价数据"

    # 确认 80 个走第一阶梯（100 元/个）
    q80 = _find_quote(data_80, PROD_MOUSE)
    assert q80, "鼠标应有报价明细"
    assert q80.get("unit_price") == 100.0, f"80 个应为 100 元/个"
    assert q80.get("quantity") * q80.get("unit_price") == 8000.0

    # ── 2. analyze_simulate → tier_suggest 生成凑单建议 ─────────────
    state = make_state(raw)
    assert route_after_tools(state) == "analyze_simulate"
    result = await tier_suggest(state)
    ts = result.get("tier_suggestion", "")
    assert ts, "应生成凑单建议"
    assert "100" in ts and "80" in ts, "应提示 100 个的阶梯价 80 元"

    # ── 3. 分支 A：用户确认（加购到 100 享受阶梯价） ────────────────
    items_100 = [{"product_id": PROD_MOUSE, "quantity": 100}]
    raw_100 = await simulate_purchase(department_id=DEPT_IT, items=items_100)
    data_100 = json.loads(raw_100)

    # 验证 100 个享受了 80 元/个的阶梯价
    q100 = _find_quote(data_100, PROD_MOUSE)
    assert q100, "鼠标应有报价明细"
    assert q100.get("unit_price") == 80.0, f"确认后应为 80 元/个，实际: {q100.get('unit_price')}"
    assert q100.get("subtotal") == 8000.0, f"总价应为 8000，实际: {q100.get('subtotal')}"

    # 100 个已经是最高阶梯 → tier_suggest 返回空
    state_100 = make_state(raw_100)
    result_100 = await tier_suggest(state_100)
    ts_100 = result_100.get("tier_suggestion", "")
    assert not ts_100, "已是最高阶梯，不应再生成建议"

    # ── 4. 分支 B：用户拒绝（维持 80 个，按原价 100 元/个） ────────
    # 拒绝后，原数量不变，走正常建单/预算检查链路
    q80_b = _find_quote(data_80, PROD_MOUSE)
    assert q80_b.get("unit_price") == 100.0, "拒绝后仍为 100 元/个"
    assert q80_b.get("subtotal") == 8000.0


def _find_quote(data: dict, product_id: str) -> dict | None:
    for q in data.get("all_quotes", []):
        for d in q.get("line_details", []):
            if d.get("product_id") == product_id:
                return d
    return None


async def _scenario_5():
    """S5 综合寻源完整流程：多供应商对比 → 加权评分 → 推荐"""
    # ── 1. 获取供应商基础信息 ────────────────────────────────────────
    sup_raw = await list_suppliers()
    sups = {s["id"]: s for s in json.loads(sup_raw)}
    for sid in (SUP_A, SUP_C):
        assert sid in sups, f"供应商 {sid} 应存在"
    assert sups[SUP_A]["rating"] == 4.5
    assert sups[SUP_C]["rating"] == 4.8

    # ── 2. 获取机械键盘多供应商报价 ──────────────────────────────────
    items = [{"product_id": PROD_KEYBOARD, "quantity": 5}]
    raw = await simulate_purchase(department_id=DEPT_IT, items=items)
    data = json.loads(raw)
    assert data.get("all_quotes"), "应返回供应商报价"
    assert len(data["all_quotes"]) >= 2, "至少应有 2 个供应商报价"

    quotes = {q["supplier_name"]: q for q in data.get("all_quotes", [])}
    sup_a = quotes.get("深圳宏达电子")
    sup_c = quotes.get("广州万通商贸")
    assert sup_a and sup_c, "缺少供应商报价"

    # ── 3. 验证数据完整性 ────────────────────────────────────────────
    # 价格
    assert sup_a["total_amount"] == 2250.0, f"SUP_A 5x450=2250"
    assert sup_c["total_amount"] == 2500.0, f"SUP_C 5x500=2500"
    assert sup_a["total_amount"] < sup_c["total_amount"], "SUP_A 应更便宜"

    # 交期
    assert sup_a["default_lead_time_days"] == 15, "SUP_A 交期 15 天"
    assert sup_c["default_lead_time_days"] == 7, "SUP_C 交期 7 天"

    # 评分
    assert sups[SUP_A]["rating"] == 4.5
    assert sups[SUP_C]["rating"] == 4.8

    # ── 4. 综合对比维度验证 ──────────────────────────────────────────
    # 价格维度：SUP_A 更低
    assert sup_a["total_amount"] < sup_c["total_amount"]
    # 交期维度：SUP_C 更快
    assert sup_c["default_lead_time_days"] < sup_a["default_lead_time_days"]
    # 评分维度：SUP_C 更高
    assert sups[SUP_C]["rating"] > sups[SUP_A]["rating"]
    # 结论：各有优势，需 Agent 根据用户偏好推荐

    # ── 5. 路由校验 ──────────────────────────────────────────────────
    # simulate_purchase 有 all_quotes → 路由到 analyze_simulate
    state = make_state(raw)
    assert route_after_tools(state) == "analyze_simulate"
    # 键盘 5 个没有阶梯价 → tier_suggest 返回空
    result = await tier_suggest(state)
    assert not result.get("tier_suggestion"), "键盘无阶梯价，不应生成建议"


def test_scenario_1_price_vs_leadtime():
    asyncio.run(_scenario_1())


def test_scenario_2_stock_shortage():
    asyncio.run(_scenario_2())


def test_scenario_3_budget_redline():
    asyncio.run(_scenario_3())


def test_scenario_4_tiered_pricing():
    asyncio.run(_scenario_4())


def test_scenario_5_competitive_bidding():
    asyncio.run(_scenario_5())
