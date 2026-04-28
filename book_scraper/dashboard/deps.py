import os
from collections.abc import Generator
from typing import Any

from sqlalchemy.orm import Session

from book_scraper.db.session import get_session_factory

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/book_scraper",
)

_session_factory = get_session_factory(DATABASE_URL)


def get_db() -> Generator[Session, None, None]:
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


def get_docker_client() -> Any:
    try:
        import docker  # type: ignore[import-untyped]

        return docker.from_env()
    except Exception:
        return None
