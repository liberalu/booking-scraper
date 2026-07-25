"""Shared run-lifecycle scaffolding for the SQL-only phase spiders.

`validate` and `match` don't crawl anything — each wraps one synchronous
service so `scrapy crawl <phase> -a shop=…` keeps working with the existing
dashboard / cron launcher. Everything around that service call (create the
`scrape_runs` row, publish `_run_id` for the heartbeat, dispatch off the
reactor thread, finish the run, failsafe on close) used to be copy-pasted
between the two spiders — `spiders/validate.py` literally said "Mirrors
book_scraper/spiders/match.py exactly", and the copies had already drifted:
match was missing validate's `closed()` failsafe, so a crash mid-SQL left
its run row stuck in 'running' until the dashboard reaper caught it.

Subclass contract:

  - set ``name`` (scrapy) and ``phase`` (the `scrape_runs.phase` value)
  - implement ``run_service(session, shop_id, run_id)`` — runs in a worker
    thread with its own session; the base commits it
  - optionally override ``finalize_result(session, run_id, result)`` to
    record phase-specific run fields or log a summary
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import scrapy

from book_scraper.config import load_shop_config
from book_scraper.db.repo import (
    create_scrape_run,
    finalize_run_failsafe,
    finish_scrape_run,
    upsert_shop,
)
from book_scraper.db.session import get_session_factory


class ServiceSpider(scrapy.Spider):
    """Runs a single synchronous service under the normal run lifecycle."""

    #: `scrape_runs.phase` written for this spider's runs.
    phase: str = ""

    custom_settings = {
        "ITEM_PIPELINES": {},  # no items, no DB pipelines
        # These phases make zero HTTP requests. StallDetector keys on
        # response_received and would close the spider after STALL_TIMEOUT
        # (180s) regardless of how healthy the SQL job is — disable it.
        # HeartbeatExtension stays ON: without it `last_heartbeat` is never
        # updated and the dashboard reaper marks the run heartbeat_timeout
        # after 60s. The synchronous service is dispatched via
        # asyncio.to_thread() in start(), so the asyncio/reactor loop stays
        # free for the heartbeat ticks.
        "EXTENSIONS": {
            "book_scraper.extensions.StallDetector": None,
            "book_scraper.extensions.CronChainTrigger": 520,
        },
    }

    def __init__(self, shop: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not shop:
            raise ValueError("Missing required argument: shop (e.g., -a shop=vaga)")
        self.shop_name = shop
        self.conf = load_shop_config(shop)

    # -- subclass hooks ----------------------------------------------------

    def run_service(self, session: Any, shop_id: int, run_id: int) -> Any:
        """Run the phase's service. Called in a worker thread."""
        raise NotImplementedError

    def finalize_result(self, session: Any, run_id: int, result: Any) -> None:
        """Hook: record phase-specific fields / log a summary before finish."""

    # -- lifecycle ---------------------------------------------------------

    def _database_url(self) -> str | None:
        return self.settings.get("DATABASE_URL") if hasattr(self, "settings") else None

    async def start(self) -> AsyncGenerator[scrapy.Request, None]:
        database_url = self._database_url()
        if not database_url:
            return  # tests / dry-run path
            yield  # unreachable

        session = get_session_factory(database_url)()
        try:
            shop = upsert_shop(session, self.shop_name, self.conf.shop.base_url)
            run = create_scrape_run(
                session,
                shop.id,
                self.phase,
                extra_payload={"shop": self.shop_name},
            )
            session.commit()
            run_id = run.id
            shop_id = shop.id
        finally:
            session.close()

        # Publish run_id so HeartbeatExtension picks it up on its next tick.
        # MUST be set before dispatching the service (heartbeat-ordering
        # invariant covered in tests/unit/test_validate_spider.py, and the
        # MatchSpider regression that caused heartbeat_timeout on runs
        # #387/#391).
        self._run_id = run_id

        def _run() -> Any:
            s = get_session_factory(database_url)()
            try:
                result = self.run_service(s, shop_id, run_id)
                s.commit()
                return result
            except Exception:
                s.rollback()
                raise
            finally:
                s.close()

        # Run synchronous SQL in a worker thread so the asyncio/Twisted
        # reactor stays free for HeartbeatExtension's callLater ticks.
        # Otherwise long multi-table scans block the reactor past
        # DEAD_RUN_SECONDS (60s) and the dashboard reaper marks the run
        # heartbeat_timeout mid-SQL.
        result = await asyncio.to_thread(_run)

        session = get_session_factory(database_url)()
        try:
            self.finalize_result(session, run_id, result)
            finish_scrape_run(session, run_id, status="completed")
            session.commit()
        finally:
            session.close()

        return
        yield  # unreachable, satisfies AsyncGenerator typing

    def closed(self, reason: str = "") -> None:
        """Finalize scrape_run on spider close.

        Uses finalize_run_failsafe (fresh-session path) so a poisoned session
        or crash mid-SQL never leaves the run row zombie. finalize_run_failsafe
        is idempotent — it only updates rows still in 'running' status, so
        calling it after a successful finish_scrape_run is a no-op.
        """
        run_id = getattr(self, "_run_id", None)
        if run_id is None:
            return
        database_url = self._database_url()
        if not database_url:
            return
        try:
            finalize_run_failsafe(
                database_url,
                run_id,
                "failed",
                reason=reason or "spider_closed",
            )
        except Exception:
            self.logger.exception(
                "%s.closed: finalize_run_failsafe failed for run %d",
                type(self).__name__,
                run_id,
            )
