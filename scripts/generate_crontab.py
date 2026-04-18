"""Generate and install the scraper container's crontab from cron_jobs.

Run by the entrypoint at boot time. Replaces the legacy static crontab
file at cron/scraper-crontab.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from book_scraper.db.models import CronJob


_LOG_PATH = "/var/log/scraper.log"
_ENV_PREFIX = (
    "cd /app && "
    "DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/book_scraper "
    "PYTHONPATH=. /app/.venv/bin/python -m scrapy crawl"
)


def build_crontab_lines(jobs: "list[CronJob]") -> list[str]:
    """Return one crontab line per enabled job."""
    lines: list[str] = []
    for job in jobs:
        if not job.enabled:
            continue
        cmd = f"{_ENV_PREFIX} {job.phase} -a shop={job.shop.name}"
        if job.strategy:
            cmd += f" -a strategy={job.strategy}"
        if job.args:
            cmd += f" {job.args}"
        line = f"{job.cron_expression} {cmd} >> {_LOG_PATH} 2>&1"
        lines.append(line)
    return lines


def main() -> int:
    # Import lazily so the unit test can import build_crontab_lines
    # without opening a DB connection.
    from book_scraper.db.repo import list_cron_jobs
    from book_scraper.db.session import get_session_factory

    session_factory = get_session_factory(os.environ.get("DATABASE_URL"))
    session = session_factory()
    try:
        jobs = list_cron_jobs(session)
        lines = build_crontab_lines(jobs)
    finally:
        session.close()
    content = "\n".join(lines) + ("\n" if lines else "")

    out_path = Path("/tmp/crontab-generated")
    out_path.write_text(content)

    result = subprocess.run(
        ["crontab", str(out_path)], check=False, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"crontab install failed: {result.stderr}", file=sys.stderr)
        return result.returncode

    print(f"Installed {len(lines)} cron line(s) from cron_jobs table")
    return 0


if __name__ == "__main__":
    sys.exit(main())
