from datetime import datetime
from uuid import uuid4

from sqlmodel import Session

from app.core.exceptions import (
    BudgetInsufficientError,
    BusinessException,
    InvalidStateTransitionError,
    PermissionDeniedError,
    PricingTierNotFoundError,
)
from app.model.product import Product
from app.model.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.repository.budget import (
    deduct_budget,
    freeze_budget,
    get_budget_by_department_id,
    reverse_budget_deduction,
    unfreeze_budget,
)
from app.repository.department import get_department_by_id
from app.repository.inventory import (
    consume_stock,
    get_inventory_by_product_id,
    lock_stock,
    reverse_consume_stock,
    unlock_stock,
)
from app.repository.product import get_products_by_ids
from app.repository.purchase_order import get_po_by_id
from app.repository.supplier import get_supplier_by_id
from app.repository.supplier_pricelist import get_pricelists_by_supplier_and_products
from app.schema.purchase_order import (
    POCreateRequest,
    POLineRead,
    PORead,
    TransitStatusResponse,
)


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


STATE_MACHINE: dict[str, dict[str, dict]] = {
    'DRAFT': {
        'PENDING':   {'guard': 'recheck_budget_and_stock', 'action': None},
        'CANCELLED': {'action': 'unfreeze_budget_and_unlock_stock'},
    },
    'PENDING': {
        'APPROVED':  {'guard': 'is_finance_manager', 'action': 'deduct_budget_and_consume_stock'},
        'REJECTED':  {'guard': 'is_finance_manager', 'action': 'unfreeze_budget_and_unlock_stock'},
        'CANCELLED': {'action': 'unfreeze_budget_and_unlock_stock'},
    },
    'REJECTED': {
        'DRAFT':     {'action': None},
    },
    'APPROVED': {
        'ORDERED':   {'action': None},
        'CANCELLED': {'action': 'reverse_approval'},
    },
    'ORDERED': {
        'SHIPPED':   {'action': None},
        'CANCELLED': {'action': None},
    },
    'SHIPPED': {
        'RECEIVED':  {'action': None},
    },
}


def _execute_guard(session: Session, guard: str, po: PurchaseOrder, operator_role: str) -> None:
    if guard == 'recheck_budget_and_stock':
        budget = get_budget_by_department_id(session, po.department_id)
        remaining = budget.total_budget - budget.used_budget - budget.frozen_budget
        if remaining < po.total_amount:
            raise BudgetInsufficientError(required=po.total_amount, remaining=remaining)
        for line in po.lines:
            inv = get_inventory_by_product_id(session, line.product_id)
            available = inv.total_qty - inv.locked_qty
            if available < line.quantity:
                raise BusinessException(
                    error_code="INSUFFICIENT_STOCK",
                    message=f"商品 {line.product_id} 库存不足",
                    context={
                        "product_id": line.product_id,
                        "requested": line.quantity,
                        "available": available,
                    },
                    suggestion="建议减少数量、等待补货或寻找替代品",
                )
    elif guard == 'is_finance_manager':
        if operator_role != 'finance_manager':
            raise PermissionDeniedError(required_role="finance_manager")


def _execute_action(session: Session, action: str, po: PurchaseOrder) -> str | None:
    if action == 'unfreeze_budget_and_unlock_stock':
        unfreeze_budget(session, po.department_id, po.total_amount)
        for line in po.lines:
            unlock_stock(session, line.product_id, line.quantity)
        return f"已释放冻结预算 ¥{_cents_to_yuan(po.total_amount):.2f}"

    if action == 'deduct_budget_and_consume_stock':
        deduct_budget(session, po.department_id, po.total_amount)
        for line in po.lines:
            consume_stock(session, line.product_id, line.quantity)
        return f"已扣减预算 ¥{_cents_to_yuan(po.total_amount):.2f}"

    if action == 'reverse_approval':
        reverse_budget_deduction(session, po.department_id, po.total_amount)
        for line in po.lines:
            reverse_consume_stock(session, line.product_id, line.quantity)
        return f"已退回预算 ¥{_cents_to_yuan(po.total_amount):.2f}"

    return None


def transit_po(
    session: Session,
    po_id: str,
    target_status: str,
    operator_role: str,
) -> TransitStatusResponse:
    po = get_po_by_id(session, po_id)
    old_status = po.status

    current_transitions = STATE_MACHINE.get(old_status)
    if not current_transitions or target_status not in current_transitions:
        raise InvalidStateTransitionError(current=old_status, target=target_status)

    rule = current_transitions[target_status]

    if 'guard' in rule and rule['guard']:
        _execute_guard(session, rule['guard'], po, operator_role)

    budget_impact = None
    if 'action' in rule and rule['action']:
        budget_impact = _execute_action(session, rule['action'], po)

    po.status = target_status
    po.updated_at = datetime.now().isoformat()
    session.add(po)

    return TransitStatusResponse(
        po_id=po.id,
        po_number=po.po_number,
        old_status=old_status,
        new_status=target_status,
        budget_impact=budget_impact,
    )
