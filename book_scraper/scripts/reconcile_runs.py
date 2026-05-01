"""Fail any scrape_runs still flagged 'running' at boot, then auto-restart them.

Invoked from the scraper container's entrypoint: if a row is still
marked running when this container starts, the process that owned
it was killed by the restart and will never finish itself.

After marking them failed (with resumable_after_failure=True), we
immediately spawn new scrapy processes so each orphaned run continues
from where it left off. The failed row stays in the timeline for
postmortem; the new run gets its own id.
"""

from __future__ import annotations

import os
import subprocess
import sys

from book_scraper.db.repo import mark_orphan_runs_failed
from book_scraper.db.session import get_session_factory


def _spawn_restart(shop: str, phase: str) -> None:
    """Spawn a detached scrapy process inside the current container."""
    if phase.startswith("discover_"):
        crawl_phase = "discover"
        strategy = phase[len("discover_"):]
    else:
        crawl_phase = phase
        strategy = ""

    cmd = ["/app/.venv/bin/scrapy", "crawl", crawl_phase, "-a", f"shop={shop}"]
    if crawl_phase == "discover" and strategy:
        cmd.extend(["-a", f"strategy={strategy}"])

    env = os.environ.copy()
    env["PYTHONPATH"] = "/app"

    subprocess.Popen(
        cmd,
        cwd="/app",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    print(f"  Spawned restart: {' '.join(cmd)}")


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set; skipping orphan reconciliation", file=sys.stderr)
        return 0
    session = get_session_factory(database_url)()
    try:
        orphans = mark_orphan_runs_failed(session)
        session.commit()
    finally:
        session.close()

    count = len(orphans)
    print(f"Reconciled {count} orphan scrape_run(s) to failed")

    for run_id, shop, phase in orphans:
        print(f"  Auto-restarting run #{run_id} ({shop}/{phase})...")
        _spawn_restart(shop, phase)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
