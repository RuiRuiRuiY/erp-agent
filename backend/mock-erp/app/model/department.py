from sqlmodel import Field

from .base import Base


class Department(Base, table=True):
    __tablename__ = "departments"

    code: str = Field(unique=True)
    name: str
