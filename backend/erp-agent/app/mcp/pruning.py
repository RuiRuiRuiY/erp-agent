from __future__ import annotations

import json

from langfuse import observe
from opentelemetry import trace


def estimate_tokens(data) -> int:
    if data is None:
        return 0
    return len(json.dumps(data, ensure_ascii=False, default=str))


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
    result: dict = {}

    remaining = raw.get("department_remaining_budget")
    if remaining is not None:
        result["remaining_budget"] = remaining

    recommended_id = raw.get("recommended_supplier_id")
    mention = raw.get("recommendation_reason")
    if mention:
        result["reason"] = mention

    for q in raw.get("all_quotes", []):
        if q.get("supplier_id") == recommended_id:
            result["recommended"] = {
                "name": q.get("supplier_name"),
                "total": q.get("total_amount"),
                "lead_time": q.get("default_lead_time_days"),
                "rating": q.get("rating"),
                "items": [
                    {
                        "name": d.get("product_name"),
                        "qty": d.get("quantity"),
                        "price": d.get("unit_price"),
                        "subtotal": d.get("subtotal"),
                    }
                    for d in q.get("line_details", [])
                ],
            }
            break

    alts = [
        {
            "name": q.get("supplier_name"),
            "total": q.get("total_amount"),
            "lead_time": q.get("default_lead_time_days"),
            "rating": q.get("rating"),
        }
        for q in raw.get("all_quotes", [])
        if q.get("supplier_id") != recommended_id
    ]
    if alts:
        result["alternatives"] = alts

    skipped = [
        f'{s.get("supplier_name")}: {s.get("reason")}'
        for s in raw.get("skipped_suppliers", [])
    ]
    if skipped:
        result["skipped"] = skipped

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


@observe(name="prune", capture_input=False)
def prune(tool_name: str, raw_response: dict | list) -> dict | list:
    pruner = PRUNERS.get(tool_name)
    if pruner is None:
        _record_metrics(tool_name, raw_response, raw_response)
        return raw_response
    result = pruner(raw_response)
    _record_metrics(tool_name, raw_response, result)
    return result


def _record_metrics(tool_name: str, raw: dict | list, pruned: dict | list) -> None:
    try:
        raw_t = estimate_tokens(raw)
        pruned_t = estimate_tokens(pruned)
        ratio = round((1 - pruned_t / raw_t) * 100, 1) if raw_t > 0 else 0.0
        span = trace.get_current_span()
        span.set_attribute("tool_name", tool_name)
        span.set_attribute("raw_tokens", raw_t)
        span.set_attribute("pruned_tokens", pruned_t)
        span.set_attribute("compression_ratio", ratio)
    except Exception:
        pass
