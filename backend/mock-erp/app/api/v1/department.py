from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import get_db_session
from app.repository.department import get_department_by_id, get_departments
from app.schema.department import DepartmentRead

router = APIRouter(prefix="/departments", tags=["departments"])


@router.get("")
def list_departments(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_db_session),  # noqa: B008
) -> list[DepartmentRead]:
    departments = get_departments(session, skip=skip, limit=limit)
    return [DepartmentRead.model_validate(d) for d in departments]


@router.get("/{department_id}")
def get_department(
    department_id: str,
    session: Session = Depends(get_db_session),  # noqa: B008
) -> DepartmentRead:
    department = get_department_by_id(session, department_id)
    return DepartmentRead.model_validate(department)
