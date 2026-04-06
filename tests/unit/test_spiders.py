"""Test generic spiders using fake Scrapy responses (no network, no DB)."""

from pathlib import Path

import pytest
from scrapy import Request
from scrapy.http import HtmlResponse, TextResponse

from book_scraper.items import DiscoveredUrlItem, ListingItem, PriceItem
from book_scraper.spiders.discover import DiscoverSpider

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fake_response(url: str, body: str, cls=HtmlResponse, meta=None):
    """Build a fake Scrapy response with optional request meta."""
    request = Request(url=url, meta=meta or {})
    return cls(url=url, body=body, encoding="utf-8", request=request)


class TestDiscoverSpiderInit:
    def test_requires_shop_arg(self):
        with pytest.raises(ValueError, match="Missing required argument: shop"):
            DiscoverSpider()

    def test_requires_valid_strategy(self):
        with pytest.raises(ValueError, match="Strategy.*not configured"):
            DiscoverSpider(shop="vaga", strategy="nonexistent")

    def test_creates_with_valid_args(self):
        spider = DiscoverSpider(shop="vaga", strategy="sitemap")
        assert spider.shop_name == "vaga"
        assert spider.strategy == "sitemap"
        assert "vaga.lt" in spider.allowed_domains


class TestDiscoverSpiderSitemap:
    def test_start_requests_yields_sitemap_url(self):
        spider = DiscoverSpider(shop="vaga", strategy="sitemap")
        requests = list(spider.start_requests())
        assert len(requests) == 1
        assert "sitemap" in requests[0].url

    def test_parse_sitemap_yields_discovered_urls(self):
        spider = DiscoverSpider(shop="vaga", strategy="sitemap")
        xml = (FIXTURES / "vaga_sitemap.xml").read_text()
        response = _fake_response("https://vaga.lt/sitemap.xml", xml, cls=TextResponse)
        items = list(spider.parse_sitemap(response))
        assert len(items) > 0
        assert all(isinstance(item, DiscoveredUrlItem) for item in items)
        assert all(item["source"] == "sitemap" for item in items)
        assert all(item["shop_name"] == "vaga" for item in items)


class TestDiscoverSpiderCategories:
    def test_start_requests_yields_page_1(self):
        spider = DiscoverSpider(shop="vaga", strategy="categories")
        requests = list(spider.start_requests())
        assert len(requests) == 1
        assert "page=1" in requests[0].url

    def test_parse_categories_yields_urls_and_prices(self):
        spider = DiscoverSpider(shop="vaga", strategy="categories")
        html = (FIXTURES / "vaga_category_page.html").read_text()
        response = _fake_response(
            "https://vaga.lt/knygos?limit=100&page=1", html, meta={"page": 1}
        )
        results = list(spider.parse_categories(response))

        discovered = [r for r in results if isinstance(r, DiscoveredUrlItem)]
        prices = [r for r in results if isinstance(r, PriceItem)]
        next_pages = [r for r in results if isinstance(r, Request)]

        assert len(discovered) > 0
        assert all(item["source"] == "category" for item in discovered)
        assert len(prices) > 0
        assert len(next_pages) == 1
        assert "page=2" in next_pages[0].url

    def test_parse_categories_empty_page_yields_nothing(self):
        spider = DiscoverSpider(shop="vaga", strategy="categories")
        html = "<html><body></body></html>"
        response = _fake_response(
            "https://vaga.lt/knygos?limit=100&page=99", html, meta={"page": 99}
        )
        results = list(spider.parse_categories(response))
        assert results == []


class TestDiscoverSpiderUrlFilter:
    def test_url_filter_applied(self):
        spider = DiscoverSpider(shop="vaga", strategy="sitemap")
        # vaga config has url_include_pattern that requires URLs to match
        assert spider.url_pattern is not None
        assert spider._url_passes_filter("https://vaga.lt/some-book-12345")
        assert not spider._url_passes_filter("https://vaga.lt/about")


class TestDiscoverSpiderFullCrawl:
    def test_start_requests_yields_start_url(self):
        spider = DiscoverSpider(shop="vaga", strategy="full_crawl")
        requests = list(spider.start_requests())
        assert len(requests) == 1
        assert requests[0].url == "https://vaga.lt"


class TestScanSpider:
    def test_requires_shop_arg(self):
        from book_scraper.spiders.scan import ScanSpider

        with pytest.raises(ValueError, match="Missing required argument: shop"):
            ScanSpider()

    def test_creates_with_valid_args(self):
        from book_scraper.spiders.scan import ScanSpider

        spider = ScanSpider(shop="vaga")
        assert spider.shop_name == "vaga"
        assert "vaga.lt" in spider.allowed_domains

    def test_parse_product_yields_listing_item(self):
        from book_scraper.spiders.scan import ScanSpider

        spider = ScanSpider(shop="vaga")
        html = (FIXTURES / "vaga_product_page.html").read_text()
        response = _fake_response(
            "https://vaga.lt/test-book", html, meta={"discovered_url_id": 1}
        )
        items = list(spider.parse_product(response))
        listing_items = [i for i in items if isinstance(i, ListingItem)]
        assert len(listing_items) == 1
        item = listing_items[0]
        assert item["title"]
        assert item["url"] == "https://vaga.lt/test-book"
        assert item["shop_name"] == "vaga"

    def test_parse_product_skips_empty_title(self):
        from book_scraper.spiders.scan import ScanSpider

        spider = ScanSpider(shop="vaga")
        html = "<html><body><h1></h1></body></html>"
        response = _fake_response(
            "https://vaga.lt/empty", html, meta={"discovered_url_id": 2}
        )
        items = list(spider.parse_product(response))
        listing_items = [i for i in items if isinstance(i, ListingItem)]
        assert listing_items == []
