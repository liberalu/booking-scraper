from pathlib import Path

from book_scraper.spiders.almalittera.parsers import (
    parse_category_page,
    parse_product_page,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "almalittera"


def test_parse_category_page_extracts_books_from_products_json():
    text = (FIXTURES / "products_page.json").read_text()
    result = parse_category_page(text)
    assert result["total"] is None
    products = result["products"]
    assert len(products) >= 1

    first = products[0]
    assert first["url"].startswith("https://almalittera.lt/products/")
    assert first["title"]
    assert first["author"]
    assert first["price"]
    assert first["sku"]
    assert first["in_stock"] is True
    assert first["image_url"].startswith("https://cdn.shopify.com/")
    assert first["type"] in ("book", "ebook", "audio")
    assert isinstance(first["properties"], dict)
    assert "shopify_tags" in first["properties"]


def test_parse_category_page_marks_epub_as_ebook():
    text = (FIXTURES / "products_page.json").read_text()
    result = parse_category_page(text)
    epubs = [p for p in result["products"] if p["type"] == "ebook"]
    assert epubs, "fixture should include at least one EPUB product"


def test_parse_category_page_normalises_placeholder_vendor_to_none():
    """Notebooks/stationery use vendor='Nėra Autoriaus' as a placeholder."""
    payload = (
        '{"products":[{"id":1,"title":"Sąsiuvinis X","handle":"x",'
        '"vendor":"Nėra Autoriaus","product_type":"","tags":[],'
        '"variants":[{"price":"5.00","sku":"S1","available":true}],'
        '"images":[]}]}'
    )
    products = parse_category_page(payload)["products"]
    assert products[0]["author"] is None


def test_parse_category_page_handles_invalid_json():
    result = parse_category_page("not json")
    assert result == {"products": [], "total": None}


def test_parse_category_page_strips_query_safe_handle():
    payload = (
        '{"products":[{"id":1,"title":"X","handle":"abc","vendor":"V",'
        '"product_type":"","tags":[],"variants":[],"images":[]}]}'
    )
    products = parse_category_page(payload)["products"]
    assert products[0]["url"] == "https://almalittera.lt/products/abc"


def test_parse_product_page_extracts_book_metadata():
    html = (FIXTURES / "product_page.html").read_text()
    data = parse_product_page(html)

    assert data["title"]
    assert data["author"]
    assert data["isbn"]
    assert data["isbn"].startswith("978")
    assert data["sku"]
    assert data["pages"] == 24
    assert data["year"] == 2026
    assert data["cover_type"] == "Kietas"
    assert data["format"] == "hardcover"
    assert data["price"] is not None
    assert data["in_stock"] is True
    assert data["is_book_product"] is True
    assert data["type"] == "book"
    assert data["image_url"]
    assert data["schema_types"]


def test_parse_product_page_classifies_ebook():
    html = (FIXTURES / "ebook_page.html").read_text()
    data = parse_product_page(html)

    assert data["title"] and "E.knyga" in data["title"]
    assert data["isbn"] and data["isbn"].startswith("978")
    assert data["type"] == "ebook"
    assert data["format"] == "ebook"
    assert data["is_book_product"] is True
    assert data["translator"]


def test_parse_product_page_drops_notebook_as_non_book():
    """Stationery products carry the 'Nėra Autoriaus' placeholder vendor and
    a non-ISBN EAN (4779*); the classifier must reject them as non-books."""
    html = (FIXTURES / "notebook_page.html").read_text()
    data = parse_product_page(html)

    assert data["title"] and "Sąsiuvinis" in data["title"]
    assert data["isbn"] and not data["isbn"].startswith("978")
    assert data["author"] is None
    assert data["is_book_product"] is False
    assert data["type"] == "non_book"


def test_parse_product_page_handles_empty_html():
    data = parse_product_page("")
    assert data["title"] is None
    assert data["isbn"] is None
    assert data["is_book_product"] is False
