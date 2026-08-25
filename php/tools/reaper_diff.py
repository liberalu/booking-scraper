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
import json
import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

# The test database is named in one place — see _testdb for why the PHP
# side cannot share the Python suite's database.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _testdb import TEST_PORT, database_name, dsn_for  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PHP = "/opt/homebrew/opt/php@8.4/bin/php"

TEST_HOST = "localhost"
TEST_DB = database_name()   # see _testdb: PHP has its own database
PY_DB, PHP_DB = f"{TEST_DB}_reap_py", f"{TEST_DB}_reap_php"
#: From the shared spec, so the PHP test plants the same marker.
MARK = json.loads(
    (Path(__file__).resolve().parents[2] / "php" / "tests" / "golden"
     / "reaper_fixtures.json").read_text()
)["marker"]


def dsn(database: str) -> str:
    return dsn_for(database)


def guard() -> None:
    if TEST_PORT != 5433 or not TEST_DB.endswith("_test"):
        sys.exit(f"refusing to run: {TEST_DB}@{TEST_PORT} is not the test cluster")


SPEC_PATH = ROOT / "php" / "tests" / "golden" / "reaper_fixtures.json"

#: Where --freeze writes the per-fixture outcome.
FREEZE_TO = ROOT / "php" / "tests" / "golden" / "reaper_expected.json"


def fixture_spec() -> dict:
    """The shapes to plant. Shared with ReaperCharacterisationTest, which plants
    the same ones and asserts the frozen outcome without Python."""
    return json.loads(SPEC_PATH.read_text())


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
        spec = fixture_spec()
        runs = {}
        for row in spec["runs"]:
            key, status, heartbeat_age, phase = (
                row["fixture"], row["status"], row["heartbeat"], row["phase"],
            )
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
        for index, item in enumerate(spec["items"]):
            key, status, claimed_age = item["run"], item["status"], item["claimed"]
            claimed = interval_expr(claimed_age)
            # The index is in the URL because (run_id, url) is unique and two
            # items can share a run and a status — the never-claimed row is a
            # second `processing` item on the paused run.
            c.execute(sa.text(
                "insert into scrape_url_items (run_id, shop_id, url, url_type,"
                " status, created_at, claimed_at, attempts)"
                f" values (:r, :s, 'https://example.test/{MARK}/' || :i || '-' || :k,"
                " 'product', :st, now() - interval '1 hour',"
                f" {claimed}, 0)"),
                {"r": runs[key], "s": shop_id, "i": index, "k": key, "st": status})


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


def fixture_outcome(database: str) -> list[dict]:
    """What the sweep did to each planted fixture, keyed by label.

    Whole-table state cannot be frozen: it carries row ids and whatever else
    the database already held. What is stable — and what actually encodes the
    reaper's behaviour — is the verdict per fixture.
    """
    engine = sa.create_engine(dsn(database), poolclass=sa.pool.NullPool)
    with engine.connect() as c:
        runs = {
            row.phase + "|" + str(row.id): row
            for row in c.execute(sa.text(
                "select id, phase, status, close_reason, resumable_after_failure"
                "  from scrape_runs where close_reason = :m or id in ("
                "     select run_id from scrape_url_items where url like :u)"
                " order by id"), {"m": MARK, "u": f"%{MARK}%"})
        }
        out = []
        for label_row in c.execute(sa.text(
            "select sui.url, sui.status, sui.done_at is not null as done,"
            "       sui.attempts, sr.status as run_status, sr.close_reason,"
            "       sr.resumable_after_failure,"
            "       (select string_agg(distinct sf.error_reason, ',' order by"
            "               sf.error_reason) from scrape_failures sf"
            "         where sf.scrape_url_item_id = sui.id) as reasons"
            "  from scrape_url_items sui join scrape_runs sr on sr.id = sui.run_id"
            f" where sui.url like :u order by sui.url"), {"u": f"%{MARK}%"}):
            # The URL carries "<index>-<fixture>"; the label is what matters.
            tail = label_row.url.rsplit("/", 1)[-1]
            out.append({
                "fixture": tail,
                "item_status": label_row.status,
                "item_done": label_row.done,
                "item_attempts": label_row.attempts,
                "failure_reasons": label_row.reasons,
                "run_status": label_row.run_status,
                "run_close_reason": label_row.close_reason,
                "run_resumable": label_row.resumable_after_failure,
            })
    return out


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
    parser.add_argument(
        "--freeze",
        metavar="PATH",
        nargs="?",
        const=str(FREEZE_TO),
        help="after both reapers agree, write the per-fixture outcome as a "
        "characterisation golden. Refuses to write on any difference.",
    )
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
            if args.freeze:
                print("NOT frozen — the golden may only record agreed behaviour.")
            return len(differences)
        if args.freeze:
            outcome = fixture_outcome(PY_DB)
            path = Path(args.freeze)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(outcome, indent=1, ensure_ascii=False) + "\n")
            print(f"froze {len(outcome)} fixture outcome(s) to {path}")

        print("identical — both reapers left the database in the same state")
        return 0
    finally:
        if not args.keep:
            drop_databases()


if __name__ == "__main__":
    sys.exit(main())
