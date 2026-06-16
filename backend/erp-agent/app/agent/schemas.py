"""Agent 结构化输出的 Pydantic 模型。"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Intent(str, Enum):
    CONFIRM = "confirm"
    NEW_REQUEST = "new_request"
    MODIFY = "modify"


class ParseResult(BaseModel):
    """parse_input 的结构化输出。"""
    intent: Intent = Intent.NEW_REQUEST
    department_id: str | None = None
    cart_items: list[dict] = Field(default_factory=list)
    selected_supplier_id: str | None = None
    changes: dict | None = None


class AnalysisResult(BaseModel):
    """analyze_simulate 的结构化输出。"""
    has_tier_opportunity: bool = False
    has_stock_risk: bool = False
