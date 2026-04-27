"""Unit tests for HeartbeatExtension lifecycle.

These exercise the bookkeeping around the spider_opened-driven tick
loop and the lazy ``spider._run_id`` polling, without engaging
Twisted's reactor or a real DB.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from book_scraper.extensions import HeartbeatExtension


@pytest.fixture
def crawler() -> MagicMock:
    c = MagicMock()
    c.settings.getfloat.return_value = 5.0
    c.settings.get.return_value = (
        "postgresql://postgres:postgres@localhost:5432/x"
    )
    # Default: no spider attached. Individual tests opt in via
    # `crawler.spider = MagicMock(_run_id=...)`.
    c.spider = None
    return c


def test_tick_before_spider_assigns_run_id_is_noop(crawler: MagicMock) -> None:
    """The spider hasn't entered start() yet — tick must reschedule
    silently without dispatching the heartbeat write. Regression for
    the bug that caused runs 188-190 to be reaped: the previous
    extension waited for a custom signal that never delivered."""
    ext = HeartbeatExtension(crawler, interval=5.0)
    crawler.spider = MagicMock(_run_id=None)
    with (
        patch("twisted.internet.threads.deferToThread") as d2t,
        patch.object(ext, "_schedule_next") as sn,
    ):
        ext._tick()
        d2t.assert_not_called()
        sn.assert_called_once()


def test_tick_dispatches_write_to_worker_thread(crawler: MagicMock) -> None:
    """Once the spider has assigned _run_id, _tick offloads the write
    to deferToThread — the reactor thread itself never blocks on
    psycopg2 I/O. Regression for runs 194/195: a hung DB call in
    _write_heartbeat froze the reactor for ~5 minutes, killing all
    other callLater-scheduled callbacks (including StallDetector)."""
    ext = HeartbeatExtension(crawler, interval=5.0)
    crawler.spider = MagicMock(_run_id=42)
    with patch("twisted.internet.threads.deferToThread") as d2t:
        d2t.return_value.addCallbacks = MagicMock()
        ext._tick()
        # The write is delegated to a worker thread, not invoked inline.
        d2t.assert_called_once_with(ext._write_heartbeat, 42)
        # Both success and failure callbacks must be registered so the
        # loop reschedules in either case.
        d2t.return_value.addCallbacks.assert_called_once_with(
            ext._on_tick_done, ext._on_tick_failed
        )
    assert ext._run_id == 42


def test_tick_picks_up_run_id_after_initial_skip(crawler: MagicMock) -> None:
    """Realistic flow: spider_opened fires → first tick fires before
    start() has set _run_id → no-op + reschedule. Spider then enters
    start() and assigns _run_id → next tick dispatches a write."""
    ext = HeartbeatExtension(crawler, interval=5.0)
    crawler.spider = MagicMock(_run_id=None)
    with (
        patch("twisted.internet.threads.deferToThread") as d2t,
        patch.object(ext, "_schedule_next") as sn,
    ):
        d2t.return_value.addCallbacks = MagicMock()
        ext._tick()
        d2t.assert_not_called()
        sn.assert_called_once()
        sn.reset_mock()

        # Spider has now started and assigned its run_id.
        crawler.spider._run_id = 99
        ext._tick()
        d2t.assert_called_once_with(ext._write_heartbeat, 99)
        # No _schedule_next here — that fires later via _on_tick_done.
        sn.assert_not_called()


def test_on_tick_done_reschedules(crawler: MagicMock) -> None:
    """Successful heartbeat write: schedule next tick, do not signal stop."""
    ext = HeartbeatExtension(crawler, interval=5.0)
    with (
        patch.object(ext, "_schedule_next") as sn,
        patch.object(ext, "_signal_stop") as ss,
    ):
        ext._on_tick_done("running")
        sn.assert_called_once()
        ss.assert_not_called()


def test_on_tick_done_handles_paused_status(crawler: MagicMock) -> None:
    """A 'paused' run is intentionally alive — heartbeat keeps ticking
    so the reaper does not kill it. Just reschedule."""
    ext = HeartbeatExtension(crawler, interval=5.0)
    with (
        patch.object(ext, "_schedule_next") as sn,
        patch.object(ext, "_signal_stop") as ss,
    ):
        ext._on_tick_done("paused")
        sn.assert_called_once()
        ss.assert_not_called()


def test_on_tick_done_handles_stopping_signals_stop(crawler: MagicMock) -> None:
    """When the dashboard flips status to 'stopping', the heartbeat
    is the carrier signal that tears the spider down cleanly."""
    ext = HeartbeatExtension(crawler, interval=5.0)
    with (
        patch.object(ext, "_schedule_next") as sn,
        patch.object(ext, "_signal_stop") as ss,
    ):
        ext._on_tick_done("stopping")
        ss.assert_called_once()
        sn.assert_not_called()


def test_on_tick_failed_logs_and_reschedules(crawler: MagicMock) -> None:
    """A worker-thread exception surfaces as a Twisted Failure. Log it
    and reschedule — a one-off DB blip must not silently kill the
    heartbeat loop."""
    ext = HeartbeatExtension(crawler, interval=5.0)
    fake_failure = MagicMock()
    fake_failure.getErrorMessage.return_value = "connection refused"
    with patch.object(ext, "_schedule_next") as sn:
        ext._on_tick_failed(fake_failure)
        sn.assert_called_once()


def test_spider_closed_cancels_pending_task(crawler: MagicMock) -> None:
    ext = HeartbeatExtension(crawler, interval=5.0)
    fake_task: Any = MagicMock()
    fake_task.active.return_value = True
    ext._task = fake_task
    ext.spider_closed()
    fake_task.cancel.assert_called_once()
    assert ext._task is None


def test_spider_opened_schedules_first_tick(crawler: MagicMock) -> None:
    """spider_opened starts the loop. Subsequent _tick fires read run_id
    lazily off the spider — no signal handshake needed."""
    ext = HeartbeatExtension(crawler, interval=5.0)
    with patch.object(ext, "_schedule_next") as sn:
        ext.spider_opened()
        sn.assert_called_once()


def test_resolve_run_id_handles_missing_spider(crawler: MagicMock) -> None:
    """If the crawler has no spider attached (e.g. between runs),
    _resolve_run_id must return None rather than raising."""
    ext = HeartbeatExtension(crawler, interval=5.0)
    crawler.spider = None
    assert ext._resolve_run_id() is None


def test_resolve_run_id_handles_non_int_run_id(crawler: MagicMock) -> None:
    """Defensive: a spider may have `_run_id = None` or a non-int
    sentinel. _resolve_run_id must filter those out."""
    ext = HeartbeatExtension(crawler, interval=5.0)
    crawler.spider = MagicMock(_run_id="not-an-int")
    assert ext._resolve_run_id() is None


# --- Back-compat surface ---


def test_on_run_started_still_writes_immediately(crawler: MagicMock) -> None:
    """Legacy entry point preserved for callers that may still emit the
    custom run_started signal. Writes immediately + schedules next tick.
    Production code no longer depends on this; spider_opened handles
    the bootstrap."""
    ext = HeartbeatExtension(crawler, interval=5.0)
    with (
        patch.object(ext, "_write_heartbeat") as wh,
        patch.object(ext, "_schedule_next") as sn,
    ):
        ext.on_run_started(run_id=3, sender=MagicMock(), some_extra="x")
        wh.assert_called_once_with(3)
        sn.assert_called_once()
        assert ext._run_id == 3
