from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def get_engine(database_url: str) -> Engine:
    # Use sync engine for Scrapy pipelines (Scrapy runs in Twisted reactor)
    sync_url = database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    return create_engine(
        sync_url,
        # Validate pooled connections before checkout — eliminates "server closed
        # the connection unexpectedly" after idle TCP drops by NAT/firewall/Postgres.
        pool_pre_ping=True,
        # Proactively recycle connections every 5 minutes so they don't go stale.
        pool_recycle=300,
        # Kill sessions stuck in an open transaction after 5 minutes (e.g. spider crash)
        connect_args={"options": "-c idle_in_transaction_session_timeout=300000"},
    )


def get_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = get_engine(database_url)
    return sessionmaker(bind=engine)
