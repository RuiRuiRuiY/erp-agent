from __future__ import annotations


def prune_search_product(raw: dict | list) -> dict | list:
    if isinstance(raw, list):
        return [
            {"id": p.get("id"), "sku": p.get("sku"), "name": p.get("name"), "category": p.get("category")}
            for p in raw
        ]
    return {
        "id": raw.get("id"),
        "sku": raw.get("sku"),
        "name": raw.get("name"),
        "category": raw.get("category"),
    }


def prune_check_department(raw: dict | list) -> dict | list:
    if isinstance(raw, list):
        return [{"id": d.get("id"), "name": d.get("name")} for d in raw]
    return {"id": raw.get("id"), "name": raw.get("name")}


def prune_check_budget(raw: dict) -> dict:
    return {
        "department_id": raw.get("department_id"),
        "fiscal_year": raw.get("fiscal_year"),
        "total_budget": raw.get("total_budget"),
        "available": raw.get("available"),
    }


def prune_check_inventory(raw: dict) -> dict:
    return {
        "product_id": raw.get("product_id"),
        "available_qty": raw.get("available_qty"),
    }


def prune_list_suppliers(raw: dict | list) -> dict | list:
    if isinstance(raw, list):
        return [
            {"id": s.get("id"), "name": s.get("name"), "rating": s.get("rating"), "lead_time_days": s.get("default_lead_time_days")}
            for s in raw
        ]
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "rating": raw.get("rating"),
        "lead_time_days": raw.get("default_lead_time_days"),
    }


def prune_get_supplier_pricelist(raw: list) -> list:
    return [
        {"product_id": p.get("product_id"), "min_qty": p.get("min_qty"), "unit_price": p.get("unit_price")}
        for p in raw
    ]


def prune_simulate_purchase(raw: dict) -> dict:
    result = {"department_remaining_budget": raw.get("department_remaining_budget")}

    recommended_id = raw.get("recommended_supplier_id")
    rec_raw = next((q for q in raw.get("all_quotes", []) if q.get("supplier_id") == recommended_id), None)

    if rec_raw:
        result["recommended"] = {
            "name": rec_raw.get("supplier_name"),
            "total_amount": rec_raw.get("total_amount"),
            "lead_time_days": rec_raw.get("default_lead_time_days"),
            "rating": rec_raw.get("rating"),
            "details": [
                {
                    "product_name": d.get("product_name"),
                    "quantity": d.get("quantity"),
                    "unit_price": d.get("unit_price"),
                    "subtotal": d.get("subtotal"),
                }
                for d in rec_raw.get("line_details", [])
            ],
        }
    else:
        result["recommended"] = None

    result["alternatives"] = [
        {
            "name": q.get("supplier_name"),
            "total_amount": q.get("total_amount"),
            "lead_time_days": q.get("default_lead_time_days"),
            "rating": q.get("rating"),
            "line_count": len(q.get("line_details", [])),
        }
        for q in raw.get("all_quotes", [])
        if q.get("supplier_id") != recommended_id
    ]

    result["skipped_reasons"] = [
        f'{s.get("supplier_name")}: {s.get("reason")}'
        for s in raw.get("skipped_suppliers", [])
    ]

    result["recommendation_reason"] = raw.get("recommendation_reason")

    return result


def prune_draft_purchase_order(raw: dict) -> dict:
    return {
        "po_id": raw.get("id"),
        "po_number": raw.get("po_number"),
        "status": raw.get("status"),
        "total_amount": raw.get("total_amount"),
        "supplier_name": raw.get("supplier_name"),
        "department_name": raw.get("department_name"),
        "lines": [
            {
                "product_name": l.get("product_name"),
                "quantity": l.get("quantity"),
                "unit_price": l.get("unit_price"),
                "line_total": l.get("line_total"),
            }
            for l in raw.get("lines", [])
        ],
    }


def prune_override_purchase_order(raw: dict) -> dict:
    return prune_draft_purchase_order(raw)


def prune_transit_po_status(raw: dict) -> dict:
    return {
        "po_id": raw.get("po_id"),
        "po_number": raw.get("po_number"),
        "old_status": raw.get("old_status"),
        "new_status": raw.get("new_status"),
        "budget_impact": raw.get("budget_impact"),
    }


PRUNERS = {
    "search_product": prune_search_product,
    "check_department": prune_check_department,
    "check_budget": prune_check_budget,
    "check_inventory": prune_check_inventory,
    "list_suppliers": prune_list_suppliers,
    "get_supplier_pricelist": prune_get_supplier_pricelist,
    "simulate_purchase": prune_simulate_purchase,
    "draft_purchase_order": prune_draft_purchase_order,
    "override_purchase_order": prune_override_purchase_order,
    "transit_po_status": prune_transit_po_status,
}


def prune(tool_name: str, raw_response: dict | list) -> dict | list:
    pruner = PRUNERS.get(tool_name)
    if pruner is None:
        return raw_response
    return pruner(raw_response)
