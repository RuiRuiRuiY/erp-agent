import sqlalchemy as sa
from sqlmodel import Field

from .base import Base


class Budget(Base, table=True):
    __tablename__ = "budgets"
    __table_args__ = (
        sa.CheckConstraint("total_budget >= 0"),
        sa.CheckConstraint("used_budget >= 0"),
        sa.UniqueConstraint(
            "department_id",
            "fiscal_year",
            name="idx_dept_fiscal_year",
        ),
    )

    department_id: str = Field(foreign_key="departments.id")
    fiscal_year: int
    total_budget: int
    used_budget: int = Field(default=0)
