"""DiscoverService: owns prepare + finish for the three discover strategies.

Analogous to ScanService. Seeds scrape_url_items with strategy-specific
starting URLs; the discover spider consumes the queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from book_scraper.db.models import ScrapeUrlItem
from book_scraper.db.repo import (
    cleanup_scrape_url_items,
    create_scrape_run,
    find_resumable_run,
    finish_scrape_run,
    insert_scrape_url_item,
    mark_cron_job_ran_if_matches,
    mark_stale_runs_failed,
    update_scrape_run_progress,
    upsert_shop,
)


_STRATEGY_URL_TYPE = {
    "sitemap": "sitemap",
    "categories": "category_page",
    "full_crawl": "crawl",
}


@dataclass
class DiscoverPlan:
    run_id: int
    urls_total: int
    freshness_warnings: list[str] = field(default_factory=list)


class DiscoverService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def prepare_discover(
        self,
        shop_name: str,
        base_url: str,
        strategy: str,
        shop_config: Any,
    ) -> DiscoverPlan:
        """Prepare a discover run for the given strategy.

        Resume an existing running run with pending items if one exists;
        otherwise create a new run and seed the queue with the strategy's
        starting URL.
        """
        if strategy not in _STRATEGY_URL_TYPE:
            raise ValueError(f"Unknown discover strategy: {strategy}")
        phase = f"discover_{strategy}"

        shop = upsert_shop(self.session, shop_name, base_url)

        resumable = find_resumable_run(self.session, shop.id, phase)
        if resumable is not None:
            pending = (
                self.session.query(ScrapeUrlItem)
                .filter_by(run_id=resumable.id, status="pending")
                .count()
            )
            return DiscoverPlan(run_id=resumable.id, urls_total=pending)

        mark_stale_runs_failed(self.session, shop.id, phase)

        run = create_scrape_run(self.session, shop.id, phase)

        seed_url = self._seed_url(strategy, shop_config)
        url_type = _STRATEGY_URL_TYPE[strategy]
        insert_scrape_url_item(
            self.session,
            run_id=run.id,
            shop_id=shop.id,
            discovered_url_id=None,
            url=seed_url,
            url_type=url_type,
        )
        self.session.commit()

        return DiscoverPlan(run_id=run.id, urls_total=1)

    @staticmethod
    def _seed_url(strategy: str, shop_config: Any) -> str:
        discover_cfg = (
            shop_config.discover
            if hasattr(shop_config, "discover")
            else shop_config["discover"]
        )
        if strategy == "sitemap":
            return (
                discover_cfg.sitemap.url
                if hasattr(discover_cfg, "sitemap")
                else discover_cfg["sitemap"]["url"]
            )
        if strategy == "categories":
            tmpl = (
                discover_cfg.categories.url
                if hasattr(discover_cfg, "categories")
                else discover_cfg["categories"]["url"]
            )
            return tmpl.format(page=1)
        if strategy == "full_crawl":
            return (
                discover_cfg.full_crawl.start_url
                if hasattr(discover_cfg, "full_crawl")
                else discover_cfg["full_crawl"]["start_url"]
            )
        raise ValueError(f"Unknown strategy: {strategy}")

    def finish_discover(
        self,
        run_id: int,
        urls_processed: int,
        reason: str,
    ) -> None:
        """Mark run completed/failed, update last_run_at on matching cron_job,
        delete staging rows."""
        from book_scraper.db.models import ScrapeRun

        status = "completed" if reason == "finished" else "failed"
        update_scrape_run_progress(self.session, run_id, urls_processed)
        finish_scrape_run(self.session, run_id, status)

        run_row = self.session.get(ScrapeRun, run_id)
        if run_row is not None:
            strategy = (
                run_row.phase.removeprefix("discover_")
                if run_row.phase.startswith("discover_")
                else None
            )
            mark_cron_job_ran_if_matches(
                self.session, run_row.shop_id, phase="discover", strategy=strategy
            )

        cleanup_scrape_url_items(self.session, run_id)
        self.session.commit()
