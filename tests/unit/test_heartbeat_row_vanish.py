"""CODEOBS-03: HeartbeatExtension tears down when its row vanishes."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

from book_scraper.extensions import HeartbeatExtension


def _make_ext() -> tuple[HeartbeatExtension, MagicMock, MagicMock]:
    crawler = MagicMock()
    spider = MagicMock()
    engine = MagicMock()
    crawler.spider = spider
    crawler.engine = engine
    ext = HeartbeatExtension(crawler, interval=5.0)
    ext._run_id = 999
    return ext, spider, engine


def test_on_tick_done_none_closes_spider_with_row_vanished(caplog) -> None:
    ext, spider, engine = _make_ext()
    with caplog.at_level(logging.WARNING, logger="book_scraper.extensions"):
        ext._on_tick_done(None)
    engine.close_spider.assert_called_once_with(spider, "row_vanished")
    assert any("run 999 vanished" in r.getMessage() for r in caplog.records)


def test_on_tick_done_stopping_uses_signal_stop() -> None:
    ext, spider, engine = _make_ext()
    ext._on_tick_done("stopping")
    engine.close_spider.assert_called_once_with(spider, "stopped_by_operator")


def test_on_tick_done_running_reschedules() -> None:
    ext, spider, engine = _make_ext()
    ext._schedule_next = MagicMock()
    ext._on_tick_done("running")
    engine.close_spider.assert_not_called()
    ext._schedule_next.assert_called_once()
