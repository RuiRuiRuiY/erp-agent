
import asyncio
import json

from app.mcp.client import get, post
from app.mcp.pruning import prune


def estimate_tokens(data) -> int:
    return len(json.dumps(data, ensure_ascii=False, default=str))


def verify_fields(label: str, data, expected_fields: dict[str, type]) -> bool:
    errors = []
    for field, ftype in expected_fields.items():
        if field not in data:
            errors.append(f"缺少字段: {field}")
        elif not isinstance(data[field], ftype):
            errors.append(f"字段 {field} 类型错误: 期望 {ftype.__name__}, 实际 {type(data[field]).__name__}")
    if errors:
        print(f"  [FAIL] {label}: {'; '.join(errors)}")
        return False
    return True


async def _verify_tool(name: str, raw, expected_fields: dict[str, type], is_list: bool = False) -> bool:
    raw_tokens = estimate_tokens(raw)
    pruned = prune(name, raw)
    pruned_tokens = estimate_tokens(pruned)
    ratio = (1 - pruned_tokens / raw_tokens) * 100 if raw_tokens > 0 else 0

    if is_list:
        if not isinstance(pruned, list):
            return False
        if len(pruned) == 0:
            return True
        return verify_fields(f"{name}[0]", pruned[0], expected_fields)
    else:
        if not isinstance(pruned, dict):
            return False
        return verify_fields(name, pruned, expected_fields)
    return True


async def _run_all():
    # 1. search_product
    raw = await get("/products", params={"limit": 5})
    ok = await _verify_tool(
        "search_product", raw,
        {"id": str, "sku": str, "name": str, "category": str},
        is_list=True,
    )
    assert ok, "search_product 裁剪验证失败"

    # 2. check_department
    raw = await get("/departments", params={"limit": 5})
    ok = await _verify_tool(
        "check_department", raw,
        {"id": str, "name": str},
        is_list=True,
    )
    assert ok, "check_department 裁剪验证失败"
    depts = raw if isinstance(raw, list) else []

    # 3. check_budget
    dept_id = depts[0]["id"] if depts else ""
    assert dept_id, "无部门 ID"
    raw = await get(f"/budgets/{dept_id}")
    ok = await _verify_tool(
        "check_budget", raw,
        {"department_id": str, "fiscal_year": int, "total_budget": (int, float), "available": (int, float)},
    )
    assert ok, "check_budget 裁剪验证失败"

    # 4. check_inventory
    products = await get("/products", params={"limit": 1})
    prod_id = products[0]["id"] if isinstance(products, list) and products else ""
    assert prod_id, "无产品 ID"
    raw = await get(f"/inventory/{prod_id}")
    ok = await _verify_tool(
        "check_inventory", raw,
        {"product_id": str, "available_qty": int},
    )
    assert ok, "check_inventory 裁剪验证失败"

    # 5. list_suppliers
    raw = await get("/suppliers", params={"limit": 5})
    ok = await _verify_tool(
        "list_suppliers", raw,
        {"id": str, "name": str, "rating": (int, float), "lead_time_days": int},
        is_list=True,
    )
    assert ok, "list_suppliers 裁剪验证失败"

    # 6. get_supplier_pricelist
    sup_id = raw[0]["id"] if isinstance(raw, list) and raw else ""
    assert sup_id, "无供应商 ID"
    raw = await get(f"/suppliers/{sup_id}/pricelists")
    ok = await _verify_tool(
        "get_supplier_pricelist", raw,
        {"product_id": str, "min_qty": int, "unit_price": (int, float)},
        is_list=True,
    )
    assert ok, "get_supplier_pricelist 裁剪验证失败"

    # 7. simulate_purchase
    assert dept_id and prod_id, "缺少部门/产品 ID"
    raw = await post("/pricing/simulate", {
        "department_id": dept_id,
        "items": [{"product_id": prod_id, "quantity": 2}],
    })
    ok = await _verify_tool(
        "simulate_purchase", raw,
        {"remaining_budget": (int, float), "recommended": (dict, type(None))},
    )
    assert ok, "simulate_purchase 裁剪验证失败"
    pruned = prune("simulate_purchase", raw)
    if pruned.get("recommended"):
        verify_fields("simulate_purchase.recommended", pruned["recommended"],
                       {"name": str, "total": (int, float),
                        "lead_time": int, "rating": (int, float),
                        "items": list})

    # 8-10: 构造数据验证结构
    sample_po = {
        "id": "test-id", "po_number": "PO-2026-0001",
        "status": "DRAFT", "total_amount": 1000.0,
        "supplier_name": "测试供应商", "department_name": "测试部门",
        "lines": [{"product_name": "测试商品", "quantity": 2,
                    "unit_price": 500.0, "line_total": 1000.0}],
    }
    ok = await _verify_tool(
        "draft_purchase_order", sample_po,
        {"po_id": str, "po_number": str, "status": str,
         "total_amount": (int, float), "supplier_name": str},
    )
    assert ok, "draft_purchase_order 裁剪验证失败"

    ok = await _verify_tool(
        "override_purchase_order", sample_po,
        {"po_id": str, "po_number": str, "status": str,
         "total_amount": (int, float), "supplier_name": str},
    )
    assert ok, "override_purchase_order 裁剪验证失败"

    sample_transit = {
        "po_id": "test-id", "po_number": "PO-2026-0001",
        "old_status": "DRAFT", "new_status": "PENDING",
        "budget_impact": "已冻结预算 ¥1000.00",
    }
    ok = await _verify_tool(
        "transit_po_status", sample_transit,
        {"po_id": str, "po_number": str, "old_status": str,
         "new_status": str, "budget_impact": str},
    )
    assert ok, "transit_po_status 裁剪验证失败"


def test_pruning():
    asyncio.run(_run_all())
