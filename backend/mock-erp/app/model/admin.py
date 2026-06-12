from sqlmodel import Field

from app.model.base import Base


class AdminUser(Base, table=True):
    __tablename__ = "admin_users"
    username: str = Field(unique=True, index=True)
    hashed_password: str
    role: str  # "admin" | "finance_manager"
    is_active: bool = Field(default=True)
