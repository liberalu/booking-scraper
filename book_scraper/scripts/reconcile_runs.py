"""Fail any scrape_runs still flagged 'running' at boot, then auto-restart them.

Invoked from the scraper container's entrypoint: if a row is still
marked running when this container starts, the process that owned
it was killed by the restart and will never finish itself.

After marking them failed (with resumable_after_failure=True), we
immediately spawn new scrapy processes so each orphaned run continues
from where it left off. The failed row stays in the timeline for
postmortem; the new run gets its own id.

Spawn discipline (added 2026-05-04 after a swarm wedged Docker Desktop's
daemon during the auto-resume bug session):

1. **Per-(shop, phase) dedup.** Two orphans for the same shop+phase
   would race anyway — the dashboard pre-flight refuses concurrent
   runs for the same key — so only spawn one.
2. **Stagger spawns** by ``RECONCILE_STAGGER_SECONDS`` so a swarm of
   5+ orphans doesn't all bring up httpx clients in the same instant.
3. **Cap total spawns** at ``MAX_RECONCILE_SPAWNS``. Excess orphans
   remain ``failed`` with ``resumable_after_failure=True``; an
   operator can hit Continue on the dashboard, or the next reconcile
   cycle picks them up.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

from book_scraper.db.repo import mark_orphan_runs_failed
from book_scraper.db.session import get_session_factory

MAX_RECONCILE_SPAWNS = 3
RECONCILE_STAGGER_SECONDS = 5.0


def _spawn_restart(shop: str, phase: str) -> None:
    """Spawn a detached scrapy process inside the current container.

    Stdout+stderr are captured to /var/log/scrapy_runs/spawn-<ts>-reconcile-restart-<shop>.log
    via book_scraper.spawn_logging.open_spawn_log. Earlier versions sent both
    streams to DEVNULL — any crash before the first heartbeat tick was invisible
    (same bug-class as run #427 and patogupirkti runs 363–366).
    """
    from book_scraper.spawn_logging import open_spawn_log, spawn_paths

    if phase.startswith("discover_"):
        crawl_phase = "discover"
        strategy = phase[len("discover_") :]
    else:
        crawl_phase = phase
        strategy = ""

    scrapy_bin, project_root = spawn_paths()
    cmd = [scrapy_bin, "crawl", crawl_phase, "-a", f"shop={shop}"]
    if crawl_phase == "discover" and strategy:
        cmd.extend(["-a", f"strategy={strategy}"])

    env = os.environ.copy()
    env["PYTHONPATH"] = project_root

    log_fd, log_path = open_spawn_log("reconcile-restart", shop)
    try:
        subprocess.Popen(
            cmd,
            cwd=project_root,
            env=env,
            stdout=log_fd,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    finally:
        log_fd.close()
    print(f"  Spawned restart: {' '.join(cmd)} (log: {log_path})")


def _select_spawns(
    orphans: list[tuple[int, str, str]],
    max_spawns: int = MAX_RECONCILE_SPAWNS,
) -> tuple[list[tuple[int, str, str]], list[tuple[int, str, str]]]:
    """Apply dedup + cap; return (to_spawn, deferred).

    Dedup keeps the first orphan seen per (shop, phase) — orphans is
    expected to be ordered by id from the DB.
    """
    seen: set[tuple[str, str]] = set()
    to_spawn: list[tuple[int, str, str]] = []
    deferred: list[tuple[int, str, str]] = []
    for orphan in orphans:
        _, shop, phase = orphan
        key = (shop, phase)
        if key in seen:
            deferred.append(orphan)
            continue
        seen.add(key)
        if len(to_spawn) >= max_spawns:
            deferred.append(orphan)
            continue
        to_spawn.append(orphan)
    return to_spawn, deferred


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

    to_spawn, deferred = _select_spawns(orphans)
    for run_id, shop, phase in deferred:
        print(
            f"  Deferring restart for run #{run_id} ({shop}/{phase}) "
            "— cap or dedup; remains resumable for operator Continue"
        )

    for idx, (run_id, shop, phase) in enumerate(to_spawn):
        if idx > 0:
            time.sleep(RECONCILE_STAGGER_SECONDS)
        print(f"  Auto-restarting run #{run_id} ({shop}/{phase})...")
        _spawn_restart(shop, phase)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
