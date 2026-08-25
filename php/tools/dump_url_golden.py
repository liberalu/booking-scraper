#!/usr/bin/env python
"""Dump normalize_url() output for the differential URL corpus.

    PYTHONPATH=. uv run python php/tools/dump_url_golden.py

The corpus is hand-picked edge cases plus a sample of real production
URLs, because canonical URL form backs `uq_shop_book_shop_url` and
`uq_discovered_urls_shop_normalized` — if PHP and Python disagree by one
character, one product silently becomes two rows.

Set DATABASE_URL to skip the production sample (the hand-picked cases
still run).
"""

import json
import os
import pathlib

import sqlalchemy as sa

from book_scraper.url_utils import normalize_url

ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "php" / "tests" / "golden" / "urls.json"

EDGE_CASES = [
    "https://vaga.lt/sirdies-kauleliai",
    "https://vaga.lt/sirdies-kauleliai/",
    "HTTPS://VAGA.LT/Sirdies-Kauleliai",
    "https://vaga.lt//knygos///romanai/",
    "https://vaga.lt/knygos?limit=100&page=3",
    "https://vaga.lt/knygos?utm_source=fb&limit=100&utm_medium=cpc",
    "https://vaga.lt/x?fbclid=abc&gclid=def&ref=nav&keep=1",
    "https://vaga.lt/x?REF=nav&UTM_Source=y&ok=2",
    "https://vaga.lt/x#fragment",
    "https://vaga.lt/x?a=&b=2",
    "https://vaga.lt/x?q=hello world",
    "https://vaga.lt/x?q=a%20b&r=c+d",
    "https://vaga.lt",
    "https://vaga.lt/",
    "  https://vaga.lt/trim  ",
    "https://vaga.lt/mišku-x",
    "https://vaga.lt/mi%C5%A1ku-x",
    "https://vaga.lt:443/x/",
    "https://user:pw@vaga.lt/x",
    "https://vaga.lt/index.php?route=product/product&product_id=123",
    "http://vaga.lt/Upper/Path/",
    "https://vaga.lt/x?b=2&a=1",
]

DB_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/book_scraper"
)


def production_sample() -> list[str]:
    """Real URL shapes from the catalogue. Empty when the DB is unreachable."""
    try:
        engine = sa.create_engine(DB_URL)
        with engine.connect() as conn:
            urls = list(
                conn.execute(
                    sa.text(
                        "select url from discovered_urls where url like '%?%' "
                        "order by md5(url) limit 15"
                    )
                ).scalars()
            )
            # Deterministic spread across the catalogue: random() would
            # make every regeneration churn the golden file.
            urls += list(
                conn.execute(
                    sa.text("select url from shop_books order by md5(url) limit 25")
                ).scalars()
            )
        engine.dispose()
        return [u for u in urls if u]
    except Exception as exc:  # noqa: BLE001 — the sample is a bonus, not required
        print(f"skipping production sample: {exc}")
        return []


def main() -> None:
    cases = EDGE_CASES + production_sample()
    mapping = {url: normalize_url(url) for url in cases}
    GOLDEN.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    print(f"wrote {len(mapping)} cases to {GOLDEN.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
