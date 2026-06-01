from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import get_db_session
from app.repository.product import get_product_by_id, get_products
from app.schema.product import ProductRead

router = APIRouter(prefix="/products", tags=["products"])


@router.get("")
def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    q: str | None = Query(None),
    session: Session = Depends(get_db_session),  # noqa: B008
) -> list[ProductRead]:
    products = get_products(session, skip=skip, limit=limit, q=q)
    return [ProductRead.model_validate(p) for p in products]


@router.get("/{product_id}")
def get_product(
    product_id: str,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> ProductRead:
    product = get_product_by_id(session, product_id)
    return ProductRead.model_validate(product)
