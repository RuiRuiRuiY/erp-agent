from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_db_session
from app.schema.purchase_order import (
    POCreateOverrideRequest,
    POCreateRequest,
    PORead,
    TransitStatusRequest,
    TransitStatusResponse,
)
from app.service.purchase_order import (
    create_purchase_order,
    create_purchase_order_override,
    transit_po,
)

router = APIRouter(prefix="/po", tags=["purchase-order"])


@router.post("", status_code=201)
def po_create(
    req: POCreateRequest,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> PORead:
    result = create_purchase_order(session, req)
    session.commit()
    return result


@router.post("/override", status_code=201)
def po_override_create(
    req: POCreateOverrideRequest,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> PORead:
    result = create_purchase_order_override(session, req)
    session.commit()
    return result


@router.post("/{po_id}/transit")
def po_transit(
    po_id: str,
    req: TransitStatusRequest,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> TransitStatusResponse:
    result = transit_po(session, po_id, req.target_status, req.operator_role)
    session.commit()
    return result
