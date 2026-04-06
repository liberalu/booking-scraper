"""Health check: exits 0 if scan is progressing, 1 if stalled.

Used by Docker HEALTHCHECK to detect stuck scrapers.
Checks if urls_processed changed since last check by comparing
against a timestamp file.
"""

import json
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text

STALE_FILE = Path("/tmp/scan_health.json")
STALL_SECONDS = 120  # unhealthy if no progress for 2 minutes
DB_URL = "postgresql://postgres:postgres@postgres:5432/book_scraper"


def main() -> int:
    try:
        engine = create_engine(DB_URL)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT urls_processed, status "
                    "FROM scrape_runs ORDER BY id DESC LIMIT 1"
                )
            ).fetchone()

        if row is None:
            return 0  # no runs yet, healthy

        urls_processed, status = row

        if status in ("completed", "failed"):
            return 0  # not running, healthy

        # Running — check progress
        now = time.time()
        prev = {"urls_processed": 0, "checked_at": now}

        if STALE_FILE.exists():
            prev = json.loads(STALE_FILE.read_text())

        if urls_processed > prev["urls_processed"]:
            # Progress made — update checkpoint
            STALE_FILE.write_text(
                json.dumps(
                    {"urls_processed": urls_processed, "checked_at": now}
                )
            )
            return 0

        # No progress — check how long
        stalled_for = now - prev["checked_at"]
        if stalled_for > STALL_SECONDS:
            return 1  # unhealthy

        return 0  # still within grace period

    except Exception:
        return 1  # can't reach DB = unhealthy


if __name__ == "__main__":
    sys.exit(main())
