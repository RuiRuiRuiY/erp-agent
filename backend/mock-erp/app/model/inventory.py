import sqlalchemy as sa
from sqlmodel import Field

from .base import Base


class Inventory(Base, table=True):
    __tablename__ = "inventory"
    __table_args__ = (
        sa.CheckConstraint("total_qty >= 0"),
        sa.CheckConstraint("locked_qty >= 0"),
        sa.CheckConstraint("total_qty >= locked_qty"),
    )

    product_id: str = Field(foreign_key="products.id", unique=True)
    total_qty: int
    locked_qty: int = Field(default=0)
