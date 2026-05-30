from collections.abc import Generator

from app.core.database import Session, get_db


def get_db_session() -> Generator[Session]:
    yield from get_db()
