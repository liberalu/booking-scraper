#!/usr/bin/env python
"""Run every write endpoint through both dashboards and compare what happens.

    PYTHONPATH=. uv run python php/tools/mutation_diff.py
    PYTHONPATH=. uv run python php/tools/mutation_diff.py --verbose
    PYTHONPATH=. uv run python php/tools/mutation_diff.py --keep   # keep the copies

TEST DATABASE ONLY, and structurally so: each stack gets its OWN database,
cloned from the test DB with CREATE DATABASE ... TEMPLATE, and the tool
refuses to run against anything that isn't the test cluster. Nothing here
can reach production, and no restore-between-passes logic is needed — the
two clones start byte-identical, receive the same requests in the same
order, and are diffed at the end.

Two things are compared:

  * the response of every case (status code and body), and
  * the final database state, table by table, so a mutation that returns the
    right JSON while writing the wrong row still fails.

Timestamp columns are compared within a tolerance: both stacks stamp
`now()` from their own process, so exact equality is impossible.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import sqlalchemy as sa

# The test database is named in one place — see _testdb for why the PHP
# side cannot share the Python suite's database.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _testdb import FIXTURE_DB, TEST_PORT, dsn_for  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PHP = "/opt/homebrew/opt/php@8.4/bin/php"

TEST_HOST = "localhost"
# The fixture database, not the seeded one. Every case here is replayed from a
# golden, and a golden can only describe data that comes back the same way
# every time — see FIXTURE_DB in _testdb.
TEST_DB = FIXTURE_DB

#: The fixture's shop. Must match SyntheticShop::SHOP — it is a constant in
#: code on both sides, which is what makes it safe to write into a golden.
#: Resolving "whatever shop is first" instead would put a copied catalogue's
#: name in there.
SHOP = "synthetic"
PY_DB, PHP_DB = f"{TEST_DB}_py", f"{TEST_DB}_php"
PY_PORT, PHP_PORT = 8011, 8012

# Fixtures are marked so a re-run can replace them rather than accumulate.
MARK = "mutation-diff"

#: Where --freeze writes. Replayed by MutationCharacterisationTest, which drives
#: the routes in-process and needs neither Python nor a running server.
FREEZE_TO = ROOT / "php" / "dashboard" / "tests" / "golden" / "mutation_cases.json"


def dsn(database: str) -> str:
    return dsn_for(database)


def guard() -> None:
    """The whole tool writes; make it impossible to point at production."""
    if TEST_PORT != 5433 or "test" not in TEST_DB:
        sys.exit(f"refusing to run: {TEST_DB}@{TEST_PORT} is not the test cluster")


# ── Fixtures ────────────────────────────────────────────────────────────────
# The seeded test DB has books and URLs but no runs, issues, failures or cron
# jobs — nothing for a write endpoint to act on. These rows supply them.


def seed_fixtures() -> dict[str, int]:
    engine = sa.create_engine(dsn(TEST_DB))
    with engine.begin() as c:
        shop_id = c.execute(
            sa.text("select id from shops where name = :s"), {"s": SHOP}
        ).scalar()
        if shop_id is None:
            sys.exit(
                f"the fixture database has no shop '{SHOP}'. Build it first:\n"
                f"    cd php && make fixture-db"
            )

        # Idempotent: drop the previous fixture set. One definition, in
        # clear_fixtures() — this used to be a second copy of the same delete
        # list, and updating one and not the other left three marked
        # shop_books behind, which moved the first row of every book list and
        # broke a frozen API shape.
        _clear(c)

        # Any run left non-terminal by an earlier test carries a stale
        # heartbeat, and the Python dashboard's reaper fires once at startup
        # and fails it — writing a run row, an event and an issue the PHP
        # side never sees. That is the reaper doing its job, not a
        # divergence, so retire those rows before cloning.
        stale = c.execute(sa.text(
            "update scrape_runs set status = 'completed', finished_at = now()"
            " where status in ('running', 'stopping', 'paused')"
            " returning id")).fetchall()
        if stale:
            print(f"  retired {len(stale)} stale non-terminal run(s) first")

        # Same reasoning one level down: a `processing` row on a terminal run
        # is swept by sweep_orphaned_processing_items, so whichever stack runs
        # a reaper first would diverge from the other on rows this comparison
        # never planted.
        orphans = c.execute(sa.text(
            "update scrape_url_items set status = 'failed', done_at = now()"
            " where status = 'processing' returning id")).fetchall()
        if orphans:
            print(f"  retired {len(orphans)} orphaned processing item(s)")

        runs: dict[str, int] = {}
        for key, phase, status in (
            ("running", "scan", "running"),
            ("running2", "scan", "running"),
            ("completed", "scan", "completed"),
            ("failed_pending", "scan", "failed"),
            ("failed_empty", "scan", "failed"),
            ("discover", "discover_sitemap", "completed"),
        ):
            runs[key] = c.execute(sa.text(
                "insert into scrape_runs (shop_id, phase, status, started_at,"
                " urls_total, urls_processed, items_added, items_updated,"
                " errors_4xx, errors_5xx, error_count, last_heartbeat,"
                " close_reason, finished_at)"
                " values (:s, :p, :st, now() - interval '10 minutes',"
                " 10, 5, 0, 0, 0, 0, 0, now(), :m,"
                " case when :st <> 'running' then now() end) returning id"),
                {"s": shop_id, "p": phase, "st": status, "m": MARK}).scalar()

        # One pending item so /continue has something to continue.
        c.execute(sa.text(
            "insert into scrape_url_items (run_id, shop_id, url, url_type,"
            " status, created_at, attempts)"
            f" values (:r, :s, 'https://example.test/{MARK}/pending', 'product',"
            " 'pending', now(), 0)"),
            {"r": runs["failed_pending"], "s": shop_id})

        # Failure buckets: one with reason+status, one with both null.
        item_id = c.execute(sa.text(
            "insert into scrape_url_items (run_id, shop_id, url, url_type,"
            " status, created_at, attempts)"
            f" values (:r, :s, 'https://example.test/{MARK}/1', 'product',"
            " 'failed', now(), 1) returning id"),
            {"r": runs["running"], "s": shop_id}).scalar()
        for reason, http_status in (("http_404", 404), (None, None)):
            c.execute(sa.text(
                "insert into scrape_failures (scrape_url_item_id, run_id, shop_id,"
                " url, occurred_at, error_reason, http_status, lifecycle_state)"
                f" values (:i, :r, :s, 'https://example.test/{MARK}/1', now(),"
                " :e, :h, 'new')"),
                {"i": item_id, "r": runs["running"], "s": shop_id,
                 "e": reason, "h": http_status})

        # Issues: two of one type so bulk-acknowledge has something to count.
        # Half of them carry a shop_book_id whose discovered_url is a real
        # product page — otherwise bulk-rescrape's join matches nothing and
        # the comparison passes without exercising the query.
        #
        # Those books are CREATED here, not borrowed. Selecting "the three
        # lowest-id books with a product URL" made bulk-rescrape's expected
        # value — a list of URLs — depend on which shop happened to hold those
        # ids, so the frozen case broke whenever the seeded catalogue shifted.
        linked_books = []
        for n in range(3):
            url = f"https://example.test/{MARK}/book/{n}"
            book = c.execute(sa.text(
                "insert into shop_books (shop_id, url, title, type, is_active,"
                " in_stock, match_status, first_seen_at, last_seen_at)"
                " values (:s, :u, :t, 'book', true, true, 'unmatched', now(), now())"
                " returning id"),
                {"s": shop_id, "u": url, "t": f"Fixture Book {n}"}).scalar()
            c.execute(sa.text(
                "insert into discovered_urls (shop_id, url, normalized_url, source,"
                " url_type, fail_count, first_seen_at, last_seen_at, shop_book_id)"
                " values (:s, :u, :u, 'sitemap', 'product', 0, now(), now(), :b)"),
                {"s": shop_id, "u": url, "b": book})
            linked_books.append(book)
        issues: dict[str, int] = {}
        for index, (key, issue, state) in enumerate((
            ("new", "missing_isbn", "new"),
            ("new2", "missing_isbn", "new"),
            ("acked", "missing_isbn", "acknowledged"),
            ("other", "price_zero", "new"),
        )):
            book = linked_books[index] if index < len(linked_books) else None
            issues[key] = c.execute(sa.text(
                "insert into validation_issues (shop_id, last_seen_run_id, url,"
                " field, issue, run_count, lifecycle_state, acknowledged_at,"
                " shop_book_id)"
                f" values (:s, :r, 'https://example.test/{MARK}/' || :k, 'isbn',"
                " :i, 1, :st, case when :st = 'acknowledged' then now() end, :b)"
                " returning id"),
                {"s": shop_id, "r": runs["completed"], "k": key,
                 "i": issue, "st": state, "b": book}).scalar()

        # Cron jobs. `args` carries the marker so the cleanup above finds them.
        jobs: dict[str, int] = {}
        for key, phase, strategy in (
            ("a", "discover", "sitemap"),
            ("b", "scan", None),
            ("target", "discover", "categories"),
            ("dependent", "scan", None),
            ("doomed", "scan", None),
        ):
            jobs[key] = c.execute(sa.text(
                "insert into cron_jobs (shop_id, phase, strategy, args,"
                " cron_expression, enabled, created_at)"
                " values (:s, :p, :g, :m, '0 2 * * *', true, now())"
                " returning id"),
                {"s": shop_id, "p": phase, "g": strategy, "m": MARK}).scalar()
        c.execute(sa.text("update cron_jobs set chain_to_job_id = :t where id = :d"),
                  {"t": jobs["target"], "d": jobs["dependent"]})

        # A linked shop_book for unlink-canonical.
        linked = c.execute(sa.text(
            "select id from shop_books where book_id is not null"
            " order by id limit 1")).scalar()
        if linked is None:
            book = c.execute(sa.text("select id from books order by id limit 1")).scalar()
            linked = c.execute(sa.text("select id from shop_books order by id limit 1")).scalar()
            c.execute(sa.text("update shop_books set book_id = :b where id = :i"),
                      {"b": book, "i": linked})

    ids = {f"run_{k}": v for k, v in runs.items()}
    ids |= {f"issue_{k}": v for k, v in issues.items()}
    ids |= {f"cron_{k}": v for k, v in jobs.items()}
    ids["shop_book_linked"] = linked
    return ids


def _clear(c: sa.Connection) -> None:
    """Delete every planted row, children before parents.

    The one definition of what the fixture set consists of. Called both before
    planting (so a re-run is idempotent) and after the clones are taken (so
    nothing is left in the shared database for the next tool to trip over).
    """
    for statement, params in (
        ("delete from scrape_failures where url like :m", {"m": f"%{MARK}%"}),
        ("delete from scrape_url_items where url like :m", {"m": f"%{MARK}%"}),
        ("delete from validation_issues where url like :m", {"m": f"%{MARK}%"}),
        ("delete from cron_jobs where args = :m", {"m": MARK}),
        ("delete from scrape_run_events where run_id in"
         " (select id from scrape_runs where close_reason = :m)", {"m": MARK}),
        ("delete from scrape_runs where close_reason = :m", {"m": MARK}),
        ("delete from discovered_urls where url like :m", {"m": f"%{MARK}%"}),
        ("delete from shop_books where url like :m", {"m": f"%{MARK}%"}),
    ):
        c.execute(sa.text(statement), params)


def clear_fixtures() -> None:
    """Remove the planted fixtures from the BASE database.

    They only need to survive being cloned. Left behind, they are a trap for
    anything else that plants the same shapes: the issue rows occupy
    `(shop_book_id, field, issue)` in a partial unique index, so the next
    planter gets a constraint violation rather than a clean fixture. Found
    exactly that way, by the characterisation test that replays these cases.
    """
    engine = sa.create_engine(dsn(TEST_DB), poolclass=sa.pool.NullPool)
    with engine.begin() as c:
        _clear(c)


def clone_databases() -> None:
    """Two byte-identical working copies, so neither stack sees the other's writes."""
    admin = sa.create_engine(
        dsn("postgres"), isolation_level="AUTOCOMMIT", poolclass=sa.pool.NullPool
    )
    with admin.connect() as c:
        for target in (PY_DB, PHP_DB):
            c.execute(sa.text(
                "select pg_terminate_backend(pid) from pg_stat_activity"
                " where datname = :d and pid <> pg_backend_pid()"), {"d": target})
            c.execute(sa.text(f'drop database if exists "{target}"'))
        # The template must be idle; the seed connection is already closed.
        c.execute(sa.text(
            "select pg_terminate_backend(pid) from pg_stat_activity"
            " where datname = :d and pid <> pg_backend_pid()"), {"d": TEST_DB})
        for target in (PY_DB, PHP_DB):
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


# ── Servers ─────────────────────────────────────────────────────────────────


def start_python() -> subprocess.Popen[bytes]:
    env = os.environ | {
        "PYTHONPATH": str(ROOT),
        "DATABASE_URL": dsn(PY_DB),
        # The reaper would fail the fixture run out from under the diff.
        "REAPER_INTERVAL_SECONDS": "86400",
    }
    return subprocess.Popen(
        ["uv", "run", "uvicorn", "book_scraper.dashboard.app:app",
         "--host", "127.0.0.1", "--port", str(PY_PORT), "--log-level", "warning"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        start_new_session=True,
    )


def start_php() -> subprocess.Popen[bytes]:
    env = os.environ | {
        "DB_HOST": TEST_HOST,
        "DB_PORT": str(TEST_PORT),
        "DB_DATABASE": PHP_DB,
    }
    cwd = ROOT / "php" / "dashboard"
    # Laravel's env() reads the real environment first, but a cached config
    # file would freeze the previous values.
    subprocess.run([PHP, "artisan", "config:clear"], cwd=cwd, env=env,
                   stdout=subprocess.DEVNULL, check=False)
    return subprocess.Popen(
        [PHP, "artisan", "serve", "--host", "127.0.0.1", "--port", str(PHP_PORT)],
        cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        start_new_session=True,
    )


def wait_ready(port: int, name: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/overview", timeout=5
            ):
                return
        except urllib.error.HTTPError:
            return  # responding is enough
        except Exception:
            time.sleep(0.4)
    sys.exit(f"{name} did not become ready on :{port}")


def stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)


# ── Cases ───────────────────────────────────────────────────────────────────


def cases(ids: dict[str, int], marker: str) -> list[tuple[str, str, str, dict | None]]:
    """(label, method, path, json body). Order matters — several cases depend
    on the state an earlier one left behind."""
    issue, issue2 = ids["issue_new"], ids["issue_new2"]
    acked, other = ids["issue_acked"], ids["issue_other"]
    run, run2, done = ids["run_running"], ids["run_running2"], ids["run_completed"]
    failed_pending = ids["run_failed_pending"]
    failed_empty = ids["run_failed_empty"]
    discover_run = ids["run_discover"]
    sb = ids["shop_book_linked"]
    a, b = ids["cron_a"], ids["cron_b"]
    target, dependent, doomed = ids["cron_target"], ids["cron_dependent"], ids["cron_doomed"]
    isbn = f"978{marker}"

    return [
        # Issue lifecycle
        ("lifecycle ack", "PATCH", f"/api/issues/{issue}/lifecycle?state=acknowledged", None),
        ("lifecycle resolved", "PATCH", f"/api/issues/{issue}/lifecycle?state=resolved", None),
        ("lifecycle bad state", "PATCH", f"/api/issues/{issue}/lifecycle?state=bogus", None),
        ("lifecycle 404", "PATCH", "/api/issues/999999999/lifecycle?state=new", None),
        ("snooze 30", "PATCH", f"/api/issues/{other}/snooze", {"days": 30}),
        ("snooze default", "PATCH", f"/api/issues/{other}/snooze", {}),
        ("snooze bad days", "PATCH", f"/api/issues/{other}/snooze", {"days": 5}),
        ("snooze 404", "PATCH", "/api/issues/999999999/snooze", {"days": 7}),
        # Bulk issue actions
        ("bulk ack", "POST", "/api/issues/bulk-acknowledge", {"issue_type": "missing_isbn"}),
        ("bulk unack", "POST", "/api/issues/bulk-unacknowledge", {"issue_type": "missing_isbn"}),
        # An unknown shop leaves the action UNSCOPED in Python, so this must
        # acknowledge everything of the type — a 0 here would mean the case
        # proves nothing.
        ("bulk ack unknown shop", "POST", "/api/issues/bulk-acknowledge",
         {"issue_type": "missing_isbn", "shop": "no-such-shop"}),
        ("bulk unack shop", "POST", "/api/issues/bulk-unacknowledge",
         {"issue_type": "missing_isbn", "shop": SHOP}),
        ("bulk ack shop", "POST", "/api/issues/bulk-acknowledge",
         {"issue_type": "missing_isbn", "shop": SHOP}),
        ("bulk ack no type", "POST", "/api/issues/bulk-acknowledge", {}),
        ("bulk unack no type", "POST", "/api/issues/bulk-unacknowledge", {}),
        # Unlink canonical
        ("unlink", "POST", f"/api/shop-books/{sb}/unlink-canonical", None),
        ("unlink again", "POST", f"/api/shop-books/{sb}/unlink-canonical", None),
        ("unlink 404", "POST", "/api/shop-books/999999999/unlink-canonical", None),
        # Manual book creation
        ("book create", "POST", "/api/books",
         {"title": " Diff Test Book ", "isbn": isbn, "author": "  Jonas   Jonaitis ",
          "publisher": " Diff Press ", "year": 2001}),
        ("book create dup isbn", "POST", "/api/books", {"title": "Other", "isbn": isbn}),
        ("book create same author", "POST", "/api/books",
         {"title": "Second", "author": "jonas jonaitis", "publisher": "Diff Press"}),
        ("book create blank title", "POST", "/api/books", {"title": "   "}),
        ("book create bad isbn", "POST", "/api/books", {"title": "X", "isbn": "12345"}),
        ("book create dashed isbn", "POST", "/api/books",
         {"title": "Dashed", "isbn": f"978-{marker[:4]}-{marker[4:]}"}),
        # Run lifecycle
        ("run stop", "POST", f"/api/runs/{run}/stop", None),
        ("run stop again", "POST", f"/api/runs/{run}/stop", None),
        ("run stop 404", "POST", "/api/runs/999999999/stop", None),
        ("run pause", "POST", f"/api/runs/{run2}/pause", None),
        ("run pause again", "POST", f"/api/runs/{run2}/pause", None),
        ("run resume", "POST", f"/api/runs/{run2}/resume", None),
        ("run resume again", "POST", f"/api/runs/{run2}/resume", None),
        ("run pause terminal", "POST", f"/api/runs/{done}/pause", None),
        ("run resume 404", "POST", "/api/runs/999999999/resume", None),
        ("run pause 404", "POST", "/api/runs/999999999/pause", None),
        # Failure acknowledgement
        ("ack bucket", "POST",
         f"/api/runs/{run}/failures/ack?error_reason=http_404&http_status=404", None),
        ("ack bucket again", "POST",
         f"/api/runs/{run}/failures/ack?error_reason=http_404&http_status=404&note=dead", None),
        ("ack null bucket", "POST",
         f"/api/runs/{run}/failures/ack?error_reason_is_null=true&http_status_is_null=true", None),
        ("ack no match", "POST",
         f"/api/runs/{run}/failures/ack?error_reason=never_happens", None),
        ("ack 404", "POST", "/api/runs/999999999/failures/ack?error_reason=http_404", None),
        # Cron CRUD
        ("cron create", "POST", "/api/cron",
         {"shop": SHOP, "phase": "discover", "strategy": "sitemap",
          "cron_expression": "0 3 * * *"}),
        ("cron create no strategy", "POST", "/api/cron",
         {"shop": SHOP, "phase": "scan", "strategy": "  ",
          "cron_expression": "15 4 * * 1-5"}),
        ("cron create chained", "POST", "/api/cron",
         {"shop": SHOP, "phase": "scan", "cron_expression": "0 5 * * *",
          "chain_to_id": target}),
        ("cron create bad shop", "POST", "/api/cron",
         {"shop": "no-such-shop", "phase": "scan", "cron_expression": "0 3 * * *"}),
        ("cron create bad phase", "POST", "/api/cron",
         {"shop": SHOP, "phase": "match", "cron_expression": "0 3 * * *"}),
        ("cron create 4 fields", "POST", "/api/cron",
         {"shop": SHOP, "phase": "scan", "cron_expression": "0 3 * *"}),
        ("cron create 6 fields", "POST", "/api/cron",
         {"shop": SHOP, "phase": "scan", "cron_expression": "0 0 3 * * *"}),
        ("cron create garbage", "POST", "/api/cron",
         {"shop": SHOP, "phase": "scan", "cron_expression": "not a cron line"}),
        ("cron create names", "POST", "/api/cron",
         {"shop": SHOP, "phase": "scan", "cron_expression": "0 3 * jan mon"}),
        ("cron create step", "POST", "/api/cron",
         {"shop": SHOP, "phase": "scan", "cron_expression": "*/15 2-6 1,15 * *"}),
        ("cron create bad field", "POST", "/api/cron",
         {"shop": SHOP, "phase": "scan", "cron_expression": "99 3 * * *"}),
        ("cron create missing chain", "POST", "/api/cron",
         {"shop": SHOP, "phase": "scan", "cron_expression": "0 3 * * *",
          "chain_to_id": 999999}),
        ("cron patch expression", "PATCH", f"/api/cron/{a}", {"cron_expression": "30 4 * * 1"}),
        ("cron patch bad expression", "PATCH", f"/api/cron/{a}", {"cron_expression": "x"}),
        ("cron patch phase", "PATCH", f"/api/cron/{a}", {"phase": "scan"}),
        ("cron patch bad phase", "PATCH", f"/api/cron/{a}", {"phase": "validate"}),
        ("cron patch strategy blank", "PATCH", f"/api/cron/{a}", {"strategy": "  "}),
        ("cron patch strategy", "PATCH", f"/api/cron/{a}", {"strategy": " sitemap "}),
        ("cron patch self chain", "PATCH", f"/api/cron/{a}", {"chain_to_id": a}),
        ("cron patch both chain args", "PATCH", f"/api/cron/{a}",
         {"chain_to_id": b, "clear_chain": True}),
        ("cron patch chain", "PATCH", f"/api/cron/{a}", {"chain_to_id": b}),
        ("cron patch cycle", "PATCH", f"/api/cron/{b}", {"chain_to_id": a}),
        ("cron patch clear chain", "PATCH", f"/api/cron/{a}", {"clear_chain": True}),
        ("cron patch empty", "PATCH", f"/api/cron/{a}", {}),
        ("cron patch 404", "PATCH", "/api/cron/9999999", {"phase": "scan"}),
        ("cron toggle", "POST", f"/api/cron/{doomed}/toggle", None),
        ("cron toggle back", "POST", f"/api/cron/{doomed}/toggle", None),
        ("cron toggle 404", "POST", "/api/cron/9999999/toggle", None),
        ("cron delete dependent target", "DELETE", f"/api/cron/{target}", None),
        ("cron delete", "DELETE", f"/api/cron/{doomed}", None),
        ("cron delete again", "DELETE", f"/api/cron/{doomed}", None),
        ("cron delete 404", "DELETE", "/api/cron/9999999", None),
        # ── Pre-SPA form endpoints (outside /api) ────────────────────────
        ("rate settings save", "POST", f"/shops/{SHOP}/rate-settings",
         {"download_delay": 2.5, "concurrent_requests_per_domain": 4}),
        ("rate settings resave", "POST", f"/shops/{SHOP}/rate-settings",
         {"download_delay": 1.0, "concurrent_requests_per_domain": 2}),
        ("rate settings bad delay", "POST", f"/shops/{SHOP}/rate-settings",
         {"download_delay": 99, "concurrent_requests_per_domain": 2}),
        ("rate settings bad concurrency", "POST", f"/shops/{SHOP}/rate-settings",
         {"download_delay": 1.0, "concurrent_requests_per_domain": 99}),
        ("rate settings bad shop", "POST", "/shops/no-such-shop/rate-settings",
         {"download_delay": 1.0, "concurrent_requests_per_domain": 2}),
        ("scrape url 404", "POST", "/scrape/url/999999999", None),
        ("scrape filtered no filter", "POST", "/scrape/filtered", None),
        ("scrape filtered bad shop", "POST", "/scrape/filtered?shop=no-such-shop", None),
        ("scrape filtered no match", "POST",
         "/scrape/filtered?q=zzzz-no-such-title-zzzz", None),
        # Bulk rescrape only reads.
        ("bulk rescrape", "POST", "/api/issues/bulk-rescrape",
         {"issue_type": "missing_isbn", "shop": SHOP}),
        ("bulk rescrape no type", "POST", "/api/issues/bulk-rescrape", {"shop": SHOP}),
        ("bulk rescrape no shop", "POST", "/api/issues/bulk-rescrape",
         {"issue_type": "missing_isbn"}),
        ("bulk rescrape bad shop", "POST", "/api/issues/bulk-rescrape",
         {"issue_type": "missing_isbn", "shop": "no-such-shop"}),
        # ── Spawning endpoints: refusal paths only ───────────────────────
        # A success here would fire a real crawl, and Python's spawn targets
        # the PRODUCTION database by design (it docker-execs into the scraper
        # container with a hardcoded DSN). Every case below is verified to
        # stop at a 4xx before the spawn; the success paths are exercised
        # against the test DB by hand, per php/README.md.
        ("create run bad phase", "POST", "/api/runs",
         {"shop": SHOP, "phase": "sitemap"}),
        ("create run bad shop", "POST", "/api/runs",
         {"shop": "no-such-shop", "phase": "scan"}),
        ("create run already active", "POST", "/api/runs",
         {"shop": SHOP, "phase": "scan"}),
        ("rerun 404", "POST", "/api/runs/999999999/rerun", None),
        ("rerun non-terminal", "POST", f"/api/runs/{run2}/rerun", None),
        ("rerun blocked by active", "POST", f"/api/runs/{done}/rerun", None),
        ("continue 404", "POST", "/api/runs/999999999/continue", None),
        ("continue non-failed", "POST", f"/api/runs/{done}/continue", None),
        ("continue nothing pending", "POST", f"/api/runs/{failed_empty}/continue", None),
        ("continue blocked by active", "POST", f"/api/runs/{failed_pending}/continue", None),
        ("retry 404", "POST", "/api/runs/999999999/retry", None),
        ("retry non-scan phase", "POST", f"/api/runs/{discover_run}/retry", None),
        ("retry no match", "POST",
         f"/api/runs/{run}/retry?error_reason=http_404&http_status=404", None),
        ("retry empty run", "POST", f"/api/runs/{failed_empty}/retry", None),
        # Live run: resets rows and emits the event, but spawns nothing.
        ("retry live run", "POST",
         f"/api/runs/{run}/retry?error_reason_is_null=true&http_status_is_null=true", None),
        ("retry live run again", "POST", f"/api/runs/{run}/retry", None),
    ]


# The pre-SPA endpoints take form fields, not JSON — FastAPI declares them
# with Form(...), so a JSON body would be a 422 on both sides and prove
# nothing about the handler.
FORM_ENDPOINTS = ("/shops/",)


#: Keys whose integer value is a row id. Everything else is a count, a day
#: span, an HTTP status — and must be left alone.
ID_KEYS = frozenset({
    "id", "run_id", "shop_book_id", "previous_book_id", "existing_book_id",
    "chain_to_id", "cron_job_id",
})


#: URL prefix -> the label prefix whose ids may appear under it.
#:
#: Ids are only unique WITHIN a table, so `labels` (value -> label) collapses
#: whenever a run and a shop_book happen to share an integer — and then a run
#: id in a path was rewritten as <shop_book_linked>. Restricting each path to
#: the labels that can legitimately appear in it removes the guess.
PATH_LABEL_PREFIX = (
    ("/api/runs/", "run_"),
    ("/api/shop-books/", "shop_book_"),
    ("/api/issues/", "issue_"),
    ("/api/cron/", "cron_"),
)

#: Field name -> the label prefix its ids come from. Same reason as above: a
#: value alone cannot say which table it belongs to. A key absent here (`id`)
#: is resolved from the request path instead.
KEY_LABEL_PREFIX = {
    "run_id": "run_",
    "shop_book_id": "shop_book_",
    "chain_to_id": "cron_",
    "cron_job_id": "cron_",
}


def group_labels(ids: dict[str, int]) -> dict[str, dict[int, str]]:
    """Fixture ids as ONE MAP PER KIND. There is deliberately no merged map.

    A single value -> label dict cannot work: ids are unique only within their
    table, and after a reseed every sequence restarts, so a run and a cron job
    both being id 5 is normal. That dict kept whichever came last, which first
    mislabelled a run id as <shop_book_linked> and then — once the surviving
    entry belonged to another kind — stopped substituting at all and froze a
    raw `5` into a path.

    Nor is there a merged fallback for ids whose kind cannot be determined.
    `POST /api/cron` returns the id of the row it just created, under the
    generic key `id` and at a path with no id in it; a merged map labelled that
    brand-new id as <run_discover> purely because the integers matched. An id
    of undeterminable kind is an unknown id, which freezes as <id>.
    """
    prefixes = [prefix for _, prefix in PATH_LABEL_PREFIX]
    grouped: dict[str, dict[int, str]] = {prefix: {} for prefix in prefixes}
    for label, value in ids.items():
        for prefix in prefixes:
            if label.startswith(prefix):
                grouped[prefix][value] = label
    return grouped


def label_for(
    value: int, labels: dict[str, dict[int, str]], key: str, path: str
) -> str | None:
    """The fixture label for `value`, or None if it is not that kind of id.

    Restricted by kind — by field name where the name says it, otherwise by
    the path being requested — because the same integer means different rows
    in different tables.
    """
    prefix = KEY_LABEL_PREFIX.get(key)
    if prefix is None:
        prefix = next(
            (p for url, p in PATH_LABEL_PREFIX if path.startswith(url)), None
        )
    return labels.get(prefix or "", {}).get(value)


def normalise_path(path: str, labels: dict[str, dict[int, str]]) -> str:
    """Ids in a URL path become labels.

    The path proper is fair game — a segment there IS an id. The QUERY STRING
    is not: `?http_status=404` is a status code, and one fixture run's id was
    404, so it froze as `http_status=<run_failed_empty>` and the replay sent
    nonsense. Query parameters are therefore gated on the parameter name, the
    same rule the response and body normalisers already follow.
    """
    head, sep, query = path.partition("?")
    allowed = next(
        (prefix for url, prefix in PATH_LABEL_PREFIX if head.startswith(url)), None
    )
    for row_id, label in labels.get(allowed or "", {}).items():
        head = re.sub(rf"\b{row_id}\b", f"<{label}>", head)

    if sep == "":
        return head

    pairs = []
    for pair in query.split("&"):
        key, eq, value = pair.partition("=")
        if key in ID_KEYS and value.isdigit():
            label = label_for(int(value), labels, key, head)
            if label is not None:
                value = f"<{label}>"
        pairs.append(f"{key}{eq}{value}")
    return f"{head}?{'&'.join(pairs)}"


def normalise_response(
    value: object, labels: dict[str, dict[int, str]], key: str = "", path: str = ""
) -> object:
    """Ids in a response become placeholders so it can be frozen.

    Gated on the KEY, never on the value. Three times over I wrote this the
    other way — substituting any integer that looked id-shaped — and three
    times it corrupted something: first counts above an arbitrary threshold,
    then the 13 inside 2013, then `{"days": 30}`, because a fixture row
    happened to have id 30. A count that collides with an id is not an id.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if key not in ID_KEYS:
            return value
        return label_for(value, labels, key, path) or "<id>"
    if isinstance(value, str):
        # A now()-derived timestamp cannot be frozen; that it came back as one
        # is the assertable part.
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?"
                        r"([+-]\d{2}:?\d{2}|Z)?", value):
            return "<timestamp>"
        # Only the one message shape that embeds an id in prose. Blanket
        # label-substitution in free text would rewrite any title containing
        # the digits of a fixture id.
        return re.sub(r"(run #)\d+", r"\1<id>", value)
    if isinstance(value, dict):
        return {
            k: normalise_response(v, labels, k, path) for k, v in value.items()
        }
    if isinstance(value, list):
        return [normalise_response(v, labels, key, path) for v in value]
    return value


def normalise_body(
    value: object, labels: dict[str, dict[int, str]], key: str = "", path: str = ""
) -> object:
    """Fixture ids in a REQUEST body become labels; nothing else changes.

    Also key-gated, and for a second reason on top of the collision above:
    several cases deliberately send an id that does not exist —
    `chain_to_id: 999999` is how "chain target not found" is provoked — so an
    unknown id must survive as itself.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if key not in ID_KEYS:
            return value
        return label_for(value, labels, key, path) or value
    if isinstance(value, dict):
        return {k: normalise_body(v, labels, k, path) for k, v in value.items()}
    if isinstance(value, list):
        return [normalise_body(v, labels, key, path) for v in value]
    return value


def call(port: int, method: str, path: str, body: dict | None) -> dict:
    form = any(path.startswith(prefix) for prefix in FORM_ENDPOINTS)
    if body is None:
        data, headers = None, {}
    elif form:
        data = urllib.parse.urlencode(body).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
    else:
        data = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=headers,
    )
    try:
        # 303s are the answer for the form endpoints, so the redirect target is
        # compared instead of being followed.
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(request, timeout=60) as response:
            payload = response.read()
            status = response.status
            location = response.headers.get("Location")
    except urllib.error.HTTPError as error:
        payload, status = error.read(), error.code
        location = error.headers.get("Location")
    except Exception as exc:  # connection refused, timeout…
        return {"_status": "ERROR", "_error": str(exc)}
    try:
        decoded = json.loads(payload)
    except ValueError:
        decoded = {"_raw": payload.decode("utf-8", "replace")[:400]}

    result = {"_status": status, "body": decoded}
    if location is not None:
        result["_location"] = location

    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Leave a 3xx alone so its Location can be compared."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


# ── Comparison ──────────────────────────────────────────────────────────────

# Projections of every table a write endpoint can touch. Full rows where the
# table is small; the interesting columns where it is not.
STATE_QUERIES = {
    "validation_issues": "select id, lifecycle_state, acknowledged_at, resolved_at,"
                         " snoozed_until from validation_issues order by id",
    "cron_jobs": "select id, shop_id, phase, strategy, args, cron_expression, enabled,"
                 " last_run_at, chain_to_job_id from cron_jobs order by id",
    "scrape_runs": "select id, shop_id, phase, status, finished_at, urls_processed,"
                   " close_reason, resumable_after_failure from scrape_runs order by id",
    "scrape_run_events": "select id, run_id, event_type, actor, payload"
                         " from scrape_run_events order by id",
    "scrape_failures": "select id, lifecycle_state, acknowledged_at, acknowledged_note"
                       " from scrape_failures order by id",
    "scrape_url_items": "select id, run_id, status, claimed_at, done_at, http_status,"
                        " response_bytes, retry_count, attempts from scrape_url_items"
                        " order by id",
    "shop_books": "select id, book_id from shop_books order by id",
    "shop_settings": "select shop_id, key, value, type from shop_settings"
                     " order by shop_id, key",
    "books": "select id, data_source, title, year, publisher_id from books order by id",
    "book_isbns": "select id, book_id, isbn, isbn_type from book_isbns order by id",
    "authors": "select id, name, normalized_name from authors order by id",
    "book_authors": "select book_id, author_id, role, position from book_authors"
                    " order by book_id, author_id, role",
    "publishers": "select id, name from publishers order by id",
}

# Both stacks stamp now() from their own process, so timestamps can only be
# compared within a window. Wide enough to cover a slow case list, narrow
# enough that a wrong-by-days value still fails.
TIME_TOLERANCE = dt.timedelta(seconds=300)


def read_state(database: str) -> dict[str, list[tuple]]:
    engine = sa.create_engine(dsn(database), poolclass=sa.pool.NullPool)
    with engine.connect() as c:
        return {name: [tuple(r) for r in c.execute(sa.text(query))]
                for name, query in STATE_QUERIES.items()}


def cell_differs(left, right) -> bool:
    if isinstance(left, dt.datetime) and isinstance(right, dt.datetime):
        return abs(left - right) > TIME_TOLERANCE
    return left != right


def diff_state(py: dict, php: dict) -> list[str]:
    out = []
    for table, py_rows in py.items():
        php_rows = php[table]
        if len(py_rows) != len(php_rows):
            out.append(f"{table}: {len(py_rows)} rows in python, {len(php_rows)} in php")
        for index, (left, right) in enumerate(zip(py_rows, php_rows)):
            for column, (a, b) in enumerate(zip(left, right)):
                if cell_differs(a, b):
                    out.append(
                        f"{table}[row {index}, col {column}]: python={a!r} php={b!r}"
                    )
    return out


def diff_json(a, b, path="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{path}.{key}: extra in php")
            elif key not in b:
                out.append(f"{path}.{key}: MISSING IN PHP")
            else:
                out += diff_json(a[key], b[key], f"{path}.{key}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        out = [] if len(a) == len(b) else [f"{path}: length {len(a)} vs {len(b)}"]
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_json(x, y, f"{path}[{i}]")
        return out
    # snoozed_until is now()-derived; compare the date, not the microsecond.
    if path.endswith(".snoozed_until") and isinstance(a, str) and isinstance(b, str):
        return [] if a[:16] == b[:16] else [f"{path}: python={a!r} php={b!r}"]
    if isinstance(a, str) and isinstance(b, str):
        a, b = normalise_set_repr(a), normalise_set_repr(b)
    return [] if a == b else [f"{path}: python={a!r} php={b!r}"]


# Python interpolates a `set` straight into one error message, and CPython
# randomises string hashing per process — so that message's member order is
# not reproducible even between two runs of Python itself. Compare the
# members, not their order.
SET_REPR_RE = re.compile(r"^(.*)\{((?:'[^']*'(?:, )?)+)\}(.*)$")


def normalise_set_repr(value: str) -> str:
    match = SET_REPR_RE.match(value)
    if match is None:
        return value
    members = sorted(part.strip() for part in match.group(2).split(","))

    return f"{match.group(1)}{{{', '.join(members)}}}{match.group(3)}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--keep", action="store_true",
                        help="leave the two clone databases in place for inspection")
    parser.add_argument(
        "--freeze",
        metavar="PATH",
        nargs="?",
        const=str(FREEZE_TO),
        help="after every case matches, write them out as a characterisation "
        "golden the dashboard suite can replay. Refuses to write on any "
        "difference.",
    )
    args = parser.parse_args()

    guard()
    print(f"building {TEST_DB} from php/schema + SyntheticShop")
    built = subprocess.run(
        [PHP, "bin/fixture-db", "--recreate", f"--database={dsn(TEST_DB)}"],
        cwd=ROOT / "php", capture_output=True, text=True)
    if built.returncode != 0:
        sys.exit(f"could not build the fixture database:\n{built.stderr.strip()}")

    print(f"seeding fixtures into {TEST_DB}")
    ids = seed_fixtures()
    print(f"cloning {TEST_DB} -> {PY_DB}, {PHP_DB}")
    clone_databases()
    # The clones have them now; the base must not keep them.
    clear_fixtures()

    # A fresh ISBN per run: book_isbns.isbn is globally unique and the clone
    # carries the previous run's row.
    marker = f"{int(time.time()) % 10_000_000_000:010d}"

    # Fixture ids -> labels, one map per kind, so responses can be frozen
    # without their row ids and without confusing one table's id for another's.
    labels = group_labels(ids)
    frozen: list[dict] = []

    python_server = php_server = None
    failures = 0
    try:
        python_server = start_python()
        php_server = start_php()
        wait_ready(PY_PORT, "python dashboard")
        wait_ready(PHP_PORT, "php dashboard")

        for label, method, path, body in cases(ids, marker):
            py = call(PY_PORT, method, path, body)
            php = call(PHP_PORT, method, path, body)
            differences = diff_json(py, php)
            if differences:
                failures += 1
                print(f"  DIFFER {label}  ({method} {path})")
                shown = differences if args.verbose else differences[:4]
                for line in shown:
                    print(f"         {line}")
                if len(differences) > len(shown):
                    print(f"         … {len(differences) - len(shown)} more (--verbose)")
            else:
                frozen.append({
                    "label": label,
                    "method": method,
                    "path": normalise_path(path, labels),
                    "body": normalise_body(body, labels, path=path),
                    "expected": normalise_response(php, labels, path=path),
                })
                extra = ""
                body = py.get("body")
                if isinstance(body, dict):
                    for key in ("count", "acknowledged", "unacknowledged", "retried"):
                        if key in body:
                            extra = f"  {key}={body[key]}"
                            break
                print(f"  OK     {label}  [{py['_status']}]{extra}")

        print("\ncomparing database state")
        state_differences = diff_state(read_state(PY_DB), read_state(PHP_DB))
        if state_differences:
            failures += 1
            shown = state_differences if args.verbose else state_differences[:15]
            for line in shown:
                print(f"  DB     {line}")
            if len(state_differences) > len(shown):
                print(f"         … {len(state_differences) - len(shown)} more (--verbose)")
        else:
            print("  OK     every table identical")
    finally:
        stop(python_server)
        stop(php_server)
        if not args.keep:
            drop_databases()

    total = len(cases(ids, marker)) + 1
    print(f"\n{total - failures}/{total} checks identical")

    if args.freeze:
        if failures:
            print(
                f"NOT frozen — {failures} check(s) differ. The golden may only "
                "record behaviour both stacks agree on."
            )
        else:
            path = Path(args.freeze)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(frozen, indent=1, ensure_ascii=False) + "\n")
            print(f"froze {len(frozen)} case(s) to {path}")

    return failures


if __name__ == "__main__":
    sys.exit(main())
