from uuid import uuid4

from sqlmodel import Field, SQLModel


class Base(SQLModel):
    id: str = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
    )
