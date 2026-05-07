"""Daily health summary of scrape runs.

Run via cron once a day. Prints one line to stdout (which the cron
crontab redirects to ``/var/log/scraper.log``) summarising the last
24 h of scrape runs:

  - "OK" line if everything completed cleanly
  - One "FAIL" line per failed run with run_id, phase, shop, close_reason

Doesn't try to be fancy — no webhooks, no email. The point is to
leave a visible breadcrumb in the log volume so operator-tail or a
future log-aggregation hook can pick it up. The dashboard's /runs
page is the rich source; this is the cheap heartbeat.

Schema note: relies on `scrape_runs.close_reason` being populated by
the spider's `closed()` callback. Stall-killed runs land here as
`stall_timeout`; clean failures as the original error reason.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from book_scraper.db.models import ScrapeRun, Shop
from book_scraper.db.session import get_session_factory


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("[health-check] DATABASE_URL unset; skipping", file=sys.stderr)
        return 1

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    session = get_session_factory(database_url)()
    try:
        rows = list(
            session.execute(
                select(
                    ScrapeRun.id,
                    ScrapeRun.phase,
                    ScrapeRun.status,
                    ScrapeRun.close_reason,
                    Shop.name,
                )
                .join(Shop, Shop.id == ScrapeRun.shop_id)
                .where(ScrapeRun.started_at >= cutoff)
                .order_by(ScrapeRun.id)
            ).all()
        )
    finally:
        session.close()

    completed = [r for r in rows if r.status == "completed"]
    failed = [r for r in rows if r.status == "failed"]
    running = [r for r in rows if r.status == "running"]

    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    if not failed and not running:
        print(
            f"[health-check] {ts} OK — {len(completed)} run(s) completed in last 24 h"
        )
        return 0

    if failed:
        for r in failed:
            print(
                f"[health-check] {ts} FAIL run_id={r.id} {r.phase} "
                f"shop={r.name} close_reason={r.close_reason or '<unset>'}"
            )

    if running:
        for r in running:
            print(
                f"[health-check] {ts} STILL_RUNNING run_id={r.id} {r.phase} "
                f"shop={r.name}"
            )

    summary = (
        f"[health-check] {ts} SUMMARY completed={len(completed)} "
        f"failed={len(failed)} running={len(running)}"
    )
    print(summary)
    # Non-zero exit when there are failures — gives the cron line a
    # signal an operator can grep/alert on (e.g. `MAILTO=` cron wrapper
    # would fire on stderr or non-zero exit). We don't change the
    # crontab to mail, but the exit code is preserved in scraper.log
    # via the same redirection.
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
