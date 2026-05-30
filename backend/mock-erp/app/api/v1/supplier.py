from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import get_db_session
from app.repository.supplier import get_supplier_by_id, get_suppliers
from app.schema.supplier import SupplierRead

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("")
def list_suppliers(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_db_session),  # noqa: B008
) -> list[SupplierRead]:
    suppliers = get_suppliers(session, skip=skip, limit=limit)
    return [SupplierRead.model_validate(s) for s in suppliers]


@router.get("/{supplier_id}")
def get_supplier(
    supplier_id: str,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> SupplierRead:
    supplier = get_supplier_by_id(session, supplier_id)
    return SupplierRead.model_validate(supplier)
