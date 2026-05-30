from datetime import datetime

from sqlmodel import Field

from .base import Base


class Product(Base, table=True):
    __tablename__ = "products"

    sku: str = Field(unique=True)
    name: str
    category: str
    unit_of_measure: str = Field(default="PCS")
    is_active: bool = Field(default=True)
    created_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
    )
