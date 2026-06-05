import json

from langgraph.types import Command

from app.agent.state import AgentState
from app.mcp.client import get as erp_get


def stock_error(state: AgentState) -> dict:
    """处理 INSUFFICIENT_STOCK 错误，生成替代方案。"""
    ctx = state.get("error_context") or {}
    product_id = ctx.get("product_id", "")
    requested = ctx.get("requested", 0)
    available = ctx.get("available", 0)

    alt_qty = min(requested, available)
    msg = (
        f"商品库存不足。"
        f"需求 {requested} 件，当前可用 {available} 件。\n\n"
        f"建议方案：\n"
        f"A. 将数量减至 {alt_qty} 件后重新下单\n"
        f"B. 更换其他商品"
    )

    return {
        "error_context": None,
        "recovery_attempted": True,
        "recovery_path": "reduce_qty" if requested > available else "change_product",
        "messages": [{"role": "assistant", "content": msg}],
    }


async def tier_suggest(state: AgentState) -> dict:
    """检测阶梯价格差距，生成凑单建议。"""
    msgs = state.get("messages", [])
    if not msgs:
        return {}

    last = msgs[-1]
    content = getattr(last, "content", "")
    if not isinstance(content, str) or not content.strip().startswith("{"):
        return {}

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return {}

    if not isinstance(data, dict):
        return {}

    all_quotes = data.get("all_quotes")
    if not all_quotes:
        return {}

    suggestions = []
    seen = set()

    for quote in all_quotes:
        sid = quote.get("supplier_id", "")
        sname = quote.get("supplier_name", "")
        for detail in quote.get("line_details", []):
            pid = detail.get("product_id", "")
            pname = detail.get("product_name", "")
            qty = detail.get("quantity", 0)
            unit_price = detail.get("unit_price", 0)

            if not pid or pid in seen or qty <= 0 or unit_price <= 0:
                continue
            seen.add(pid)

            try:
                pricelist = await erp_get(f"/suppliers/{sid}/pricelists", params={"product_id": pid})
            except Exception:
                continue

            if not isinstance(pricelist, list):
                continue

            tiers = sorted(pricelist, key=lambda t: t.get("min_qty", 0))
            for tier in tiers:
                tier_min = tier.get("min_qty", 0)
                tier_price = tier.get("unit_price", 0)
                if tier_min > qty and tier_price > 0 and tier_price < unit_price:
                    add_qty = tier_min - qty
                    savings = round((unit_price - tier_price) * tier_min, 2)
                    suggestions.append({
                        "supplier": sname,
                        "product": pname,
                        "current_qty": qty,
                        "current_price": unit_price,
                        "suggested_qty": tier_min,
                        "suggested_price": tier_price,
                        "extra_qty": add_qty,
                        "savings": savings,
                    })
                    break

    if not suggestions:
        return {}

    lines = ["阶梯价格建议："]
    for s in suggestions:
        lines.append(
            f"- {s['product']}（{s['supplier']}）：当前 {s['current_qty']}件×¥{s['current_price']:.2f}"
            f" → 加购 {s['extra_qty']}件至 {s['suggested_qty']}件×¥{s['suggested_price']:.2f}"
            f"，可节省约 ¥{s['savings']:.2f}"
        )
    lines.append("\n是否按建议调整数量？")

    msg = "\n".join(lines)
    return {
        "tier_suggestion": msg,
        "messages": [{"role": "assistant", "content": msg}],
    }


def budget_check(state: AgentState) -> dict:
    """处理预算不足情况，设 pending_approval_type 并产生警告消息。"""
    msgs = state.get("messages", [])
    if not msgs:
        return {}

    last = msgs[-1]
    content = getattr(last, "content", "")
    if not isinstance(content, str) or not content.strip().startswith("{"):
        return {}

    try:
        budget_data = json.loads(content)
    except json.JSONDecodeError:
        return {}

    if not isinstance(budget_data, dict):
        return {}

    available = budget_data.get("available", 0)
    department_id = budget_data.get("department_id", "")
    fiscal_year = budget_data.get("fiscal_year", "")

    if available >= 0:
        return {}

    msg = (
        f"预算警告：部门 [{department_id}] 财年 [{fiscal_year}] "
        f"可用预算为 ¥{available:.2f}，已出现透支。\n"
        f"需要财务主管审批（override_token）后才能继续。"
    )

    return {
        "pending_approval_type": "budget",
        "messages": [{"role": "assistant", "content": msg}],
    }
