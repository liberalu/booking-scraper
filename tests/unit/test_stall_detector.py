"""Unit tests for StallDetector._check_stall in-flight request guard.

These exercise the new two-condition stall logic (elapsed AND idle
downloader) without engaging Twisted's reactor or a real DB.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from book_scraper.extensions import StallDetector


@pytest.fixture
def crawler() -> MagicMock:
    c = MagicMock()
    c.settings.getfloat.return_value = 0  # STALL_FORCE_EXIT_S off by default
    c.settings.getint.return_value = 0  # STALL_AUTO_RESUME_MAX off
    c.settings.get.return_value = "postgresql://localhost/test"
    c.spider = MagicMock(_run_id=None)
    return c


def _make_downloader(in_flight: int) -> MagicMock:
    """Build a minimal mock downloader with `in_flight` active requests."""
    slot = MagicMock()
    slot.active = set(range(in_flight))  # set of size in_flight
    downloader = MagicMock()
    downloader.slots = {"host": slot} if in_flight > 0 else {}
    return downloader


def test_in_flight_requests_suppress_stall(crawler: MagicMock) -> None:
    """When the timer has expired but the downloader still has active
    requests, the stall must NOT fire — reset the timer and reschedule."""
    ext = StallDetector(crawler, stall_timeout=1.0)
    # Simulate elapsed time exceeding timeout
    ext._last_activity -= 2.0

    crawler.engine = MagicMock()
    crawler.engine.downloader = _make_downloader(in_flight=2)

    # twisted.internet.reactor is a lazy attribute not present until a
    # reactor is installed; create=True lets patch inject a mock for it.
    with patch("twisted.internet.reactor", create=True) as mock_reactor:
        mock_reactor.callLater = MagicMock()
        with patch("book_scraper.extensions.StallDetector._finalize_run_failed") as fin:
            ext._check_stall()
            # Stall kill must NOT have been triggered
            crawler.engine.close_spider.assert_not_called()
            fin.assert_not_called()
        # Timer must have been rescheduled
        mock_reactor.callLater.assert_called_once()


def test_idle_downloader_fires_stall(crawler: MagicMock) -> None:
    """When the timer has expired AND the downloader has no active
    requests, the stall kill must fire."""
    ext = StallDetector(crawler, stall_timeout=1.0)
    ext._last_activity -= 2.0

    crawler.engine = MagicMock()
    crawler.engine.downloader = _make_downloader(in_flight=0)

    with (
        patch("book_scraper.extensions.StallDetector._finalize_run_failed"),
        patch("book_scraper.extensions.StallDetector._maybe_auto_resume"),
    ):
        ext._check_stall()
        crawler.engine.close_spider.assert_called_once_with(
            crawler.spider, "stall_timeout"
        )


def test_engine_none_still_fires_stall(crawler: MagicMock) -> None:
    """If engine is None we can't check in-flight, but we still log and
    return early (no close_spider call either). This matches the existing
    guard: 'Skipping stall shutdown because no engine is active'."""
    ext = StallDetector(crawler, stall_timeout=1.0)
    ext._last_activity -= 2.0

    crawler.engine = None

    with patch("book_scraper.extensions.StallDetector._finalize_run_failed") as fin:
        ext._check_stall()
        # close_spider can't be called — engine is None
        fin.assert_not_called()


def test_no_stall_when_within_timeout(crawler: MagicMock) -> None:
    """If the elapsed time is within the timeout, neither the in-flight
    check nor the kill should be triggered."""
    ext = StallDetector(crawler, stall_timeout=60.0)
    # Don't advance _last_activity — still fresh

    crawler.engine = MagicMock()
    crawler.engine.downloader = _make_downloader(in_flight=0)

    with patch("twisted.internet.reactor", create=True) as mock_reactor:
        mock_reactor.callLater = MagicMock()
        ext._check_stall()
        crawler.engine.close_spider.assert_not_called()
        mock_reactor.callLater.assert_called_once()
