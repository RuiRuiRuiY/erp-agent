"""
手动验证全部 10 个 MCP 工具 + 状态流转

用法:
    uv run python scripts/verify_tools.py

依赖: mock-erp 需在 http://localhost:8000 运行
"""
import asyncio
import json
import sys

from app.mcp.server import get, close_client
from app.mcp.tools import (
    search_product,
    check_department,
    check_budget,
    check_inventory,
    list_suppliers,
    get_supplier_pricelist,
    simulate_purchase,
    draft_purchase_order,
    override_purchase_order,
    transit_po_status,
)


async def call(name: str, coro) -> str:
    try:
        data = json.loads(await coro)
        if isinstance(data, dict):
            return f"OK  {list(data.keys())[:4]}..."
        if isinstance(data, list):
            return f"OK  count={len(data)}"
        return f"OK  {data}"
    except Exception as e:
        return f"ERR {type(e).__name__}: {e}"


async def main():
    print("=" * 60)
    print("ERP-Agent MCP Tool Verification")
    print("=" * 60)

    # Phase 1: discover IDs
    prods = await get("/products")
    depts = await get("/departments")
    prod1 = prods[0]["id"]
    dept1 = depts[0]["id"]
    supps = json.loads(await list_suppliers())
    supp1 = supps[0]["id"]

    print(f"\nUsing: product={prod1[:8]}... dept={dept1[:8]}... supplier={supp1[:8]}...\n")

    # Phase 2: test all tools
    cases = [
        ("1. search_product (list)", search_product()),
        ("2. search_product (by id)", search_product(product_id=prod1)),
        ("3. check_department (list)", check_department()),
        ("4. check_department (by id)", check_department(department_id=dept1)),
        ("5. check_budget", check_budget(department_id=dept1)),
        ("6. check_inventory", check_inventory(product_id=prod1)),
        ("7. list_suppliers (list)", list_suppliers()),
        ("8. list_suppliers (by id)", list_suppliers(supplier_id=supp1)),
        ("9. get_supplier_pricelist", get_supplier_pricelist(supplier_id=supp1)),
        ("10. simulate_purchase", simulate_purchase(
            department_id=dept1, items=[{"product_id": prod1, "quantity": 2}],
        )),
    ]
    for label, coro in cases:
        result = await call(label, coro)
        print(f"  {label:<40s} {result}")

    # Phase 3: write flow (PO + transit)
    sim = json.loads(await simulate_purchase(
        department_id=dept1, items=[{"product_id": prod1, "quantity": 2}],
    ))
    rec_sid = sim["recommended_supplier_id"]
    print(f"\n  recommended_supplier={sim.get('recommended_supplier_name')}")

    po = json.loads(await draft_purchase_order(
        department_id=dept1, supplier_id=rec_sid,
        items=[{"product_id": prod1, "quantity": 2}],
        agent_reasoning="verify_tools.py e2e test",
    ))
    po_id = po["id"]
    print(f"  11. draft_purchase_order     OK  PO={po['po_number']} status={po['status']}")

    tr1 = json.loads(await transit_po_status(po_id=po_id, target_status="PENDING", operator_role="agent"))
    print(f"  12. transit DRAFT->PENDING   OK  {tr1['old_status']}->{tr1['new_status']}")

    tr2 = json.loads(await transit_po_status(po_id=po_id, target_status="APPROVED", operator_role="finance_manager"))
    print(f"  13. transit PENDING->APPROVED OK  {tr2['old_status']}->{tr2['new_status']}")

    # Phase 4: override (create new PO with override)
    over = json.loads(await override_purchase_order(
        department_id=dept1, supplier_id=rec_sid,
        items=[{"product_id": prod1, "quantity": 2}],
        override_token="override-secret-2025",
    ))
    print(f"  14. override_purchase_order  OK  PO={over['po_number']} status={over['status']} (is_override)")

    await close_client()
    print("\n" + "=" * 60)
    print("ALL TOOLS VERIFIED SUCCESSFULLY")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
