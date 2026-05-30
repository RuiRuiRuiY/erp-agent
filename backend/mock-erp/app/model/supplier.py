import sqlalchemy as sa
from sqlmodel import Field

from .base import Base


class Supplier(Base, table=True):
    __tablename__ = "suppliers"
    __table_args__ = (sa.CheckConstraint("rating >= 0 AND rating <= 5"),)

    code: str = Field(unique=True)
    name: str
    default_lead_time_days: int = Field(default=7)
    rating: float = Field(default=5.0)
    is_active: bool = Field(default=True)
