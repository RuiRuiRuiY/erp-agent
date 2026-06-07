from pydantic import BaseModel, Field


class POCreateItem(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)


class POCreateRequest(BaseModel):
    department_id: str
    supplier_id: str
    items: list[POCreateItem] = Field(min_length=1)
    agent_reasoning: str | None = None


class POCreateOverrideRequest(POCreateRequest):
    override_token: str


class POLineRead(BaseModel):
    id: str
    product_id: str
    product_name: str
    quantity: int
    unit_price: float
    line_total: float


class PORead(BaseModel):
    id: str
    po_number: str
    supplier_id: str
    supplier_name: str
    department_id: str
    department_name: str
    status: str
    total_amount: float
    created_by_agent: bool
    agent_reasoning: str | None
    created_at: str
    lines: list[POLineRead]


class TransitStatusRequest(BaseModel):
    target_status: str = Field(description="目标状态")
    operator_role: str = Field(default="purchaser", description="操作者角色")


class TransitStatusResponse(BaseModel):
    po_id: str
    po_number: str
    old_status: str
    new_status: str
    budget_impact: str | None = None
