from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, Relationship

from .base import Base


class PurchaseOrder(Base, table=True):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PENDING', 'APPROVED', 'REJECTED', "
            "'ORDERED', 'SHIPPED', 'RECEIVED', 'CANCELLED')",
        ),
    )

    po_number: str = Field(unique=True)
    supplier_id: str = Field(foreign_key="suppliers.id")
    department_id: str = Field(foreign_key="departments.id")
    status: str = Field(default="DRAFT")
    total_amount: int = Field(default=0)
    created_by_agent: bool = Field(default=False)
    agent_reasoning: str | None = Field(default=None)
    is_override: bool = Field(default=False)
    created_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
    )

    lines: list["PurchaseOrderLine"] = Relationship(
        back_populates="purchase_order",
    )


class PurchaseOrderLine(Base, table=True):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        sa.CheckConstraint("quantity > 0"),
        sa.CheckConstraint("unit_price >= 0"),
        sa.Index("idx_po_lines_po_id", "po_id"),
    )

    po_id: str = Field(foreign_key="purchase_orders.id")
    product_id: str = Field(foreign_key="products.id")
    quantity: int
    unit_price: int

    purchase_order: PurchaseOrder | None = Relationship(
        back_populates="lines",
    )
