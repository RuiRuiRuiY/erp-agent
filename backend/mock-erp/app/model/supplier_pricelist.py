from datetime import date

import sqlalchemy as sa
from sqlmodel import Field

from .base import Base


class SupplierPricelist(Base, table=True):
    __tablename__ = "supplier_pricelists"
    __table_args__ = (
        sa.CheckConstraint("min_qty >= 1"),
        sa.CheckConstraint("unit_price >= 0"),
        sa.UniqueConstraint(
            "supplier_id",
            "product_id",
            "min_qty",
            name="idx_supplier_product_qty",
        ),
    )

    supplier_id: str = Field(foreign_key="suppliers.id")
    product_id: str = Field(foreign_key="products.id")
    min_qty: int
    unit_price: int
    valid_from: str = Field(default_factory=lambda: date.today().isoformat())
    valid_to: str | None = Field(default=None)
