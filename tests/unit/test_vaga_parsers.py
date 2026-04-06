from pathlib import Path

from book_scraper.spiders.vaga.parsers import (
    parse_category_page,
    parse_product_page,
    parse_sitemap_urls,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_sitemap_urls():
    xml_content = (FIXTURES / "vaga_sitemap.xml").read_text()
    urls = parse_sitemap_urls(xml_content)
    assert len(urls) > 0
    assert all(url.startswith("https://vaga.lt/") for url in urls)


def test_parse_category_page():
    html = (FIXTURES / "vaga_category_page.html").read_text()
    products = parse_category_page(html)
    assert len(products) > 0
    first = products[0]
    assert "url" in first
    assert "title" in first
    assert "price" in first
    assert first["url"].startswith("https://vaga.lt/")


def test_parse_product_page():
    html = (FIXTURES / "vaga_product_page.html").read_text()
    data = parse_product_page(html)
    assert data["title"] is not None
    assert data["price"] is not None
    assert data["author"] is not None
    assert "isbn" in data
    assert "in_stock" in data
    assert "categories" in data
