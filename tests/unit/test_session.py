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


def test_get_engine_is_memoized_per_url():
    """Repeated calls for the same URL must reuse one Engine (one pool).

    Regression for the per-response engine churn in scan._mark_response:
    creating a fresh engine per call leaked ~50 Postgres connections/min and
    blocked the reactor on connect/pre-ping, stranding requests at
    `processing` until the 120s reaper swept them to stuck_in_processing.
    """
    a = get_engine("postgresql+psycopg2://localhost/memodb")
    b = get_engine("postgresql+psycopg2://localhost/memodb")
    assert a is b
    # The asyncpg form normalises to the same psycopg2 URL → same engine.
    c = get_engine("postgresql+asyncpg://localhost/memodb")
    assert c is a


def test_get_engine_distinct_urls_get_distinct_engines():
    main = get_engine("postgresql+psycopg2://localhost/main_db")
    other = get_engine("postgresql+psycopg2://localhost/other_db")
    assert main is not other


def test_get_session_factory_shares_memoized_engine():
    f1 = get_session_factory("postgresql+psycopg2://localhost/sharedb")
    f2 = get_session_factory("postgresql+psycopg2://localhost/sharedb")
    assert f1.kw["bind"] is f2.kw["bind"]
