from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from book_scraper.db.models import DiscoveredUrl
from book_scraper.db.repo import (
    check_discover_freshness,
    create_scrape_run,
    finish_scrape_run,
    get_pending_scan_urls,
    get_urls_already_scraped,
    mark_stale_runs_failed,
    update_discovered_url_status,
    update_scrape_run_progress,
    upsert_shop,
)


@dataclass
class ScanPlan:
    run_id: int
    urls_to_scrape: list[DiscoveredUrl]
    urls_skipped: int
    freshness_warnings: list[str] = field(default_factory=list)


class ScanService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def prepare_scan(
        self,
        shop_name: str,
        base_url: str,
        shop_config: dict[str, Any],
    ) -> ScanPlan:
        """Prepare a scan run: upsert shop, mark stale, check freshness,
        load pending URLs, filter already done, create run."""
        shop = upsert_shop(self.session, shop_name, base_url)

        mark_stale_runs_failed(self.session, shop.id, "scan")

        discover_config = shop_config.get("discover", {})
        warnings = check_discover_freshness(
            self.session, shop.id, shop_name, discover_config
        )

        pending_urls = get_pending_scan_urls(self.session, shop.id)

        already_done = get_urls_already_scraped(self.session, shop.id)
        urls_to_scrape = [u for u in pending_urls if u.url not in already_done]
        urls_skipped = len(pending_urls) - len(urls_to_scrape)

        run = create_scrape_run(
            self.session, shop.id, "scan", urls_total=len(urls_to_scrape)
        )
        self.session.commit()

        return ScanPlan(
            run_id=run.id,
            urls_to_scrape=urls_to_scrape,
            urls_skipped=urls_skipped,
            freshness_warnings=warnings,
        )

    def flush_progress(
        self,
        run_id: int,
        urls_processed: int,
        url_status_updates: list[dict[str, Any]],
    ) -> None:
        """Flush queued URL status updates and progress to DB mid-run."""
        for update in url_status_updates:
            update_discovered_url_status(self.session, **update)
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
            update_discovered_url_status(self.session, **update)

        status = "completed" if reason == "finished" else "failed"
        update_scrape_run_progress(self.session, run_id, urls_processed)
        finish_scrape_run(self.session, run_id, status)
        self.session.commit()
