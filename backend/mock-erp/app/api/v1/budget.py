from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from app.api.deps import get_db_session
from app.repository.budget import get_budget_by_department_id
from app.schema.budget import BudgetRead

router = APIRouter(prefix="/budgets", tags=["budgets"])


@router.get("/{department_id}")
def get_budget(
    department_id: str,
    fiscal_year: int | None = Query(None, description="财年，默认当前年"),
    session: Session = Depends(get_db_session),  # noqa: B008
) -> BudgetRead:
    budget = get_budget_by_department_id(
        session, department_id, fiscal_year=fiscal_year,
    )
    return BudgetRead.model_validate(budget)
