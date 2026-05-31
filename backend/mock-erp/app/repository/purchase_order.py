from sqlmodel import Session, select

from app.core.exceptions import ResourceNotFoundError
from app.model.purchase_order import PurchaseOrder


def get_po_by_id(session: Session, po_id: str) -> PurchaseOrder:
    stmt = select(PurchaseOrder).where(PurchaseOrder.id == po_id)
    po = session.exec(stmt).first()
    if not po:
        raise ResourceNotFoundError(resource="PurchaseOrder", resource_id=po_id)
    return po
