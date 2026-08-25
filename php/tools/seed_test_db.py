#!/usr/bin/env python
"""Copy one shop's rows from the live database into the test database.

    PYTHONPATH=. uv run python php/tools/seed_test_db.py --shop vaga

The validator's suppression rules were tuned against real catalogue shapes,
so comparing Python and PHP validators on an empty database proves nothing.
This gives both a realistic corpus to run over. Reads production, writes
ONLY to the test database (port 5433), preserving ids so foreign keys line
up on both sides.
"""

import argparse
import sys
from pathlib import Path

import sqlalchemy as sa

# The test database is named in one place — see _testdb for why the PHP
# side cannot share the Python suite's database.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _testdb import TEST_DSN  # noqa: E402

PROD = "postgresql+psycopg2://postgres:postgres@localhost:5432/book_scraper"

# Parents first. publishers/series are here because `books` has FKs to them.
TABLES = [
    ("shops", "name = :shop"),
    ("publishers", None),
    ("series", None),
    ("books", None),
    ("book_isbns", None),
    # authors/book_authors are needed for match step 2 (author backfill);
    # without them the step links nothing and its comparison is vacuous.
    ("authors", None),
    ("book_authors", None),
    ("shop_books", "shop_id = (select id from shops where name = :shop)"),
    ("shop_authors", None),
    ("shop_book_authors", None),
    ("discovered_urls", "shop_id = (select id from shops where name = :shop)"),
    (
        "prices",
        "shop_book_id in (select id from shop_books "
        "where shop_id = (select id from shops where name = :shop))",
    ),
]

# scrape_runs are not copied (each stack creates its own), so any column
# referencing them must be nulled or the FK fails.
# Scoped to this shop's books, same reasoning as BOOK_SCOPE.
AUTHOR_SCOPE = """
    id in (
        -- Canonical authors already linked from this shop's shop_authors.
        -- Without this arm, copying shop_authors violates its FK.
        select distinct sa.canonical_author_id from shop_authors sa
        where sa.canonical_author_id is not null
          and sa.id in (
            select distinct author_id from shop_book_authors
            where shop_book_id in (
                select id from shop_books
                where shop_id = (select id from shops where name = :shop)
            )
          )
        union
        select distinct ba.author_id from book_authors ba
        where ba.book_id in (
            select distinct bi.book_id from book_isbns bi
            join shop_books sb on replace(replace(sb.isbn,'-',''),' ','') = bi.isbn
            where sb.shop_id = (select id from shops where name = :shop)
            union
            select distinct book_id from shop_books
            where shop_id = (select id from shops where name = :shop)
              and book_id is not null
        )
    )
"""

BOOK_AUTHOR_SCOPE = """
    book_id in (
        select distinct bi.book_id from book_isbns bi
        join shop_books sb on replace(replace(sb.isbn,'-',''),' ','') = bi.isbn
        where sb.shop_id = (select id from shops where name = :shop)
        union
        select distinct book_id from shop_books
        where shop_id = (select id from shops where name = :shop)
          and book_id is not null
    )
"""

SHOP_BOOK_AUTHOR_SCOPE = """
    shop_book_id in (
        select id from shop_books
        where shop_id = (select id from shops where name = :shop)
    )
"""

SHOP_AUTHOR_SCOPE = """
    id in (
        select distinct author_id from shop_book_authors
        where shop_book_id in (
            select id from shop_books
            where shop_id = (select id from shops where name = :shop)
        )
    )
"""

NULLED_COLUMNS = {
    "shop_books": ("last_run_id", "created_run_id"),
    "discovered_urls": ("last_seen_run_id",),
    "prices": ("scrape_run_id",),
    "books": ("source_run_id",),
}

# books/book_isbns are only needed for the match checks; a full copy is
# millions of rows, so take the slice reachable from this shop's ISBNs.
# Books reachable by ISBN join OR already linked from this shop's rows.
# The second arm matters: a drifted link points at a book the ISBN join no
# longer reaches, and that is precisely the row match_isbn_drift is about.
BOOK_SCOPE = """
    id in (
        select distinct bi.book_id from book_isbns bi
        join shop_books sb on replace(replace(sb.isbn,'-',''),' ','') = bi.isbn
        where sb.shop_id = (select id from shops where name = :shop)
        union
        select distinct book_id from shop_books
        where shop_id = (select id from shops where name = :shop)
          and book_id is not null
    )
"""
ISBN_SCOPE = """
    book_id in (
        select distinct bi.book_id from book_isbns bi
        join shop_books sb on replace(replace(sb.isbn,'-',''),' ','') = bi.isbn
        where sb.shop_id = (select id from shops where name = :shop)
        union
        select distinct book_id from shop_books
        where shop_id = (select id from shops where name = :shop)
          and book_id is not null
    )
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shop", default="vaga")
    parser.add_argument("--limit-prices", type=int, default=50_000)
    args = parser.parse_args()
    shop = args.shop

    prod = sa.create_engine(PROD)
    test = sa.create_engine(TEST_DSN)

    with test.begin() as t:
        # Truncate everything so ids can be copied verbatim — a pre-existing
        # `vaga` row at a different id is what makes a partial wipe fail.
        # Safe: this is the test database, rebuilt from the models on demand.
        tables = [
            r[0]
            for r in t.execute(
                sa.text(
                    "select tablename from pg_tables where schemaname = 'public' "
                    "and tablename != 'alembic_version'"
                )
            )
        ]
        if tables:
            t.execute(sa.text(f"truncate {', '.join(tables)} restart identity cascade"))

    copied: dict[str, int] = {}
    with prod.connect() as p:
        for table, where in TABLES:
            clause = where
            if table == "books":
                clause = BOOK_SCOPE
            elif table == "book_isbns":
                clause = ISBN_SCOPE
            elif table == "authors":
                clause = AUTHOR_SCOPE
            elif table == "book_authors":
                clause = BOOK_AUTHOR_SCOPE
            elif table == "shop_authors":
                clause = SHOP_AUTHOR_SCOPE
            elif table == "shop_book_authors":
                clause = SHOP_BOOK_AUTHOR_SCOPE

            sql = f"select * from {table}"
            if clause:
                sql += f" where {clause}"
            if table == "prices":
                sql += f" order by id desc limit {args.limit_prices}"

            rows = [dict(r) for r in p.execute(sa.text(sql), {"shop": shop}).mappings()]
            copied[table] = len(rows)
            if not rows:
                continue

            columns = list(rows[0])
            # discount_pct is generated; Postgres rejects an explicit value.
            columns = [c for c in columns if c != "discount_pct"]
            for row in rows:
                for column in NULLED_COLUMNS.get(table, ()):
                    if column in row:
                        row[column] = None
            placeholders = ", ".join(f":{c}" for c in columns)
            insert = sa.text(
                f"insert into {table} ({', '.join(columns)}) values ({placeholders}) "
                "on conflict do nothing"
            )
            try:
                with test.begin() as t:
                    for i in range(0, len(rows), 1000):
                        t.execute(
                            insert, [{c: r[c] for c in columns} for r in rows[i : i + 1000]]
                        )
            except sa.exc.SQLAlchemyError as exc:
                # SQLAlchemy dumps every bound parameter set on failure, which
                # for a 1000-row batch of book descriptions is unreadable.
                detail = str(getattr(exc, "orig", exc)).split("\n")[0]
                print(f"  FAILED {table}: {detail}", file=sys.stderr)
                return 1

    # Keep sequences ahead of the copied ids so later inserts don't collide.
    with test.begin() as t:
        # Join tables (book_authors, shop_book_authors) have composite PKs
        # and no id sequence, so they are not listed here.
        for table in (
            "shops", "publishers", "series", "books", "book_isbns",
            "authors", "shop_books", "shop_authors",
            "discovered_urls", "prices",
        ):
            t.execute(
                sa.text(
                    f"select setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"coalesce((select max(id) from {table}), 1))"
                )
            )

    # ANALYZE before anyone queries this: a freshly bulk-loaded table has no
    # statistics, and the validator's correlated EXISTS self-join on
    # shop_books gets a plan bad enough to hit the statement timeout.
    with test.connect() as t:
        t.execution_options(isolation_level="AUTOCOMMIT").execute(sa.text("analyze"))

    prod.dispose()
    test.dispose()
    print("copied into test db:")
    for table, count in copied.items():
        print(f"  {table:18} {count:>7}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
