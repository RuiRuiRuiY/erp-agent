import json

from langgraph.types import Command, interrupt

from app.agent.state import AgentState
from app.mcp.client import get as erp_get
from app.mcp.server import override_purchase_order, transit_po_status


def _extract_error_context(state: AgentState) -> dict:
    """从 state.error_context 或最后一条 tool message 的 context 中提取。"""
    ctx = state.get("error_context") or {}
    if ctx:
        return ctx
    msgs = state.get("messages", [])
    if not msgs:
        return {}
    last = msgs[-1]
    content = getattr(last, "content", "")
    if not isinstance(content, str):
        return {}
    try:
        data = json.loads(content)
        return data.get("context", {}) if isinstance(data, dict) else {}
    except (json.JSONDecodeError, AttributeError):
        return {}


def stock_error(state: AgentState) -> dict:
    """处理 INSUFFICIENT_STOCK 错误，生成替代方案。"""
    ctx = _extract_error_context(state)
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
    """处理预算不足情况，设 pending_approval_type 并产生警告消息。

    支持两种触发方式：
    - check_budget 返回 available < 0（预算推算透支）
    - draft_purchase_order 返回 BUDGET_INSUFFICIENT（实际扣预算失败）
    """
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

    # 场景 A: draft_purchase_order 返回 BUDGET_INSUFFICIENT
    # catch_erp_error 已把 context 金额从分转为元，直接使用
    if data.get("_error") and data.get("error_code") == "BUDGET_INSUFFICIENT":
        ctx = data.get("context", {})
        required = ctx.get("required", 0) or 0
        remaining = ctx.get("remaining", 0) or 0
        deficit = ctx.get("deficit", 0) or 0
        msg = (
            f"预算不足：采购需 ¥{required:.2f}，部门仅剩 ¥{remaining:.2f}，"
            f"缺口 ¥{deficit:.2f}。\n"
            f"需要财务主管审批（override_token）后才能继续。"
        )
        return {
            "pending_approval_type": "budget",
            "messages": [{"role": "assistant", "content": msg}],
        }

    # 场景 B: check_budget 返回 available < 0
    if "available" in data:
        available = data.get("available", 0)
        if available >= 0:
            return {}

        department_id = data.get("department_id", "")
        fiscal_year = data.get("fiscal_year", "")
        msg = (
            f"预算警告：部门 [{department_id}] 财年 [{fiscal_year}] "
            f"可用预算为 ¥{available:.2f}，已出现透支。\n"
            f"需要财务主管审批（override_token）后才能继续。"
        )
        return {
            "pending_approval_type": "budget",
            "messages": [{"role": "assistant", "content": msg}],
        }

    return {}


def hitl_gate(state: AgentState) -> dict:
    """HITL 审批门：挂起图等待 override_token，恢复后注入 state 继续执行。

    interrupt() 调用后图暂停，resume 时传入 {"override_token": "..."}。
    """
    if state.get("override_token"):
        return {"pending_approval_type": None}

    token = interrupt({
        "pending_type": state.get("pending_approval_type"),
        "request": "override_token",
        "message": "需要财务主管审批（override_token）后才能继续",
    })
    if isinstance(token, dict):
        token = token.get("override_token", token)

    return {"override_token": token, "pending_approval_type": None}


async def override_po(state: AgentState) -> dict:
    """resume 后调用 override_purchase_order 创建特批采购单。

    从 state 中读取 department_id / selected_supplier_id / cart_items / override_token，
    调用 MCP override 工具创建特批 PO，将结果写入 state。
    """
    override_token = state.get("override_token")
    dept_id = state.get("department_id")
    supplier_id = state.get("selected_supplier_id")
    cart_items = state.get("cart_items", [])

    if not all([override_token, dept_id, supplier_id, cart_items]):
        return {
            "messages": [{
                "role": "assistant",
                "content": "缺少必要参数（部门/供应商/商品/override_token），无法执行特批建单。",
            }],
        }

    items = [
        {"product_id": item["product_id"], "quantity": item["quantity"]}
        for item in cart_items
    ]
    reasoning = (
        f"特批采购: department={dept_id}, supplier={supplier_id}, "
        f"items={json.dumps(items, ensure_ascii=False)}"
    )

    raw = await override_purchase_order(
        department_id=dept_id,
        supplier_id=supplier_id,
        items=items,
        override_token=override_token,
        agent_reasoning=reasoning,
    )
    data = json.loads(raw)

    if data.get("_error"):
        return {
            "messages": [{
                "role": "assistant",
                "content": f"特批建单失败：{data.get('user_message', data.get('message', ''))}",
            }],
        }

    po_id = data["id"]
    msg = (
        f"特批采购单已创建：{data['po_number']}，金额 ¥{data['total_amount']:.2f}，状态 {data['status']}"
    )

    return {
        "po_draft_id": po_id,
        "po_status": data["status"],
        "po_supplier_id": supplier_id,
        "messages": [{"role": "assistant", "content": msg}],
    }


async def transit_to_pending(state: AgentState) -> dict:
    """将特批 PO 从 DRAFT 流转到 PENDING（提交审批）。

    override 单在 transit 时会跳过预算重校验。
    """
    po_id = state.get("po_draft_id")
    if not po_id:
        return {
            "messages": [{
                "role": "assistant",
                "content": "缺少 PO ID，无法提交审批。",
            }],
        }

    raw = await transit_po_status(po_id=po_id, target_status="PENDING")
    data = json.loads(raw)

    if data.get("_error"):
        return {
            "messages": [{
                "role": "assistant",
                "content": f"提交审批失败：{data.get('user_message', data.get('message', ''))}",
            }],
        }

    return {
        "po_status": "PENDING",
        "messages": [{
            "role": "assistant",
            "content": (
                f"采购单已提交审批，单号: {data['po_number']}。\n"
                f"当前状态: 待审批。财务主管审批通过后即可下单。"
            ),
        }],
    }
