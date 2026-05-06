"""Unit tests for CronChainTrigger extension."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from book_scraper.extensions import CronChainTrigger


@pytest.fixture
def crawler() -> MagicMock:
    c = MagicMock()
    c.settings.get.return_value = "postgresql://localhost/test"
    c.spider = MagicMock(_run_id=None)
    return c


def test_no_spawn_when_reason_is_not_finished(crawler: MagicMock) -> None:
    """Chain must NOT fire if spider closes for any reason other than 'finished'."""
    ext = CronChainTrigger(crawler)
    spider = MagicMock()
    spider.cron_job_id = "3"
    ext.spider_opened(spider)

    with patch.object(ext, "_spawn_chain_subprocess") as mock_spawn:
        ext.spider_closed(spider, reason="shutdown")
        mock_spawn.assert_not_called()

    with patch.object(ext, "_spawn_chain_subprocess") as mock_spawn:
        ext.spider_closed(spider, reason="stall_timeout")
        mock_spawn.assert_not_called()


def test_no_spawn_when_no_cron_job_id(crawler: MagicMock) -> None:
    """Chain must NOT fire if cron_job_id was not set (e.g. manually triggered run)."""
    ext = CronChainTrigger(crawler)
    spider = MagicMock(spec=[])  # no cron_job_id attribute
    ext.spider_opened(spider)

    with patch.object(ext, "_spawn_chain_subprocess") as mock_spawn:
        ext.spider_closed(spider, reason="finished")
        mock_spawn.assert_not_called()


def test_no_spawn_when_chain_to_job_id_is_none(crawler: MagicMock) -> None:
    """Chain must NOT fire if the job has no chain configured."""
    ext = CronChainTrigger(crawler)
    spider = MagicMock()
    spider.cron_job_id = "5"
    ext.spider_opened(spider)

    mock_job = MagicMock()
    mock_job.chain_to_job_id = None

    with (
        patch.object(ext, "_get_chain_job", return_value=(mock_job, None)),
        patch.object(ext, "_spawn_chain_subprocess") as mock_spawn,
    ):
        ext.spider_closed(spider, reason="finished")
        mock_spawn.assert_not_called()


def test_spawns_chain_on_finished(crawler: MagicMock) -> None:
    """Chain job subprocess is spawned when reason='finished' and chain exists."""
    ext = CronChainTrigger(crawler)
    spider = MagicMock()
    spider.cron_job_id = "3"
    ext.spider_opened(spider)

    mock_this_job = MagicMock()
    mock_this_job.chain_to_job_id = 7

    mock_chain_job = MagicMock()
    mock_chain_job.id = 7
    mock_chain_job.phase = "scan"
    mock_chain_job.strategy = None
    mock_chain_job.args = ""
    mock_chain_job.shop.name = "vaga"

    ret = (mock_this_job, mock_chain_job)
    with (
        patch.object(ext, "_get_chain_job", return_value=ret),
        patch.object(ext, "_spawn_chain_subprocess") as mock_spawn,
    ):
        ext.spider_closed(spider, reason="finished")
        mock_spawn.assert_called_once_with(
            phase="scan",
            shop="vaga",
            strategy=None,
            args="",
            chain_job_id=7,
        )


def test_spawns_chain_with_strategy(crawler: MagicMock) -> None:
    """Discover chain job includes strategy arg."""
    ext = CronChainTrigger(crawler)
    spider = MagicMock()
    spider.cron_job_id = "1"
    ext.spider_opened(spider)

    mock_this_job = MagicMock()
    mock_this_job.chain_to_job_id = 2

    mock_chain_job = MagicMock()
    mock_chain_job.id = 2
    mock_chain_job.phase = "discover"
    mock_chain_job.strategy = "graphql"
    mock_chain_job.args = ""
    mock_chain_job.shop.name = "pegasas"

    ret = (mock_this_job, mock_chain_job)
    with (
        patch.object(ext, "_get_chain_job", return_value=ret),
        patch.object(ext, "_spawn_chain_subprocess") as mock_spawn,
    ):
        ext.spider_closed(spider, reason="finished")
        mock_spawn.assert_called_once_with(
            phase="discover",
            shop="pegasas",
            strategy="graphql",
            args="",
            chain_job_id=2,
        )
