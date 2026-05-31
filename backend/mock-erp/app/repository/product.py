from sqlmodel import Session, select

from app.core.exceptions import ResourceNotFoundError
from app.model.product import Product


def get_products(
    session: Session,
    skip: int = 0,
    limit: int = 100,
) -> list[Product]:
    return list(session.exec(select(Product).offset(skip).limit(limit)).all())


def get_product_by_id(session: Session, product_id: str) -> Product:
    product = session.get(Product, product_id)
    if not product:
        raise ResourceNotFoundError(resource="Product", resource_id=product_id)
    return product


def get_products_by_ids(
    session: Session,
    product_ids: list[str],
) -> dict[str, Product]:
    stmt = select(Product).where(Product.id.in_(product_ids))
    result = {p.id: p for p in session.exec(stmt).all()}
    for pid in product_ids:
        if pid not in result:
            raise ResourceNotFoundError(resource="Product", resource_id=pid)
    return result
