import pytest

from book_scraper.spiders.registry import load_parsers


def test_load_parsers_returns_vaga_module():
    parsers = load_parsers("vaga")
    assert hasattr(parsers, "parse_sitemap_urls")
    assert hasattr(parsers, "parse_category_page")
    assert hasattr(parsers, "parse_product_page")


def test_load_parsers_unknown_shop_raises():
    with pytest.raises(ImportError):
        load_parsers("nonexistent_shop")
