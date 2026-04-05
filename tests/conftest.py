import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from book_scraper.db.models import Base

TEST_DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5433/book_scraper_test"


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    yield session
    session.close()
    transaction.rollback()
    connection.close()
