from datetime import date

from sqlmodel import Session, select

from app.core.exceptions import BudgetInsufficientError, ResourceNotFoundError
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


def freeze_budget(
    session: Session,
    department_id: str,
    amount_cents: int,
    force: bool = False,
) -> Budget:
    budget = get_budget_by_department_id(session, department_id)
    if not force:
        remaining = budget.total_budget - budget.used_budget - budget.frozen_budget
        if remaining < amount_cents:
            raise BudgetInsufficientError(required=amount_cents, remaining=remaining)
    budget.frozen_budget += amount_cents
    session.add(budget)
    return budget


def unfreeze_budget(session: Session, department_id: str, amount_cents: int) -> Budget:
    budget = get_budget_by_department_id(session, department_id)
    budget.frozen_budget -= amount_cents
    session.add(budget)
    return budget


def deduct_budget(session: Session, department_id: str, amount_cents: int) -> Budget:
    budget = get_budget_by_department_id(session, department_id)
    budget.frozen_budget -= amount_cents
    budget.used_budget += amount_cents
    session.add(budget)
    return budget


def reverse_budget_deduction(session: Session, department_id: str, amount_cents: int) -> Budget:
    budget = get_budget_by_department_id(session, department_id)
    budget.used_budget -= amount_cents
    session.add(budget)
    return budget
