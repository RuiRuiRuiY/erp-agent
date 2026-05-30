from sqlmodel import Session, select

from app.core.exceptions import ResourceNotFoundError
from app.model.department import Department


def get_departments(
    session: Session,
    skip: int = 0,
    limit: int = 100,
) -> list[Department]:
    return list(session.exec(select(Department).offset(skip).limit(limit)).all())


def get_department_by_id(session: Session, department_id: str) -> Department:
    dept = session.get(Department, department_id)
    if not dept:
        raise ResourceNotFoundError(resource="Department", resource_id=department_id)
    return dept
