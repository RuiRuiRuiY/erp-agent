from collections import defaultdict
from datetime import date

from sqlmodel import Session, desc, select

from app.model.supplier_pricelist import SupplierPricelist


def _active_filter(stmt):
    today = date.today().isoformat()
    return stmt.where(
        SupplierPricelist.valid_from <= today,
        (SupplierPricelist.valid_to == None)
        | (SupplierPricelist.valid_to >= today),
    )


def get_pricelists_by_supplier(
    session: Session,
    supplier_id: str,
    product_id: str | None = None,
) -> list[SupplierPricelist]:
    stmt = select(SupplierPricelist).where(
        SupplierPricelist.supplier_id == supplier_id,
    )
    if product_id:
        stmt = stmt.where(SupplierPricelist.product_id == product_id)
    stmt = _active_filter(stmt).order_by(SupplierPricelist.product_id, desc(SupplierPricelist.min_qty))
    return list(session.exec(stmt).all())


def get_pricelists_by_product(
    session: Session,
    product_id: str,
) -> list[SupplierPricelist]:
    stmt = (
        _active_filter(select(SupplierPricelist))
        .where(SupplierPricelist.product_id == product_id)
        .order_by(desc(SupplierPricelist.min_qty))
    )
    return list(session.exec(stmt).all())


def get_pricelists_by_product_ids(
    session: Session,
    product_ids: list[str],
) -> list[SupplierPricelist]:
    stmt = (
        _active_filter(select(SupplierPricelist))
        .where(SupplierPricelist.product_id.in_(product_ids))
        .order_by(
            SupplierPricelist.supplier_id,
            SupplierPricelist.product_id,
            desc(SupplierPricelist.min_qty),
        )
    )
    return list(session.exec(stmt).all())


def get_pricelists_by_supplier_and_products(
    session: Session,
    supplier_id: str,
    product_ids: list[str],
) -> dict[str, list[SupplierPricelist]]:
    stmt = (
        _active_filter(select(SupplierPricelist))
        .where(SupplierPricelist.supplier_id == supplier_id)
        .where(SupplierPricelist.product_id.in_(product_ids))
        .order_by(SupplierPricelist.product_id, desc(SupplierPricelist.min_qty))
    )
    result: dict[str, list[SupplierPricelist]] = defaultdict(list)
    for pl in session.exec(stmt).all():
        result[pl.product_id].append(pl)
    return result
