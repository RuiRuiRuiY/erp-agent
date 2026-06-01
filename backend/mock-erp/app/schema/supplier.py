from pydantic import BaseModel, ConfigDict


class SupplierRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code: str
    name: str
    default_lead_time_days: int
    rating: float
    is_active: bool


class PricelistItemRead(BaseModel):
    id: str
    supplier_id: str
    product_id: str
    min_qty: int
    unit_price: float
    valid_from: str
    valid_to: str | None = None
