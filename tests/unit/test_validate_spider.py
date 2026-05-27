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


def test_closed_calls_finalize_run_failsafe(stub_db_layer) -> None:
    """closed() must call finalize_run_failsafe so a crash mid-SQL never
    leaves the run row in 'running'.  The failsafe's own terminal-state
    guard (added with the run-424 fix) makes this a no-op when the happy
    path already completed the run — but the call must still happen."""
    with patch("book_scraper.spiders.validate.finalize_run_failsafe") as mock_failsafe:
        spider = _build_spider()
        spider._run_id = 999
        spider.settings = MagicMock()
        spider.settings.get.return_value = "postgresql://fake/url"

        spider.closed(reason="finished")

        mock_failsafe.assert_called_once()
        _args, kwargs = mock_failsafe.call_args
        assert kwargs.get("status") == "failed" or _args[2] == "failed"


def test_counters_logged_with_per_issue_breakdown(stub_db_layer, caplog) -> None:
    """The validate spider must log a `validate_counters` line on every run
    with the per-issue emit counts. Without it, the only signal that a
    check has silently stopped emitting (typo, swallowed exception,
    deleted `results.extend` line) is a sudden drop in the dashboard's
    open-issue count — easy to miss. `resolve_gone_issues` then
    unconditionally clears the backlog for that type on the next run.

    Format is `key=value`-pair-friendly so LogQL can `| logfmt` and
    alert on "issue_type that historically emits > N drops to 0".
    """
    import logging

    stub_db_layer.vs_cls.return_value.run.return_value = {
        "isbn_duplicate": 4,
        "active_no_price": 2,
        "slug_title_mismatch": 0,
    }

    with caplog.at_level(logging.INFO, logger="scrapy.spiders.validate"):
        # Scrapy's spider.logger writes to a child of the spider's name
        # (per Scrapy convention). Capture everything at INFO and filter
        # by message text below.
        caplog.set_level(logging.INFO)
        asyncio.run(_drain(_build_spider()))

    matches = [
        rec.getMessage()
        for rec in caplog.records
        if "validate_counters" in rec.getMessage()
    ]
    assert len(matches) == 1, (
        f"expected exactly one validate_counters log line, got: {matches}"
    )
    line = matches[0]
    # Run/shop identifiers present
    assert "run_id=999" in line
    assert "shop=testshop" in line
    # Aggregate fields present
    assert "total=6" in line
    assert "distinct=3" in line
    # Per-issue counts present (sorted, key=value)
    assert "active_no_price=2" in line
    assert "isbn_duplicate=4" in line
    assert "slug_title_mismatch=0" in line


def test_counters_logged_when_validator_returns_empty(stub_db_layer, caplog) -> None:
    """Empty counters dict is the most dangerous case — every standing
    issue gets auto-resolved by `resolve_gone_issues`. The log line
    must still emit with total=0 so dashboards can alert on it.
    """
    import logging

    stub_db_layer.vs_cls.return_value.run.return_value = {}

    with caplog.at_level(logging.INFO):
        asyncio.run(_drain(_build_spider()))

    matches = [
        rec.getMessage()
        for rec in caplog.records
        if "validate_counters" in rec.getMessage()
    ]
    assert len(matches) == 1
    assert "total=0" in matches[0]
    assert "distinct=0" in matches[0]


async def _drain(spider: ValidateSpider) -> list:
    return [x async for x in spider.start()]
