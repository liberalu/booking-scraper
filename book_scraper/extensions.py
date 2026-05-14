import logging  # pragma: no cover
import time  # pragma: no cover
from typing import Any  # pragma: no cover

from scrapy import signals  # pragma: no cover
from scrapy.crawler import Crawler  # pragma: no cover
from scrapy.exceptions import NotConfigured  # pragma: no cover

logger = logging.getLogger(__name__)  # pragma: no cover


class StallDetector:  # pragma: no cover
    """Close the spider if no responses arrive for STALL_TIMEOUT seconds.

    Checks every 10 seconds. Two conditions must both hold before the kill
    fires: (1) no ``response_received`` or ``item_scraped`` signal for
    longer than STALL_TIMEOUT seconds, AND (2) the downloader has no
    in-flight requests. Condition (2) prevents false kills on slow
    cold-cache backends (e.g. Pegasas Magento) where a request can take
    60–150 s without producing a signal.
    """

    def __init__(self, crawler: Crawler, stall_timeout: float):
        self.crawler = crawler
        self.stall_timeout = stall_timeout
        self._last_activity = time.monotonic()
        self._check_interval = 10.0
        self._task: Any = None
        # Auto-resume bookkeeping: when a stall fires, _check_stall
        # records the spawn params here, and `spider_closed` does the
        # actual subprocess.Popen. Spawning earlier (inside _check_stall)
        # races with the still-shutting-down spider — both spiders end
        # up active for ~30s, both running concurrency=N, producing
        # 2×N concurrent requests instead of N and exhausting the
        # backend faster than a single spider would.
        self._pending_auto_resume: dict[str, Any] | None = None

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
        # If _check_stall queued an auto-resume, spawn it now — by this
        # point the spider has fully drained and exited, so the new
        # subprocess can't overlap with us.
        if self._pending_auto_resume is not None:
            params = self._pending_auto_resume
            self._pending_auto_resume = None
            self._spawn_resume_subprocess(
                params["spider_name"],
                params["shop"],
                params["strategy"],
                params["attempt"],
                params["max_attempts"],
            )

    def _check_stall(self) -> None:
        elapsed = time.monotonic() - self._last_activity
        if elapsed > self.stall_timeout:
            # Before declaring a stall, verify the downloader is actually
            # idle. Cold-cache backends (e.g. Pegasas Magento) can hold
            # requests open for 60–150s with no response_received signal
            # landing — that's slow but not stalled. Only fire the kill
            # when both the timer has expired AND there are no in-flight
            # requests.
            engine = self.crawler.engine
            if engine is not None:
                in_flight = sum(
                    len(slot.active) for slot in engine.downloader.slots.values()
                )
                if in_flight > 0:
                    logger.debug(
                        "Activity timer expired but %d request(s) still in"
                        " flight — resetting stall timer",
                        in_flight,
                    )
                    self._last_activity = time.monotonic()
                    from twisted.internet import reactor

                    self._task = reactor.callLater(  # type: ignore[attr-defined]
                        self._check_interval, self._check_stall
                    )
                    return

            logger.warning(
                "Spider stalled for %.0fs — forcing shutdown",
                elapsed,
            )
            spider = self.crawler.spider
            if spider is None:
                logger.warning("Skipping stall shutdown because no spider is active")
                return
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
                # Auto-resume on stall: the underlying queue still has
                # pending URLs that the next process can pick up. Spawn
                # a detached scrapy process now so the crawl makes
                # progress without operator intervention.
                self._maybe_auto_resume(spider, run_id)

            engine.close_spider(spider, "stall_timeout")

            # Force-exit fallback: engine.close_spider drains the
            # pipeline before firing spider_closed. With a backed-up
            # PostgresPipeline that drain has been observed to take
            # 6+ minutes, blocking the auto-resume the whole time.
            # Schedule an os._exit fallback so we don't leave the
            # queue paused.
            force_exit_s = self.crawler.settings.getfloat("STALL_FORCE_EXIT_S", 0)
            if force_exit_s and force_exit_s > 0:
                from twisted.internet import reactor

                reactor.callLater(  # type: ignore[attr-defined]
                    force_exit_s, self._force_exit_after_stall
                )
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

        Delegates to the shared ``finalize_run_failsafe`` so all
        belt-and-suspenders close paths converge on one implementation
        (statement_timeout, exception swallowing, INFO log line).
        """
        from book_scraper.db.repo import finalize_run_failsafe

        database_url = self.crawler.settings.get("DATABASE_URL")
        finalize_run_failsafe(
            database_url, run_id, "failed", reason, resumable_after_failure=True
        )

    def _maybe_auto_resume(self, spider: Any, run_id: int) -> None:
        """Queue a deferred auto-resume; the actual spawn happens in
        ``spider_closed`` once the current spider has fully drained.

        Spawning earlier (here in `_check_stall`) leaves the dying
        spider's downloader still draining in-flight httpx requests
        for ~30s while a fresh spider boots up. Both run their own
        concurrency budget against the same backend, so the per-host
        rate is N×concurrency for the duration of the overlap and the
        StallDetector gets retriggered on the new spider almost
        immediately. By deferring to spider_closed we get clean
        single-spider-at-a-time semantics.
        """
        max_attempts = self.crawler.settings.getint("STALL_AUTO_RESUME_MAX", 0)
        if max_attempts <= 0:
            return

        shop_name = getattr(spider, "shop_name", None)
        if not shop_name:
            logger.warning(
                "Auto-resume: spider has no shop_name on run %d; skipping", run_id
            )
            return

        database_url = self.crawler.settings.get("DATABASE_URL")
        if not database_url:
            return

        from book_scraper.db.repo import (
            count_auto_resume_chain_depth,
            count_consecutive_zero_progress_resumes,
        )
        from book_scraper.db.session import get_session_factory

        try:
            session = get_session_factory(database_url)()
            try:
                depth = count_auto_resume_chain_depth(session, run_id)
                zero_progress = count_consecutive_zero_progress_resumes(session, run_id)
            finally:
                session.close()
        except Exception:
            logger.exception(
                "Auto-resume: chain-depth lookup failed for run %d", run_id
            )
            return

        # Circuit-break on consecutive zero-progress failures. Bug class:
        # patogupirkti runs 363→364→365 all died at heartbeat_timeout
        # with urls_processed=0 because the queue size starved the
        # reactor before any fetch landed. STALL_AUTO_RESUME_MAX caps
        # depth, but it still lets the same structural bug burn 3
        # attempts. If the previous run AND this run both finished
        # with 0 progress, the next attempt will too — bail now and
        # let an operator diagnose. Threshold = 2 (this run + 1
        # previous), which fires earlier than the depth cap (3) so the
        # user sees the structural-bug signal sooner.
        zero_progress_threshold = 2
        if zero_progress >= zero_progress_threshold:
            logger.warning(
                "Auto-resume circuit-break for run %d: %d consecutive "
                "zero-progress runs in the chain (threshold=%d). The "
                "bug is structural — operator must hit Continue after "
                "diagnosing.",
                run_id,
                zero_progress,
                zero_progress_threshold,
            )
            return

        if depth >= max_attempts:
            logger.warning(
                "Auto-resume cap reached for run %d (depth=%d, max=%d); "
                "leaving run failed. Operator can hit Continue on the "
                "dashboard to override.",
                run_id,
                depth,
                max_attempts,
            )
            return

        # Stash params for spider_closed to consume.
        self._pending_auto_resume = {
            "spider_name": getattr(spider, "name", "discover") or "discover",
            "shop": shop_name,
            "strategy": getattr(spider, "strategy", "") or "",
            "attempt": depth + 1,
            "max_attempts": max_attempts,
        }
        logger.warning(
            "Auto-resume queued for run %d (attempt %d/%d); spawn on spider_closed",
            run_id,
            depth + 1,
            max_attempts,
        )

    def _spawn_resume_subprocess(
        self,
        spider_name: str,
        shop: str,
        strategy: str,
        attempt: int,
        max_attempts: int,
    ) -> None:
        """Detach a `scrapy crawl …` subprocess after the current spider closes.

        Belt-and-suspenders: also checks the DB for an already-running
        run on the same shop+phase, in case spider_closed fired but a
        manual operator started another run in parallel. Without the
        check we'd produce two parallel spiders and double the load
        on the target host.
        """
        import os
        import shlex
        import subprocess

        # Belt-and-suspenders: don't spawn if the dashboard's preflight
        # would currently say "already running". Catches the operator-
        # races-with-StallDetector window.
        if self._another_run_active(shop, spider_name, strategy):
            logger.warning(
                "Auto-resume: another %s/%s run already active for %s; skipping spawn",
                spider_name,
                strategy or "—",
                shop,
            )
            return

        cmd_parts = [
            "/app/.venv/bin/scrapy",
            "crawl",
            spider_name,
            "-a",
            f"shop={shop}",
        ]
        if spider_name == "discover" and strategy:
            cmd_parts.extend(["-a", f"strategy={strategy}"])
        cmd = " ".join(shlex.quote(p) for p in cmd_parts)

        env = os.environ.copy()
        env.setdefault("PYTHONPATH", "/app")

        from book_scraper.spawn_logging import open_spawn_log

        log_fd, log_path = open_spawn_log("stall-resume", shop)
        try:
            try:
                subprocess.Popen(
                    cmd_parts,
                    cwd="/app",
                    env=env,
                    stdout=log_fd,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except Exception:
                logger.exception("Auto-resume: failed to spawn %s", cmd)
                return
        finally:
            log_fd.close()

        logger.warning(
            "Auto-resuming after stall: spawned %s (attempt %d/%d) — log=%s",
            cmd,
            attempt,
            max_attempts,
            log_path,
        )

    def _force_exit_after_stall(self) -> None:
        """If spider_closed hasn't fired by now, spawn the resume + os._exit.

        Scheduled via reactor.callLater(STALL_FORCE_EXIT_S) right after
        engine.close_spider is called. If the natural close path beat
        us to it, ``self._pending_auto_resume`` was already consumed
        by ``spider_closed`` and we have nothing to do. Otherwise the
        engine is still draining (typically a slow PostgresPipeline);
        fire the spawn ourselves and force-exit so the next spider
        can pick up the queue without waiting on this process.
        """
        if self._pending_auto_resume is None:
            return  # spider_closed already handled it; nothing to do
        params = self._pending_auto_resume
        self._pending_auto_resume = None
        logger.warning(
            "Force-exit fallback: spider_closed didn't fire within "
            "STALL_FORCE_EXIT_S; spawning resume + os._exit"
        )
        self._spawn_resume_subprocess(
            params["spider_name"],
            params["shop"],
            params["strategy"],
            params["attempt"],
            params["max_attempts"],
        )
        # Hard exit. atexit/finalisation skipped on purpose — the
        # dying spider can't make further useful progress and is
        # blocking the new spider's spawn from taking effect.
        import os

        os._exit(1)

    def _another_run_active(self, shop: str, spider_name: str, strategy: str) -> bool:
        """Is there already a running/stopping/paused run for this shop+phase?"""
        from book_scraper.db.models import ScrapeRun, Shop
        from book_scraper.db.session import get_session_factory

        database_url = self.crawler.settings.get("DATABASE_URL")
        if not database_url:
            return False

        if spider_name == "discover" and strategy:
            phase = f"discover_{strategy}"
        else:
            phase = spider_name

        try:
            session = get_session_factory(database_url)()
            try:
                exists = (
                    session.query(ScrapeRun.id)
                    .join(Shop, Shop.id == ScrapeRun.shop_id)
                    .filter(
                        Shop.name == shop,
                        ScrapeRun.phase == phase,
                        ScrapeRun.status.in_(("running", "stopping", "paused")),
                    )
                    .first()
                )
                return exists is not None
            finally:
                session.close()
        except Exception:
            logger.exception("Auto-resume: active-run check failed; skipping spawn")
            return True


class HeartbeatExtension:  # pragma: no cover
    """Tick `scrape_runs.last_heartbeat` every N seconds while a run is live.

    Hooks into Scrapy's built-in ``spider_opened`` signal (proven to
    deliver — StallDetector uses the same wiring). Earlier versions of
    this extension hooked a custom ``run_started`` signal so the run_id
    would be set when the handler fired; in practice that custom signal
    didn't deliver to this extension's bound method (the custom-signal
    + WeakMethod combination silently dropped the connection — see
    runs 188-190 with `last_heartbeat` frozen at row creation).

    Now we tick on a timer that starts at `spider_opened` and lazily
    reads ``spider._run_id`` on every tick. The first few ticks may
    fire before ``start()`` has assigned ``_run_id`` (the spider creates
    the run row inside ``start()``, after ``spider_opened`` has already
    been emitted). Those ticks are no-ops and reschedule.

    The actual heartbeat write runs in Twisted's worker thread pool via
    ``deferToThread`` — see ``_tick``. This keeps the reactor itself
    free of synchronous psycopg2 I/O so a hung DB call cannot freeze
    the event loop the way it did on runs 194/195. The heartbeat is
    the canary that proves the reactor is alive; making it dependent
    on reactor-thread DB calls would defeat its purpose.

    Independent of request flow, so a request hung in the downloader
    doesn't make the process look dead. Stops on ``spider_closed``.
    """

    def __init__(self, crawler: Crawler, interval: float):
        self.crawler = crawler
        self.interval = interval
        # Cached run_id once the spider has populated it. Used only as
        # a hint to the operator-stop callback path; the live source of
        # truth on each tick is `spider._run_id`.
        self._run_id: int | None = None
        self._task: Any = None
        self._session_factory: Any = None
        # Diagnostic: track when the last `_tick` actually fired (i.e.
        # the reactor unblocked enough to run our callLater). If a tick
        # fires more than ~2× interval after the previous one, the
        # reactor was starved — log a warning so reactor pressure
        # surfaces in normal logs *before* the dashboard reaper kills
        # the run. Patogupirkti runs 363–366 (2026-05-08) died from
        # exactly this pattern, but the only diagnostic was the run row
        # going `failed`.
        self._last_tick_at: float | None = None

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "HeartbeatExtension":
        interval = crawler.settings.getfloat("HEARTBEAT_INTERVAL_S", 5.0)
        if interval <= 0:
            raise NotConfigured
        ext = cls(crawler, interval)
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_opened(self) -> None:
        """Begin ticking. The first ticks may run before the spider's
        ``start()`` has assigned ``_run_id``; they are silent no-ops
        until run_id appears."""
        logger.info("HeartbeatExtension started (interval=%.1fs)", self.interval)
        self._schedule_next()

    # Back-compat: kept so existing unit tests still exercise the
    # write-immediately + schedule pattern. Production code no longer
    # depends on this — `spider_opened` schedules ticks regardless.
    def on_run_started(self, run_id: int, sender: Any = None, **kwargs: Any) -> None:
        self._run_id = run_id
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

    def _resolve_run_id(self) -> int | None:
        """Pull the current run_id from the live spider.

        Reads ``spider._run_id`` on every tick rather than caching, so
        we always have the latest value once ``start()`` populates it
        — without depending on a custom-signal handshake to deliver it.
        """
        spider = getattr(self.crawler, "spider", None)
        if spider is None:
            return None
        run_id = getattr(spider, "_run_id", None)
        if isinstance(run_id, int):
            self._run_id = run_id
            return run_id
        return None

    def _tick(self) -> None:
        """Schedule the heartbeat write on a worker thread.

        Why off-thread: ``_write_heartbeat`` does synchronous psycopg2 I/O.
        If it ran on the reactor thread (the natural place for callLater
        callbacks) and a query hung — postgres restart, dropped TCP, NAT
        idle reaper — the entire Twisted reactor would freeze for as
        long as the kernel takes to give up on the dead socket (often
        minutes). That freeze stops every other callLater, every HTTP
        response, and the StallDetector's own ticks — exactly the
        long-run stall pattern observed on runs 194/195.

        ``deferToThread`` runs the write in Twisted's worker pool. The
        reactor stays free to dispatch HTTP requests and fire other
        scheduled callbacks while the heartbeat is in flight.
        Callbacks (`_on_tick_done` / `_on_tick_failed`) fire back on the
        reactor thread, so `_schedule_next` and `_signal_stop` are safe
        to call there.
        """
        # Diagnostic: callLater is scheduled `interval` seconds out. If
        # this fires materially later than that, the reactor was busy
        # in synchronous code between scheduling and now — which is the
        # exact failure pattern that killed runs 363–366. Surface it.
        import time as _time

        now = _time.monotonic()
        if self._last_tick_at is not None:
            gap = now - self._last_tick_at
            if gap > 2 * self.interval:
                logger.warning(
                    "HeartbeatExtension: tick fired %.1fs after the "
                    "previous one (interval=%.1fs). The reactor was "
                    "starved — likely synchronous I/O blocking the "
                    "event loop. If this keeps happening the dashboard "
                    "reaper will kill the run.",
                    gap,
                    self.interval,
                )
        self._last_tick_at = now

        run_id = self._resolve_run_id()
        if run_id is None:
            # spider hasn't assigned _run_id yet — no-op, try again next tick.
            self._schedule_next()
            return
        from twisted.internet.threads import deferToThread

        d = deferToThread(self._write_heartbeat, run_id)  # type: ignore[no-untyped-call]
        d.addCallbacks(self._on_tick_done, self._on_tick_failed)

    def _on_tick_done(self, status: str | None) -> None:
        # Worker-thread result lands here on the reactor thread.
        if status is None:
            # Row vanished (deleted by operator, or by a parallel cleanup).
            # The spider has no live row to refresh — tear it down so the
            # process exits cleanly instead of ghost-ticking forever
            # (CODEOBS-03). Use a distinct close reason so the postmortem
            # tells "operator deleted my row" from "operator pressed Stop".
            logger.warning(
                "Heartbeat tick: scrape_runs row for run %d vanished — tearing down spider",
                self._run_id,
            )
            self._signal_stop_with_reason("row_vanished")
            return
        if status == "stopping":
            self._signal_stop()
            return
        # 'paused': heartbeat keeps ticking so the reaper doesn't kill
        # the run. The spider's start() loop handles the actual wait.
        self._schedule_next()

    def _on_tick_failed(self, failure: Any) -> None:
        # Worker-thread exceptions surface here as a Twisted Failure.
        # Log and reschedule so the loop stays alive — a one-off DB
        # blip must not silently kill the heartbeat.
        logger.error(
            "Heartbeat write failed: %s",
            failure.getErrorMessage()
            if hasattr(failure, "getErrorMessage")
            else failure,
        )
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
        logger.info("Run %d transitioned to 'stopping' — closing spider", self._run_id)
        engine.close_spider(spider, "stopped_by_operator")

    def _signal_stop_with_reason(self, reason: str) -> None:
        """Close the spider with a specific reason. Used by CODEOBS-03 to
        distinguish row-vanished from operator-requested stop."""
        spider = getattr(self.crawler, "spider", None)
        engine = getattr(self.crawler, "engine", None)
        if spider is None or engine is None:
            logger.warning(
                "Heartbeat saw '%s' for run %d but spider/engine missing",
                reason,
                self._run_id,
            )
            return
        logger.info("Run %d closing with reason '%s'", self._run_id, reason)
        engine.close_spider(spider, reason)

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
            # Tick on 'running' and 'paused' — a paused run is alive and
            # must not be reaped. Skip 'stopping'/'failed'/'completed'.
            session.execute(
                sa_text(
                    "UPDATE scrape_runs SET last_heartbeat = now() "
                    "WHERE id = :run_id AND status IN ('running', 'paused')"
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


class CronChainTrigger:  # pragma: no cover
    """After a cron-scheduled run finishes successfully, spawn the chained job."""

    def __init__(self, crawler: Crawler) -> None:
        self.crawler = crawler
        self._cron_job_id: int | None = None

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> "CronChainTrigger":
        ext = cls(crawler)
        crawler.signals.connect(ext.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(ext.spider_closed, signal=signals.spider_closed)
        return ext

    def spider_opened(self, spider: Any) -> None:
        raw = getattr(spider, "cron_job_id", None)
        try:
            self._cron_job_id = int(raw) if raw is not None else None
        except (TypeError, ValueError):
            self._cron_job_id = None

    def spider_closed(self, spider: Any, reason: str) -> None:
        if reason != "finished":
            return
        if self._cron_job_id is None:
            return
        this_job, chain_job = self._get_chain_job(self._cron_job_id)
        if chain_job is None:
            return
        self._spawn_chain_subprocess(
            phase=chain_job.phase,
            shop=chain_job.shop.name,
            strategy=chain_job.strategy,
            args=chain_job.args or "",
            chain_job_id=chain_job.id,
        )

    def _get_chain_job(self, cron_job_id: int) -> tuple[Any, Any]:
        from book_scraper.db.models import CronJob
        from book_scraper.db.session import get_session_factory

        database_url = self.crawler.settings.get("DATABASE_URL")
        if not database_url:
            return None, None
        try:
            session = get_session_factory(database_url)()
            try:
                this_job = session.get(CronJob, cron_job_id)
                if this_job is None or not this_job.chain_to_job_id:
                    return this_job, None
                chain_job = session.get(CronJob, this_job.chain_to_job_id)
                if chain_job is not None:
                    _ = chain_job.shop.name  # eagerly load while session is open
                return this_job, chain_job
            finally:
                session.close()
        except Exception:
            logger.exception(
                "CronChainTrigger: DB lookup failed for cron_job_id=%d", cron_job_id
            )
            return None, None

    def _spawn_chain_subprocess(
        self,
        *,
        phase: str,
        shop: str,
        strategy: str | None,
        args: str,
        chain_job_id: int,
    ) -> None:
        import os
        import shlex
        import subprocess

        cmd_parts = ["/app/.venv/bin/scrapy", "crawl", phase, "-a", f"shop={shop}"]
        if phase == "discover" and strategy:
            cmd_parts.extend(["-a", f"strategy={strategy}"])
        cmd_parts.extend(["-a", f"cron_job_id={chain_job_id}"])
        if args:
            cmd_parts.extend(shlex.split(args))

        env = os.environ.copy()
        env.setdefault("PYTHONPATH", "/app")
        cmd_str = " ".join(shlex.quote(p) for p in cmd_parts)

        from book_scraper.spawn_logging import open_spawn_log

        log_fd, log_path = open_spawn_log("cron-chain", shop)
        try:
            try:
                subprocess.Popen(
                    cmd_parts,
                    cwd="/app",
                    env=env,
                    stdout=log_fd,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except Exception:
                logger.exception("CronChainTrigger: failed to spawn %s", cmd_str)
                return
        finally:
            log_fd.close()

        logger.info(
            "CronChainTrigger: spawned chain job %d → %s (cron_job_id=%d, log=%s)",
            self._cron_job_id or -1,
            cmd_str,
            chain_job_id,
            log_path,
        )
