#!/usr/bin/env python
"""Insert rows that trigger the validator checks real data doesn't reach.

    PYTHONPATH=. uv run python php/tools/synthesize_validate_cases.py

Six of the 21 issue types never fired across vaga, patogupirkti or pegasas:
format_is_dimensions, non_book_has_isbn, non_product_active, orphan_no_url,
sku_duplicate and unreachable_active. Without these the parity check simply
doesn't exercise those code paths, so this builds a synthetic shop that hits
each one — including the suppression cases, which matter as much as the
positives.

Test database only. Creates its own shop so it never perturbs a copied one.
"""

import sys

import sqlalchemy as sa

TEST_DSN = "postgresql+psycopg2://postgres:postgres@localhost:5433/book_scraper_test"
SHOP = "synthetic"
BASE = "https://synthetic.test"


def main() -> int:
    engine = sa.create_engine(TEST_DSN)

    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "delete from validation_issues where shop_id in "
                "(select id from shops where name = :s)"
            ),
            {"s": SHOP},
        )
        for table in ("prices", "shop_book_attributes", "shop_book_authors", "shop_book_changes"):
            conn.execute(
                sa.text(
                    f"delete from {table} where shop_book_id in (select sb.id from shop_books sb "
                    "join shops s on s.id = sb.shop_id where s.name = :s)"
                ),
                {"s": SHOP},
            )
        conn.execute(
            sa.text(
                "delete from discovered_urls where shop_id in "
                "(select id from shops where name = :s)"
            ),
            {"s": SHOP},
        )
        conn.execute(
            sa.text(
                "delete from shop_books where shop_id in "
                "(select id from shops where name = :s)"
            ),
            {"s": SHOP},
        )
        sid = conn.execute(
            sa.text(
                "insert into shops (name, base_url) values (:s, :u) "
                "on conflict (name) do update set base_url = excluded.base_url "
                "returning id"
            ),
            {"s": SHOP, "u": BASE},
        ).scalar_one()

    # (slug, kwargs) — every book is active, in stock, freshly seen and
    # priced unless the case under test needs otherwise, so each row trips
    # exactly the check it is named for.
    books: list[tuple[str, dict]] = [
        # format_is_dimensions: format looks like a dimension expression.
        ("dims-a", {"format": "17x24"}),
        ("dims-b", {"format": "170 x 205 mm"}),
        # …and the shape that must NOT fire.
        ("dims-ok", {"format": "paperback"}),

        # non_book_has_isbn: type=non_book carrying a real 978 ISBN.
        ("nonbook-isbn", {"type": "non_book", "isbn": "9786090901595"}),
        # Suppressed: category marks it a legitimate non-book product.
        ("nonbook-isbn-puzzle", {
            "type": "non_book", "isbn": "9786090901601",
            "categories": ["Žaislai", "Dėlionės"],
        }),
        # Suppressed: title marks it a DVD.
        ("nonbook-isbn-dvd", {
            "type": "non_book", "isbn": "9786090901618",
            "title": "Something (DVD)",
        }),
        # Not flagged: plain EAN on a non-book is just a GTIN.
        ("nonbook-ean", {"type": "non_book", "isbn": "4001234567890"}),

        # sku_duplicate: two active rows sharing a SKU.
        ("sku-dup-a", {"sku": "SHARED-SKU"}),
        ("sku-dup-b", {"sku": "SHARED-SKU"}),
        # Must not fire: the sibling is inactive.
        ("sku-dup-inactive-a", {"sku": "HALF-SKU"}),
        ("sku-dup-inactive-b", {"sku": "HALF-SKU", "is_active": False}),

        # orphan_no_url: no discovered_urls row at all.
        ("orphan", {"_no_url": True}),

        # non_product_active: one non_product URL alongside a good one, so
        # the auto-heal leaves it active and it gets flagged.
        ("mixed-nonproduct", {"_extra_urls": [("non_product", "mixed-nonproduct-alt")]}),
        # All URLs non_product -> auto-healed to inactive, NOT flagged.
        ("all-nonproduct", {"_url_type": "non_product"}),

        # unreachable_active: active book whose URL is unreachable.
        ("unreachable", {"_url_type": "unreachable"}),
    ]

    defaults = {
        "title": None,
        "author": "Synthetic Author",
        "isbn": None,
        "sku": None,
        "publisher": "Synthetic Press",
        "year": 2024,
        "format": None,
        "type": "book",
        "price": "9.99",
        "in_stock": True,
        "is_active": True,
        "categories": ["Grožinė literatūra"],
    }

    with engine.begin() as conn:
        for slug, overrides in books:
            row = {**defaults, **{k: v for k, v in overrides.items() if not k.startswith("_")}}
            row["title"] = row["title"] or slug.replace("-", " ").title()
            url = f"{BASE}/{slug}"

            book_id = conn.execute(
                sa.text(
                    "insert into shop_books (shop_id, url, title, author, isbn, sku, "
                    "publisher, year, format, type, price, in_stock, is_active, "
                    "categories, match_status, first_seen_at, last_seen_at) "
                    "values (:shop_id, :url, :title, :author, :isbn, :sku, :publisher, "
                    ":year, :format, :type, :price, :in_stock, :is_active, :categories, "
                    "'unmatched', now(), now()) returning id"
                ),
                {**row, "shop_id": sid, "url": url},
            ).scalar_one()

            if overrides.get("_no_url"):
                continue

            conn.execute(
                sa.text(
                    "insert into discovered_urls (shop_id, url, normalized_url, source, "
                    "url_type, fail_count, first_seen_at, last_seen_at, shop_book_id) "
                    "values (:shop_id, :url, :url, 'sitemap', :url_type, 0, now(), now(), :sb)"
                ),
                {
                    "shop_id": sid,
                    "url": url,
                    "url_type": overrides.get("_url_type", "product"),
                    "sb": book_id,
                },
            )
            for url_type, alt_slug in overrides.get("_extra_urls", []):
                alt = f"{BASE}/{alt_slug}"
                conn.execute(
                    sa.text(
                        "insert into discovered_urls (shop_id, url, normalized_url, source, "
                        "url_type, fail_count, first_seen_at, last_seen_at, shop_book_id) "
                        "values (:shop_id, :url, :url, 'sitemap', :url_type, 0, now(), now(), :sb)"
                    ),
                    {"shop_id": sid, "url": alt, "url_type": url_type, "sb": book_id},
                )

            # A price row keeps no_price_history from firing on every book.
            conn.execute(
                sa.text(
                    "insert into prices (shop_book_id, price, in_stock, scraped_at) "
                    "values (:sb, :price, :in_stock, now())"
                ),
                {"sb": book_id, "price": row["price"], "in_stock": row["in_stock"]},
            )

    engine.dispose()
    print(f"synthesised {len(books)} rows on shop '{SHOP}' (id {sid})")
    print("  targets: format_is_dimensions, non_book_has_isbn, non_product_active,")
    print("           orphan_no_url, sku_duplicate, unreachable_active (+ suppressions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
