"""Unit tests for ValidateSpider — covers the dispatch invariants that
broke silently for MatchSpider on runs #387/#391:

  - ``self._run_id`` must be assigned BEFORE ValidateService runs, so
    HeartbeatExtension's lazy ``_resolve_run_id`` lookup picks it up
    on its first tick.
  - ValidateService must run off the asyncio/Twisted reactor thread so
    long synchronous SQL doesn't block heartbeat ticks.
  - finish_scrape_run must be called with status="completed" on success.
  - ValidateService.run() receives the correct (shop_id, run_id) args.
  - Missing shop argument raises ValueError.

These are structural invariants — no DB needed. Mock everything that
would touch postgres or load TOML config.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from book_scraper.spiders.validate import ValidateSpider


def _build_spider() -> ValidateSpider:
    """ValidateSpider that bypasses Scrapy's Settings + load_shop_config."""
    spider = ValidateSpider.__new__(ValidateSpider)
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
        patch("book_scraper.spiders.validate.get_session_factory") as get_factory,
        patch(
            "book_scraper.spiders.validate.upsert_shop", return_value=fake_shop
        ) as ush,
        patch(
            "book_scraper.spiders.validate.create_scrape_run", return_value=fake_run
        ) as csr,
        patch("book_scraper.spiders.validate.finish_scrape_run") as fsr,
        patch("book_scraper.spiders.validate.ValidateService") as vs_cls,
    ):
        get_factory.return_value = lambda: MagicMock()
        yield SimpleNamespace(
            upsert_shop=ush,
            create_scrape_run=csr,
            finish_scrape_run=fsr,
            vs_cls=vs_cls,
            fake_shop=fake_shop,
            fake_run=fake_run,
        )


def test_run_id_is_set_before_validate_service_runs(stub_db_layer) -> None:
    """Heartbeat extension reads `_run_id` lazily — the spider must
    publish it before any blocking SQL kicks off."""
    spider = _build_spider()
    seen_run_id: list[int | None] = []

    def fake_run(shop_id: int, run_id: int) -> dict[str, int]:
        seen_run_id.append(getattr(spider, "_run_id", None))
        return {}

    stub_db_layer.vs_cls.return_value.run.side_effect = fake_run

    asyncio.run(_drain(spider))

    assert seen_run_id == [stub_db_layer.fake_run.id]


def test_validate_service_runs_off_main_thread(stub_db_layer) -> None:
    """Without thread dispatch, synchronous SQL blocks the asyncio loop
    and HeartbeatExtension can't tick — exactly the bug that killed
    runs #387/#391."""
    main_thread_id = threading.get_ident()
    seen_thread: list[int] = []

    def fake_run(shop_id: int, run_id: int) -> dict[str, int]:
        seen_thread.append(threading.get_ident())
        return {}

    stub_db_layer.vs_cls.return_value.run.side_effect = fake_run

    asyncio.run(_drain(_build_spider()))

    assert seen_thread, "ValidateService.run was not invoked"
    assert seen_thread[0] != main_thread_id, (
        "ValidateService ran on the event loop thread — it must dispatch via "
        "asyncio.to_thread so the reactor stays free for HeartbeatExtension"
    )


def test_finish_scrape_run_called_with_completed_on_success(stub_db_layer) -> None:
    """On success, the spider must mark the run 'completed'."""
    stub_db_layer.vs_cls.return_value.run.return_value = {}

    asyncio.run(_drain(_build_spider()))

    stub_db_layer.finish_scrape_run.assert_called_once()
    _args, kwargs = stub_db_layer.finish_scrape_run.call_args
    assert kwargs.get("status") == "completed"


def test_validate_service_invoked_with_shop_id_and_run_id(stub_db_layer) -> None:
    """ValidateService.run() must receive (shop_id, run_id) positional args."""
    stub_db_layer.vs_cls.return_value.run.return_value = {}

    asyncio.run(_drain(_build_spider()))

    stub_db_layer.vs_cls.return_value.run.assert_called_once_with(
        stub_db_layer.fake_shop.id, stub_db_layer.fake_run.id
    )


def test_missing_shop_argument_raises() -> None:
    """Instantiating ValidateSpider without a shop arg raises ValueError."""
    with pytest.raises(ValueError, match="shop"):
        ValidateSpider()


async def _drain(spider: ValidateSpider) -> list:
    return [x async for x in spider.start()]
