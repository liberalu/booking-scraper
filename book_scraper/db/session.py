import logging

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

_pool_logger = logging.getLogger("book_scraper.db.pool")

# One Engine (one connection pool) per normalised URL, per process.
#
# get_engine used to build a brand-new Engine on every call. Hot paths that
# call it per-item — scan._mark_response, the discover/scan progress writers —
# therefore created a fresh QueuePool (5 + 10 overflow) for every response,
# never disposed. Two failure modes resulted:
#   1. Connection churn: ~50 new Postgres connections/min, ~70 held idle,
#      intermittently exhausting max_connections=100 ("too many clients").
#   2. Reactor stalls: each new engine's synchronous connect() + pool_pre_ping
#      round-trip ran inside the Twisted/asyncio reactor thread. Under
#      connection pressure these blocked the event loop in bursts, stranding
#      in-flight requests past the 120s reaper window so they were swept to
#      stuck_in_processing (http_status NULL) instead of completing.
# Memoising by normalised URL bounds the whole process to one pool.
_engines: dict[str, Engine] = {}


def get_engine(database_url: str) -> Engine:
    # Use sync engine for Scrapy pipelines (Scrapy runs in Twisted reactor)
    sync_url = database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    cached = _engines.get(sync_url)
    if cached is not None:
        return cached
    engine = create_engine(
        sync_url,
        # Validate pooled connections before checkout — eliminates "server closed
        # the connection unexpectedly" after idle TCP drops by NAT/firewall/Postgres.
        pool_pre_ping=True,
        # Proactively recycle connections every 5 minutes so they don't go stale.
        pool_recycle=300,
        connect_args={
            # Server-side guards:
            #   idle_in_transaction_session_timeout: kill sessions stuck in an
            #     open transaction after 5 min (e.g. spider crash mid-tx).
            #   statement_timeout: cap any single query at 10s by default. The
            #     reactor thread runs sync psycopg2 — a hung query freezes
            #     scrapy's event loop, blocking heartbeat ticks AND request
            #     dispatching. 10s is the worst-case reactor stall budget;
            #     code paths needing more (large upserts) can SET LOCAL
            #     statement_timeout higher inside their own transaction.
            "options": (
                "-c idle_in_transaction_session_timeout=300000 "
                "-c statement_timeout=10000"
            ),
            # Client-side connect timeout: bounds a new pool connection's TCP
            # handshake. Without this, psycopg2.connect() blocks indefinitely
            # if Postgres is unreachable, which freezes whichever sync call
            # tried to acquire it (typically a heartbeat tick or _mark_response).
            "connect_timeout": 5,
            # TCP keepalives: detect dropped connections in ~60s instead of
            # the kernel default (~2 hours on Linux). Without these, a
            # silently-dropped TCP connection (NAT idle, postgres restart,
            # network blip) causes the next recv() on it to hang for hours,
            # and pool_pre_ping doesn't help — it only checks at checkout,
            # not while a connection is in use.
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 3,
        },
    )

    @event.listens_for(engine, "checkout")
    def _pool_checkout(dbapi_conn, conn_record, conn_proxy) -> None:  # type: ignore[misc]
        pool = engine.pool
        overflow = getattr(pool, "overflow", lambda: 0)
        overflow_val = overflow() if callable(overflow) else overflow
        if overflow_val > 0:
            size = getattr(pool, "size", lambda: 0)
            size_val = size() if callable(size) else size
            checked_out = getattr(pool, "checkedout", lambda: 0)
            checked_out_val = checked_out() if callable(checked_out) else checked_out
            _pool_logger.warning(
                "Pool overflow on checkout: size=%d checkedout=%d overflow=%d",
                size_val,
                checked_out_val,
                overflow_val,
            )

    @event.listens_for(engine, "invalidate")
    def _pool_invalidate(dbapi_conn, conn_record, exception) -> None:  # type: ignore[misc]
        _pool_logger.warning("Pool connection invalidated: exception=%r", exception)

    _engines[sync_url] = engine
    return engine


def get_session_factory(database_url: str) -> sessionmaker[Session]:
    engine = get_engine(database_url)
    return sessionmaker(bind=engine)
