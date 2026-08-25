#!/usr/bin/env python
"""Compare the two reapers on identical zombie runs.

    PYTHONPATH=. uv run python php/tools/reaper_diff.py

Test database only. Each stack gets its own clone of the test DB (the same
trick mutation_diff uses) so neither can see the other's writes, the same
fixture zombies are planted in both, and every table a reap touches is
compared afterwards.

The fixtures are the cases that made the Python code consolidate onto one
fail transition: a `running` run gone silent, a `stopping` run whose close
callback never fired, a `paused` run that must NOT be reaped, a live run
with a hung worker, and a terminal run with orphaned `processing` rows.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]
PHP = "/opt/homebrew/opt/php@8.4/bin/php"

TEST_HOST, TEST_PORT = "localhost", 5433
TEST_DB = "book_scraper_test"
PY_DB, PHP_DB = f"{TEST_DB}_reap_py", f"{TEST_DB}_reap_php"
MARK = "reaper-diff"


def dsn(database: str) -> str:
    return f"postgresql+psycopg2://postgres:postgres@{TEST_HOST}:{TEST_PORT}/{database}"


def guard() -> None:
    if TEST_PORT != 5433 or not TEST_DB.endswith("_test"):
        sys.exit(f"refusing to run: {TEST_DB}@{TEST_PORT} is not the test cluster")


def interval_expr(age: str | None) -> str:
    """A timestamp literal for the fixture SQL. Ages are hardcoded above, so
    there is no user input to interpolate here."""
    return "null" if age is None else f"now() - interval '{age}'"


def plant_fixtures() -> None:
    """Zombies in every shape the reaper distinguishes."""
    engine = sa.create_engine(dsn(TEST_DB))
    with engine.begin() as c:
        shop_id = c.execute(sa.text("select id from shops order by id limit 1")).scalar()
        if shop_id is None:
            sys.exit("test DB has no shops — run `make seed-test-db` first")

        c.execute(sa.text(
            "delete from scrape_failures where url like :m"), {"m": f"%{MARK}%"})
        c.execute(sa.text(
            "delete from scrape_url_items where url like :m"), {"m": f"%{MARK}%"})
        c.execute(sa.text(
            "delete from validation_issues where url in"
            " (select 'run:' || id::text from scrape_runs where close_reason = :m)"),
            {"m": MARK})
        c.execute(sa.text(
            "delete from scrape_run_events where run_id in"
            " (select id from scrape_runs where close_reason = :m)"), {"m": MARK})
        c.execute(sa.text("delete from scrape_runs where close_reason = :m"), {"m": MARK})

        # close_reason doubles as the fixture marker. It is also what the
        # reaper writes, so it is set to MARK here and compared as-is: both
        # stacks must overwrite it identically (or leave it, per first-writer).
        runs = {}
        for key, status, heartbeat_age, phase in (
            ("silent_running", "running", "10 minutes", "scan"),
            ("stuck_stopping", "stopping", "10 minutes", "scan"),
            ("paused_alive", "paused", "10 minutes", "discover_sitemap"),
            ("fresh_running", "running", "5 seconds", "scan"),
            ("terminal_with_orphans", "completed", "10 minutes", "scan"),
            ("no_heartbeat", "running", None, "scan"),
        ):
            heartbeat = interval_expr(heartbeat_age)
            runs[key] = c.execute(sa.text(
                "insert into scrape_runs (shop_id, phase, status, started_at,"
                " urls_total, urls_processed, items_added, items_updated,"
                " errors_4xx, errors_5xx, error_count, last_heartbeat,"
                " close_reason, finished_at)"
                " values (:s, :p, :st, now() - interval '1 hour', 10, 5, 0, 0,"
                f" 0, 0, 0, {heartbeat},"
                " :m, case when :st in ('completed','failed') then now() end)"
                " returning id"),
                {"s": shop_id, "p": phase, "st": status, "m": MARK}).scalar()

        # Rows the sweep has to act on, and rows it must leave alone.
        for key, status, claimed_age in (
            ("silent_running", "processing", "10 minutes"),   # aborted with the run
            ("stuck_stopping", "processing", "10 minutes"),   # ditto
            ("paused_alive", "processing", "10 minutes"),     # hung worker on a live run
            ("fresh_running", "processing", "5 seconds"),     # in flight, leave alone
            ("terminal_with_orphans", "processing", "1 hour"),  # orphan on a done run
            ("silent_running", "pending", None),             # pending is never touched
        ):
            claimed = interval_expr(claimed_age)
            c.execute(sa.text(
                "insert into scrape_url_items (run_id, shop_id, url, url_type,"
                " status, created_at, claimed_at, attempts)"
                f" values (:r, :s, 'https://example.test/{MARK}/' || :k || '/' || :st,"
                " 'product', :st, now() - interval '1 hour',"
                f" {claimed}, 0)"),
                {"r": runs[key], "s": shop_id, "k": key, "st": status})

        # A claimed-at-null processing row must never be reaped, however old.
        c.execute(sa.text(
            "insert into scrape_url_items (run_id, shop_id, url, url_type,"
            " status, created_at, claimed_at, attempts)"
            f" values (:r, :s, 'https://example.test/{MARK}/never-claimed',"
            " 'product', 'processing', now() - interval '1 day', null, 0)"),
            {"r": runs["paused_alive"], "s": shop_id})


def clone_databases() -> None:
    admin = sa.create_engine(
        dsn("postgres"), isolation_level="AUTOCOMMIT", poolclass=sa.pool.NullPool
    )
    with admin.connect() as c:
        for target in (PY_DB, PHP_DB, TEST_DB):
            c.execute(sa.text(
                "select pg_terminate_backend(pid) from pg_stat_activity"
                " where datname = :d and pid <> pg_backend_pid()"), {"d": target})
        for target in (PY_DB, PHP_DB):
            c.execute(sa.text(f'drop database if exists "{target}"'))
            c.execute(sa.text(f'create database "{target}" template "{TEST_DB}"'))


def drop_databases() -> None:
    admin = sa.create_engine(
        dsn("postgres"), isolation_level="AUTOCOMMIT", poolclass=sa.pool.NullPool
    )
    with admin.connect() as c:
        for target in (PY_DB, PHP_DB):
            c.execute(sa.text(
                "select pg_terminate_backend(pid) from pg_stat_activity"
                " where datname = :d and pid <> pg_backend_pid()"), {"d": target})
            c.execute(sa.text(f'drop database if exists "{target}"'))


def reap_python() -> None:
    code = (
        "from book_scraper.dashboard.queries import mark_stale_runs;"
        "from book_scraper.db.session import get_session_factory;"
        f"s = get_session_factory({dsn(PY_DB)!r})();"
        "killed = mark_stale_runs(s);"
        "s.commit(); s.close();"
        "print(len(killed))"
    )
    # Same interpreter this script runs under, so no PATH assumptions.
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT, check=True, capture_output=True,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )


def reap_php() -> None:
    subprocess.run(
        [PHP, "artisan", "runs:reap"],
        cwd=ROOT / "php" / "dashboard", check=True, capture_output=True,
        env={
            **os.environ,
            "DB_HOST": TEST_HOST, "DB_PORT": str(TEST_PORT), "DB_DATABASE": PHP_DB,
        },
    )


STATE = {
    "scrape_runs": "select id, status, close_reason, resumable_after_failure,"
                   " finished_at is not null as finished from scrape_runs order by id",
    "scrape_url_items": "select id, status, done_at is not null as done, attempts"
                        " from scrape_url_items order by id",
    "scrape_failures": "select scrape_url_item_id, run_id, error_reason, http_status,"
                       " error_detail, lifecycle_state from scrape_failures"
                       " order by scrape_url_item_id, error_reason",
    "scrape_run_events": "select run_id, event_type, actor, payload"
                         " from scrape_run_events order by id",
    "validation_issues": "select last_seen_run_id, shop_id, url, field, issue,"
                         " raw_value, lifecycle_state, run_count from validation_issues"
                         " where issue = 'scrape_run_failed' order by last_seen_run_id",
}


def read_state(database: str) -> dict:
    engine = sa.create_engine(dsn(database), poolclass=sa.pool.NullPool)
    with engine.connect() as c:
        return {name: [tuple(r) for r in c.execute(sa.text(q))] for name, q in STATE.items()}


def diff_state(py: dict, php: dict) -> list[str]:
    out = []
    for table, py_rows in py.items():
        php_rows = php[table]
        if len(py_rows) != len(php_rows):
            out.append(f"{table}: {len(py_rows)} rows in python, {len(php_rows)} in php")
        for index, (left, right) in enumerate(zip(py_rows, php_rows)):
            for column, (a, b) in enumerate(zip(left, right)):
                if isinstance(a, dt.datetime) and isinstance(b, dt.datetime):
                    continue
                if a != b:
                    out.append(f"{table}[row {index}, col {column}]: python={a!r} php={b!r}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    guard()
    print(f"planting zombie fixtures in {TEST_DB}")
    plant_fixtures()
    print(f"cloning {TEST_DB} -> {PY_DB}, {PHP_DB}")
    clone_databases()

    try:
        # Measured as a delta, not an absolute: the test DB already holds
        # plenty of failed runs, so counting them would pass even if the
        # sweep did nothing at all.
        before = read_state(PY_DB)
        print("  reaping with python…")
        reap_python()
        print("  reaping with php…")
        reap_php()

        python_state = read_state(PY_DB)
        php_state = read_state(PHP_DB)

        failed_before = sum(1 for row in before["scrape_runs"] if row[1] == "failed")
        failed_after = sum(1 for row in python_state["scrape_runs"] if row[1] == "failed")
        reaped = failed_after - failed_before
        aborted = len(python_state["scrape_failures"]) - len(before["scrape_failures"])
        print(f"  python reaped {reaped} run(s), wrote {aborted} failure row(s)")
        if reaped == 0 or aborted == 0:
            print(
                "\nINCONCLUSIVE — the reference reaper did nothing, so this"
                " proves nothing.\n  Check the fixtures still look stale"
                " (DEAD_RUN_SECONDS may have changed)."
            )
            return 1

        differences = diff_state(python_state, php_state)
        print()
        if differences:
            shown = differences if args.verbose else differences[:20]
            for line in shown:
                print(f"  {line}")
            if len(differences) > len(shown):
                print(f"  … {len(differences) - len(shown)} more (--verbose)")
            print(f"\n{len(differences)} DIFFERENCES")
            return len(differences)
        print("identical — both reapers left the database in the same state")
        return 0
    finally:
        if not args.keep:
            drop_databases()


if __name__ == "__main__":
    sys.exit(main())
