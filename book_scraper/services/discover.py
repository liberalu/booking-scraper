"""DiscoverService: owns prepare + finish for the three discover strategies.

Analogous to ScanService. Seeds scrape_url_items with strategy-specific
starting URLs; the discover spider consumes the queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from book_scraper.db import scrape_run_events as run_event_types
from book_scraper.db.models import ScrapeRunEvent, ScrapeUrlItem
from book_scraper.db.repo import (
    create_scrape_run,
    find_resumable_run,
    finish_scrape_run,
    insert_scrape_url_item,
    mark_cron_job_ran_if_matches,
    mark_stale_runs_failed,
    restart_run_in_place,
    update_scrape_run_progress,
    upsert_shop,
)

_STRATEGY_URL_TYPE = {
    "sitemap": "sitemap",
    "categories": "category_page",
    "full_crawl": "crawl",
    "graphql": "category_page",
    "lupasearch": "lupasearch_page",
    "ibiblioteka_api": "ibiblioteka_page",
}


@dataclass
class DiscoverPlan:
    run_id: int
    shop_id: int
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
            # Running run: reuse the same row (queue already owned).
            if resumable.status == "running":
                self.session.commit()
                return DiscoverPlan(
                    run_id=resumable.id, shop_id=shop.id, urls_total=pending
                )
            # Failed-but-resumable run: mutate same row back to running.
            attempt_number = (
                self.session.query(ScrapeRunEvent)
                .filter(
                    ScrapeRunEvent.run_id == resumable.id,
                    ScrapeRunEvent.event_type == run_event_types.RESTARTED,
                )
                .count()
                + 1
            )
            restart_run_in_place(
                self.session,
                resumable,
                payload={
                    "previous_close_reason": resumable.close_reason,
                    "attempt": attempt_number,
                    "urls_processed_snapshot": resumable.urls_processed,
                    "strategy": strategy,
                },
                actor=run_event_types.ACTOR_SYSTEM,
            )
            self.session.commit()
            return DiscoverPlan(
                run_id=resumable.id, shop_id=shop.id, urls_total=pending
            )

        mark_stale_runs_failed(self.session, shop.id, phase)

        run = create_scrape_run(
            self.session, shop.id, phase, extra_payload={"strategy": strategy}
        )

        seed_urls = self._seed_urls(strategy, shop_config)
        url_type = _STRATEGY_URL_TYPE[strategy]
        for url in seed_urls:
            insert_scrape_url_item(
                self.session,
                run_id=run.id,
                shop_id=shop.id,
                discovered_url_id=None,
                url=url,
                url_type=url_type,
            )
        self.session.commit()

        return DiscoverPlan(run_id=run.id, shop_id=shop.id, urls_total=len(seed_urls))

    @classmethod
    def _seed_urls(cls, strategy: str, shop_config: Any) -> list[str]:
        """Strategy-specific seed URLs. Always a list so prepare_discover
        can enqueue multiple page-1 entries (humanitas combines two
        language filters; other strategies emit a one-element list)."""
        if strategy == "categories":
            return cls._categories_seed_urls(shop_config)
        if strategy == "ibiblioteka_api":
            return cls._ibiblioteka_seed_urls(shop_config)
        return [cls._seed_url(strategy, shop_config)]

    @staticmethod
    def _ibiblioteka_seed_urls(shop_config: Any) -> list[str]:
        from book_scraper.spiders.ibiblioteka_api_urls import (
            build_ibiblioteka_seed_urls,
        )

        discover_cfg = (
            shop_config.discover
            if hasattr(shop_config, "discover")
            else shop_config["discover"]
        )
        ibiblioteka_cfg = (
            discover_cfg.ibiblioteka_api
            if hasattr(discover_cfg, "ibiblioteka_api")
            else discover_cfg["ibiblioteka_api"]
        )
        return build_ibiblioteka_seed_urls(ibiblioteka_cfg)

    @staticmethod
    def _categories_seed_urls(shop_config: Any) -> list[str]:
        discover_cfg = (
            shop_config.discover
            if hasattr(shop_config, "discover")
            else shop_config["discover"]
        )
        cats_cfg = (
            discover_cfg.categories
            if hasattr(discover_cfg, "categories")
            else discover_cfg["categories"]
        )
        # Pydantic model exposes `url_templates()` returning a list;
        # raw-dict fallback handles `url: str | list[str]`.
        if hasattr(cats_cfg, "url_templates"):
            templates: list[str] = cats_cfg.url_templates()
        else:
            raw = cats_cfg["url"]
            templates = [raw] if isinstance(raw, str) else list(raw)
        return [t.format(page=1) for t in templates]

    @staticmethod
    def _seed_url(strategy: str, shop_config: Any) -> str:
        discover_cfg = (
            shop_config.discover
            if hasattr(shop_config, "discover")
            else shop_config["discover"]
        )
        if strategy == "sitemap":
            url: str = (
                discover_cfg.sitemap.url
                if hasattr(discover_cfg, "sitemap")
                else discover_cfg["sitemap"]["url"]
            )
            return url
        if strategy == "categories":
            # Kept for backwards-compat call sites and unit tests; the
            # production path now goes through `_categories_seed_urls`
            # which can return >1 templates. This shim returns the
            # first element (matches old single-URL behaviour).
            return DiscoverService._categories_seed_urls(shop_config)[0]
        if strategy == "full_crawl":
            start_url: str = (
                discover_cfg.full_crawl.start_url
                if hasattr(discover_cfg, "full_crawl")
                else discover_cfg["full_crawl"]["start_url"]
            )
            return start_url
        if strategy == "graphql":
            gql_cfg = (
                discover_cfg.graphql
                if hasattr(discover_cfg, "graphql")
                else discover_cfg["graphql"]
            )
            from book_scraper.spiders.graphql_urls import build_graphql_page_url

            base_url = (
                shop_config.shop.base_url
                if hasattr(shop_config, "shop")
                else shop_config["shop"]["base_url"]
            )
            return build_graphql_page_url(base_url, gql_cfg, page=1)
        if strategy == "lupasearch":
            ls_cfg = (
                discover_cfg.lupasearch
                if hasattr(discover_cfg, "lupasearch")
                else discover_cfg["lupasearch"]
            )
            from book_scraper.spiders.lupasearch_urls import (
                build_lupasearch_seed_url,
            )

            return build_lupasearch_seed_url(ls_cfg)
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
        finish_scrape_run(self.session, run_id, status, reason=reason)

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

        self.session.commit()
