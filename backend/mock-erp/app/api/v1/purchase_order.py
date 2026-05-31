from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_db_session
from app.schema.purchase_order import POCreateRequest, PORead
from app.service.purchase_order import create_purchase_order

router = APIRouter(prefix="/po", tags=["purchase-order"])


@router.post("", status_code=201)
def po_create(
    req: POCreateRequest,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> PORead:
    return create_purchase_order(session, req)
