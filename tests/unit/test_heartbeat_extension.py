"""Unit tests for HeartbeatExtension lifecycle.

These exercise the bookkeeping around the run_started signal and the
LoopingCall scheduling without engaging Twisted's reactor or a real DB.
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
    return c


def test_no_tick_before_run_started(crawler: MagicMock) -> None:
    """Ticking before run_started must skip without raising."""
    ext = HeartbeatExtension(crawler, interval=5.0)
    # _run_id is None at this point — tick should warn and skip.
    with (
        patch.object(ext, "_write_heartbeat") as wh,
        patch.object(ext, "_schedule_next") as sn,
    ):
        ext._tick()
        wh.assert_not_called()
        sn.assert_called_once()


def test_tick_writes_with_run_id_after_signal(crawler: MagicMock) -> None:
    ext = HeartbeatExtension(crawler, interval=5.0)
    with (
        patch.object(ext, "_write_heartbeat") as wh,
        patch.object(ext, "_schedule_next") as sn,
    ):
        ext.on_run_started(run_id=42, sender=MagicMock())
        # on_run_started writes immediately so dashboards see the run
        # alive without waiting for the first tick.
        wh.assert_called_with(42)
        sn.assert_called_once()
        wh.reset_mock()
        sn.reset_mock()
        ext._tick()
        wh.assert_called_once_with(42)
        sn.assert_called_once()
    assert ext._run_id == 42


def test_tick_swallows_db_errors_and_reschedules(
    crawler: MagicMock,
) -> None:
    """A failing DB write must not poison the loop."""
    ext = HeartbeatExtension(crawler, interval=5.0)
    with (
        patch.object(
            ext, "_write_heartbeat", side_effect=RuntimeError("boom")
        ),
        patch.object(ext, "_schedule_next") as sn,
    ):
        # The immediate on_run_started write also raises; must be
        # swallowed so the loop still gets scheduled.
        ext.on_run_started(run_id=7, sender=MagicMock())
        sn.assert_called_once()
        sn.reset_mock()
        ext._tick()
        # And the periodic tick stays resilient.
        sn.assert_called_once()


def test_spider_closed_cancels_pending_task(crawler: MagicMock) -> None:
    ext = HeartbeatExtension(crawler, interval=5.0)
    fake_task: Any = MagicMock()
    fake_task.active.return_value = True
    ext._task = fake_task
    ext.spider_closed()
    fake_task.cancel.assert_called_once()
    assert ext._task is None


def test_on_run_started_accepts_extra_kwargs(crawler: MagicMock) -> None:
    """Scrapy may inject additional keys; receiver must tolerate them."""
    ext = HeartbeatExtension(crawler, interval=5.0)
    with (
        patch.object(ext, "_write_heartbeat"),
        patch.object(ext, "_schedule_next"),
    ):
        ext.on_run_started(run_id=3, sender=MagicMock(), some_extra="x")
        assert ext._run_id == 3
