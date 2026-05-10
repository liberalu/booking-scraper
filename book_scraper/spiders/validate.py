"""Validate phase spider.

Thin wrapper around ValidateService so `scrapy crawl validate -a shop=…`
works with the existing dashboard / cron launcher. No HTTP — runs the
service in a worker thread so the reactor stays free for
HeartbeatExtension to tick, otherwise the dashboard reaper kills the run
after DEAD_RUN_SECONDS (60s) for a stale heartbeat.

Mirrors book_scraper/spiders/match.py exactly, adding a closed()
failsafe that calls finalize_run_failsafe (scan.py pattern) so a crash
mid-SQL doesn't leave the scrape_runs row zombie.
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
from book_scraper.services.validate import ValidateService


class ValidateSpider(scrapy.Spider):
    name = "validate"
    custom_settings = {
        "ITEM_PIPELINES": {},  # no items, no DB pipelines
        # Validate makes zero HTTP requests. StallDetector keys on
        # response_received and would close the spider after
        # STALL_TIMEOUT (180s) regardless of how healthy the SQL job
        # is — disable it. HeartbeatExtension stays ON: without it
        # `last_heartbeat` is never updated and the dashboard reaper
        # marks the run heartbeat_timeout after 60s. The synchronous
        # ValidateService is dispatched via asyncio.to_thread() in
        # start(), so the asyncio/reactor loop stays free for the
        # heartbeat ticks.
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

    async def start(self) -> AsyncGenerator[scrapy.Request, None]:
        database_url = (
            self.settings.get("DATABASE_URL") if hasattr(self, "settings") else None
        )
        if not database_url:
            return  # tests / dry-run path
            yield  # unreachable

        session = get_session_factory(database_url)()
        try:
            shop = upsert_shop(session, self.shop_name, self.conf.shop.base_url)
            run = create_scrape_run(
                session,
                shop.id,
                "validate",
                extra_payload={"shop": self.shop_name},
            )
            session.commit()
            run_id = run.id
            shop_id = shop.id
        finally:
            session.close()

        # Publish run_id so HeartbeatExtension picks it up on its next tick.
        # MUST be set before dispatching the service (heartbeat-ordering invariant
        # documented in tests/unit/test_validate_spider.py and confirmed by the
        # MatchSpider regression that caused heartbeat_timeout on runs #387/#391).
        self._run_id = run_id

        def _run_validate() -> Any:
            s = get_session_factory(database_url)()
            try:
                counters = ValidateService(s).run(shop_id, run_id)
                s.commit()
                return counters
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
        await asyncio.to_thread(_run_validate)

        session = get_session_factory(database_url)()
        try:
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
        database_url = (
            self.settings.get("DATABASE_URL") if hasattr(self, "settings") else None
        )
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
                "ValidateSpider.closed: finalize_run_failsafe failed for run %d",
                run_id,
            )
