"""Mock 工具集：用于替代真实 MCP 工具进行单元测试。"""
import json
from typing import Any

from langchain_core.tools import tool


def make_mock_tools(
    *,
    simulate_response: str | None = None,
    draft_response: str | None = None,
    inventory_response: str | None = None,
) -> list:
    """创建 mock 工具集，simulate/draft/inventory 可按场景覆盖。"""

    @tool(description="搜索商品列表")
    async def search_product(q: str = "", product_id: str = "") -> str:
        return json.dumps([{"id": "p001", "name": "显示器", "sku": "MON-001"}])

    @tool(description="查询部门预算")
    async def check_budget(department_id: str = "") -> str:
        return json.dumps({
            "department_id": department_id,
            "total_budget": 100000.0, "used_budget": 50000.0, "available": 50000.0,
        })

    @tool(description="查询库存")
    async def check_inventory(product_id: str = "") -> str:
        if inventory_response:
            return inventory_response
        return json.dumps({"product_id": product_id, "total_qty": 20, "available_qty": 20})

    @tool(description="模拟采购试算")
    async def simulate_purchase(department_id: str = "", items: Any = "[]") -> str:
        if simulate_response:
            return simulate_response
        item_list = json.loads(items) if isinstance(items, str) else items
        total = sum(1000.0 * i.get("quantity", 1) for i in item_list)
        return json.dumps({
            "department_remaining_budget": 50000.0,
            "all_quotes": [{
                "supplier_id": "sup_a", "supplier_name": "深圳宏达电子",
                "default_lead_time_days": 15, "rating": 4.5, "total_amount": total,
                "line_details": [{"product_id": i.get("product_id", "p001"), "product_name": "显示器",
                                  "quantity": i.get("quantity", 1), "unit_price": 1000.0,
                                  "subtotal": 1000.0 * i.get("quantity", 1)} for i in item_list],
            }],
        })

    @tool(description="创建采购单")
    async def draft_purchase_order(
        department_id: str = "", supplier_id: str = "",
        items: Any = "[]", agent_reasoning: str = "",
    ) -> str:
        if draft_response:
            return draft_response
        return json.dumps({"id": "po-001", "po_number": "PO-20260607-001", "status": "DRAFT", "total_amount": 5000.0})

    return [search_product, check_budget, check_inventory, simulate_purchase, draft_purchase_order]
