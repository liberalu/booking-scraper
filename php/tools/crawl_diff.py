#!/usr/bin/env python
"""Scrape the same URLs with both stacks and diff the rows they write.

This is the check that makes the PHP crawler trustworthy: identical input
through both pipelines must produce identical database state.

    PYTHONPATH=. uv run python php/tools/crawl_diff.py
    PYTHONPATH=. uv run python php/tools/crawl_diff.py --urls a,b,c

Runs ONLY against the test database (port 5433) and wipes the shop's rows
between passes, so it must never be pointed at production.

Live data forces two exclusions, both verified rather than assumed:

* `price` moves between the two passes, so prices are compared by row
  COUNT, not value.
* The JSON-API strategies (`graphql`, `lupasearch`, `ibiblioteka_api`) ARE
  compared row-for-row: they sort explicitly, so a fixed page of a fixed
  pageSize returns the same items to both stacks.
* `discover --strategy=categories` cannot be compared URL-for-URL. The
  paginated listing reorders between requests — two *identical* PHP runs
  minutes apart differ by several URLs — so page 2 of one run holds
  different products than page 2 of the next. That comparison falls back to
  aggregates and prints the overlap for information. `--strategy=sitemap`
  is a single fetch and IS compared exactly.

Exit code is the number of differences.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]
TEST_DSN = "postgresql+psycopg2://postgres:postgres@localhost:5433/book_scraper_test"
PHP = "/opt/homebrew/opt/php@8.4/bin/php"

# No cross-shop default. Falling back to another shop's URLs silently
# produced a meaningless comparison: vaga product pages parsed by the
# almalittera parser, reported as a real divergence.


def urls_from_db(shop: str, limit: int) -> list[str]:
    """Pick URLs to compare from the seeded catalogue.

    Deterministic (md5 ordering) so both passes fetch the same pages, and
    scoped to rows the shop actually lists.
    """
    with engine().connect() as conn:
        return [
            row[0]
            for row in conn.execute(
                sa.text(
                    "select url from shop_books sb join shops s on s.id = sb.shop_id "
                    "where s.name = :shop and sb.is_active = true "
                    "order by md5(sb.url) limit :limit"
                ),
                {"shop": shop, "limit": limit},
            )
        ]

# Deleted child-first so foreign keys stay satisfied.
WIPE = [
    "delete from prices where shop_book_id in (select sb.id from shop_books sb join shops s on s.id=sb.shop_id where s.name=:shop)",
    "delete from shop_book_changes where shop_book_id in (select sb.id from shop_books sb join shops s on s.id=sb.shop_id where s.name=:shop)",
    "delete from shop_book_attributes where shop_book_id in (select sb.id from shop_books sb join shops s on s.id=sb.shop_id where s.name=:shop)",
    "delete from shop_book_authors where shop_book_id in (select sb.id from shop_books sb join shops s on s.id=sb.shop_id where s.name=:shop)",
    "delete from scrape_url_items where shop_id in (select id from shops where name=:shop)",
    # Before shop_books and discovered_urls: an issue found during the crawl
    # carries an FK to whichever of them it was about.
    "delete from validation_issues where shop_id in (select id from shops where name=:shop)",
    "delete from discovered_urls where shop_id in (select id from shops where name=:shop)",
    "delete from shop_books where shop_id in (select id from shops where name=:shop)",
    "delete from scrape_run_events where run_id in (select id from scrape_runs where shop_id in (select id from shops where name=:shop))",
    "delete from scrape_runs where shop_id in (select id from shops where name=:shop)",
]

# `price` is deliberately absent: the shop is live and the two passes run
# minutes apart, so the value legitimately moves.
SNAPSHOT = {
    "shop_books": """
        select sb.url, sb.title, sb.author, sb.sku, sb.isbn, sb.publisher, sb.year,
               sb.format, sb.type, sb.description,
               sb.image_url, sb.categories::text as categories, sb.in_stock,
               sb.is_active, sb.match_status, sb.last_run_action,
               sb.planned_availability_date, sb.rating, sb.review_count
        from shop_books sb join shops s on s.id = sb.shop_id
        where s.name = :shop order by sb.url""",
    "attributes": """
        select sb.url, a.key, a.value from shop_book_attributes a
        join shop_books sb on sb.id = a.shop_book_id
        join shops s on s.id = sb.shop_id
        where s.name = :shop order by sb.url, a.key""",
    "authors": """
        select sb.url, au.name, sba.position from shop_book_authors sba
        join shop_authors au on au.id = sba.author_id
        join shop_books sb on sb.id = sba.shop_book_id
        join shops s on s.id = sb.shop_id
        where s.name = :shop order by sb.url, sba.position""",
    # Issues the CRAWL noticed (empty page, bad ISBN, redirect to homepage).
    # These were not compared at all until the PHP crawler learned to record
    # them, which is exactly why the gap went unnoticed.
    "issues": """
        select vi.issue, vi.field, vi.url, vi.raw_value, vi.lifecycle_state,
               vi.run_count, vi.shop_book_id is not null as on_book,
               vi.discovered_url_id is not null as on_url
        from validation_issues vi join shops s on s.id = vi.shop_id
        where s.name = :shop order by vi.issue, vi.url, vi.field""",
    "urls": """
        select du.normalized_url, du.url_type, du.shop_book_id is not null as linked
        from discovered_urls du join shops s on s.id = du.shop_id
        where s.name = :shop order by du.normalized_url""",
}


def engine() -> sa.Engine:
    return sa.create_engine(TEST_DSN)


# The canonical layer has no shop_id, so it can't be wiped per shop — and a
# watermark on max(id) is no good either, because a record already in the
# catalogue is UPDATED rather than inserted and would look like "nothing
# happened". Rows are keyed on the URL they came from instead: deleted before
# each pass, then compared by content. Without this the ibiblioteka scan —
# which writes `books`, not `shop_books` — was compared against nothing.


def canonical_reset(urls: list[str]) -> None:
    if not urls:
        return
    with engine().begin() as conn:
        # book_isbns and book_authors cascade from books.
        conn.execute(
            sa.text("delete from books where source_url = any(:urls)"), {"urls": urls}
        )


def canonical_snapshot(urls: list[str]) -> dict:
    """The canonical rows these URLs produced, keyed so the two passes line up
    even though their ids differ."""
    if not urls:
        return {"canonical_books": [], "canonical_isbns": [], "canonical_authors": []}

    with engine().connect() as conn:
        books = [
            dict(row._mapping)
            for row in conn.execute(
                sa.text(
                    "select b.libis_code, b.data_source, b.title, b.title_full,"
                    " b.year, b.release_place, b.type, b.format, b.pages,"
                    " b.duration, b.dimensions, b.language, b.translated_from,"
                    " b.description, b.cover_url, b.upcoming_release,"
                    " b.udc_codes, b.subjects, b.audience, b.libis_rating,"
                    " b.libis_review_count, b.source_url,"
                    " p.name as publisher, s.title as series"
                    " from books b"
                    " left join publishers p on p.id = b.publisher_id"
                    " left join series s on s.id = b.series_id"
                    " where b.source_url = any(:urls)"
                    " order by b.source_url"
                ),
                {"urls": urls},
            )
        ]
        isbns = [
            (row.source_url, row.isbn, row.isbn_type)
            for row in conn.execute(
                sa.text(
                    "select b.source_url, i.isbn, i.isbn_type from book_isbns i"
                    " join books b on b.id = i.book_id"
                    " where b.source_url = any(:urls)"
                    " order by b.source_url, i.isbn"
                ),
                {"urls": urls},
            )
        ]
        authors = [
            (row.source_url, row.name, row.normalized_name, row.author_libis,
             row.role, row.position)
            for row in conn.execute(
                sa.text(
                    "select b.source_url, a.name, a.normalized_name,"
                    " a.libis_code as author_libis, ba.role, ba.position"
                    " from book_authors ba"
                    " join books b on b.id = ba.book_id"
                    " join authors a on a.id = ba.author_id"
                    " where b.source_url = any(:urls)"
                    " order by b.source_url, ba.position, a.name, ba.role"
                ),
                {"urls": urls},
            )
        ]

    return {
        "canonical_books": books,
        "canonical_isbns": isbns,
        "canonical_authors": authors,
    }


def wipe(shop: str) -> None:
    with engine().begin() as conn:
        for statement in WIPE:
            conn.execute(sa.text(statement), {"shop": shop})
        conn.execute(
            sa.text(
                "insert into shops (name, base_url) values (:shop, :url) "
                "on conflict (name) do nothing"
            ),
            {"shop": shop, "url": f"https://{shop}.lt"},
        )


def snapshot(shop: str) -> dict:
    out: dict = {}
    with engine().connect() as conn:
        for key, query in SNAPSHOT.items():
            out[key] = [
                dict(row) for row in conn.execute(sa.text(query), {"shop": shop}).mappings()
            ]
        out["price_count"] = conn.execute(
            sa.text(
                "select count(*) from prices p "
                "join shop_books sb on sb.id = p.shop_book_id "
                "join shops s on s.id = sb.shop_id where s.name = :shop"
            ),
            {"shop": shop},
        ).scalar()
    return json.loads(json.dumps(out, default=str))


@contextlib.contextmanager
def narrowed_year_range(shop: str, strategy: str):
    """Temporarily shrink an ibiblioteka_api year window to one year.

    The strategy opens one request per calendar MONTH in [year_from, year_to),
    so the production window (1990-2027) is 444 seeds per stack — far too much
    to fetch twice for a comparison, and rude to the server. Python reads the
    range from the shop TOML with no CLI override, so the only way to compare
    the two stacks on equal terms is to narrow the file for the duration and
    put it back. Restored in a finally, and the original bytes are held in
    memory rather than a sidecar file so a crash cannot leave a stale copy
    lying around.
    """
    if strategy != "ibiblioteka_api":
        yield
        return

    path = ROOT / "config" / "shops" / f"{shop}.toml"
    original = path.read_text()
    narrowed = re.sub(
        r"^year_from\s*=.*$", "year_from = 2026", original, count=1, flags=re.M
    )
    narrowed = re.sub(
        r"^year_to\s*=.*$", "year_to = 2027", narrowed, count=1, flags=re.M
    )
    if narrowed == original:
        print("  warning: could not narrow the year range; comparing the full window")
        yield
        return

    print("  narrowing the year range to 2026 for the duration of the comparison")
    path.write_text(narrowed)
    try:
        yield
    finally:
        path.write_text(original)


def run_python_discover(shop: str, strategy: str, max_pages: int) -> None:
    env = {
        **os.environ,
        "DATABASE_URL": TEST_DSN,
        "POST_PHASE_AUTO_TRIGGER": "0",
        "PYTHONPATH": str(ROOT),
    }
    cmd = ["uv", "run", "scrapy", "crawl", "discover",
           "-a", f"shop={shop}", "-a", f"strategy={strategy}"]
    if max_pages:
        cmd += ["-a", f"max_pages={max_pages}"]
    subprocess.run(cmd, cwd=ROOT, env=env, check=True, capture_output=True)


def run_php_discover(shop: str, strategy: str, max_pages: int) -> None:
    env = {
        **os.environ,
        "DATABASE_URL": TEST_DSN.replace("+psycopg2", ""),
        # Same reason as the Python side: the auto-trigger would run ISBN
        # linkage and spawn a validate mid-comparison, so match_status would
        # differ purely because of what ran after the crawl.
        "POST_PHASE_AUTO_TRIGGER": "0",
    }
    cmd = [PHP, "bin/crawl", "discover", f"--shop={shop}", f"--strategy={strategy}"]
    if max_pages:
        cmd.append(f"--max-pages={max_pages}")
    subprocess.run(cmd, cwd=ROOT / "php" / "crawler", env=env, check=True, capture_output=True)


def run_python(shop: str, urls: list[str]) -> None:
    env = {
        **os.environ,
        "DATABASE_URL": TEST_DSN,
        # The auto-trigger would spawn a validate subprocess mid-comparison.
        "POST_PHASE_AUTO_TRIGGER": "0",
        "PYTHONPATH": str(ROOT),
    }
    subprocess.run(
        ["uv", "run", "scrapy", "crawl", "scan", "-a", f"shop={shop}", "-a", f"urls={','.join(urls)}"],
        cwd=ROOT, env=env, check=True, capture_output=True,
    )


def run_php(shop: str, urls: list[str]) -> None:
    env = {
        **os.environ,
        "DATABASE_URL": TEST_DSN.replace("+psycopg2", ""),
        "POST_PHASE_AUTO_TRIGGER": "0",
    }
    subprocess.run(
        [PHP, "bin/crawl", "scan", f"--shop={shop}", f"--urls={','.join(urls)}"],
        cwd=ROOT / "php" / "crawler", env=env, check=True, capture_output=True,
    )


def aggregates(rows: dict) -> dict:
    """Shape of a discovery result, independent of which exact URLs landed."""
    by_kind: dict[str, int] = {}
    for row in rows["urls"]:
        key = f"{row['url_type']}/{'linked' if row['linked'] else 'unlinked'}"
        by_kind[key] = by_kind.get(key, 0) + 1

    return {
        "url_count": len(rows["urls"]),
        "urls_by_type": dict(sorted(by_kind.items())),
        "book_count": len(rows["shop_books"]),
        "attribute_count": len(rows["attributes"]),
        "author_count": len(rows["authors"]),
        "price_count": rows["price_count"],
    }


def canonical_only(rows: dict) -> dict:
    """Carry the canonical comparison through the reducers — those exist to
    tolerate an unstable URL order, which says nothing about `books`."""
    return {k: v for k, v in rows.items() if k.startswith("canonical_")}


def shape(rows: dict) -> dict:
    """What was written, ignoring how many — for an unstable upstream order."""
    return {
        "url_types": sorted({
            f"{row['url_type']}/{'linked' if row['linked'] else 'unlinked'}"
            for row in rows["urls"]
        }),
        "wrote_urls": bool(rows["urls"]),
        "book_count": len(rows["shop_books"]),
        "attribute_count": len(rows["attributes"]),
        "author_count": len(rows["authors"]),
        "price_count": rows["price_count"],
    }


def diff(a: object, b: object, path: str = "") -> list[str]:
    if type(a) is not type(b):
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
    return [] if a == b else [f"{path}: python={a!r} php={b!r}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop", default="vaga")
    parser.add_argument(
        "--urls",
        default="",
        help="comma-separated URLs; defaults to a deterministic sample from the "
        "seeded catalogue for the shop",
    )
    parser.add_argument("--limit", type=int, default=2, help="how many sampled URLs")
    parser.add_argument(
        "--phase", default="scan", choices=["scan", "discover"],
        help="scan compares product-page writes; discover compares URL discovery",
    )
    parser.add_argument(
        "--strategy", default="categories",
        choices=["sitemap", "categories", "graphql", "lupasearch", "ibiblioteka_api"],
    )
    parser.add_argument(
        "--max-pages", type=int, default=2,
        help="discover only: cap category pages so a comparison run stays quick",
    )
    args = parser.parse_args()

    urls = [u.strip() for u in args.urls.split(",") if u.strip()]
    # Discovery builds its own work list from the shop config, so it needs no
    # sample — requiring one blocked the shops that have no production rows.
    if not urls and args.phase == "scan":
        urls = urls_from_db(args.shop, args.limit)
    if not urls and args.phase == "scan":
        sys.exit(
            f"no URLs to compare for shop '{args.shop}'.\n"
            f"Seed it first (php/tools/seed_test_db.py --shop {args.shop}), or pass "
            f"--urls explicitly.\n"
            f"Note: almalittera and ibiblioteka have no rows in production, so "
            f"there is nothing to sample — pass --urls for those."
        )

    if args.phase == "discover":
        label = f"discover/{args.strategy}"
        if args.strategy != "sitemap":
            label += f" (max {args.max_pages} pages)"
        print(f"comparing {label} on shop '{args.shop}' (test db only)\n")
        py_run = lambda: run_python_discover(args.shop, args.strategy, args.max_pages)
        php_run = lambda: run_php_discover(args.shop, args.strategy, args.max_pages)
    else:
        print(f"comparing scan of {len(urls)} url(s) on shop '{args.shop}' (test db only)\n")
        py_run = lambda: run_python(args.shop, urls)
        php_run = lambda: run_php(args.shop, urls)

    # Only a scan writes canonical rows, and only for the URLs it was given.
    canonical_urls = urls if args.phase == "scan" else []

    with narrowed_year_range(args.shop, args.strategy if args.phase == "discover" else ""):
        wipe(args.shop)
        canonical_reset(canonical_urls)
        print("  running python…")
        py_run()
        python_rows = snapshot(args.shop) | canonical_snapshot(canonical_urls)

        wipe(args.shop)
        canonical_reset(canonical_urls)
        print("  running php…")
        php_run()
        php_rows = snapshot(args.shop) | canonical_snapshot(canonical_urls)

    for name, rows in (("python", python_rows), ("php", php_rows)):
        print(
            f"  {name:<7} {len(rows['shop_books']):>5} books  "
            f"{len(rows['urls']):>6} urls  "
            f"{len(rows['attributes']):>4} attrs  "
            f"{rows['price_count']:>4} prices  "
            f"{len(rows['canonical_books']):>4} canonical  "
            f"{len(rows['issues']):>3} issues"
        )
    print()

    # A pass only means something if at least one side wrote something.
    # Both-empty means both FAILED — for a FlareSolverr shop the Python side
    # reads the endpoint straight from the shop TOML with no env override, so
    # `flaresolverr:8191` does not resolve on the host and every fetch dies.
    # Reporting that as parity is worse than reporting nothing.
    if (
        not python_rows["shop_books"] and not php_rows["shop_books"]
        and not python_rows["urls"] and not php_rows["urls"]
        and not python_rows["canonical_books"] and not php_rows["canonical_books"]
    ):
        print(
            "INCONCLUSIVE — neither stack wrote anything, so this proves nothing.\n"
            "  Either every URL is a non-book page, the shop blocked both\n"
            "  fetchers, or a required sidecar was unreachable.\n"
            f"  FlareSolverr shops (humanitas) cannot be compared from the host:\n"
            f"  Python reads the endpoint from config/shops/{args.shop}.toml and\n"
            "  has no env override, so the compose hostname never resolves.\n"
            "  Run the comparison inside the compose network instead."
        )
        return 1

    # ibiblioteka's search API sorts by MATCH on an empty query, so its
    # result ORDER is not stable — paging it by pageStartIndex overlaps and
    # drops records differently every time. Measured: two consecutive runs of
    # the SAME stack returned 900 and 800 URLs with 700 shared. Nothing about
    # that is comparable row-for-row, and neither is the count; what can be
    # checked is the SHAPE of what gets written (URL-only items, typed
    # `product`, no books, no prices).
    if args.phase == "discover" and args.strategy == "ibiblioteka_api":
        py_urls = {r["normalized_url"] for r in python_rows["urls"]}
        php_urls = {r["normalized_url"] for r in php_rows["urls"]}
        union = py_urls | php_urls
        overlap = len(py_urls & php_urls) / len(union) * 100 if union else 100.0
        print(
            f"  url overlap {overlap:.1f}% "
            f"({len(py_urls & php_urls)} shared, {len(py_urls - php_urls)} python-only, "
            f"{len(php_urls - py_urls)} php-only)"
        )
        print(
            "  comparing shape only — the API's result order is unstable, so\n"
            "  even two runs of one stack disagree on which records they see\n"
        )
        python_rows = shape(python_rows) | canonical_only(python_rows)
        php_rows = shape(php_rows) | canonical_only(php_rows)

    # Categories discovery can't be compared row-for-row: see the module
    # docstring. Compare shape, and report overlap as a signal.
    elif args.phase == "discover" and args.strategy == "categories":
        py_urls = {r["normalized_url"] for r in python_rows["urls"]}
        php_urls = {r["normalized_url"] for r in php_rows["urls"]}
        union = py_urls | php_urls
        overlap = len(py_urls & php_urls) / len(union) * 100 if union else 100.0
        print(
            f"  url overlap {overlap:.1f}% "
            f"({len(py_urls & php_urls)} shared, {len(py_urls - php_urls)} python-only, "
            f"{len(php_urls - py_urls)} php-only)"
        )
        print("  comparing aggregates only — the live listing reorders between runs\n")
        python_rows = aggregates(python_rows) | canonical_only(python_rows)
        php_rows = aggregates(php_rows) | canonical_only(php_rows)

    differences = diff(python_rows, php_rows)
    if differences:
        print(f"{len(differences)} DIFFERENCES")
        for line in differences[:40]:
            print(f"   {line}")
    else:
        print("identical — both stacks wrote the same rows")

    return len(differences)


if __name__ == "__main__":
    sys.exit(main())
