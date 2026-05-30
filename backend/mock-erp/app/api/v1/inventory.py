from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_db_session
from app.repository.inventory import get_inventory_by_product_id
from app.schema.inventory import InventoryRead

router = APIRouter(prefix="/inventory", tags=["inventory"])


@router.get("/{product_id}")
def get_inventory(
    product_id: str,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> InventoryRead:
    inv = get_inventory_by_product_id(session, product_id)
    return InventoryRead.model_validate(inv)
