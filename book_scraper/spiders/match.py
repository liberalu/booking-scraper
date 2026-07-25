"""Match phase spider.

Thin wrapper around MatchService — the run lifecycle (create run, heartbeat
ordering, off-reactor dispatch, finish, close failsafe) lives in
ServiceSpider. All this adds is the service call and propagating the update
count onto the run row.
"""

from __future__ import annotations

from typing import Any

from book_scraper.db.models import ScrapeRun
from book_scraper.services.match import MatchService
from book_scraper.spiders.service_spider import ServiceSpider


class MatchSpider(ServiceSpider):
    name = "match"
    phase = "match"

    def run_service(self, session: Any, shop_id: int, run_id: int) -> Any:
        return MatchService(session).run(self.shop_name)

    def finalize_result(self, session: Any, run_id: int, result: Any) -> None:
        """Record how many shop_books the match phase linked."""
        run = session.get(ScrapeRun, run_id)
        if run is not None and result is not None:
            run.items_updated = result.total_updates
