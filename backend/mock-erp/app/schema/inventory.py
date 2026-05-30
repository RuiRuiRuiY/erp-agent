from pydantic import BaseModel, ConfigDict, computed_field


class InventoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    total_qty: int
    locked_qty: int

    @computed_field
    @property
    def available_qty(self) -> int:
        return self.total_qty - self.locked_qty
