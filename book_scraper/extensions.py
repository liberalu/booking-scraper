import logging  # pragma: no cover
import time  # pragma: no cover
from typing import Any  # pragma: no cover

from scrapy import signals  # pragma: no cover
from scrapy.crawler import Crawler  # pragma: no cover
from scrapy.exceptions import NotConfigured  # pragma: no cover

logger = logging.getLogger(__name__)  # pragma: no cover


class StallDetector:  # pragma: no cover
    """Close the spider if no responses arrive for STALL_TIMEOUT seconds.

    Checks every 10 seconds. If the last response was more than
    STALL_TIMEOUT seconds ago, forces a graceful shutdown.
    """

    def __init__(self, crawler: Crawler, stall_timeout: float):
        self.crawler = crawler
        self.stall_timeout = stall_timeout
        self._last_activity = time.monotonic()
        self._check_interval = 10.0
        self._task: Any = None

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "StallDetector":
        timeout = crawler.settings.getfloat("STALL_TIMEOUT", 0)
        if not timeout:
            raise NotConfigured
        ext = cls(crawler, timeout)
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(
            ext.response_received,
            signal=signals.response_received,
        )
        crawler.signals.connect(ext.item_scraped, signal=signals.item_scraped)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_opened(self) -> None:
        self._last_activity = time.monotonic()
        from twisted.internet import reactor

        self._task = reactor.callLater(  # type: ignore[attr-defined]
            self._check_interval, self._check_stall
        )

    def response_received(self, **kwargs: Any) -> None:
        self._last_activity = time.monotonic()

    def item_scraped(self, **kwargs: Any) -> None:
        self._last_activity = time.monotonic()

    def spider_closed(self) -> None:
        if self._task and self._task.active():
            self._task.cancel()

    def _check_stall(self) -> None:
        elapsed = time.monotonic() - self._last_activity
        if elapsed > self.stall_timeout:
            logger.warning(
                "Spider stalled for %.0fs — forcing shutdown",
                elapsed,
            )
            spider = self.crawler.spider
            if spider is None:
                logger.warning("Skipping stall shutdown because no spider is active")
                return
            engine = self.crawler.engine
            if engine is None:
                logger.warning("Skipping stall shutdown because no engine is active")
                return

            # Belt-and-suspenders: directly mark the run failed in a fresh
            # session before closing the spider. The close path can fail
            # (PendingRollbackError if the pipeline session is poisoned)
            # leaving the run zombie-running. This guarantees finalisation.
            run_id = getattr(spider, "_run_id", None)
            if run_id is not None:
                self._finalize_run_failed(run_id, "stall_timeout")

            engine.close_spider(spider, "stall_timeout")
            return

        from twisted.internet import reactor

        self._task = reactor.callLater(  # type: ignore[attr-defined]
            self._check_interval, self._check_stall
        )

    def _finalize_run_failed(self, run_id: int, reason: str) -> None:
        """Mark a stalled run failed via a fresh DB session.

        Stalls are recoverable — the underlying queue still has pending
        URLs that the next scheduled run can adopt. Set
        ``resumable_after_failure`` so ``find_resumable_run`` picks the
        run up next time.
        """
        try:
            from book_scraper.db.models import ScrapeRun
            from book_scraper.db.repo import finish_scrape_run
            from book_scraper.db.session import get_session_factory

            database_url = self.crawler.settings.get("DATABASE_URL")
            session_factory = get_session_factory(database_url)
            session = session_factory()
            try:
                finish_scrape_run(session, run_id, "failed", reason=reason)
                run = session.get(ScrapeRun, run_id)
                if run is not None:
                    run.resumable_after_failure = True
                session.commit()
            finally:
                session.close()
        except Exception:
            logger.exception("Failed to mark run %d failed on stall", run_id)


class HeartbeatExtension:  # pragma: no cover
    """Tick `scrape_runs.last_heartbeat` every N seconds while a run is live.

    Hooks into the custom `run_started` signal (not `spider_opened`)
    because `_run_id` is assigned inside `start()`, after spider_opened
    has already fired. See the live observability spec.

    Independent of request flow, so a request hung in the downloader
    doesn't make the process look dead. Stops on `spider_closed`.
    """

    def __init__(self, crawler: Crawler, interval: float):
        self.crawler = crawler
        self.interval = interval
        self._run_id: int | None = None
        self._task: Any = None
        self._session_factory: Any = None

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "HeartbeatExtension":
        from book_scraper.signals import run_started

        interval = crawler.settings.getfloat("HEARTBEAT_INTERVAL_S", 5.0)
        if interval <= 0:
            raise NotConfigured
        ext = cls(crawler, interval)
        crawler.signals.connect(ext.on_run_started, signal=run_started)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def on_run_started(self, run_id: int, sender: Any = None, **kwargs: Any) -> None:
        self._run_id = run_id
        # Immediate write so even short runs (faster than the tick
        # interval) get a fresh heartbeat — otherwise a 4-second scan
        # would leave the dashboard reading the stale value from
        # create_scrape_run.
        try:
            self._write_heartbeat(run_id)
        except Exception:
            logger.exception("Initial heartbeat write failed for run %d", run_id)
        self._schedule_next()

    def spider_closed(self) -> None:
        if self._task is not None and self._task.active():
            self._task.cancel()
        self._task = None

    def _schedule_next(self) -> None:
        from twisted.internet import reactor

        self._task = reactor.callLater(  # type: ignore[attr-defined]
            self.interval, self._tick
        )

    def _tick(self) -> None:
        if self._run_id is None:
            logger.warning("HeartbeatExtension tick before run_id; skipping")
            self._schedule_next()
            return
        try:
            status = self._write_heartbeat(self._run_id)
        except Exception:
            logger.exception("Heartbeat write failed for run %d", self._run_id)
            status = None
        # Operator-requested stop: the dashboard flipped status to
        # 'stopping'. Tear the spider down cleanly. The spider's
        # `closed()` callback transitions the row to 'failed' with
        # error_reason='stopped_by_operator'.
        if status == "stopping":
            self._signal_stop()
            return
        self._schedule_next()

    def _signal_stop(self) -> None:
        spider = getattr(self.crawler, "spider", None)
        engine = getattr(self.crawler, "engine", None)
        if spider is None or engine is None:
            logger.warning(
                "Heartbeat saw 'stopping' for run %d but spider/engine missing",
                self._run_id,
            )
            return
        logger.info(
            "Run %d transitioned to 'stopping' — closing spider", self._run_id
        )
        engine.close_spider(spider, "stopped_by_operator")

    def _write_heartbeat(self, run_id: int) -> str | None:
        """Tick the heartbeat and report the run's current status.

        Returns the row's `status` after the UPDATE, so the caller can
        notice an operator-requested stop ('stopping') and tear the
        spider down. Returns None if the row vanished.
        """
        from sqlalchemy import text as sa_text

        from book_scraper.db.session import get_session_factory

        if self._session_factory is None:
            database_url = self.crawler.settings.get("DATABASE_URL")
            self._session_factory = get_session_factory(database_url)
        session = self._session_factory()
        try:
            # Apply a per-statement timeout so a hung DB doesn't pile
            # up ticks. SET LOCAL stays scoped to the transaction.
            session.execute(sa_text("SET LOCAL statement_timeout = '2s'"))
            # Terminal-state guard: don't refresh the heartbeat for a
            # reaped run. Without this, a tick that fires after the
            # dashboard reaper transitioned to `failed` would make the
            # row look alive again on the next reaper pass.
            session.execute(
                sa_text(
                    "UPDATE scrape_runs SET last_heartbeat = now() "
                    "WHERE id = :run_id AND status = 'running'"
                ),
                {"run_id": run_id},
            )
            current_status = session.execute(
                sa_text("SELECT status FROM scrape_runs WHERE id = :run_id"),
                {"run_id": run_id},
            ).scalar()
            session.commit()
            return str(current_status) if current_status is not None else None
        finally:
            session.close()
