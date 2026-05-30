from sqlmodel import Session, desc, select

from app.model.supplier_pricelist import SupplierPricelist


def get_pricelists_by_supplier(
    session: Session,
    supplier_id: str,
) -> list[SupplierPricelist]:
    stmt = (
        select(SupplierPricelist)
        .where(SupplierPricelist.supplier_id == supplier_id)
        .order_by(SupplierPricelist.product_id, SupplierPricelist.min_qty)
    )
    return list(session.exec(stmt).all())


def get_pricelists_by_product(
    session: Session,
    product_id: str,
) -> list[SupplierPricelist]:
    stmt = (
        select(SupplierPricelist)
        .where(SupplierPricelist.product_id == product_id)
        .order_by(desc(SupplierPricelist.min_qty))
    )
    return list(session.exec(stmt).all())
