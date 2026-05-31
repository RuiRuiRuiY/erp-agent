from sqlmodel import Session, select

from app.core.exceptions import ResourceNotFoundError
from app.model.supplier import Supplier


def get_suppliers(
    session: Session,
    skip: int = 0,
    limit: int = 100,
) -> list[Supplier]:
    return list(session.exec(select(Supplier).offset(skip).limit(limit)).all())


def get_supplier_by_id(session: Session, supplier_id: str) -> Supplier:
    supplier = session.get(Supplier, supplier_id)
    if not supplier:
        raise ResourceNotFoundError(resource="Supplier", resource_id=supplier_id)
    return supplier


def get_suppliers_by_ids(
    session: Session,
    supplier_ids: list[str],
) -> dict[str, Supplier]:
    stmt = select(Supplier).where(Supplier.id.in_(supplier_ids))
    return {s.id: s for s in session.exec(stmt).all()}
