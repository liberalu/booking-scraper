from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from book_scraper.db.session import get_engine, get_session_factory


def test_get_engine_converts_asyncpg_to_psycopg2():
    engine = get_engine("postgresql+asyncpg://localhost/testdb")
    assert isinstance(engine, Engine)
    assert "psycopg2" in str(engine.url)


def test_get_engine_preserves_psycopg2():
    engine = get_engine("postgresql+psycopg2://localhost/testdb")
    assert isinstance(engine, Engine)
    assert "psycopg2" in str(engine.url)


def test_get_session_factory_returns_sessionmaker():
    factory = get_session_factory("postgresql+psycopg2://localhost/testdb")
    assert isinstance(factory, sessionmaker)
