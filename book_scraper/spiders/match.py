"""Match phase spider.

Thin wrapper around MatchService so `scrapy crawl match -a shop=…` works
with the existing dashboard / cron launcher. No HTTP — runs the service
in a worker thread so the reactor stays free for HeartbeatExtension to
tick, otherwise the dashboard reaper kills the run after
DEAD_RUN_SECONDS (60s) for a stale heartbeat.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import scrapy

from book_scraper.config import load_shop_config
from book_scraper.db.models import ScrapeRun
from book_scraper.db.repo import (
    create_scrape_run,
    finish_scrape_run,
    upsert_shop,
)
from book_scraper.db.session import get_session_factory
from book_scraper.services.match import MatchService


class MatchSpider(scrapy.Spider):
    name = "match"
    custom_settings = {
        "ITEM_PIPELINES": {},  # no items, no DB pipelines
        # Match makes zero HTTP requests. StallDetector keys on
        # response_received and would close the spider after
        # STALL_TIMEOUT (180s) regardless of how healthy the SQL job
        # is — disable it. HeartbeatExtension stays ON: without it
        # `last_heartbeat` is never updated and the dashboard reaper
        # marks the run heartbeat_timeout after 60s. The synchronous
        # MatchService is dispatched via asyncio.to_thread() in
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
                session, shop.id, "match",
                extra_payload={"shop": self.shop_name},
            )
            session.commit()
            run_id = run.id
        finally:
            session.close()

        # Publish run_id so HeartbeatExtension picks it up on its next tick.
        self._run_id = run_id

        def _run_match() -> Any:
            s = get_session_factory(database_url)()
            try:
                counters = MatchService(s).run(self.shop_name)
                s.commit()
                return counters
            except Exception:
                s.rollback()
                raise
            finally:
                s.close()

        # Run synchronous SQL in a worker thread so the asyncio/Twisted
        # reactor stays free for HeartbeatExtension's callLater ticks.
        # Otherwise step 3 (shop_inferred synthesis) blocks the reactor
        # past DEAD_RUN_SECONDS (60s) and the dashboard reaper marks the
        # run heartbeat_timeout mid-SQL.
        counters = await asyncio.to_thread(_run_match)

        session = get_session_factory(database_url)()
        try:
            run = session.get(ScrapeRun, run_id)
            if run is not None:
                run.items_updated = counters.total_updates
            finish_scrape_run(session, run_id, status="completed")
            session.commit()
        finally:
            session.close()

        return
        yield  # unreachable, satisfies AsyncGenerator typing
