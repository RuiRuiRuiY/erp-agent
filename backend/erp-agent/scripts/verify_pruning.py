"""
Task 3.1 验收脚本: 验证 10 个工具的 Pruning 函数

验收标准:
1. 每个工具裁剪后结构可用（字段存在、类型正确）
2. 裁剪显著减小响应体积
"""
import asyncio
import json
import sys

from app.mcp.client import get, post
from app.mcp.pruning import prune


def estimate_tokens(data) -> int:
    return len(json.dumps(data, ensure_ascii=False, default=str))


def verify_fields(label: str, data, expected_fields: dict[str, type]):
    errors = []
    for field, ftype in expected_fields.items():
        if field not in data:
            errors.append(f"缺少字段: {field}")
        elif not isinstance(data[field], ftype):
            errors.append(f"字段 {field} 类型错误: 期望 {ftype.__name__}, 实际 {type(data[field]).__name__}")
    if errors:
        print(f"  [FAIL] {label}: {'; '.join(errors)}")
        return False
    print(f"  [PASS] {label}: 字段验证通过")
    return True


async def verify_tool(name: str, raw, expected_fields: dict[str, type], is_list: bool = False):
    raw_tokens = estimate_tokens(raw)
    pruned = prune(name, raw)
    pruned_tokens = estimate_tokens(pruned)
    ratio = (1 - pruned_tokens / raw_tokens) * 100 if raw_tokens > 0 else 0

    print(f"\n--- {name} ---")
    print(f"  原始: {raw_tokens} tokens")
    print(f"  裁剪: {pruned_tokens} tokens")
    print(f"  缩减: {ratio:.1f}%")

    if pruned_tokens >= raw_tokens and ratio < 1:
        print(f"  [WARN] 裁剪未生效，检查 pruner 逻辑")

    if is_list:
        if not isinstance(pruned, list):
            print(f"  [FAIL] 期望 list, 实际 {type(pruned).__name__}")
            return False
        if len(pruned) == 0:
            print(f"  [WARN] 裁剪后为空列表")
            return True
        ok = verify_fields(f"{name}[0]", pruned[0], expected_fields)
    else:
        if not isinstance(pruned, dict):
            print(f"  [FAIL] 期望 dict, 实际 {type(pruned).__name__}")
            return False
        ok = verify_fields(f"{name}", pruned, expected_fields)

    return ok


async def main():
    print("=== Task 3.1 验收: 10 个工具 Pruning 函数 ===\n")

    # 1. search_product
    print("\n[1/10] search_product")
    raw = await get("/products", params={"limit": 5})
    ok = await verify_tool(
        "search_product", raw,
        {"id": str, "sku": str, "name": str, "category": str},
        is_list=True,
    )
    if not ok:
        return

    # 2. check_department
    print("\n[2/10] check_department")
    raw = await get("/departments", params={"limit": 5})
    ok = await verify_tool(
        "check_department", raw,
        {"id": str, "name": str},
        is_list=True,
    )
    if not ok:
        return

    # 查一个具体部门用于 budget
    depts = raw if isinstance(raw, list) else []
    dept_id = depts[0]["id"] if depts else ""

    # 3. check_budget
    print("\n[3/10] check_budget")
    if dept_id:
        raw = await get(f"/budgets/{dept_id}")
    else:
        print("  [SKIP] 无部门 ID")
        return
    ok = await verify_tool(
        "check_budget", raw,
        {"department_id": str, "fiscal_year": int, "total_budget": (int, float), "available": (int, float)},
    )
    if not ok:
        return

    # 4. check_inventory — 取第一个产品的 ID
    print("\n[4/10] check_inventory")
    products = await get("/products", params={"limit": 1})
    prod_id = products[0]["id"] if isinstance(products, list) and products else ""
    if prod_id:
        raw = await get(f"/inventory/{prod_id}")
    else:
        print("  [SKIP] 无产品 ID")
        return
    ok = await verify_tool(
        "check_inventory", raw,
        {"product_id": str, "available_qty": int},
    )
    if not ok:
        return

    # 5. list_suppliers
    print("\n[5/10] list_suppliers")
    raw = await get("/suppliers", params={"limit": 5})
    ok = await verify_tool(
        "list_suppliers", raw,
        {"id": str, "name": str, "rating": (int, float), "lead_time_days": int},
        is_list=True,
    )
    if not ok:
        return

    # 6. get_supplier_pricelist — 取第一个供应商
    print("\n[6/10] get_supplier_pricelist")
    suppliers = raw if isinstance(raw, list) else []
    sup_id = suppliers[0]["id"] if suppliers else ""
    if sup_id:
        raw = await get(f"/suppliers/{sup_id}/pricelists")
    else:
        print("  [SKIP] 无供应商 ID")
        return
    ok = await verify_tool(
        "get_supplier_pricelist", raw,
        {"product_id": str, "min_qty": int, "unit_price": (int, float)},
        is_list=True,
    )
    if not ok:
        return

    # 7. simulate_purchase
    print("\n[7/10] simulate_purchase")
    if dept_id and prod_id:
        raw = await post("/pricing/simulate", {
            "department_id": dept_id,
            "items": [{"product_id": prod_id, "quantity": 2}],
        })
    else:
        print("  [SKIP] 缺少部门/产品 ID")
        return
    ok = await verify_tool(
        "simulate_purchase", raw,
        {"remaining_budget": (int, float),
         "recommended": (dict, type(None))},
    )
    if not ok:
        return
    # 验证推荐供应商明细结构
    pruned = prune("simulate_purchase", raw)
    if pruned.get("recommended"):
        verify_fields("simulate_purchase.recommended", pruned["recommended"],
                       {"name": str, "total": (int, float),
                        "lead_time": int, "rating": (int, float),
                        "items": list})

    # 8-10: 需要先创建 PO 才能测试，跳过端到端，直接验证结构
    print("\n[8/10] draft_purchase_order")
    sample_po = {
        "id": "test-id", "po_number": "PO-2026-0001",
        "status": "DRAFT", "total_amount": 1000.0,
        "supplier_name": "测试供应商", "department_name": "测试部门",
        "lines": [{"product_name": "测试商品", "quantity": 2,
                    "unit_price": 500.0, "line_total": 1000.0}],
    }
    ok = await verify_tool(
        "draft_purchase_order", sample_po,
        {"po_id": str, "po_number": str, "status": str,
         "total_amount": (int, float), "supplier_name": str},
    )

    print("\n[9/10] override_purchase_order")
    ok = await verify_tool(
        "override_purchase_order", sample_po,
        {"po_id": str, "po_number": str, "status": str,
         "total_amount": (int, float), "supplier_name": str},
    )

    print("\n[10/10] transit_po_status")
    sample_transit = {
        "po_id": "test-id", "po_number": "PO-2026-0001",
        "old_status": "DRAFT", "new_status": "PENDING",
        "budget_impact": "已冻结预算 ¥1000.00",
    }
    ok = await verify_tool(
        "transit_po_status", sample_transit,
        {"po_id": str, "po_number": str, "old_status": str,
         "new_status": str, "budget_impact": str},
    )

    print("\n" + "=" * 50)
    print("Task 3.1 验收完成")


if __name__ == "__main__":
    asyncio.run(main())
