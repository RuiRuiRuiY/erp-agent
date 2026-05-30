from pydantic import BaseModel


class BudgetRead(BaseModel):
    """Budget 查询出参，金额单位：元（从 DB 分自动转换）。"""

    department_id: str
    fiscal_year: int
    total_budget: float
    used_budget: float
    frozen_budget: float
    available: float

    @classmethod
    def from_orm(cls, budget: "Budget") -> "BudgetRead":  # noqa: F821
        return cls(
            department_id=budget.department_id,
            fiscal_year=budget.fiscal_year,
            total_budget=budget.total_budget / 100.0,
            used_budget=budget.used_budget / 100.0,
            frozen_budget=budget.frozen_budget / 100.0,
            available=(
                budget.total_budget - budget.used_budget - budget.frozen_budget
            ) / 100.0,
        )
