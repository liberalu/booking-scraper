"""CODEOBS-04: StallDetector stall log carries full diagnostic stats."""
from __future__ import annotations
from unittest.mock import MagicMock
from book_scraper.extensions import StallDetector


def _make_detector() -> StallDetector:
    crawler = MagicMock()
    crawler.stats.get_value.return_value = 42
    slot = MagicMock()
    slot.active = [MagicMock(), MagicMock(), MagicMock()]
    crawler.engine.downloader.slots = {"vaga.lt": slot}
    scheduler_slot = MagicMock()
    scheduler_slot.scheduler.__len__ = lambda self: 17
    crawler.engine.slot = scheduler_slot
    det = StallDetector(crawler, stall_timeout=180, check_interval=10)
    det._last_response_url = "https://www.vaga.lt/some-book"
    return det


def test_collect_stall_diagnostics_returns_all_fields() -> None:
    det = _make_detector()
    stats = det._collect_stall_diagnostics()
    assert stats["request_count"] == 42
    assert stats["last_url"] == "https://www.vaga.lt/some-book"
    assert stats["in_flight_by_domain"] == {"vaga.lt": 3}
    assert stats["scheduler_queue"] == 17


def test_collect_stall_diagnostics_no_engine_returns_defaults() -> None:
    crawler = MagicMock()
    crawler.stats.get_value.return_value = 0
    crawler.engine = None
    det = StallDetector(crawler, stall_timeout=180, check_interval=10)
    det._last_response_url = None
    stats = det._collect_stall_diagnostics()
    assert stats["last_url"] == "<none>"
    assert stats["in_flight_by_domain"] == {}
    assert stats["scheduler_queue"] == -1
