from langgraph.types import Command

from app.agent.state import AgentState


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
