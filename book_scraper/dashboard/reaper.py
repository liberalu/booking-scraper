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
    """Run mark_stale_runs every REAPER_INTERVAL_SECONDS until cancelled."""
    while True:
        try:
            session = _session_factory()
            try:
                marked = mark_stale_runs(session)
                if marked:
                    logger.info("Reaper marked %d stale run(s) failed", marked)
            finally:
                session.close()
        except Exception:
            logger.exception("Reaper iteration failed")
        try:
            await asyncio.sleep(REAPER_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            return
