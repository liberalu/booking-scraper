#!/usr/bin/env python
"""Dump the Python vaga parser's output over the shared fixtures.

The PHP port is verified differentially: php/tests/VagaParserDifferentialTest
asserts the PHP parser reproduces these files exactly. Regenerate whenever
the Python parser changes on purpose:

    PYTHONPATH=. uv run python php/tools/dump_golden.py

A diff in git after running this is the signal that Python behaviour moved
and the PHP side needs the same change.
"""

import json
import pathlib

from book_scraper.spiders.almalittera import parsers as alma_parsers
from book_scraper.spiders.humanitas import parsers as humanitas_parsers
from book_scraper.spiders.ibiblioteka import parsers as ibiblioteka_parsers
from book_scraper.spiders.patogupirkti import parsers as patogu_parsers
from book_scraper.spiders.pegasas import parsers as pegasas_parsers
from book_scraper.spiders.vaga import parsers

ROOT = pathlib.Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
GOLDEN = ROOT / "php" / "tests" / "golden"


def main() -> None:
    GOLDEN.mkdir(parents=True, exist_ok=True)
    graphql_body = (FIXTURES / "pegasas_graphql_category.json").read_text()
    lupasearch_body = (FIXTURES / "pegasas_lupasearch_page1.json").read_text()

    cases = {
        "product": parsers.parse_product_page(
            (FIXTURES / "vaga_product_page.html").read_text()
        ),
        "category": parsers.parse_category_page(
            (FIXTURES / "vaga_category_page.html").read_text()
        ),
        "sitemap": parsers.parse_sitemap_urls(
            (FIXTURES / "vaga_sitemap.xml").read_text()
        ),
        "pegasas_graphql": pegasas_parsers.parse_category_page(graphql_body),
        "pegasas_lupasearch": pegasas_parsers.parse_lupasearch_response(lupasearch_body),
        # The per-SKU product path shares graphql_item_to_product, so running
        # the category body through it exercises the same mapping plus the
        # product-page envelope.
        "pegasas_product": pegasas_parsers.parse_product_page(graphql_body),
        "alma_category": alma_parsers.parse_category_page(
            (FIXTURES / "almalittera" / "products_page.json").read_text()
        ),
        "alma_product": alma_parsers.parse_product_page(
            (FIXTURES / "almalittera" / "product_page.html").read_text()
        ),
        "alma_ebook": alma_parsers.parse_product_page(
            (FIXTURES / "almalittera" / "ebook_page.html").read_text()
        ),
        # A notebook: the classifier must refuse it despite the shop listing
        # it alongside books.
        "alma_notebook": alma_parsers.parse_product_page(
            (FIXTURES / "almalittera" / "notebook_page.html").read_text()
        ),
        "patogu_category": patogu_parsers.parse_category_page(
            (FIXTURES / "patogupirkti" / "category_page.html").read_text()
        ),
        "patogu_product": patogu_parsers.parse_product_page(
            (FIXTURES / "patogupirkti" / "product_page.html").read_text()
        ),
        # A second template: legacy pages lean on the spec table where the
        # newer ones carry microdata.
        "patogu_product_alt": patogu_parsers.parse_product_page(
            (FIXTURES / "patogupirkti" / "product_page_alt.html").read_text()
        ),
        "patogu_sitemap": patogu_parsers.parse_sitemap_urls(
            (FIXTURES / "patogupirkti" / "sitemap_product.xml").read_text()
        ),
        "humanitas_index": humanitas_parsers.parse_sitemap_urls(
            (FIXTURES / "humanitas" / "index_page.html").read_text()
        ),
        "humanitas_category": humanitas_parsers.parse_category_page(
            (FIXTURES / "humanitas" / "index_page.html").read_text()
        ),
        "humanitas_product": humanitas_parsers.parse_product_page(
            (FIXTURES / "humanitas" / "product_with_book_info.html").read_text()
        ),
        # The book-info block is absent on some legacy imports; the parser
        # must fall back to OG metadata alone.
        "humanitas_product_bare": humanitas_parsers.parse_product_page(
            (FIXTURES / "humanitas" / "product_without_book_info.html").read_text()
        ),
        "ibiblioteka_search": ibiblioteka_parsers.parse_ibiblioteka_search_response(
            (FIXTURES / "ibiblioteka" / "search_response.json").read_text()
        ),
        "ibiblioteka_translated": ibiblioteka_parsers.parse_product_page(
            (FIXTURES / "ibiblioteka" / "product_detail_translated.json").read_text()
        ),
        # An audiobook: ELECTRONIC format is shared with e-books, and only
        # the physical description separates them.
        "ibiblioteka_audio": ibiblioteka_parsers.parse_product_page(
            (FIXTURES / "ibiblioteka" / "product_detail_audio.json").read_text()
        ),
        "ibiblioteka_rewrite": [
            {"url": url, "result": ibiblioteka_parsers.rewrite_scan_url(url)}
            for url in (
                "https://ibiblioteka.lt/metis-api/bibliographic-records/public/2097094",
                "https://ibiblioteka.lt/metis-api/bibliographic-records/public/C1B0000814700",
            )
        ],
        "pegasas_rewrite": [
            {"url": url, "result": pegasas_parsers.rewrite_scan_url(url)}
            for url in (
                "https://www.pegasas.lt/knyga-1115331",
                "https://www.pegasas.lt/knyga-1115331/",
                "https://www.pegasas.lt/no-sku-here",
                "https://www.pegasas.lt/multi-dash-slug-42",
            )
        ],
    }
    for name, data in cases.items():
        path = GOLDEN / f"{name}.json"
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            + "\n"
        )
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
