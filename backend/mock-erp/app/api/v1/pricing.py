from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_db_session
from app.schema.pricing import SimulateRequest, SimulateResponse
from app.service.pricing import simulate_pricing

router = APIRouter(prefix="/pricing", tags=["pricing"])


@router.post("/simulate")
def pricing_simulate(
    req: SimulateRequest,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> SimulateResponse:
    return simulate_pricing(session, req)
