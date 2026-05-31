from collections import defaultdict

from sqlmodel import Session

from app.repository.budget import get_budget_by_department_id
from app.repository.product import get_products_by_ids
from app.repository.supplier import get_suppliers_by_ids
from app.repository.supplier_pricelist import get_pricelists_by_product_ids
from app.schema.pricing import (
    SimulateRequest,
    SimulateResponse,
    SkippedSupplierInfo,
    SupplierQuoteDetail,
    SupplierTotalQuote,
)


def _cents_to_yuan(cents: int) -> float:
    return cents / 100.0


def simulate_pricing(
    session: Session,
    req: SimulateRequest,
) -> SimulateResponse:
    product_ids = [item.product_id for item in req.items]
    products = get_products_by_ids(session, product_ids)

    pricelists = get_pricelists_by_product_ids(session, product_ids)

    by_supplier: dict[str, list] = defaultdict(list)
    supplier_ids: set[str] = set()
    for pl in pricelists:
        by_supplier[pl.supplier_id].append(pl)
        supplier_ids.add(pl.supplier_id)

    suppliers = get_suppliers_by_ids(session, list(supplier_ids))
    supplier_names: dict[str, str] = {sid: s.name for sid, s in suppliers.items()}

    all_quotes: list[SupplierTotalQuote] = []
    for supplier_id, spl_list in by_supplier.items():
        tiers_by_product: dict[str, list] = defaultdict(list)
        for spl in spl_list:
            tiers_by_product[spl.product_id].append(spl)

        lines: list[SupplierQuoteDetail] = []
        total_cents = 0
        can_fulfill = True

        for item in req.items:
            tiers = tiers_by_product.get(item.product_id, [])
            hit = next(
                (t for t in tiers if item.quantity >= t.min_qty),
                None,
            )

            if hit:
                unit_cents = hit.unit_price
                subtotal_cents = unit_cents * item.quantity
                total_cents += subtotal_cents
                lines.append(SupplierQuoteDetail(
                    product_id=item.product_id,
                    product_name=products[item.product_id].name,
                    quantity=item.quantity,
                    hit_tier_min_qty=hit.min_qty,
                    unit_price=_cents_to_yuan(unit_cents),
                    subtotal=_cents_to_yuan(subtotal_cents),
                ))
            else:
                can_fulfill = False
                lines.append(SupplierQuoteDetail(
                    product_id=item.product_id,
                    product_name=products[item.product_id].name,
                    quantity=item.quantity,
                    hit_tier_min_qty=0,
                    unit_price=0.0,
                    subtotal=0.0,
                ))

        all_quotes.append(SupplierTotalQuote(
            supplier_id=supplier_id,
            supplier_name=supplier_names.get(supplier_id, "Unknown"),
            total_amount=_cents_to_yuan(total_cents),
            can_fulfill=can_fulfill,
            line_details=lines,
        ))

    fulfillable = [q for q in all_quotes if q.can_fulfill]
    recommended = min(fulfillable, key=lambda x: x.total_amount) if fulfillable else None

    budget = get_budget_by_department_id(session, req.department_id)
    remaining_cents = budget.total_budget - budget.used_budget - budget.frozen_budget

    skipped: list[SkippedSupplierInfo] = []
    if recommended:
        skipped = [
            SkippedSupplierInfo(
                supplier_id=q.supplier_id,
                supplier_name=q.supplier_name,
                reason=(
                    f"总价 {q.total_amount:.2f} 元，"
                    f"高于推荐供应商 {recommended.total_amount:.2f} 元"
                    if q.total_amount > recommended.total_amount
                    else "无法满足全部采购需求"
                ),
            )
            for q in all_quotes
            if q.supplier_id != recommended.supplier_id
        ]

    reason = None
    if recommended:
        reason = f"总价最低，合计 {recommended.total_amount:.2f} 元"
    elif all_quotes:
        reason = "无供应商可满足全部采购需求"

    return SimulateResponse(
        department_remaining_budget=_cents_to_yuan(remaining_cents),
        all_quotes=all_quotes,
        recommended_supplier_id=recommended.supplier_id if recommended else None,
        recommended_supplier_name=recommended.supplier_name if recommended else None,
        recommendation_reason=reason,
        skipped_suppliers=skipped,
    )
