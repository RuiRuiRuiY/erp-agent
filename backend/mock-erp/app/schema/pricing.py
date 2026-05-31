from pydantic import BaseModel, Field


class SimulateRequestItem(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)


class SimulateRequest(BaseModel):
    department_id: str
    items: list[SimulateRequestItem] = Field(min_length=1)


class SupplierQuoteDetail(BaseModel):
    """某个供应商针对某商品的报价明细（展示阶梯命中情况）。"""

    product_id: str
    product_name: str
    quantity: int
    hit_tier_min_qty: int
    unit_price: float
    subtotal: float


class SupplierTotalQuote(BaseModel):
    """单个供应商的整体报价汇总。"""

    supplier_id: str
    supplier_name: str
    total_amount: float
    can_fulfill: bool
    line_details: list[SupplierQuoteDetail]


class SkippedSupplierInfo(BaseModel):
    """被跳过的供应商及其原因（Agent 决策参考）。"""

    supplier_id: str
    supplier_name: str
    reason: str


class SimulateResponse(BaseModel):
    """试算引擎最终返回给 Agent 的结果。"""

    department_remaining_budget: float
    all_quotes: list[SupplierTotalQuote]
    recommended_supplier_id: str | None = None
    recommended_supplier_name: str | None = None
    recommendation_reason: str | None = None
    skipped_suppliers: list[SkippedSupplierInfo] = []
