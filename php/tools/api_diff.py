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
import json
import sys
import csv
import io
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# Endpoints ported so far. Each entry is compared field by field.
ENDPOINTS = [
    "/api/overview",
    "/api/shops",
    "/api/books/stats",
    "/api/books/years",
    "/api/books?per_page=3&year=2024",
    "/api/books?per_page=3&data_source=shop_inferred",
    "/api/books?per_page=3&search=9789986971535",
    "/api/books/1",
    "/api/books/1/prices",
    "/api/books/999999999",
    "/api/prices?per_page=3",
    "/api/prices?days=30&per_page=5",
    "/api/prices?days=30&shop=vaga&per_page=3",
    "/api/cron",
    "/api/shops/vaga",
    "/api/shops/pegasas",
    "/api/shops/nope",
    "/api/runs/842",
    "/api/runs/841",
    "/api/runs/999999999",
    "/api/urls/1",
    "/api/urls/2",
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
    "/api/issues?per_page=3&shop=vaga",
    "/api/issues?per_page=3&issue_type=unmatched_has_isbn",
    "/api/issues/groups?group_by=type&state=new",
    "/api/issues/groups?group_by=type_shop&state=new",
    "/api/issues/trend?days=14&state=new",
    "/api/issues/trend?days=7",
    "/api/issues/15202",
    "/api/issues/999999999",
    "/api/shop-books/341",
    "/api/shop-books/1",
    "/api/shop-books/999999999",
    "/api/runs/842/urls?per_page=3",
    "/api/runs/841/urls?per_page=3",
    "/api/runs/836/urls?per_page=3",
    "/api/runs/841/urls?per_page=3&status=done&sort=done",
    "/api/runs/841/urls?per_page=3&sort=status",
    "/api/runs/842/live",
    "/api/runs/841/live",
    "/api/runs/836/live",
    "/api/runs/841/live?include_acked=true",
    "/api/runs/999999999/live",
    "/api/runs/390/books?type=added&per_page=3",
    "/api/runs/423/books?type=updated&per_page=3",
    "/api/runs/842/books?type=added",
    "/api/runs/842/books?type=bogus",
    "/api/runs/999999999/books",
    "/api/cron/1/detail",
    "/api/cron/2/detail",
    "/api/cron/999999/detail",
    "/api/books/export?search=Tolkien",
    "/api/books/export?year=1975",
    "/api/schedule",
    "/api/runs/repeated-failures",
    "/api/runs?per_page=10",
    "/api/runs?per_page=5&status=completed",
    "/api/runs?per_page=5&shop=vaga",
    "/api/runs?per_page=5&phase=discover",
    "/api/runs?status=running&per_page=1",
    "/api/shop-books?per_page=5",
    "/api/shop-books?per_page=5&shop=vaga&active=true",
    "/api/shop-books?per_page=5&missing_field=isbn",
    "/api/shop-books?per_page=5&has_isbn=true&linked=linked",
    "/api/shop-books?per_page=5&sort_by=title&sort_order=asc",
    "/api/urls?per_page=5",
    "/api/urls?per_page=5&shop=vaga",
    "/api/urls?per_page=5&failing=true",
    "/api/urls?per_page=5&has_book=true&sort_by=book",
    "/api/urls?per_page=5&shop=pegasas&url_type=product",
    # These used to be envelope-only: both stacks sorted on a non-unique
    # column with no tiebreaker, so the rows on a page were arbitrary among
    # ties (339 books share one created_at, 65 shop_books share price 0.00)
    # and two identical calls to the SAME stack disagreed. Both now append an
    # id tiebreaker, so they compare row for row.
    "/api/books?per_page=3",
    "/api/books?per_page=3&has_isbn=true",
    "/api/books?per_page=3&search=Tolkien",
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

ENVELOPE_KEYS = ("total", "page", "per_page", "pages", "kpis", "stats", "counts", "kind")

# CSV endpoints, compared as parsed rows rather than as JSON.
#
# These stay under the 500-row export page size, which used to be load-bearing:
# paging the export walked an unstable sort and Python's own export duplicated
# 227 of ~6,300 rows. The list query now has an id tiebreaker, so a larger
# filter would be safe to add here.
CSV_ENDPOINTS = {
    "/api/books/export?search=Tolkien",
    "/api/books/export?year=1975",
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

        return {"_http_status": error.code, **(payload if isinstance(payload, dict) else {"_body": payload})}


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
    if not (isinstance(a, numeric) and isinstance(b, numeric)) and type(a) is not type(b):
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
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
        return out
    if isinstance(a, numeric) and isinstance(b, numeric) and is_clock_relative(path):
        drift = abs(float(a) - float(b))

        return (
            []
            if drift <= CLOCK_TOLERANCE_S
            else [f"{path}: python={a!r} php={b!r} (drift {drift:.1f}s > {CLOCK_TOLERANCE_S}s)"]
        )

    return [] if a == b else [f"{path}: python={a!r} php={b!r}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--py", default="http://localhost:8001")
    parser.add_argument("--php", default="http://127.0.0.1:8002")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    failures = 0
    for endpoint in ENDPOINTS + sorted(ENVELOPE_ONLY):
        # Fetch both at once: several fields are clock-relative.
        getter = fetch_csv if endpoint in CSV_ENDPOINTS else fetch
        with ThreadPoolExecutor(max_workers=2) as pool:
            py_future = pool.submit(getter, args.py, endpoint)
            php_future = pool.submit(getter, args.php, endpoint)
            try:
                py, php = py_future.result(), php_future.result()
            except Exception as exc:
                print(f"  ERROR  {endpoint}\n         {exc}")
                failures += 1
                continue

        if endpoint in ENVELOPE_ONLY:
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
                print(f"         … {len(differences) - len(shown)} more (--verbose)")
        else:
            print(f"  OK     {label}")

    total = len(ENDPOINTS) + len(ENVELOPE_ONLY)
    print(f"\n{total - failures}/{total} endpoints identical")
    return failures


if __name__ == "__main__":
    sys.exit(main())
