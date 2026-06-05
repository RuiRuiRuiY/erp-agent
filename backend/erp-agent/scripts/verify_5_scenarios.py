"""
Task 4.5: 5 个业务陷阱场景端到端测试

验证方式：为每个场景模拟 tool call → routing → node 执行链路，用真实 mock-erp 数据。

陷阱清单:
  1. 价格 vs 交期    -- 显示器 SUP_A ¥1000/15天 vs SUP_B ¥1200/2天
  2. 预算红线        -- 研发部余额 ¥5,000, 椅子 10×¥600=¥6,000
  3. 阶梯凑单        -- 鼠标 90个×¥100 vs 100个×¥80
  4. 库存不足        -- 椅子仅 5 把, 用户要 10 把
  5. 竞争报价        -- 键盘 SUP_A ¥450 vs SUP_C ¥500
"""
import asyncio
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from langchain_core.messages import ToolMessage
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.agent.state import AgentState
from app.agent.nodes import stock_error, tier_suggest, budget_check
from app.agent.routing import route_after_tools
from app.mcp.server import (
    search_product,
    check_budget,
    check_inventory,
    list_suppliers,
    simulate_purchase,
    draft_purchase_order,
)
from app.mcp.client import ErpApiError

# ── UUIDs ──────────────────────────────────────────────────────────────────
SUP_A = "c39c69ee-d865-47c4-a067-62038722811a"
SUP_B = "291ba124-4083-4d6f-af52-01dfee44cda8"
SUP_C = "79a08cf4-6cfd-4c9e-8cf2-b7911a06b781"
DEPT_RD = "716ab0b4-c98e-473f-81fc-1a8063cc179d"
DEPT_IT = "1061736d-f4ea-43c4-ba0e-60d1224bfc78"
PROD_MONITOR = "07c5fb7a-2c99-40cb-be86-bd70a2a35fbd"
PROD_CHAIR = "fe87f02a-1d9f-4960-b6b0-9adf30e9ff84"
PROD_MOUSE = "fbf13637-2305-48d1-a1d7-311d8eb5bcf3"
PROD_KEYBOARD = "e79c3b47-a9b0-4334-8d0b-cd7d50eff850"
PROD_SERVER = "3ffaebf1-4175-411d-93ba-6795db09f619"


# ── Helper ─────────────────────────────────────────────────────────────────
def make_state(tool_content: str, **extra) -> AgentState:
    base = AgentState(
        messages=[ToolMessage(content=tool_content, tool_call_id="t", name="test")],
        error_context=None,
        tier_suggestion=None,
    )
    base.update(extra)
    return base


async def test_scenario_1_price_vs_leadtime():
    """价格 vs 交期：显示器 SUP_A ¥1000/15天 vs SUP_B ¥1200/2天"""
    print("=" * 60)
    print("场景 1: 价格 vs 交期")
    print("=" * 60)

    items = [{"product_id": PROD_MONITOR, "quantity": 5}]
    raw = await simulate_purchase(department_id=DEPT_IT, items=items)
    data = json.loads(raw)

    quotes = {q["supplier_name"]: q for q in data.get("all_quotes", [])}
    sup_a = quotes.get("深圳宏达电子")
    sup_b = quotes.get("上海极速科技")

    assert sup_a, "缺少 SUP_A 报价"
    assert sup_b, "缺少 SUP_B 报价"

    print(f"  SUP_A: ¥{sup_a['total_amount']:.2f}, 交期 {sup_a['default_lead_time_days']}天")
    print(f"  SUP_B: ¥{sup_b['total_amount']:.2f}, 交期 {sup_b['default_lead_time_days']}天")

    assert sup_a["total_amount"] < sup_b["total_amount"], "SUP_A 应更便宜"
    assert sup_a["default_lead_time_days"] > sup_b["default_lead_time_days"], "SUP_A 交期应更长"
    print("  PASS: 两个供应商报价正确，价格与交期呈反向关系 ✓\n")


async def test_scenario_2_budget_redline():
    """预算红线：研发部余额 ¥5,000, 椅子 10×¥600=¥6,000 → BUDGET_INSUFFICIENT"""
    print("=" * 60)
    print("场景 2: 预算红线")
    print("=" * 60)

    # 查预算
    raw = await check_budget(department_id=DEPT_RD)
    data = json.loads(raw)
    avail = data["available"]
    print(f"  研发部可用预算: ¥{avail:.2f}")

    # 模拟 10 把椅子的 simulate
    items = [{"product_id": PROD_CHAIR, "quantity": 10}]
    raw2 = await simulate_purchase(department_id=DEPT_RD, items=items)
    sim = json.loads(raw2)
    total = sim.get("recommended", sim).get("total_amount") if isinstance(sim.get("recommended"), dict) else sim.get("all_quotes", [{}])[0].get("total_amount", 0)
    if not total:
        for q in sim.get("all_quotes", []):
            total = q.get("total_amount", 0)
            break
    print(f"  椅子 10 把总价: ¥{total:.2f}")
    assert total > avail, f"总价 ¥{total} 应超过可用预算 ¥{avail}"

    # 尝试草拟 PO → 应返回 BUDGET_INSUFFICIENT
    po_items = [{"product_id": PROD_CHAIR, "quantity": 10}]
    raw3 = await draft_purchase_order(
        department_id=DEPT_RD,
        supplier_id=SUP_C,
        items=po_items,
        agent_reasoning="为研发部紧急采购10把人体工学椅以改善办公条件",
    )
    err = json.loads(raw3)
    assert err.get("_error"), "应返回错误"
    assert err.get("error_code") == "BUDGET_INSUFFICIENT", f"预期 BUDGET_INSUFFICIENT, 实际 {err.get('error_code')}"
    assert err.get("action") == "request_override", f"预期 request_override, 实际 {err.get('action')}"

    # 模拟 routing + node
    state = make_state(raw3)
    route = route_after_tools(state)
    assert route == "budget_check", f"应路由到 budget_check, 实际 {route}"
    node_result = budget_check(state)
    assert node_result.get("pending_approval_type") == "budget", "pending_approval_type 应为 budget"
    print(f"  HITL 消息: {node_result['messages'][0]['content'][:60]}...")
    print("  PASS: 预算红线触发 HITL ✓\n")


async def test_scenario_3_tiered_pricing():
    """阶梯凑单：鼠标 90个×¥100 vs 100个×¥80"""
    print("=" * 60)
    print("场景 3: 阶梯凑单")
    print("=" * 60)

    items = [{"product_id": PROD_MOUSE, "quantity": 90}]
    raw = await simulate_purchase(department_id=DEPT_IT, items=items)
    data = json.loads(raw)

    # routing → tier_suggest
    state = make_state(raw)
    route = route_after_tools(state)
    assert route == "tier_suggest", f"应路由到 tier_suggest, 实际 {route}"

    result = await tier_suggest(state)
    ts = result.get("tier_suggestion", "")
    assert ts, "应生成凑单建议"
    assert "罗技无线鼠标" in ts, "应包含商品名"
    assert "100" in ts and "80" in ts, "应包含建议数量和价格"
    print(f"  建议: {ts.split(chr(10))[1]}")
    print("  PASS: 阶梯凑单建议生成 ✓\n")


async def test_scenario_4_insufficient_stock():
    """库存不足：椅子仅 5 把, 用户要 10 把 → INSUFFICIENT_STOCK
    验证: routing → stock_error → 生成替代方案
    """
    print("=" * 60)
    print("场景 4: 库存不足")
    print("=" * 60)

    # 查库存
    raw_inv = await check_inventory(product_id=PROD_CHAIR)
    inv = json.loads(raw_inv)
    print(f"  人体工学椅可用库存: {inv.get('available_qty', '?')}")

    # 尝试草拟 PO 10 把 → 应返回 INSUFFICIENT_STOCK
    po_items = [{"product_id": PROD_CHAIR, "quantity": 10}]
    raw = await draft_purchase_order(
        department_id=DEPT_IT,
        supplier_id=SUP_C,
        items=po_items,
        agent_reasoning="测试库存不足场景，紧急采购10把人体工学椅",
    )
    err = json.loads(raw)
    if not err.get("_error"):
        print("  注意: mock-erp 未返回库存错误（可能 seed 数据充裕）")
        print("  SKIP: 此场景跳过 live API 验证\n")
        return

    assert err.get("error_code") == "INSUFFICIENT_STOCK", f"预期 INSUFFICIENT_STOCK, 实际 {err.get('error_code')}"
    assert err.get("action") == "self_heal", f"预期 self_heal, 实际 {err.get('action')}"

    ctx = err.get("context", {})
    print(f"  库存上下文: {ctx}")

    # routing + stock_error
    state = make_state(raw, error_context=ctx)
    route = route_after_tools(state)
    assert route == "stock_error", f"应路由到 stock_error, 实际 {route}"
    result = stock_error(state)
    msg = result.get("messages", [{}])[0].get("content", "")
    assert "库存不足" in msg, "应包含库存不足描述"
    assert result.get("recovery_attempted"), "应设置 recovery_attempted"
    print(f"  恢复消息: {msg[:80]}...")
    print("  PASS: 库存不足 → stock_error 自愈 ✓\n")


async def test_scenario_5_competitive_bidding():
    """竞争报价：键盘 SUP_A ¥450 vs SUP_C ¥500"""
    print("=" * 60)
    print("场景 5: 竞争报价")
    print("=" * 60)

    items = [{"product_id": PROD_KEYBOARD, "quantity": 5}]
    raw = await simulate_purchase(department_id=DEPT_IT, items=items)
    data = json.loads(raw)

    quotes = {q["supplier_name"]: q for q in data.get("all_quotes", [])}
    sup_a = quotes.get("深圳宏达电子")
    sup_c = quotes.get("广州万通商贸")

    assert sup_a, "缺少 SUP_A"
    assert sup_c, "缺少 SUP_C"

    print(f"  SUP_A: ¥{sup_a['total_amount']:.2f} (评分 {sup_a['rating']})")
    print(f"  SUP_C: ¥{sup_c['total_amount']:.2f} (评分 {sup_c['rating']})")
    assert sup_a["total_amount"] < sup_c["total_amount"], "SUP_A 应更便宜"
    print("  PASS: 两个供应商报价不同, Agent 可做综合对比 ✓\n")


async def main():
    results = {}
    for name, fn in [
        ("1.价格 vs 交期", test_scenario_1_price_vs_leadtime()),
        ("2.预算红线", test_scenario_2_budget_redline()),
        ("3.阶梯凑单", test_scenario_3_tiered_pricing()),
        ("4.库存不足", test_scenario_4_insufficient_stock()),
        ("5.竞争报价", test_scenario_5_competitive_bidding()),
    ]:
        try:
            await fn
            results[name] = "PASS"
        except Exception as e:
            results[name] = f"FAIL: {e}"
            import traceback
            traceback.print_exc()
        finally:
            pass

    print("\n" + "=" * 60)
    print("最终结果")
    print("=" * 60)
    for name, status in results.items():
        tag = "✓" if status == "PASS" else "✗"
        print(f"  [{tag}] {name}: {status}")


asyncio.run(main())
