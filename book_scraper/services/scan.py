from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from book_scraper.db.models import ScrapeRun, ScrapeUrlItem
from book_scraper.db.repo import (
    check_discover_freshness,
    cleanup_scrape_url_items,
    create_scrape_run,
    find_resumable_run,
    finish_scrape_run,
    get_pending_scan_urls,
    get_urls_already_scraped,
    insert_scrape_url_item,
    mark_cron_job_ran_if_matches,
    mark_scrape_url_item_done,
    mark_scrape_url_item_failed,
    mark_stale_runs_failed,
    prepare_scrape_url_items,
    update_discovered_url_status,
    update_scrape_run_progress,
    upsert_shop,
)


@dataclass
class ScanPlan:
    run_id: int
    urls_total: int
    urls_skipped: int
    freshness_warnings: list[str] = field(default_factory=list)


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
        """Prepare a scan run.

        If a previous 'running' run with pending scrape_url_items exists for
        this shop, resume it (return its run_id, keep the queue). Otherwise
        mark stale runs failed, create a new run, and populate the queue.
        """
        shop = upsert_shop(self.session, shop_name, base_url)

        resumable = find_resumable_run(self.session, shop.id, "scan")
        if resumable is not None:
            pending_count = (
                self.session.query(ScrapeUrlItem)
                .filter_by(run_id=resumable.id, status="pending")
                .count()
            )
            return ScanPlan(
                run_id=resumable.id,
                urls_total=pending_count,
                urls_skipped=0,
                freshness_warnings=[],
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
            self.session, shop.id, "scan", urls_total=len(urls_to_scrape)
        )
        # Persist work queue to DB for crash recovery
        prepare_scrape_url_items(self.session, shop.id, run.id, urls_to_scrape)
        self.session.commit()

        return ScanPlan(
            run_id=run.id,
            urls_total=len(urls_to_scrape),
            urls_skipped=urls_skipped,
            freshness_warnings=warnings,
        )

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
        """Flush queued URL status updates and progress to DB mid-run."""
        for update in url_status_updates:
            scrape_item_id = update.pop("scrape_url_item_id", None)
            scrape_item_success = update.pop("scrape_url_item_success", False)
            update_discovered_url_status(self.session, **update)
            if scrape_item_id is not None:
                if scrape_item_success:
                    mark_scrape_url_item_done(self.session, scrape_item_id)
                else:
                    mark_scrape_url_item_failed(self.session, scrape_item_id)
        update_scrape_run_progress(self.session, run_id, urls_processed)
        self.session.commit()

    def finish_scan(
        self,
        run_id: int,
        urls_processed: int,
        url_status_updates: list[dict[str, Any]],
        reason: str,
    ) -> None:
        """Finalize a scan run: process URL status updates, update progress,
        mark run as completed/failed."""
        for update in url_status_updates:
            scrape_item_id = update.pop("scrape_url_item_id", None)
            scrape_item_success = update.pop("scrape_url_item_success", False)
            update_discovered_url_status(self.session, **update)
            if scrape_item_id is not None:
                if scrape_item_success:
                    mark_scrape_url_item_done(self.session, scrape_item_id)
                else:
                    mark_scrape_url_item_failed(self.session, scrape_item_id)

        status = "completed" if reason == "finished" else "failed"
        update_scrape_run_progress(self.session, run_id, urls_processed)
        finish_scrape_run(self.session, run_id, status)

        # Update matching cron_job's last_run_at (best-effort; no-op if no match).
        run_row = self.session.get(ScrapeRun, run_id)
        if run_row is not None:
            mark_cron_job_ran_if_matches(
                self.session, run_row.shop_id, phase="scan", strategy=None
            )

        cleanup_scrape_url_items(self.session, run_id)
        self.session.commit()
