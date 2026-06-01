from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import get_db_session
from app.repository.supplier import get_supplier_by_id, get_suppliers
from app.repository.supplier_pricelist import get_pricelists_by_supplier
from app.schema.supplier import PricelistItemRead, SupplierRead

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


@router.get("/{supplier_id}/pricelists")
def list_supplier_pricelists(
    supplier_id: str,
    product_id: str | None = Query(None),
    session: Session = Depends(get_db_session),  # noqa: B008
) -> list[PricelistItemRead]:
    get_supplier_by_id(session, supplier_id)
    pricelists = get_pricelists_by_supplier(
        session, supplier_id, product_id=product_id,
    )
    return [
        PricelistItemRead(
            id=p.id,
            supplier_id=p.supplier_id,
            product_id=p.product_id,
            min_qty=p.min_qty,
            unit_price=p.unit_price / 100.0,
            valid_from=p.valid_from,
            valid_to=p.valid_to,
        )
        for p in pricelists
    ]
