import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from book_scraper.db.models import Base, ScrapeRun, Shop, ShopBook

TEST_DATABASE_URL = (
    "postgresql+psycopg2://postgres:postgres@localhost:5433/book_scraper_test"
)


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(engine, checkfirst=True)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db_session(engine):
    """Rollback-isolated session using the SAVEPOINT-nested-transaction pattern.

    The test transaction is held on `connection`. The Session joins it via
    a SAVEPOINT (`join_transaction_mode="create_savepoint"`), so any
    `session.commit()` inside the test only releases the savepoint — the
    outer transaction stays open and is rolled back at teardown. Without
    this, `session.commit()` would commit the outer transaction and leak
    rows across tests (causing UniqueViolation on shared keys like
    publisher 'Šviesa' or shop 'vaga' in later tests).

    The after-savepoint listener auto-restarts a fresh SAVEPOINT each time
    the test releases one, so back-to-back commits inside a single test
    keep working.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


# Alias so class-based tests can use `session` instead of `db_session`.
@pytest.fixture()
def session(db_session: Session) -> Session:
    return db_session


@pytest.fixture()
def shop(db_session: Session) -> Shop:
    s = Shop(name="test_shop_vi", base_url="https://test-vi.lt")
    db_session.add(s)
    db_session.flush()
    return s


@pytest.fixture()
def scrape_run(db_session: Session, shop: Shop) -> ScrapeRun:
    from datetime import UTC, datetime

    run = ScrapeRun(
        shop_id=shop.id,
        phase="validate",
        started_at=datetime.now(UTC),
        status="completed",
    )
    db_session.add(run)
    db_session.flush()
    return run


@pytest.fixture()
def shop_book(db_session: Session, shop: Shop) -> ShopBook:
    sb = ShopBook(
        shop_id=shop.id,
        url="https://test-vi.lt/book/test-isbn",
        title="Test Book",
    )
    db_session.add(sb)
    db_session.flush()
    return sb
