"""Unit tests for MatchSpider — covers the dispatch invariants that broke
silently before (heartbeat_timeout failures on runs #387, #391):

  - ``self._run_id`` must be assigned BEFORE MatchService runs, so
    HeartbeatExtension's lazy ``_resolve_run_id`` lookup picks it up
    on its first tick.
  - MatchService must run off the asyncio/Twisted reactor thread, so
    long synchronous SQL in step 3 doesn't block heartbeat ticks.
  - Counters from MatchService.run() must propagate to
    ``ScrapeRun.items_updated`` before the run row is finalised.

These are structural invariants — no DB needed. Mock everything that
would touch postgres or load TOML config.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from book_scraper.services.match import MatchCounters
from book_scraper.spiders.match import MatchSpider


def _build_spider() -> MatchSpider:
    """MatchSpider that bypasses Scrapy's Settings + load_shop_config."""
    spider = MatchSpider.__new__(MatchSpider)
    spider.shop_name = "testshop"
    spider.conf = SimpleNamespace(shop=SimpleNamespace(base_url="https://t.lt"))
    spider.settings = MagicMock()
    spider.settings.get.return_value = "postgresql://fake/url"
    return spider


@pytest.fixture
def stub_db_layer():
    """Patch repo / session / service so start() does no real I/O."""
    fake_shop = SimpleNamespace(id=42)
    fake_run = SimpleNamespace(id=999)

    with (
        patch("book_scraper.spiders.service_spider.get_session_factory") as get_factory,
        patch(
            "book_scraper.spiders.service_spider.upsert_shop", return_value=fake_shop
        ) as ush,
        patch(
            "book_scraper.spiders.service_spider.create_scrape_run",
            return_value=fake_run,
        ) as csr,
        patch("book_scraper.spiders.service_spider.finish_scrape_run") as fsr,
        patch("book_scraper.spiders.match.MatchService") as ms_cls,
    ):
        # Each call to get_session_factory(url)() returns a fresh MagicMock.
        get_factory.return_value = lambda: MagicMock()
        # MatchService(session).run(shop) returns the counters we want.
        yield SimpleNamespace(
            upsert_shop=ush,
            create_scrape_run=csr,
            finish_scrape_run=fsr,
            ms_cls=ms_cls,
            fake_run=fake_run,
        )


def test_run_id_is_set_before_match_service_runs(stub_db_layer):
    """Heartbeat extension reads `_run_id` lazily — the spider must
    publish it before any blocking SQL kicks off."""
    spider = _build_spider()
    seen_run_id: list[int | None] = []

    def fake_run(shop_name: str) -> MatchCounters:
        seen_run_id.append(getattr(spider, "_run_id", None))
        return MatchCounters(books_linked=3, authors_linked=2)

    stub_db_layer.ms_cls.return_value.run.side_effect = fake_run

    asyncio.run(_drain(spider))

    assert seen_run_id == [stub_db_layer.fake_run.id]


def test_match_service_runs_off_event_loop_thread(stub_db_layer):
    """Without thread dispatch, synchronous SQL in MatchService blocks
    the asyncio loop and HeartbeatExtension can't tick — exactly the
    bug that killed runs #387/#391."""
    main_thread_id = threading.get_ident()
    seen_thread: list[int] = []

    def fake_run(shop_name: str) -> MatchCounters:
        seen_thread.append(threading.get_ident())
        return MatchCounters()

    stub_db_layer.ms_cls.return_value.run.side_effect = fake_run

    asyncio.run(_drain(_build_spider()))

    assert seen_thread, "MatchService.run was not invoked"
    assert seen_thread[0] != main_thread_id, (
        "MatchService ran on the event loop thread — it must dispatch via "
        "asyncio.to_thread so the reactor stays free for HeartbeatExtension"
    )


def test_counters_propagate_to_items_updated(stub_db_layer):
    """The completed run row must reflect what MatchService actually did."""
    counters = MatchCounters(books_linked=10, authors_linked=4, books_synthesized=2)
    stub_db_layer.ms_cls.return_value.run.return_value = counters

    # Capture the ScrapeRun the spider mutates after the thread returns.
    captured: list[int] = []

    def fake_session_get(model, run_id):
        run = SimpleNamespace(items_updated=0)

        # When the spider sets run.items_updated, record it.
        class _Watch:
            def __setattr__(self_, name, value):
                if name == "items_updated":
                    captured.append(value)
                object.__setattr__(self_, name, value)

        return _Watch()

    finalize_session = MagicMock()
    finalize_session.get.side_effect = fake_session_get

    # Replace get_session_factory so the third session (finalize) is the
    # watcher, while the first two (run-create, MatchService) stay plain.
    sessions = [MagicMock(), MagicMock(), finalize_session]
    with patch(
        "book_scraper.spiders.service_spider.get_session_factory",
        return_value=lambda: sessions.pop(0),
    ):
        asyncio.run(_drain(_build_spider()))

    assert captured == [counters.total_updates] == [14]
    stub_db_layer.finish_scrape_run.assert_called_once()
    # Spider should request the 'completed' terminal status.
    _args, kwargs = stub_db_layer.finish_scrape_run.call_args
    assert kwargs.get("status") == "completed"


def test_closed_calls_finalize_run_failsafe() -> None:
    """closed() must call finalize_run_failsafe so a crash mid-SQL never
    leaves the run row in 'running'.

    MatchSpider had no `closed()` at all until the lifecycle moved into
    ServiceSpider (2026-07-25) — validate.py had the failsafe, its "mirrors
    match.py exactly" copy did not, so a match crash left the run zombie
    until the dashboard reaper caught it 60s later.
    """
    with patch(
        "book_scraper.spiders.service_spider.finalize_run_failsafe"
    ) as mock_failsafe:
        spider = _build_spider()
        spider._run_id = 999

        spider.closed(reason="finished")

        mock_failsafe.assert_called_once()
        _args, kwargs = mock_failsafe.call_args
        assert kwargs.get("status") == "failed" or _args[2] == "failed"


async def _drain(spider: MatchSpider) -> list:
    return [x async for x in spider.start()]
