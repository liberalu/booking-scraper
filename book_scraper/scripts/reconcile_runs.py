"""Fail any scrape_runs still flagged 'running' at boot.

Invoked from the scraper container's entrypoint: if a row is still
marked running when this container starts, the process that owned
it was killed by the restart and will never finish itself.
"""

from __future__ import annotations

import os
import sys

from book_scraper.db.repo import mark_orphan_runs_failed
from book_scraper.db.session import get_session_factory


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL not set; skipping orphan reconciliation", file=sys.stderr)
        return 0
    session = get_session_factory(database_url)()
    try:
        count = mark_orphan_runs_failed(session)
        session.commit()
    finally:
        session.close()
    print(f"Reconciled {count} orphan scrape_run(s) to failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
