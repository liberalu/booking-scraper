#!/usr/bin/env python
"""Compare the PHP dashboard's JSON API against the Python one, endpoint by
endpoint.

Both dashboards read the same Postgres and serve the same React SPA, so a
ported endpoint is correct exactly when its payload is indistinguishable
from Python's. Run both dashboards, then:

    python php/tools/api_diff.py
    python php/tools/api_diff.py --verbose        # show every difference
    python php/tools/api_diff.py --py :8001 --php :8002

Both sides are fetched as close to simultaneously as possible: several
fields are clock-relative ("4w ago", startedH) and drift between calls.

Exit code is the number of endpoints that differ, so this works as a gate.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PHP = "/opt/homebrew/opt/php@8.4/bin/php"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _testdb import TEST_DSN, php_dsn  # noqa: E402

MAIN_DSN = "postgresql+psycopg2://postgres:postgres@localhost:5432/book_scraper"

#: Ports used only by --freeze, so a manually-run pair on 8001/8002 is
#: untouched. Bound-check before use: a detached server whose parent died keeps
#: its port and becomes invisible to pgrep, which cost an hour of "address
#: already in use" against a port nothing appeared to hold.
FREEZE_PY_PORT, FREEZE_PHP_PORT = 8031, 8032


def assert_ports_free(*ports: int) -> None:
    import socket

    for port in ports:
        probe = socket.socket()
        # SO_REUSEADDR because uvicorn and `php -S` both set it. Without it the
        # probe fails on leftover TIME_WAIT connections from the previous run
        # and reports a busy port that would in fact bind fine.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            raise SystemExit(
                f"port {port} is already in use ({error.strerror}). An earlier "
                f"run may have left a detached server behind; "
                f"`lsof -nP -iTCP:{port} -sTCP:LISTEN` finds it."
            ) from error
        finally:
            probe.close()


FREEZE_TO = ROOT / "php" / "dashboard" / "tests" / "golden" / "api_shapes.json"
#: Placeholders resolved from whichever database is under test.
#:
#: The list below was written against the main catalogue, so every detail route
#: carried a literal id and 404s against any other database — which would have
#: frozen "not found" as the expected shape for half the API. A placeholder is
#: resolved to a row that actually exists, so the route is exercised.
#: Resolved against the SYNTHETIC shop wherever it can be, not against
#: "whatever row is first". The synthetic shop is built from nothing by
#: php/src/Testing/SyntheticShop.php, so its rows are the same every time —
#: while the copied catalogue moves with every crawl, and a detail route whose
#: row gained or lost a null would change the frozen shape for no reason.
SYNTHETIC = "(select id from shops where name = 'synthetic')"

ID_PLACEHOLDERS = {
    # The OLDEST run, not the newest: that is the one the fixture hangs its
    # queue items, events, failures and changes off. Pointed at the newest, the
    # run detail, queue, live and books endpoints all froze empty.
    "{run}": f"select id from scrape_runs where shop_id = {SYNTHETIC}"
    " order by id limit 1",
    "{run_scan}": f"select id from scrape_runs where shop_id = {SYNTHETIC}"
    " and phase = 'scan' order by id limit 1",
    # A canonical that a shop_book actually points at, so the detail route's
    # shops[] and price series are populated.
    "{book}": "select book_id from shop_books where book_id is not null"
    " order by id limit 1",
    "{shop_book}": f"select id from shop_books where shop_id = {SYNTHETIC}"
    " order by id limit 1",
    "{issue}": f"select id from validation_issues where shop_id = {SYNTHETIC}"
    " order by id limit 1",
    "{url}": f"select id from discovered_urls where shop_id = {SYNTHETIC}"
    " order by id limit 1",
    "{cron}": f"select id from cron_jobs where shop_id = {SYNTHETIC}"
    " order by id limit 1",
    # Not ids, but the same problem: the list was written with literal shop
    # names, titles and ISBNs from the real catalogue, so against any other
    # database those filters matched nothing and the shape froze as an empty
    # list — which pins that a field is a list and nothing about its rows.
    "{shop}": "select name from shops order by id limit 1",
    # A CANONICAL ISBN: /api/books searches book_isbns, so a shop-only ISBN
    # matched nothing.
    "{isbn}": "select isbn from book_isbns order by isbn limit 1",
    # A CANONICAL title: /api/books and the export both search books, not
    # shop_books, so a shop-only title matched nothing.
    "{title}": "select title from books order by id limit 1",
    "{year}": "select year from books where year is not null order by year limit 1",
    "{issue_type}": "select issue from validation_issues order by issue limit 1",
}

#: Ids chosen to be absent, so the 404 paths stay covered on purpose rather
#: than by accident.
MISSING_ID = "999999999"


def build_fixture_db(template_dsn: str) -> str:
    """Build a database holding NOTHING but the fixture, and return its DSN.

    Not the seeded database: its list endpoints read every shop, so the shape
    of their first row came from the copied catalogue — and the copy is taken
    from the live one, which moves. A reseed turned a field from `str` into
    `null` and the golden failed with nothing having regressed. Re-freezing is
    not an answer once Python is gone: there would be nothing left to agree
    with, so the "fix" would be to bless whatever PHP currently emits.

    Delegated to `php bin/fixture-db`, which builds the schema from
    php/schema's baseline and then the fixture. Both are code, so the same
    database comes back every time — with or without Python.
    """
    result = subprocess.run(
        [PHP, "bin/fixture-db", "--recreate", f"--database={template_dsn}"],
        cwd=ROOT / "php",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit("could not build the fixture database:\n" + result.stderr.strip())
    return result.stdout.strip()


def resolve_placeholders(endpoints: list[str], dsn: str) -> list[tuple[str, str]]:
    """Pair each endpoint with its resolved form: (template, resolved).

    Pairs rather than a resolved->template dict because two placeholders can
    resolve to the SAME row — {run} and {run_scan} both land on the newest run
    when that run's phase is scan — and a dict silently collapses them, so the
    golden would record one template twice and the other never.

    The golden stores the template, not the resolved id: concrete ids belong to
    whichever database the freeze ran against, and the cron row is planted with
    a fresh serial then removed, so a frozen literal id would 404 on replay.
    """
    import sqlalchemy as sa

    engine = sa.create_engine(dsn, poolclass=sa.pool.NullPool)
    resolved = {}
    with engine.connect() as conn:
        for token, query in ID_PLACEHOLDERS.items():
            value = conn.execute(sa.text(query)).scalar()
            if value is None:
                raise SystemExit(
                    f"cannot resolve {token}: the database under test has no row "
                    f"for `{query}`. Seed it first."
                )
            # Percent-encoded: some of these are titles with spaces and
            # Lithuanian diacritics, and they land in a query string. PHP's
            # rawurlencode() produces the same bytes.
            resolved[token] = urllib.parse.quote(str(value), safe="")

    out = []
    for template in endpoints:
        endpoint = template
        for token, value in resolved.items():
            endpoint = endpoint.replace(token, value)
        out.append((template, endpoint))
    return out


# Endpoints ported so far. Each entry is compared field by field.
ENDPOINTS = [
    "/api/overview",
    "/api/shops",
    "/api/books/stats",
    "/api/books/years",
    "/api/books?per_page=3&year=2024",
    "/api/books?per_page=3&data_source=shop_inferred",
    "/api/books?per_page=3&search={isbn}",
    "/api/books/{book}",
    "/api/books/{book}/prices",
    "/api/books/999999999",
    "/api/prices?per_page=3",
    "/api/prices?days=30&per_page=5",
    "/api/prices?days=30&shop={shop}&per_page=3",
    "/api/cron",
    "/api/shops/{shop}",
    "/api/shops/nope",
    "/api/runs/{run}",
    "/api/runs/{run}",
    "/api/runs/999999999",
    "/api/urls/{url}",
    "/api/urls/{url}",
    "/api/urls/999999999",
    "/api/issues?per_page=3",
    "/api/issues?per_page=3&state=new",
    "/api/issues?per_page=3&kind=validation",
    "/api/issues?per_page=3&kind=scrape_failure",
    "/api/issues?per_page=3&severity=critical",
    "/api/issues?per_page=3&severity=warning",
    "/api/issues?per_page=3&sort_by=id&order=asc",
    "/api/issues?per_page=3&sort_by=type",
    "/api/issues?per_page=3&sort_by=shop",
    "/api/issues?per_page=3&sort_by=sev",
    "/api/issues?per_page=3&shop={shop}",
    "/api/issues?per_page=3&issue_type={issue_type}",
    "/api/issues/groups?group_by=type&state=new",
    "/api/issues/groups?group_by=type_shop&state=new",
    "/api/issues/trend?days=14&state=new",
    "/api/issues/trend?days=7",
    "/api/issues/{issue}",
    "/api/issues/999999999",
    "/api/shop-books/{shop_book}",
    "/api/shop-books/{shop_book}",
    "/api/shop-books/999999999",
    "/api/runs/{run}/urls?per_page=3",
    "/api/runs/{run}/urls?per_page=3",
    "/api/runs/{run}/urls?per_page=3",
    "/api/runs/{run}/urls?per_page=3&status=done&sort=done",
    "/api/runs/{run}/urls?per_page=3&sort=status",
    "/api/runs/{run}/live",
    "/api/runs/{run}/live",
    "/api/runs/{run}/live",
    "/api/runs/{run}/live?include_acked=true",
    "/api/runs/999999999/live",
    "/api/runs/{run}/books?type=added&per_page=3",
    "/api/runs/{run}/books?type=updated&per_page=3",
    "/api/runs/{run}/books?type=added",
    "/api/runs/{run}/books?type=bogus",
    "/api/runs/999999999/books",
    "/api/cron/{cron}/detail",
    "/api/cron/{cron}/detail",
    "/api/cron/999999999/detail",
    "/api/books/export?search={title}",
    "/api/books/export?year={year}",
    "/api/schedule",
    "/api/runs/repeated-failures",
    "/api/runs?per_page=10",
    "/api/runs?per_page=5&status=completed",
    "/api/runs?per_page=5&shop={shop}",
    "/api/runs?per_page=5&phase=discover",
    "/api/runs?status=running&per_page=1",
    "/api/shop-books?per_page=5",
    "/api/shop-books?per_page=5&shop={shop}&active=true",
    "/api/shop-books?per_page=5&missing_field=isbn",
    "/api/shop-books?per_page=5&has_isbn=true&linked=linked",
    "/api/shop-books?per_page=5&sort_by=title&sort_order=asc",
    "/api/urls?per_page=5",
    "/api/urls?per_page=5&shop={shop}",
    "/api/urls?per_page=5&failing=true",
    "/api/urls?per_page=5&has_book=true&sort_by=book",
    "/api/urls?per_page=5&shop={shop}&url_type=product",
    # These used to be envelope-only: both stacks sorted on a non-unique
    # column with no tiebreaker, so the rows on a page were arbitrary among
    # ties (339 books share one created_at, 65 shop_books share price 0.00)
    # and two identical calls to the SAME stack disagreed. Both now append an
    # id tiebreaker, so they compare row for row.
    "/api/books?per_page=3",
    "/api/books?per_page=3&has_isbn=true",
    "/api/books?per_page=3&search={title}",
    "/api/books?per_page=3&has_conflicts=true",
    "/api/books?per_page=3&shop_count_min=2",
    "/api/shop-books?per_page=3&sort_by=price&sort_order=asc",
    "/api/urls?per_page=5&sort_by=fails&sort_order=desc",
]

# Endpoints compared on the envelope only. Empty since the id tiebreakers
# landed: every paginated list now has a total order, so page contents are
# reproducible and comparable row for row. Add an entry here only with a
# reason that is not "the sort is unstable" — fix the sort instead.
ENVELOPE_ONLY: set[str] = set()

ENVELOPE_KEYS = (
    "total",
    "page",
    "per_page",
    "pages",
    "kpis",
    "stats",
    "counts",
    "kind",
)

# CSV endpoints, compared as parsed rows rather than as JSON.
#
# These stay under the 500-row export page size, which used to be load-bearing:
# paging the export walked an unstable sort and Python's own export duplicated
# 227 of ~6,300 rows. The list query now has an id tiebreaker, so a larger
# filter would be safe to add here.
CSV_ENDPOINTS = {
    "/api/books/export?search={title}",
    "/api/books/export?year={year}",
}


def fetch_csv(base: str, endpoint: str) -> object:
    """Parse a CSV response into a comparable structure."""
    with urllib.request.urlopen(f"{base}{endpoint}", timeout=120) as response:
        text = response.read().decode("utf-8")

    rows = list(csv.reader(io.StringIO(text)))

    return {"header": rows[0] if rows else [], "rows": sorted(rows[1:])}


def fetch(base: str, endpoint: str) -> object:
    """Fetch and decode, including error responses.

    urlopen raises on any non-2xx, which meant error responses could not be
    compared at all — a stack returning 500 where the other returns 404 read
    as a tooling failure rather than a divergence. The status is folded into
    the compared value so it is part of the contract.
    """
    request = urllib.request.Request(f"{base}{endpoint}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        body = error.read()
        try:
            payload = json.loads(body)
        except ValueError:
            payload = {"_raw": body.decode("utf-8", "replace")[:400]}

        return {
            "_http_status": error.code,
            **(payload if isinstance(payload, dict) else {"_body": payload}),
        }


# Fields measured from "now". Two processes cannot produce the same value,
# so they are compared within a tolerance rather than exactly. Keep this list
# tight: a real divergence hiding behind a fuzzy match is worse than a flake.
CLOCK_RELATIVE_SUFFIXES = ("_age_s", "startedH")

CLOCK_TOLERANCE_S = 2.0


def is_clock_relative(path: str) -> bool:
    field = path.rsplit(".", 1)[-1]

    return any(field.endswith(suffix) for suffix in CLOCK_RELATIVE_SUFFIXES)


def diff(a: object, b: object, path: str = "") -> list[str]:
    """Structural diff. Ints and floats compare by value (Python emits 0.0
    where PHP emits 0; both parse to the same number in JS)."""
    numeric = (int, float)
    if isinstance(a, bool) != isinstance(b, bool):
        return [f"{path}: type {type(a).__name__} vs {type(b).__name__}"]
    if not (isinstance(a, numeric) and isinstance(b, numeric)) and type(a) is not type(
        b
    ):
        return [f"{path}: type {type(a).__name__} vs {type(b).__name__}"]

    if isinstance(a, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{path}.{key}: extra in php")
            elif key not in b:
                out.append(f"{path}.{key}: MISSING IN PHP")
            else:
                out += diff(a[key], b[key], f"{path}.{key}")
        return out
    if isinstance(a, list):
        out = []
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} vs {len(b)}")
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            out += diff(x, y, f"{path}[{i}]")
        return out
    if isinstance(a, numeric) and isinstance(b, numeric) and is_clock_relative(path):
        drift = abs(float(a) - float(b))

        return (
            []
            if drift <= CLOCK_TOLERANCE_S
            else [
                f"{path}: python={a!r} php={b!r} "
                f"(drift {drift:.1f}s > {CLOCK_TOLERANCE_S}s)"
            ]
        )

    return [] if a == b else [f"{path}: python={a!r} php={b!r}"]


def shape(value: object) -> object:
    """A response's type skeleton: keys and types, no values.

    What gets frozen for the read endpoints, because the values are DATA and
    the shape is the CONTRACT. A frozen payload would break the moment anyone
    crawled anything; a frozen shape breaks when a route disappears, a field is
    renamed or dropped, or a type changes — which is what a regression test
    should catch.

    int and float collapse to "number": JSON gives 12 for one stack and 12.0
    for the other depending on how a count was computed, and that distinction
    has never meant anything here.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        # An empty map freezes as the string "{}", not as {}. JSON's {} and []
        # both decode to an empty PHP array, so a bare {} in the golden would
        # be indistinguishable from an empty list on replay — which is exactly
        # the divergence class this caught (attributes, rate_settings: PHP's
        # json_encode renders an empty assoc array as []).
        return {k: shape(v) for k, v in sorted(value.items())} if value else "{}"
    if isinstance(value, list):
        # The first element stands for all of them; an empty list is its own
        # shape, since "no rows" and "rows of this form" are different answers.
        return [shape(value[0])] if value else []
    return "unknown"


def start_python(dsn: str, port: int) -> subprocess.Popen[bytes]:
    env = os.environ | {
        "PYTHONPATH": str(ROOT),
        "DATABASE_URL": dsn,
        # The reaper would mutate runs mid-comparison.
        "REAPER_INTERVAL_SECONDS": "86400",
    }
    return subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "book_scraper.dashboard.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def start_php(dsn: str, port: int) -> subprocess.Popen[bytes]:
    parsed = urllib.parse.urlparse(dsn.replace("+psycopg2", ""))
    env = os.environ | {
        "DB_HOST": parsed.hostname or "127.0.0.1",
        "DB_PORT": str(parsed.port or 5433),
        "DB_DATABASE": (parsed.path or "").lstrip("/"),
    }
    cwd = ROOT / "php" / "dashboard"
    subprocess.run(
        [PHP, "artisan", "config:clear"],
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        check=False,
    )
    return subprocess.Popen(
        [PHP, "artisan", "serve", "--host", "127.0.0.1", "--port", str(port)],
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )


def wait_ready(
    port: int,
    name: str,
    process: subprocess.Popen[bytes] | None = None,
    timeout: float = 90.0,
) -> None:
    """Poll until the server answers, and say why if it never does.

    The child's stderr is surfaced on failure: "did not become ready" on its own
    sends you hunting for a port clash when the real cause is in the first line
    the process printed.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process is not None and process.poll() is not None:
            break
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/overview", timeout=5
            ):
                return
        except urllib.error.HTTPError:
            return
        except Exception:
            time.sleep(0.4)

    detail = ""
    if process is not None:
        process.terminate()
        try:
            _out, err = process.communicate(timeout=5)
            detail = (err or b"").decode("utf-8", "replace").strip()[-1200:]
        except Exception:
            pass
    sys.exit(
        f"{name} did not become ready on :{port}"
        + (f"\n--- its stderr ---\n{detail}" if detail else "")
    )


def free_port(port: int) -> None:
    """Kill whatever still listens on `port`.

    stop() signals the process group it started, but `uv run uvicorn` leaves a
    grandchild that outlives it and keeps the socket — invisible to pgrep,
    visible only to netstat. This has leaked a port three times, so teardown
    now finishes the job by the one identifier that is definitely right: the
    listener itself.
    """
    try:
        found = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    for pid in found.stdout.split():
        with contextlib.suppress(ProcessLookupError, PermissionError, ValueError):
            os.kill(int(pid), signal.SIGKILL)


def stop(process: subprocess.Popen[bytes] | None) -> None:
    if process is None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=10)
    except (ProcessLookupError, PermissionError):
        pass
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--py", default="http://localhost:8001")
    parser.add_argument("--php", default="http://127.0.0.1:8002")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="start both dashboards against the PHP test database, compare, and "
        "write each endpoint's status and response SHAPE as a characterisation "
        "golden. Refuses on any difference.",
    )
    args = parser.parse_args()

    servers: list[subprocess.Popen[bytes] | None] = []
    # dict.fromkeys dedupes while preserving order: the list was written with
    # several concrete ids per route ("/api/runs/466", "/api/runs/501"), and
    # templating those into {run} makes them the same request.
    endpoints = list(dict.fromkeys(ENDPOINTS))
    envelope_only = set(ENVELOPE_ONLY)

    if args.freeze:
        # Self-hosted against the test database: the golden has to be replayable,
        # and the main catalogue changes whenever anything is crawled.
        assert_ports_free(FREEZE_PY_PORT, FREEZE_PHP_PORT)
        dsn = build_fixture_db(php_dsn(TEST_DSN))
        print(f"starting both dashboards against {dsn.rsplit('/', 1)[-1]}")
        # Placeholders resolve BEFORE anything is started. Resolution can fail
        # fatally, and it used to do so after the servers were up but before
        # the try/finally that stops them — leaking two detached processes that
        # held their ports and were invisible to pgrep.
        pairs = resolve_placeholders(endpoints, dsn)
        envelope_pairs = resolve_placeholders(sorted(envelope_only), dsn)
        servers = [start_python(dsn, FREEZE_PY_PORT), start_php(dsn, FREEZE_PHP_PORT)]
        try:
            wait_ready(FREEZE_PY_PORT, "python dashboard", servers[0])
            wait_ready(FREEZE_PHP_PORT, "php dashboard", servers[1])
        except BaseException:
            for server in servers:
                stop(server)
            raise
        args.py = f"http://127.0.0.1:{FREEZE_PY_PORT}"
        args.php = f"http://127.0.0.1:{FREEZE_PHP_PORT}"
    else:
        pairs = resolve_placeholders(endpoints, MAIN_DSN)
        envelope_pairs = resolve_placeholders(sorted(envelope_only), MAIN_DSN)

    frozen: list[dict] = []
    failures = 0
    try:
        envelope_resolved = {resolved for _, resolved in envelope_pairs}
        for template, endpoint in pairs + sorted(envelope_pairs):
            # Keyed on the TEMPLATE: CSV_ENDPOINTS holds placeholders.
            getter = fetch_csv if template in CSV_ENDPOINTS else fetch
            with ThreadPoolExecutor(max_workers=2) as pool:
                py_future = pool.submit(getter, args.py, endpoint)
                php_future = pool.submit(getter, args.php, endpoint)
                try:
                    py, php = py_future.result(), php_future.result()
                except Exception as exc:
                    print(f"  ERROR  {endpoint}\n         {exc}")
                    failures += 1
                    continue

            if endpoint in envelope_resolved:
                py = {k: v for k, v in py.items() if k in ENVELOPE_KEYS}
                php = {k: v for k, v in php.items() if k in ENVELOPE_KEYS}
                label = f"{endpoint}  (envelope only: unstable sort)"
            else:
                label = endpoint

            differences = diff(py, php)
            if differences:
                failures += 1
                print(f"  DIFFER {label}  ({len(differences)})")
                shown = differences if args.verbose else differences[:5]
                for line in shown:
                    print(f"         {line}")
                if len(differences) > len(shown):
                    print(
                        f"         … {len(differences) - len(shown)} more (--verbose)"
                    )
            else:
                print(f"  OK     {label}")
                # Not every endpoint answers with an object: /books/years is a
                # bare JSON list, and .get() on it is an AttributeError.
                frozen.append(
                    {
                        "endpoint": template,
                        "status": php.get("_http_status", 200)
                        if isinstance(php, dict)
                        else 200,
                        "shape": shape(php),
                    }
                )
    finally:
        for server in servers:
            stop(server)
        if args.freeze:
            free_port(FREEZE_PY_PORT)
            free_port(FREEZE_PHP_PORT)

    total = len(endpoints) + len(envelope_only)
    print(f"\n{total - failures}/{total} endpoints identical")

    if args.freeze:
        if failures:
            print("NOT frozen — the golden may only record agreed behaviour.")
        else:
            FREEZE_TO.parent.mkdir(parents=True, exist_ok=True)
            FREEZE_TO.write_text(
                json.dumps(frozen, indent=1, ensure_ascii=False) + "\n"
            )
            print(f"froze {len(frozen)} endpoint(s) to {FREEZE_TO}")

    return failures


if __name__ == "__main__":
    sys.exit(main())
