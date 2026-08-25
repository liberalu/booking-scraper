"""The one place the PHP side's test database is named.

The Python suite and the PHP differentials both used to point at
`book_scraper_test`, and they cannot share it: `tests/conftest.py` builds an
empty schema from `Base.metadata` and drops it on teardown, while the
differentials need it loaded with a copy of the real catalogue. Whichever ran
last won, and the other reported failures that had nothing to do with the code
under test — 75 spurious integration failures one run, 61 the next, and once
the schema gone entirely.

So the two are separate databases now, and this module is the single
definition of the PHP one. It was eight copies of the same DSN literal across
eight scripts; that is why the name could not be changed in one place.

Override with `PHP_TEST_DATABASE_URL` for a scratch database — the guard below
still refuses anything that is not clearly a test target.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

#: Port 5433 is the `postgres-test` compose service. 5432 is the real
#: catalogue and nothing here may touch it.
TEST_PORT = 5433

TEST_DB = "book_scraper_php_test"

#: A database holding NOTHING but the fixture, built from php/schema's baseline
#: by `php bin/fixture-db`. Everything frozen as a golden is taken over this
#: one: the seeded database carries a copy of the live catalogue, which moves,
#: so a shape or a count taken over it stops matching for reasons that are not
#: regressions — and after Python is gone there is nothing left to re-freeze
#: against.
FIXTURE_DB = "book_scraper_php_test_fixture"

#: SQLAlchemy form (psycopg2). PHP's PDO wants the bare form — see `php_dsn`.
TEST_DSN = os.environ.get(
    "PHP_TEST_DATABASE_URL",
    f"postgresql+psycopg2://postgres:postgres@localhost:{TEST_PORT}/{TEST_DB}",
)


def php_dsn(dsn: str | None = None) -> str:
    """The same URL without SQLAlchemy's driver suffix, for `--database=`."""
    return (dsn or TEST_DSN).replace("+psycopg2", "")


def database_name(dsn: str | None = None) -> str:
    return urlparse(php_dsn(dsn)).path.lstrip("/")


def dsn_for(database: str) -> str:
    """A sibling database on the same cluster — for the per-stack clones the
    mutation and reaper harnesses build."""
    base = php_dsn()
    return base.rsplit("/", 1)[0] + "/" + database


def guard(dsn: str | None = None) -> None:
    """Refuse to run against anything but a test database.

    Every tool importing this writes, and several drop and recreate whole
    databases. The port check is the load-bearing one: the real catalogue is
    the only thing on 5432, so a tool that never accepts 5432 cannot destroy
    it however wrong its other arguments are.
    """
    parsed = urlparse(php_dsn(dsn))
    name = (parsed.path or "").lstrip("/")
    if parsed.port != TEST_PORT:
        raise SystemExit(
            f"refusing to run: {name or '<unnamed>'} is on port {parsed.port}, "
            f"not the test cluster ({TEST_PORT}). The real catalogue is on 5432."
        )
    if "test" not in name:
        raise SystemExit(
            f"refusing to run: database {name!r} is not named as a test database."
        )
