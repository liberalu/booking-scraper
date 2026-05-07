"""Unit tests for the patogupirkti.lt parser module.

patogupirkti is a Magento 1 shop with rich `itemprop` microdata on
product pages and a `<div class="product">` card grid on category
listings whose cards carry an inline `product_tracking_data_<id>` JS
object with name/id/price/category/brand/variant.

Sitemap is a sitemap-of-sitemaps (index → two product sitemaps with
~50 k + ~10 k URLs). The parser handles the index format by fetching
child sitemaps; tests stub the fetch with a fake transport.
"""

from pathlib import Path
from unittest.mock import patch

from book_scraper.spiders.patogupirkti.parsers import (
    parse_category_page,
    parse_product_page,
    parse_sitemap_urls,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "patogupirkti"


def test_parse_sitemap_urls_returns_urls_from_flat_urlset():
    """A plain `<urlset>` returns its <loc> entries verbatim."""
    xml = (FIXTURES / "sitemap_product.xml").read_text(encoding="utf-8")
    urls = parse_sitemap_urls(xml)
    assert urls
    assert all(u.startswith("https://www.patogupirkti.lt/knyga/") for u in urls)
    assert all(u.endswith(".html") for u in urls)
    # Fixture is truncated to 30 entries.
    assert len(urls) == 30


def test_parse_sitemap_urls_recurses_into_sitemap_index():
    """A `<sitemapindex>` causes the parser to fetch each child product
    sitemap and concatenate their URL lists.

    Fetch is stubbed: discover only runs once per week so blocking
    briefly during sitemap parsing is acceptable, but tests don't make
    real network calls.
    """
    xml = (FIXTURES / "sitemap_index.xml").read_text(encoding="utf-8")
    child_xml = (FIXTURES / "sitemap_product.xml").read_text(encoding="utf-8")

    fetched: list[str] = []

    def fake_fetch(url: str) -> str:
        fetched.append(url)
        return child_xml

    with patch(
        "book_scraper.spiders.patogupirkti.parsers._fetch_child_sitemap",
        side_effect=fake_fetch,
    ):
        urls = parse_sitemap_urls(xml)

    # Two product sitemaps should be fetched (sitemap_product.xml +
    # sitemap_product-1.xml). Other children (category/page/main/...) are
    # skipped — they don't carry product URLs.
    assert len(fetched) == 2
    assert all("sitemap_product" in u for u in fetched)
    # 30 URLs from each fake fetch → 60 total.
    assert len(urls) == 60
    assert all(u.startswith("https://www.patogupirkti.lt/knyga/") for u in urls)


def test_parse_category_page_extracts_card_grid():
    html = (FIXTURES / "category_page.html").read_text(encoding="utf-8")
    result = parse_category_page(html)
    assert result["total"] is None  # patogupirkti doesn't expose count
    products = result["products"]
    # Live grozine-literatura page renders 150 cards.
    assert len(products) >= 100

    # Every card must carry url + title.
    assert all(p["url"] for p in products)
    assert all(p["title"] for p in products)
    # Every URL is on the /knyga/ namespace.
    assert all("/knyga/" in p["url"] and p["url"].endswith(".html") for p in products)


def test_parse_category_page_card_carries_price_author_sku():
    """A card with a `product_tracking_data_<id>` JS block has all of
    name, id, price, brand (author), variant (publisher/year/format)."""
    html = (FIXTURES / "category_page.html").read_text(encoding="utf-8")
    products = parse_category_page(html)["products"]
    # Find the Nutildytieji card — known from recon: id=62181, price=15.39,
    # brand=Patricia Gibney, discount 22%.
    nutildytieji = next(
        (p for p in products if "nutildytieji" in p["url"]),
        None,
    )
    assert nutildytieji is not None
    assert nutildytieji["title"] == "Nutildytieji"
    assert nutildytieji["author"] == "Patricia Gibney"
    # `product_tracking_data` carries the regular (pre-discount) price.
    # The actual currently-displayed price is the discounted value
    # rendered in the card's price block — both should be captured.
    assert nutildytieji["price_original"] == "15.39"
    # Discounted price rendered in the card.
    assert nutildytieji["price"] == "12.05"
    assert nutildytieji["sku"] == "62181"
    assert nutildytieji["in_stock"] is True


def test_parse_product_page_extracts_microdata_fields():
    html = (FIXTURES / "product_page.html").read_text(encoding="utf-8")
    data = parse_product_page(html)

    assert data["title"] == "Pelynų medus. Mano istorija"
    assert data["author"] == "Edita Mildažytė"
    assert data["publisher"] == "Makas"
    assert data["year"] == 2025
    assert data["pages"] == 288
    assert data["isbn"] == "9786099658308"
    assert data["price"] == "23.84"
    assert data["in_stock"] is True
    assert data["cover_type"] == "15x21, kieti viršeliai"
    # cover_type contains "kieti viršeliai" → format normalises to
    # "hardcover" via format_from_cover_type.
    assert data["format"] == "hardcover"
    assert data["description"]
    assert "Pelynų medus" in data["description"]
    assert data["image_url"]
    assert data["categories"]  # breadcrumb chain
    assert data["is_book_product"] is True
    assert data["type"] == "book"


def test_parse_product_page_translator_field():
    """The alt fixture is a translated book — Vertėjas + Iš kokios
    kalbos versta should both be captured (translator stays as a top-
    level field; source language under properties)."""
    html = (FIXTURES / "product_page_alt.html").read_text(encoding="utf-8")
    data = parse_product_page(html)

    assert data["title"] == "Širdies puslapiai"
    assert data["author"] == "Kate Storey"
    assert data["publisher"] == "Tyto alba"
    assert data["year"] == 2026
    assert data["isbn"] == "9786094669354"
    assert data["translator"] == "Jolita Parvickienė"
    assert data["is_book_product"] is True


def test_parse_product_page_handles_missing_microdata():
    """A response without `itemprop` attributes (e.g. blocked / partial
    fetch) returns an empty product result without raising."""
    data = parse_product_page("<html><body>nothing here</body></html>")
    assert data["title"] is None
    assert data["isbn"] is None
    assert data["price"] is None
    assert data["is_book_product"] is False
