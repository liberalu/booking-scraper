"""Match phase spider.

Thin wrapper around MatchService so `scrapy crawl match -a shop=…` works
with the existing dashboard / cron launcher. No HTTP — calls the service
synchronously inside start() and closes immediately.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import scrapy

from book_scraper.config import load_shop_config
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
        # Match makes zero HTTP requests — disable stall/heartbeat
        # extensions that key on response_received. A long step 3
        # (shop_inferred synthesis scans all shop_books) would
        # otherwise trip stall_timeout and the run gets killed mid-SQL.
        "EXTENSIONS": {
            "book_scraper.extensions.StallDetector": None,
            "book_scraper.extensions.HeartbeatExtension": None,
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

        session = get_session_factory(database_url)()
        try:
            counters = MatchService(session).run(self.shop_name)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

        session = get_session_factory(database_url)()
        try:
            finish_scrape_run(
                session, run_id, status="completed",
                items_updated=counters.total_updates,
            )
            session.commit()
        finally:
            session.close()

        return
        yield  # unreachable, satisfies AsyncGenerator typing
