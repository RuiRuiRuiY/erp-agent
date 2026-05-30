from datetime import date

from sqlmodel import Session, select

from app.core.exceptions import ResourceNotFoundError
from app.model.budget import Budget


def get_budget_by_department_id(
    session: Session,
    department_id: str,
    fiscal_year: int | None = None,
) -> Budget:
    year = fiscal_year or date.today().year
    stmt = (
        select(Budget)
        .where(Budget.department_id == department_id)
        .where(Budget.fiscal_year == year)
    )
    budget = session.exec(stmt).first()
    if not budget:
        raise ResourceNotFoundError(
            resource="Budget",
            resource_id=f"dept={department_id}, year={year}",
        )
    return budget
