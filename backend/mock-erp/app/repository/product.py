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
