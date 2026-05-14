"""Background reaper that periodically fails zombie scrape runs.

Same code path as `/runs` page load (`mark_stale_runs`), but on a timer
so a zombie row doesn't linger until someone visits the dashboard.
"""

import asyncio
import logging
import os

from book_scraper.dashboard.deps import _session_factory
from book_scraper.dashboard.queries import mark_stale_runs

logger = logging.getLogger(__name__)

REAPER_INTERVAL_SECONDS = int(os.environ.get("REAPER_INTERVAL_SECONDS", "30"))


async def reaper_loop() -> None:
    """Run mark_stale_runs every REAPER_INTERVAL_SECONDS until cancelled.

    Per killed run, emits one WARNING log line carrying run_id, shop, phase,
    close_reason. The Grafana "Scrape runs overview" dashboard surfaces
    these via the dashboard-logs panel — operators can grep `Reaper killed
    run` to find every reaping in the time range.
    """
    while True:
        try:
            session = _session_factory()
            try:
                killed = mark_stale_runs(session)
                for k in killed:
                    logger.warning(
                        "Reaper killed run #%d shop=%s phase=%s close_reason=%s",
                        k["run_id"], k["shop"], k["phase"], k["close_reason"],
                    )
                if killed:
                    logger.info("Reaper iteration: %d run(s) killed", len(killed))
            finally:
                session.close()
        except Exception:
            logger.exception("Reaper iteration failed")
        try:
            await asyncio.sleep(REAPER_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            return
