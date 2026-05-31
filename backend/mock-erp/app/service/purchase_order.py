from datetime import datetime
from uuid import uuid4

from sqlmodel import Session

from app.core.exceptions import PricingTierNotFoundError
from app.model.product import Product
from app.model.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.repository.budget import freeze_budget
from app.repository.department import get_department_by_id
from app.repository.inventory import lock_stock
from app.repository.product import get_products_by_ids
from app.repository.supplier import get_supplier_by_id
from app.repository.supplier_pricelist import get_pricelists_by_supplier_and_products
from app.schema.purchase_order import POCreateRequest, POLineRead, PORead


def _cents_to_yuan(cents: int) -> float:
    return cents / 100.0


def _generate_po_number() -> str:
    return f"PO-{datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:8].upper()}"


def _find_tier(
    tiers: list,
    quantity: int,
) -> object | None:
    return next((t for t in tiers if quantity >= t.min_qty), None)


def _po_to_read(
    po: PurchaseOrder,
    supplier_name: str,
    department_name: str,
    products: dict[str, Product],
) -> PORead:
    return PORead(
        id=po.id,
        po_number=po.po_number,
        supplier_id=po.supplier_id,
        supplier_name=supplier_name,
        department_id=po.department_id,
        department_name=department_name,
        status=po.status,
        total_amount=_cents_to_yuan(po.total_amount),
        created_by_agent=po.created_by_agent,
        agent_reasoning=po.agent_reasoning,
        created_at=po.created_at,
        lines=[
            POLineRead(
                id=line.id,
                product_id=line.product_id,
                product_name=products[line.product_id].name,
                quantity=line.quantity,
                unit_price=_cents_to_yuan(line.unit_price),
                line_total=_cents_to_yuan(line.unit_price * line.quantity),
            )
            for line in po.lines
        ],
    )


def create_purchase_order(session: Session, req: POCreateRequest) -> PORead:
    supplier = get_supplier_by_id(session, req.supplier_id)
    department = get_department_by_id(session, req.department_id)

    product_ids = [item.product_id for item in req.items]
    products = get_products_by_ids(session, product_ids)

    pricelists_by_product = get_pricelists_by_supplier_and_products(
        session, req.supplier_id, product_ids,
    )

    lines_data: list[PurchaseOrderLine] = []
    total_cents = 0

    for item in req.items:
        tiers = pricelists_by_product.get(item.product_id, [])
        hit = _find_tier(tiers, item.quantity)
        if not hit:
            raise PricingTierNotFoundError(
                product_id=item.product_id,
                quantity=item.quantity,
            )

        unit_cents = hit.unit_price
        subtotal_cents = unit_cents * item.quantity
        total_cents += subtotal_cents

        lines_data.append(PurchaseOrderLine(
            product_id=item.product_id,
            quantity=item.quantity,
            unit_price=unit_cents,
        ))

    freeze_budget(session, req.department_id, total_cents)

    for item in req.items:
        lock_stock(session, item.product_id, item.quantity)

    po = PurchaseOrder(
        po_number=_generate_po_number(),
        supplier_id=req.supplier_id,
        department_id=req.department_id,
        status="DRAFT",
        total_amount=total_cents,
        created_by_agent=bool(req.agent_reasoning),
        agent_reasoning=req.agent_reasoning,
        lines=lines_data,
    )
    session.add(po)
    session.flush()
    session.refresh(po)

    return _po_to_read(po, supplier.name, department.name, products)
