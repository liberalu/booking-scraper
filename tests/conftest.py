import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from book_scraper.db.models import Base

TEST_DATABASE_URL = (
    "postgresql+psycopg2://postgres:postgres@localhost:5433/book_scraper_test"
)


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(engine)
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
