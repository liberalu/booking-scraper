from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def get_engine(database_url: str) -> Engine:
    # Use sync engine for Scrapy pipelines (Scrapy runs in Twisted reactor)
    sync_url = database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    return create_engine(sync_url)


def get_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = get_engine(database_url)
    return sessionmaker(bind=engine)
