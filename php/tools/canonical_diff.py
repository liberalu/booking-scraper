#!/usr/bin/env python
"""Compare the canonical-book writers on identical input.

    PYTHONPATH=. uv run python php/tools/canonical_diff.py
    PYTHONPATH=. uv run python php/tools/canonical_diff.py --records 2097094,2113082

Test database only.

This exists because the end-to-end comparison can't reach this code path on
the Python side: its scan sends an HTML-preferring `Accept`, the endpoint
content-negotiates, and every fetch returns the SPA shell — so Python's
ibiblioteka scan writes nothing at all (see php/README.md). The record JSON
is therefore fetched ONCE, then handed to both writers, which is the
comparison the port actually needs: same bytes in, same rows out.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]
TEST_DSN = "postgresql+psycopg2://postgres:postgres@localhost:5433/book_scraper_test"
PHP = "/opt/homebrew/opt/php@8.4/bin/php"
DETAIL = "https://ibiblioteka.lt/metis-api/bibliographic-records/public/{record}"

DEFAULT_RECORDS = ["2097094", "2113082", "2126803"]


def engine():
    return sa.create_engine(TEST_DSN)


def fetch(record: str) -> tuple[str, str]:
    """(url, body). Accept matters: the default browser Accept gets the shell."""
    url = DETAIL.format(record=record)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return url, response.read().decode("utf-8")


def reset(urls: list[str]) -> None:
    with engine().begin() as conn:
        # book_isbns and book_authors cascade.
        conn.execute(
            sa.text("delete from books where source_url = any(:urls)"), {"urls": urls}
        )


def snapshot(urls: list[str]) -> dict:
    with engine().connect() as conn:
        books = [
            dict(row._mapping)
            for row in conn.execute(
                sa.text(
                    "select b.source_url, b.libis_code, b.data_source, b.title,"
                    " b.title_full, b.year, b.release_place, b.type, b.format,"
                    " b.pages, b.duration, b.dimensions, b.language,"
                    " b.translated_from, b.description, b.cover_url,"
                    " b.upcoming_release, b.udc_codes, b.subjects, b.audience,"
                    " b.libis_rating, b.libis_review_count,"
                    " p.name as publisher, s.title as series"
                    " from books b"
                    " left join publishers p on p.id = b.publisher_id"
                    " left join series s on s.id = b.series_id"
                    " where b.source_url = any(:urls) order by b.source_url"
                ),
                {"urls": urls},
            )
        ]
        isbns = [
            [row.source_url, row.isbn, row.isbn_type]
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
            [row.source_url, row.name, row.normalized_name, row.author_libis,
             row.role, row.position]
            for row in conn.execute(
                sa.text(
                    "select b.source_url, a.name, a.normalized_name,"
                    " a.libis_code as author_libis, ba.role, ba.position"
                    " from book_authors ba join books b on b.id = ba.book_id"
                    " join authors a on a.id = ba.author_id"
                    " where b.source_url = any(:urls)"
                    " order by b.source_url, ba.position, a.name, ba.role"
                ),
                {"urls": urls},
            )
        ]
    return {"books": books, "isbns": isbns, "authors": authors}


def run_python(pairs: list[tuple[str, str]]) -> None:
    from itemadapter import ItemAdapter

    from book_scraper.items import BookItem
    from book_scraper.pipelines import PostgresPipeline
    from book_scraper.spiders.ibiblioteka.parsers import parse_product_page

    pipeline = PostgresPipeline(database_url=TEST_DSN)
    pipeline.open_spider()
    try:
        for url, body in pairs:
            data = parse_product_page(body)
            book = BookItem()
            # The same whitelist the scan spider copies, plus source_url,
            # which the spider sets from the response URL.
            for key in (
                "libis_code", "data_source", "title", "title_full", "year",
                "publisher", "series", "isbns", "authors", "release_place",
                "type", "format", "pages", "duration", "dimensions",
                "language", "translated_from", "description", "cover_url",
                "upcoming_release", "udc_codes", "subjects", "audience",
                "libis_rating", "libis_review_count",
            ):
                if key in data and data[key] is not None:
                    book[key] = data[key]
            book["source_url"] = url
            pipeline._upsert_book(ItemAdapter(book))
    finally:
        pipeline.close_spider()


def run_php(pairs: list[tuple[str, str]], scratch: Path) -> None:
    for index, (url, body) in enumerate(pairs):
        path = scratch / f"record-{index}.json"
        path.write_text(body)
        subprocess.run(
            [PHP, "bin/canonical", f"--url={url}", f"--file={path}",
             f"--database={TEST_DSN.replace('+psycopg2', '')}"],
            cwd=ROOT / "php" / "crawler", check=True, capture_output=True,
        )


def diff(a: object, b: object, path: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{path}.{key}: extra in php")
            elif key not in b:
                out.append(f"{path}.{key}: MISSING IN PHP")
            else:
                out += diff(a[key], b[key], f"{path}.{key}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        out = [] if len(a) == len(b) else [f"{path}: length {len(a)} vs {len(b)}"]
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
        return out
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return [] if float(a) == float(b) else [f"{path}: python={a!r} php={b!r}"]
    return [] if a == b else [f"{path}: python={a!r} php={b!r}"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", default=",".join(DEFAULT_RECORDS))
    args = parser.parse_args()

    records = [r.strip() for r in args.records.split(",") if r.strip()]
    print(f"fetching {len(records)} record(s) once, feeding both writers\n")
    pairs = [fetch(record) for record in records]
    urls = [url for url, _ in pairs]

    scratch = ROOT / "php" / ".canonical-diff"
    scratch.mkdir(exist_ok=True)
    try:
        reset(urls)
        print("  running python writer…")
        run_python(pairs)
        python_rows = snapshot(urls)

        reset(urls)
        print("  running php writer…")
        run_php(pairs, scratch)
        php_rows = snapshot(urls)
    finally:
        for leftover in scratch.glob("record-*.json"):
            leftover.unlink()
        scratch.rmdir()

    for name, rows in (("python", python_rows), ("php", php_rows)):
        print(
            f"  {name:<7} {len(rows['books']):>3} books  "
            f"{len(rows['isbns']):>3} isbns  {len(rows['authors']):>3} authors"
        )
    print()

    if not python_rows["books"] and not php_rows["books"]:
        print("INCONCLUSIVE — neither writer wrote anything, so this proves nothing.")
        return 1

    differences = diff(python_rows, php_rows)
    if differences:
        print(f"{len(differences)} DIFFERENCES")
        for line in differences[:40]:
            print(f"   {line}")
    else:
        print("identical — both writers produced the same canonical rows")

    return len(differences)


if __name__ == "__main__":
    sys.exit(main())
