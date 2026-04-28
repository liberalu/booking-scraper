from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from book_scraper.db import run_events as run_event_types
from book_scraper.db.models import ScrapeRun, ScrapeUrlItem
from book_scraper.db.repo import (
    check_discover_freshness,
    create_scrape_run,
    emit_run_event,
    find_resumable_run,
    finish_scrape_run,
    get_pending_scan_urls,
    get_urls_already_scraped,
    inherit_pending_items,
    insert_scrape_url_item,
    mark_cron_job_ran_if_matches,
    mark_stale_runs_failed,
    prepare_scrape_url_items,
    try_acquire_scan_lock,
    update_discovered_url_status,
    update_scrape_run_progress,
    upsert_shop,
    upsert_url_classification,
)


@dataclass
class ScanPlan:
    run_id: int
    urls_total: int
    urls_skipped: int
    freshness_warnings: list[str] = field(default_factory=list)
    # Deferred queue-population payload. None when the plan resolves to a
    # resumable run (queue already populated) or when the lock could not
    # be acquired. The spider populates the queue after `prepare_scan`
    # so that the HeartbeatExtension's tick loop (started at
    # `spider_opened`) is already running before the slow row-insert
    # begins.
    _shop_id: int | None = None
    _urls_to_scrape: list[Any] | None = None
    # When the lock for (shop_id, "scan") can't be acquired because
    # another scrapy process owns the active run, this is True and the
    # spider should exit cleanly.
    lock_not_acquired: bool = False
    # When `find_resumable_run` returned a previously-failed run flagged
    # `resumable_after_failure`, this carries that run's id; the spider
    # should re-point its pending items to the new run before yielding.
    _inherit_from_run_id: int | None = None


class ScanService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def prepare_scan(
        self,
        shop_name: str,
        base_url: str,
        shop_config: Any,
        rescrape: bool = False,
    ) -> ScanPlan:
        """Prepare a scan run end-to-end (create run + populate queue).

        Convenience wrapper kept for callers that don't need the heartbeat
        blackout fix (tests, non-spider invocations). The spider uses the
        two-phase API: ``prepare_scan_create_run`` then
        ``populate_scan_queue``.
        """
        plan = self.prepare_scan_create_run(
            shop_name, base_url, shop_config, rescrape=rescrape
        )
        if plan.lock_not_acquired:
            return plan
        self.populate_scan_queue(plan)
        return plan

    def prepare_scan_create_run(
        self,
        shop_name: str,
        base_url: str,
        shop_config: Any,
        rescrape: bool = False,
    ) -> ScanPlan:
        """Phase 1: acquire the shop+phase lock and create a fresh run row.

        Resolves to either a resumable run (queue already populated, no
        further work) or a fresh run with a deferred queue (plan carries
        the URL list for ``populate_scan_queue``).

        Why split: the queue insert can take 30+ seconds on cold cache.
        Phase 1 returns control to the spider before the insert so the
        HeartbeatExtension (already ticking on a `spider_opened` timer)
        can pick up the new ``_run_id`` and refresh ``last_heartbeat``
        before the dashboard reaper threshold trips.
        """
        shop = upsert_shop(self.session, shop_name, base_url)

        # Acquire advisory lock keyed on (shop_id, "scan"). Held for the
        # duration of this transaction; released on commit. Two scrapy
        # processes hitting this concurrently: one wins, one returns
        # lock_not_acquired and exits cleanly upstream.
        if not try_acquire_scan_lock(self.session, shop.id, "scan"):
            return ScanPlan(
                run_id=0,
                urls_total=0,
                urls_skipped=0,
                lock_not_acquired=True,
            )

        resumable = find_resumable_run(self.session, shop.id, "scan")
        if resumable is not None:
            pending_count = (
                self.session.query(ScrapeUrlItem)
                .filter_by(run_id=resumable.id, status="pending")
                .count()
            )
            # Resumable-running run: reuse the row outright.
            if resumable.status == "running":
                self.session.commit()
                return ScanPlan(
                    run_id=resumable.id,
                    urls_total=pending_count,
                    urls_skipped=0,
                    freshness_warnings=[],
                )
            # Resumable-failed run (heartbeat_timeout / stall_timeout):
            # spawn a fresh run row that inherits the failed run's pending
            # queue. Old run stays `failed` for postmortem.
            run = create_scrape_run(
                self.session,
                shop.id,
                "scan",
                urls_total=pending_count,
                extra_payload={"rescrape": rescrape},
            )
            emit_run_event(
                self.session,
                run.id,
                run_event_types.RESUMED_AFTER_FAILURE,
                payload={"previous_run_id": resumable.id},
                actor=run_event_types.ACTOR_SYSTEM,
            )
            self.session.commit()
            return ScanPlan(
                run_id=run.id,
                urls_total=pending_count,
                urls_skipped=0,
                freshness_warnings=[],
                _inherit_from_run_id=resumable.id,
            )

        mark_stale_runs_failed(self.session, shop.id, "scan")

        # Support both typed ShopConfig and dict for backward compat in tests
        if isinstance(shop_config, dict):
            discover_config = shop_config.get("discover", {})
        else:
            discover_config = shop_config.discover
        warnings = check_discover_freshness(
            self.session, shop.id, shop_name, discover_config
        )

        pending_urls = get_pending_scan_urls(self.session, shop.id)

        if rescrape:
            urls_to_scrape = pending_urls
            urls_skipped = 0
        else:
            already_done = get_urls_already_scraped(self.session, shop.id)
            urls_to_scrape = [u for u in pending_urls if u.url not in already_done]
            urls_skipped = len(pending_urls) - len(urls_to_scrape)

        run = create_scrape_run(
            self.session,
            shop.id,
            "scan",
            urls_total=len(urls_to_scrape),
            extra_payload={"rescrape": rescrape, "urls_skipped": urls_skipped},
        )
        # Commit so the run row + heartbeat are visible to the reaper
        # before the (potentially slow) queue insert begins.
        self.session.commit()

        return ScanPlan(
            run_id=run.id,
            urls_total=len(urls_to_scrape),
            urls_skipped=urls_skipped,
            freshness_warnings=warnings,
            _shop_id=shop.id,
            _urls_to_scrape=urls_to_scrape,
        )

    def populate_scan_queue(self, plan: ScanPlan) -> None:
        """Phase 2: insert scrape_url_items rows for the plan.

        No-op when the plan is for a resumable-running run (queue already
        populated) or when the lock was not acquired. When the plan
        carries `_inherit_from_run_id`, re-points pending items from the
        failed predecessor instead of inserting fresh rows.
        """
        if plan.lock_not_acquired:
            return
        if plan._inherit_from_run_id is not None:
            inherit_pending_items(self.session, plan._inherit_from_run_id, plan.run_id)
            self.session.commit()
            return
        if plan._urls_to_scrape is None or plan._shop_id is None:
            # Resumable-running fast path — queue already there.
            return
        prepare_scrape_url_items(
            self.session, plan._shop_id, plan.run_id, plan._urls_to_scrape
        )
        self.session.commit()

    def enqueue_new_url(
        self,
        run_id: int,
        shop_id: int,
        discovered_url_id: int | None,
        url: str,
        url_type: str = "product",
    ) -> int:
        """Queue a newly-discovered URL for same-run processing. Returns item id.

        Does NOT commit — caller (pipeline) controls commit cadence. The row
        becomes visible to the spider's fresh spider_idle session only after
        the caller commits.

        Phase 1 scope: currently only called when a ``DiscoveredUrlItem`` is
        processed by the pipeline in rescrape mode. The scan spider does not
        yet emit ``DiscoveredUrlItem``s — activating the second-pass path
        fully requires Phase 2 work (scan parsers extracting internal product
        links). The infrastructure (this function, ``insert_scrape_url_item``,
        the ``spider_idle`` handler on ``ScanSpider``) is ready.
        """
        item = insert_scrape_url_item(
            self.session, run_id, shop_id, discovered_url_id, url, url_type
        )
        self.session.flush()
        return item.id

    def flush_progress(
        self,
        run_id: int,
        urls_processed: int,
        url_status_updates: list[dict[str, Any]],
    ) -> None:
        """Flush queued discovered_url + classification updates and run progress.

        Per the live observability spec, this method no longer writes
        scrape_url_items terminal state — that's owned by the spider's
        immediate `_mark_response` path. This method now only touches
        `discovered_urls`, `url_classifications`, and `scrape_runs`
        aggregate counters.
        """
        for update in url_status_updates:
            book_score = update.pop("book_score", None)
            is_book_product = update.pop("is_book_product", None)
            book_score_reasons = update.pop("book_score_reasons", None)
            update_discovered_url_status(self.session, **update)
            if (
                book_score is not None
                and is_book_product is not None
                and update.get("url_id") is not None
            ):
                upsert_url_classification(
                    self.session,
                    discovered_url_id=update["url_id"],
                    book_score=book_score,
                    is_book_product=is_book_product,
                    reasons=book_score_reasons or [],
                )
        update_scrape_run_progress(self.session, run_id, urls_processed)
        self.session.commit()

    def finish_scan(
        self,
        run_id: int,
        urls_processed: int,
        url_status_updates: list[dict[str, Any]],
        reason: str,
    ) -> None:
        """Finalize a scan run.

        Same ownership split as `flush_progress`: this drains the batch
        of `discovered_urls` + classification updates and finalises the
        run row. Per-URL terminal state on `scrape_url_items` is already
        owned by the spider's `_mark_response`.
        """
        for update in url_status_updates:
            book_score = update.pop("book_score", None)
            is_book_product = update.pop("is_book_product", None)
            book_score_reasons = update.pop("book_score_reasons", None)
            update_discovered_url_status(self.session, **update)
            if (
                book_score is not None
                and is_book_product is not None
                and update.get("url_id") is not None
            ):
                upsert_url_classification(
                    self.session,
                    discovered_url_id=update["url_id"],
                    book_score=book_score,
                    is_book_product=is_book_product,
                    reasons=book_score_reasons or [],
                )

        status = "completed" if reason == "finished" else "failed"
        update_scrape_run_progress(self.session, run_id, urls_processed)
        finish_scrape_run(self.session, run_id, status, reason=reason)

        # Update matching cron_job's last_run_at (best-effort; no-op if no match).
        run_row = self.session.get(ScrapeRun, run_id)
        if run_row is not None:
            mark_cron_job_ran_if_matches(
                self.session, run_row.shop_id, phase="scan", strategy=None
            )

        # NOTE: scrape_url_items rows are kept after the run finishes —
        # they are the source of truth for per-URL run history, surfaced
        # on the run detail page. Used to be deleted via cleanup_scrape_url_items.
        self.session.commit()
