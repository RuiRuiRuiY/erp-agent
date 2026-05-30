from typing import Any

from pydantic import BaseModel, ConfigDict, computed_field, field_validator


class BudgetRead(BaseModel):
    """Budget 查询出参，DB 存分（int），API 出元（float）。"""

    model_config = ConfigDict(from_attributes=True)

    department_id: str
    fiscal_year: int
    total_budget: float
    used_budget: float
    frozen_budget: float

    @computed_field
    @property
    def available(self) -> float:
        return self.total_budget - self.used_budget - self.frozen_budget

    @field_validator("total_budget", "used_budget", "frozen_budget", mode="before")
    @classmethod
    def fen_to_yuan(cls, v: Any) -> float:
        if isinstance(v, int):
            return v / 100.0
        return float(v)
