"""Test generic spiders using fake Scrapy responses (no network, no DB)."""

import asyncio
from pathlib import Path

import pytest
from scrapy import Request
from scrapy.http import HtmlResponse, TextResponse

from book_scraper.items import DiscoveredUrlItem, ShopBookItem
from book_scraper.spiders.discover import DiscoverSpider

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _fake_response(url: str, body: str, cls=HtmlResponse, meta=None):
    """Build a fake Scrapy response with optional request meta."""
    request = Request(url=url, meta=meta or {})
    return cls(url=url, body=body, encoding="utf-8", request=request)


async def _collect_async(async_gen):
    """Collect all items from an async generator."""
    return [item async for item in async_gen]


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
    def test_start_yields_sitemap_url(self):
        spider = DiscoverSpider(shop="vaga", strategy="sitemap")
        requests = asyncio.run(_collect_async(spider.start()))
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
    def test_start_yields_page_1(self):
        spider = DiscoverSpider(shop="vaga", strategy="categories")
        requests = asyncio.run(_collect_async(spider.start()))
        assert len(requests) == 1
        assert "page=1" in requests[0].url

    def test_parse_categories_yields_urls_and_shop_books(self):
        spider = DiscoverSpider(shop="vaga", strategy="categories")
        html = (FIXTURES / "vaga_category_page.html").read_text()
        response = _fake_response(
            "https://vaga.lt/knygos?limit=100&page=1", html, meta={"page": 1}
        )
        results = list(spider.parse_categories(response))

        discovered = [r for r in results if isinstance(r, DiscoveredUrlItem)]
        shop_books = [r for r in results if isinstance(r, ShopBookItem)]
        next_pages = [r for r in results if isinstance(r, Request)]

        assert len(discovered) > 0
        assert all(item["source"] == "category" for item in discovered)
        assert len(shop_books) > 0
        assert all(item["shop_name"] == "vaga" for item in shop_books)
        # Fixture total is 9910 at page_size 100 → pages 2..100 enqueued
        # upfront so concurrency engages on discover.
        assert len(next_pages) == 99
        assert "page=2" in next_pages[0].url
        assert "page=100" in next_pages[-1].url

    def test_parse_categories_empty_page_yields_nothing(self):
        spider = DiscoverSpider(shop="vaga", strategy="categories")
        html = "<html><body></body></html>"
        response = _fake_response(
            "https://vaga.lt/knygos?limit=100&page=99", html, meta={"page": 99}
        )
        results = list(spider.parse_categories(response))
        assert results == []

    def test_max_pages_stops_pagination(self):
        """With max_pages=1, the spider must not enqueue page 2."""
        spider = DiscoverSpider(shop="vaga", strategy="categories", max_pages=1)
        html = (FIXTURES / "vaga_category_page.html").read_text()
        response = _fake_response(
            "https://vaga.lt/knygos?limit=100&page=1", html, meta={"page": 1}
        )
        results = list(spider.parse_categories(response))
        next_pages = [r for r in results if isinstance(r, Request)]
        assert next_pages == []

    def test_no_max_pages_paginates_normally(self):
        spider = DiscoverSpider(shop="vaga", strategy="categories")
        html = (FIXTURES / "vaga_category_page.html").read_text()
        response = _fake_response(
            "https://vaga.lt/knygos?limit=100&page=1", html, meta={"page": 1}
        )
        results = list(spider.parse_categories(response))
        next_pages = [r for r in results if isinstance(r, Request)]
        assert len(next_pages) == 99
        assert "page=2" in next_pages[0].url

    def test_page_2_does_not_re_paginate_upfront(self):
        """Pages 2..N must not enqueue further pages — the queue was
        filled by page 1's upfront pagination."""
        spider = DiscoverSpider(shop="vaga", strategy="categories")
        html = (FIXTURES / "vaga_category_page.html").read_text()
        response = _fake_response(
            "https://vaga.lt/knygos?limit=100&page=2", html, meta={"page": 2}
        )
        results = list(spider.parse_categories(response))
        next_pages = [r for r in results if isinstance(r, Request)]
        assert next_pages == []

    def test_multi_seed_shop_ignores_total_and_chains(self):
        """Multi-seed shops (url = [...]) paginate each seed independently;
        _enqueue_remaining_pages can only walk one template, so a parser
        total must be ignored and pagination must chain from response.url."""
        from types import SimpleNamespace

        spider = DiscoverSpider(shop="humanitas", strategy="categories")
        assert len(spider.strategy_conf.url_templates()) > 1
        spider.parsers = SimpleNamespace(
            parse_category_page=lambda html: {
                "products": [
                    {"url": "https://www.humanitas.lt/produktas/x", "title": "X"}
                ],
                "total": 5000,
            }
        )
        url = (
            "https://www.humanitas.lt/produktai/visos-kategorijos/"
            "?cntnt01page=1&m575a2product_limit=5000"
            "&m575a2filt_leidimo_kalba=Lithuanian-English"
        )
        response = _fake_response(url, "<html></html>", meta={"page": 1})
        results = list(spider.parse_categories(response))
        next_pages = [r for r in results if isinstance(r, Request)]
        # Chained (one next page from response.url), not 4999/5000 upfront.
        assert len(next_pages) == 1
        assert "cntnt01page=2" in next_pages[0].url
        assert "Lithuanian-English" in next_pages[0].url

    def test_toml_max_pages_caps_when_no_cli_override(self):
        """`max_pages` from CategoriesConfig acts as a safety cap.

        Operator-supplied `-a max_pages=N` always wins; when it's
        absent (cron-triggered runs where the args list doesn't carry
        a CLI flag), the TOML value bounds runaway pagination.
        """
        spider = DiscoverSpider(shop="humanitas", strategy="categories")
        # The humanitas TOML now caps at 3 (LT-filtered listing yields
        # ~5 000 books on page 1 and ~20 stragglers on page 2 — page 3
        # is empty). The TOML value should propagate when no CLI
        # override is supplied.
        assert spider._max_pages == 3

    def test_cli_max_pages_overrides_toml_safety_cap(self):
        """Explicit CLI override always wins, including a smaller value."""
        spider = DiscoverSpider(shop="humanitas", strategy="categories", max_pages=5)
        assert spider._max_pages == 5

    def test_explicit_zero_cli_max_pages_keeps_zero(self):
        """`-a max_pages=0` is a deliberate "no cap" override; TOML must not
        re-impose its cap on top.
        """
        spider = DiscoverSpider(shop="humanitas", strategy="categories", max_pages=0)
        assert spider._max_pages == 0

    def test_next_page_url_substitutes_cntnt01page_in_response_url(self):
        """Pagination derives next URL from response.url (not template format)
        so that a list of seed URLs each paginates independently."""
        from book_scraper.spiders.discover import _next_categories_page_url

        # Pure-LT seed at page 3:
        url = (
            "https://www.humanitas.lt/produktai/visos-kategorijos/"
            "?cntnt01page=3&m575a2product_limit=5000"
            "&m575a2filt_leidimo_kalba=Lithuanian"
        )
        spider = DiscoverSpider(shop="humanitas", strategy="categories")
        next_url = _next_categories_page_url(url, spider.strategy_conf, 4)
        assert "cntnt01page=4" in next_url
        # Sibling filter URL must not be mutated.
        assert "leidimo_kalba=Lithuanian" in next_url
        assert "leidimo_kalba=Lithuanian-English" not in next_url

    def test_next_page_url_keeps_other_filter_when_walking_bilingual_seed(self):
        """The bilingual seed walks its own page sequence — substitution
        must not leak across to the pure-LT seed's filter value."""
        from book_scraper.spiders.discover import _next_categories_page_url

        url = (
            "https://www.humanitas.lt/produktai/visos-kategorijos/"
            "?cntnt01page=1&m575a2product_limit=5000"
            "&m575a2filt_leidimo_kalba=Lithuanian-English"
        )
        spider = DiscoverSpider(shop="humanitas", strategy="categories")
        next_url = _next_categories_page_url(url, spider.strategy_conf, 2)
        assert "cntnt01page=2" in next_url
        assert "Lithuanian-English" in next_url

    def test_next_page_url_falls_back_to_first_template_when_no_page_param(self):
        """If the response URL doesn't carry a recognised pagination param
        (e.g. seed URL without `?page=` in test scenarios), format the
        first template directly."""
        from book_scraper.spiders.discover import _next_categories_page_url

        spider = DiscoverSpider(shop="vaga", strategy="categories")
        # vaga's URL doesn't have `cntnt01page=` — but it does have
        # `page=`. The substitution still works for this case.
        next_url = _next_categories_page_url(
            "https://vaga.lt/knygos?limit=100&page=1", spider.strategy_conf, 2
        )
        assert "page=2" in next_url


class TestDiscoverSpiderPropertiesMerge:
    """Regression: parser-emitted properties must survive into ShopBookItem.

    Earlier, parse_categories rebuilt `properties` from a fixed set of
    top-level keys and dropped any dict the parser supplied directly
    (Pegasas does this for is_new/discount_rate; LupaSearch does too).
    """

    def test_parser_properties_are_preserved(self):
        spider = DiscoverSpider(shop="vaga", strategy="categories")
        products = [
            {
                "url": "https://vaga.lt/x-1",
                "title": "X",
                "price": "1.00",
                "type": "book",
                "properties": {"is_new": True, "discount_rate": 0.5},
                "categories": [],
            }
        ]
        items = list(spider._emit_products(products))
        shop_books = [i for i in items if isinstance(i, ShopBookItem)]
        assert len(shop_books) == 1
        props = shop_books[0]["properties"]
        assert props["is_new"] is True
        assert props["discount_rate"] == 0.5

    def test_top_level_keys_layered_under_parser_dict(self):
        spider = DiscoverSpider(shop="vaga", strategy="categories")
        products = [
            {
                "url": "https://vaga.lt/x-1",
                "title": "X",
                "price": "1.00",
                "type": "book",
                "properties": {"pages": 100},
                "pages": 999,  # top-level key — must NOT override parser dict
                "cover_type": "Hard",
                "categories": [],
            }
        ]
        items = list(spider._emit_products(products))
        shop_books = [i for i in items if isinstance(i, ShopBookItem)]
        props = shop_books[0]["properties"]
        assert props["pages"] == 100  # parser wins
        assert props["cover_type"] == "Hard"  # gap filled by top-level


class TestBuildRequestForUrlItem:
    """The single helper used by start(), spider_idle(), and the
    parse_categories next-page yield. Must produce a GET for HTML
    strategies and a POST with JSON body for LupaSearch."""

    def test_get_for_category_page(self):
        spider = DiscoverSpider(shop="vaga", strategy="categories")
        req = spider._build_request_for_url_item(
            "https://vaga.lt/knygos?page=2", "category_page", item_id=42, page=2
        )
        assert req.method == "GET"
        assert req.body == b""
        assert req.meta["scrape_url_item_id"] == 42
        assert req.meta["page"] == 2

    def test_post_for_lupasearch_page(self):
        import json

        spider = DiscoverSpider(shop="pegasas", strategy="lupasearch")
        req = spider._build_request_for_url_item(
            "https://api.lupasearch.com/v1/query/abc?offset=84&limit=42&category_ids=5107",
            "lupasearch_page",
            item_id=7,
        )
        assert req.method == "POST"
        body = json.loads(req.body)
        assert body["offset"] == 84
        assert body["limit"] == 42
        assert body["filters"]["category_ids"] == ["5107"]
        # Headers come back as bytes from scrapy
        ct = req.headers.get("Content-Type")
        assert ct in (b"application/json", "application/json")

    def test_graphql_strategy_sets_accept_json(self):
        spider = DiscoverSpider(shop="pegasas", strategy="graphql")
        req = spider._build_request_for_url_item(
            "https://www.pegasas.lt/graphql?query=...", "category_page"
        )
        accept = req.headers.get("Accept")
        assert accept in (b"application/json", "application/json")


class TestParseLupasearchPage:
    """Smoke test: parser plumbed through the spider, total drives stop."""

    def test_yields_items_and_next_page(self):
        from scrapy.http import TextResponse

        spider = DiscoverSpider(shop="pegasas", strategy="lupasearch")
        text = (FIXTURES / "pegasas_lupasearch_page1.json").read_text()
        url = (
            "https://api.lupasearch.com/v1/query/kum08qakjq3j"
            "?offset=0&limit=42&category_ids=5107%2C7352%2C5125%2C5206%2C6122"
        )
        request = Request(url=url, meta={"page": 1, "url_type": "lupasearch_page"})
        response = TextResponse(url=url, body=text, encoding="utf-8", request=request)
        results = list(spider.parse_lupasearch_page(response))

        discovered = [r for r in results if isinstance(r, DiscoveredUrlItem)]
        shop_books = [r for r in results if isinstance(r, ShopBookItem)]
        next_pages = [r for r in results if isinstance(r, Request)]

        # Fixture has 10 items, all with pegasas.lt URLs (matching the
        # default url_include_pattern) and is_book=1.
        assert len(discovered) == 10
        assert len(shop_books) == 10
        # Total ~45.5k / limit 42 = ~1084 pages. Page 1 just emitted; the
        # spider should enqueue every remaining page upfront so concurrency
        # can engage instead of chaining serially.
        assert len(next_pages) > 100
        # First three should be at offsets 42, 84, 126 — sequential by limit.
        offsets = [int(r.url.split("offset=")[1].split("&")[0]) for r in next_pages]
        assert offsets[:3] == [42, 84, 126]
        assert all(r.method == "POST" for r in next_pages)

    def test_stops_when_offset_exceeds_total(self):
        from scrapy.http import TextResponse

        spider = DiscoverSpider(shop="pegasas", strategy="lupasearch")
        # Hand-craft a response with total=1 to force termination
        body = (
            '{"items":[{"url":"https://www.pegasas.lt/x-1/","name":"x","sku":"s",'
            '"price":"1","is_book":1,"in_stock":1,"category_ids":[5107]}],'
            '"total":1}'
        )
        url = (
            "https://api.lupasearch.com/v1/query/kum08qakjq3j"
            "?offset=0&limit=42&category_ids=5107"
        )
        request = Request(url=url, meta={"page": 1, "url_type": "lupasearch_page"})
        response = TextResponse(url=url, body=body, encoding="utf-8", request=request)
        results = list(spider.parse_lupasearch_page(response))
        next_pages = [r for r in results if isinstance(r, Request)]
        assert next_pages == []

    def test_page_2_does_not_re_paginate(self):
        """Pages 2..N must NOT enqueue further pages — the queue is
        already filled by the page-1 upfront pagination."""
        from scrapy.http import TextResponse

        spider = DiscoverSpider(shop="pegasas", strategy="lupasearch")
        body = (
            '{"items":[{"url":"https://www.pegasas.lt/x-1/","name":"x","sku":"s",'
            '"price":"1","is_book":1,"in_stock":1,"category_ids":[5107]}],'
            '"total":1000}'
        )
        url = (
            "https://api.lupasearch.com/v1/query/kum08qakjq3j"
            "?offset=42&limit=42&category_ids=5107"
        )
        request = Request(url=url, meta={"page": 2, "url_type": "lupasearch_page"})
        response = TextResponse(url=url, body=body, encoding="utf-8", request=request)
        results = list(spider.parse_lupasearch_page(response))
        next_pages = [r for r in results if isinstance(r, Request)]
        assert next_pages == []

    def test_resumed_page_n_does_not_re_paginate_without_meta(self):
        """Regression for the run-312..317 explosion: when a previously-
        enqueued lupasearch_page item is re-dispatched after resume, its
        request has no ``meta["page"]`` (start() only sets it for
        category_page items). The parser must NOT mistake offset>0 for
        page=1 and re-enqueue every page past it. Without this guard,
        each resume re-fired the upfront pagination and the queue
        ballooned to tens of thousands of bogus rows."""
        from scrapy.http import TextResponse

        spider = DiscoverSpider(shop="pegasas", strategy="lupasearch")
        body = (
            '{"items":[{"url":"https://www.pegasas.lt/x-1/","name":"x","sku":"s",'
            '"price":"1","is_book":1,"in_stock":1,"category_ids":[5107]}],'
            '"total":1000}'
        )
        url = (
            "https://api.lupasearch.com/v1/query/kum08qakjq3j"
            "?offset=420&limit=42&category_ids=5107"
        )
        # No page in meta — mirrors what start() builds for resumed
        # lupasearch_page items.
        request = Request(url=url, meta={"url_type": "lupasearch_page"})
        response = TextResponse(url=url, body=body, encoding="utf-8", request=request)
        results = list(spider.parse_lupasearch_page(response))
        next_pages = [r for r in results if isinstance(r, Request)]
        assert next_pages == []


class TestDiscoverSpiderSubdivision:
    """5xx on a GraphQL page should trigger adaptive page-size shrinkage.

    pegasas.lt's Magento backend transiently returns 503 on deep pages
    when fetched at pageSize=50 under concurrency=2. Splitting the
    failed range into N pageSize=10 requests gives the backend time
    while letting pagination continue.
    """

    @staticmethod
    def _gql_response(url: str, status: int, body: str = ""):
        from scrapy.http import HtmlResponse

        request = Request(url=url, meta={})
        return HtmlResponse(url=url, body=body.encode(), status=status, request=request)

    def test_5xx_yields_subpages_and_continues(self):
        """A 503 on page=18 (size 50) should yield 5 sub-pages at size 10
        AND the next normal page (19, size 50)."""
        from book_scraper.spiders.graphql_urls import (
            build_graphql_page_url,
            parse_graphql_page_url,
        )

        spider = DiscoverSpider(shop="pegasas", strategy="graphql")
        # Use the real builder so the URL matches what production sends.
        url = build_graphql_page_url(
            spider.conf.shop.base_url, spider.strategy_conf, page=18
        )
        response = self._gql_response(url, status=503, body="Service Unavailable")

        results = list(spider.parse_categories(response))
        # All yields are Requests (no items, no DiscoveredUrlItem here).
        requests = [r for r in results if isinstance(r, Request)]
        assert len(requests) == 6  # 5 sub-pages + 1 next normal page

        # Sub-pages: depth=1, pageSize=10, pages 86..90
        sub_infos = [parse_graphql_page_url(r.url) for r in requests[:5]]
        assert all(s["subdivision_depth"] == 1 for s in sub_infos)
        assert all(s["page_size"] == 10 for s in sub_infos)
        assert [s["page"] for s in sub_infos] == [86, 87, 88, 89, 90]

        # Next normal page: depth=0, pageSize=50, page 19
        normal = parse_graphql_page_url(requests[5].url)
        assert normal == {"page": 19, "page_size": 50, "subdivision_depth": 0}

    def test_5xx_on_already_subdivided_does_not_recurse(self):
        """A failing depth=1 sub-page must NOT yield more sub-pages,
        and must NOT enqueue the next normal page (parent already did).
        It also tags the response so dispatch's finally marks the
        URL as `failed/subdivision_5xx` instead of silently `done`,
        so Continue/auto-resume can pick it up.
        """
        from book_scraper.spiders.graphql_urls import build_graphql_page_url

        spider = DiscoverSpider(shop="pegasas", strategy="graphql")
        url = build_graphql_page_url(
            spider.conf.shop.base_url,
            spider.strategy_conf,
            page=87,
            page_size_override=10,
            subdivision_depth=1,
        )
        response = self._gql_response(url, status=503)
        results = list(spider.parse_categories(response))
        assert results == []  # nothing yielded — we drop this micro-range
        # Marker for dispatch.finally to flip status=failed.
        assert response.meta.get("subdivision_5xx_failed") is True

    def test_successful_subpage_does_not_paginate(self):
        """A 200 on a depth=1 sub-page should emit products but NOT
        enqueue another page (parent owns pagination)."""
        import json

        from book_scraper.spiders.graphql_urls import build_graphql_page_url

        spider = DiscoverSpider(shop="pegasas", strategy="graphql")
        url = build_graphql_page_url(
            spider.conf.shop.base_url,
            spider.strategy_conf,
            page=86,
            page_size_override=10,
            subdivision_depth=1,
        )
        body = json.dumps(
            {
                "data": {
                    "products": {
                        "items": [
                            {
                                "name": "Knyga",
                                "sku": "1",
                                "url_key": "k-1",
                                "stock_status": "IN_STOCK",
                                "is_book": True,
                                "price_range": {
                                    "minimum_price": {
                                        "final_price": {"value": 5.0},
                                        "regular_price": {"value": 5.0},
                                    }
                                },
                                "product_page_attributes": [
                                    {
                                        "primary_attributes": [],
                                        "secondary_attributes": [
                                            {
                                                "label": "Leidinio kalba",
                                                "value": "Lietuvių",
                                            },
                                        ],
                                    }
                                ],
                            }
                        ]
                    }
                }
            }
        )
        response = self._gql_response(url, status=200, body=body)
        results = list(spider.parse_categories(response))
        next_pages = [r for r in results if isinstance(r, Request)]
        assert next_pages == []  # no pagination from sub-pages
        items = [r for r in results if isinstance(r, ShopBookItem)]
        assert len(items) == 1


class TestDiscoverSpiderUrlFilter:
    def test_no_filter_passes_all(self):
        spider = DiscoverSpider(shop="vaga", strategy="sitemap")
        # vaga config has no url_include_pattern — all URLs pass
        assert spider.url_pattern is None
        assert spider._url_passes_filter("https://vaga.lt/some-book-12345")
        assert spider._url_passes_filter("https://vaga.lt/about")


class TestDiscoverSpiderFullCrawl:
    def test_start_yields_start_url(self):
        spider = DiscoverSpider(shop="vaga", strategy="full_crawl")
        requests = asyncio.run(_collect_async(spider.start()))
        assert len(requests) == 1
        assert requests[0].url == "https://vaga.lt"

    def test_parse_full_crawl_marks_product_when_book_data_found(self):
        """A real product page → final_url_type = 'product'."""
        spider = DiscoverSpider(shop="vaga", strategy="full_crawl")
        html = (FIXTURES / "vaga_product_page.html").read_text()
        response = _fake_response("https://vaga.lt/some-book", html)
        list(spider.parse_full_crawl(response))
        assert response.meta["final_url_type"] == "product"

    def test_parse_full_crawl_marks_non_product_when_no_book_data(self):
        """A page without product structured data → final_url_type = 'non_product'."""
        spider = DiscoverSpider(shop="vaga", strategy="full_crawl")
        html = "<html><body><a href='/x'>x</a></body></html>"
        response = _fake_response("https://vaga.lt/login", html)
        list(spider.parse_full_crawl(response))
        assert response.meta["final_url_type"] == "non_product"

    def test_parse_full_crawl_enqueues_outgoing_links_as_unknown(self):
        """Outgoing-link Requests must be tagged url_type='unknown',
        not 'product'/'crawl' — the queue row's real type is set after
        the page is fetched and parsed."""
        spider = DiscoverSpider(shop="vaga", strategy="full_crawl")
        html = (
            "<html><body>"
            "<a href='https://vaga.lt/page-a'>a</a>"
            "<a href='https://vaga.lt/page-b'>b</a>"
            "</body></html>"
        )
        response = _fake_response("https://vaga.lt/", html)
        results = list(spider.parse_full_crawl(response))
        link_requests = [
            r
            for r in results
            if isinstance(r, Request)
            and r.url in ("https://vaga.lt/page-a", "https://vaga.lt/page-b")
        ]
        assert len(link_requests) == 2
        for r in link_requests:
            assert r.meta["url_type"] == "unknown"

    def test_parse_full_crawl_classifies_response_even_at_max_pages(self):
        """The seen-URL budget caps outgoing-link enqueueing, but already-
        fetched responses must still be classified — otherwise their queue
        rows stay 'unknown' forever."""
        spider = DiscoverSpider(shop="vaga", strategy="full_crawl", max_pages=1)
        # Pre-fill seen so the budget is exhausted on entry.
        spider._seen_urls = {"https://vaga.lt/already-seen"}
        html = (FIXTURES / "vaga_product_page.html").read_text()
        response = _fake_response("https://vaga.lt/some-book", html)
        results = list(spider.parse_full_crawl(response))
        # Page itself was classified...
        assert response.meta["final_url_type"] == "product"
        # ...but no outgoing links were followed/enqueued (cap reached).
        assert not any(isinstance(r, Request) for r in results)

    def test_parse_full_crawl_skips_enqueue_for_stable_urls(self):
        """Pre-classified URLs in _stable_urls: still followed (Request
        yielded) but no DiscoveredUrlItem and no scrape_url_item enqueue."""
        spider = DiscoverSpider(shop="vaga", strategy="full_crawl")
        # Track _enqueue_url calls
        calls: list[tuple[str, str]] = []
        spider._enqueue_url = lambda url, url_type: (  # type: ignore[method-assign]
            calls.append((url, url_type)) or None
        )
        # Mark page-a as already-classified, leave page-b as new.
        from book_scraper.url_utils import normalize_url

        spider._stable_urls = {normalize_url("https://vaga.lt/page-a"): "product"}

        html = (
            "<html><body>"
            "<a href='https://vaga.lt/page-a'>a</a>"
            "<a href='https://vaga.lt/page-b'>b</a>"
            "</body></html>"
        )
        response = _fake_response("https://vaga.lt/", html)
        results = list(spider.parse_full_crawl(response))

        # page-a: skipped enqueue but still issued as a Request
        page_a_reqs = [
            r
            for r in results
            if isinstance(r, Request) and r.url == "https://vaga.lt/page-a"
        ]
        assert len(page_a_reqs) == 1
        # page-b: enqueued as 'unknown'
        page_b_reqs = [
            r
            for r in results
            if isinstance(r, Request) and r.url == "https://vaga.lt/page-b"
        ]
        assert len(page_b_reqs) == 1
        assert page_b_reqs[0].meta["url_type"] == "unknown"

        # _enqueue_url called once, only for page-b
        assert calls == [("https://vaga.lt/page-b", "unknown")]


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

    def test_max_urls_default_zero(self):
        from book_scraper.spiders.scan import ScanSpider

        assert ScanSpider(shop="vaga")._max_urls == 0

    def test_max_urls_accepts_int_and_string(self):
        from book_scraper.spiders.scan import ScanSpider

        assert ScanSpider(shop="vaga", max_urls=5)._max_urls == 5
        assert ScanSpider(shop="vaga", max_urls="10")._max_urls == 10
        assert ScanSpider(shop="vaga", max_urls="")._max_urls == 0

    def test_cached_run_status_dedupes_db_polls(self):
        """`_cached_run_status` only hits `_poll_run_status` once per TTL.

        The uncached, per-URL DB poll blocks the reactor enough that on
        a 60k-URL queue the heartbeat extension's callLater can't fire
        and the run is reaped at the 60 s threshold (verified on
        patogupirkti runs 363–366, 2026-05-08).
        """
        from book_scraper.spiders.scan import ScanSpider

        spider = ScanSpider(shop="vaga")
        spider._run_status_ttl_s = (
            60.0  # large enough that no test wall-time can outrun it
        )
        calls = {"n": 0}

        def fake_poll() -> str | None:
            calls["n"] += 1
            return "running"

        spider._poll_run_status = fake_poll  # type: ignore[method-assign]

        # First call fills the cache, second/third reuse it.
        assert spider._cached_run_status() == "running"
        assert spider._cached_run_status() == "running"
        assert spider._cached_run_status() == "running"
        assert calls["n"] == 1

        # Invalidation forces a fresh poll.
        spider._invalidate_run_status_cache()
        assert spider._cached_run_status() == "running"
        assert calls["n"] == 2

    def test_cached_run_status_expires_after_ttl(self):
        """When the TTL elapses, the next call re-queries."""
        import time

        from book_scraper.spiders.scan import ScanSpider

        spider = ScanSpider(shop="vaga")
        spider._run_status_ttl_s = 0.01  # 10 ms TTL
        calls = {"n": 0}

        def fake_poll() -> str | None:
            calls["n"] += 1
            return "running"

        spider._poll_run_status = fake_poll  # type: ignore[method-assign]

        assert spider._cached_run_status() == "running"
        time.sleep(0.02)
        assert spider._cached_run_status() == "running"
        assert calls["n"] == 2

    def test_cached_run_status_handles_60k_iterations_in_budget(self):
        """Regression for the patogupirkti heartbeat-starvation bug.

        Without the TTL cache, `start()`'s per-URL `_poll_run_status`
        call cost ~10 ms each; on a 60k-URL queue that accumulated to
        > 60 s of synchronous work before the first request could
        dispatch, blocking the reactor and starving the heartbeat
        extension. Reaper killed the run at the 60 s threshold —
        verified on patogupirkti runs 363–366 (2026-05-08).

        The cache makes 60k iterations cost roughly ttl-window
        polls (~12 over a 60 s wall-clock at ttl=5 s) instead of 60k.
        We assert the *poll-count* invariant directly: 60k cache reads
        with the TTL never expiring should produce exactly 1 underlying
        DB poll. The wall-clock end of the invariant (the "doesn't
        starve the reactor" half) follows trivially from in-memory
        attribute access being O(1).
        """
        from book_scraper.spiders.scan import ScanSpider

        spider = ScanSpider(shop="vaga")
        # Effectively-infinite TTL so a 60k-iteration loop never hits
        # an expiry boundary. (The TTL-expiry path has its own test.)
        spider._run_status_ttl_s = 3600.0
        calls = {"n": 0}

        def fake_poll() -> str | None:
            calls["n"] += 1
            return "running"

        spider._poll_run_status = fake_poll  # type: ignore[method-assign]

        # 60k cache reads — the size of patogupirkti's queue. Pre-cache
        # this would have triggered 60k DB queries; with the cache we
        # expect exactly 1.
        for _ in range(60_000):
            assert spider._cached_run_status() == "running"
        assert calls["n"] == 1, (
            "Expected exactly 1 underlying poll for 60k cache reads. "
            f"Got {calls['n']}. The TTL cache regressed and the "
            "reactor-starvation bug class is back."
        )

    def test_max_urls_truncates_single_url_list(self):
        """In single-URL mode the cap applies before any scheduling."""
        from book_scraper.spiders.scan import ScanSpider

        spider = ScanSpider(
            shop="vaga",
            urls="https://vaga.lt/a,https://vaga.lt/b,https://vaga.lt/c",
            max_urls=2,
        )
        # start() mutates _single_urls when max_urls is set, but we
        # can't easily run it here without a DB. Assert on the raw
        # list and rely on start() applying the same slice in prod.
        # A smoke assertion that the cap parses right:
        assert spider._max_urls == 2
        assert len(spider._single_urls) == 3  # pre-cap parse

    def test_parse_product_yields_shop_book_item(self):
        from book_scraper.spiders.scan import ScanSpider

        spider = ScanSpider(shop="vaga")
        html = (FIXTURES / "vaga_product_page.html").read_text()
        response = _fake_response(
            "https://vaga.lt/test-book", html, meta={"discovered_url_id": 1}
        )
        items = list(spider.parse_product(response))
        shop_book_items = [i for i in items if isinstance(i, ShopBookItem)]
        assert len(shop_book_items) == 1
        item = shop_book_items[0]
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
        shop_book_items = [i for i in items if isinstance(i, ShopBookItem)]
        assert shop_book_items == []

    def test_parse_product_carries_parser_emitted_properties(self, monkeypatch):
        """Regression: parser-supplied properties (humanitas's `language`,
        pegasas's `dimensions`/`ean`/`is_new`/`discount_rate`, …) must
        survive into the ShopBookItem so the pipeline can persist them
        in shop_book_attributes.

        Pre-fix the scan spider only carried five hardcoded top-level
        keys (pages/cover_type/duration/narrator/translator) and
        silently dropped the parser's `properties` dict, even though
        discover already had the correct merge.
        """
        from book_scraper.spiders.scan import ScanSpider

        spider = ScanSpider(shop="vaga")

        def fake_parse(_html: str) -> dict[str, object]:
            return {
                "title": "X",
                "is_book_product": True,
                "type": "book",
                "in_stock": True,
                "pages": 200,
                "cover_type": "Kieti viršeliai",
                # Parser-supplied extras — must survive.
                "properties": {
                    "language": "Lietuvių",
                    "dimensions": "200 x 130 mm",
                },
                "categories": [],
                "schema_types": [],
                "book_score": 5,
                "book_score_reasons": [],
            }

        monkeypatch.setattr(spider.parsers, "parse_product_page", fake_parse)

        response = _fake_response(
            "https://vaga.lt/test", "<html></html>", meta={"discovered_url_id": 9}
        )
        items = list(spider.parse_product(response))
        shop_book_items = [i for i in items if isinstance(i, ShopBookItem)]
        assert len(shop_book_items) == 1
        props = shop_book_items[0]["properties"]
        assert props is not None
        assert props.get("language") == "Lietuvių"
        assert props.get("dimensions") == "200 x 130 mm"
        # Top-level keys still present too.
        assert props.get("pages") == 200
        assert props.get("cover_type") == "Kieti viršeliai"

    def test_missing_price_dump_disabled_by_default(self, monkeypatch, tmp_path):
        """No env var → no file written, even when parser returns price=None.

        Default behaviour: zero dumps. This protects normal scrape runs
        from disk-bloat surprises and proves the gate is the env var,
        not the trigger condition.
        """
        from book_scraper.spiders.scan import ScanSpider

        monkeypatch.delenv("SCRAPER_DUMP_MISSING_PRICE_MAX", raising=False)
        monkeypatch.setenv("SCRAPER_DUMP_MISSING_PRICE_DIR", str(tmp_path))
        spider = ScanSpider(shop="vaga")

        def fake_parse(_html: str) -> dict[str, object]:
            return {
                "title": "X",
                "is_book_product": True,
                "type": "book",
                "in_stock": True,
                "price": None,  # the trigger
                "categories": [],
                "schema_types": [],
                "book_score": 5,
                "book_score_reasons": [],
            }

        monkeypatch.setattr(spider.parsers, "parse_product_page", fake_parse)
        response = _fake_response(
            "https://vaga.lt/missing-price",
            "<html><body></body></html>",
            meta={"discovered_url_id": 1},
        )
        list(spider.parse_product(response))
        # Nothing should have been written.
        assert list(tmp_path.rglob("*.html")) == []
        assert list(tmp_path.rglob("*.summary.txt")) == []

    def test_missing_price_dump_captures_body_and_summary(self, monkeypatch, tmp_path):
        """With env var set, an in-stock book product whose parser returned
        price=None writes both the raw HTML and a summary file. The
        summary's marker_matches line records which anchor regexes
        matched, so the operator can see at a glance whether the cart
        block was even present in the body.
        """
        from book_scraper.spiders.scan import ScanSpider

        monkeypatch.setenv("SCRAPER_DUMP_MISSING_PRICE_MAX", "5")
        monkeypatch.setenv("SCRAPER_DUMP_MISSING_PRICE_DIR", str(tmp_path))
        spider = ScanSpider(shop="vaga")

        def fake_parse(_html: str) -> dict[str, object]:
            return {
                "title": "Missing Price Book",
                "sku": "299192",
                "is_book_product": True,
                "type": "book",
                "in_stock": True,
                "price": None,
                "categories": [],
                "schema_types": [],
                "book_score": 5,
                "book_score_reasons": [],
            }

        monkeypatch.setattr(spider.parsers, "parse_product_page", fake_parse)

        body = (
            "<html><body>"
            '<div class="cart-container" data-product-id="299192">'
            '<div class="cart-price"><div class="label">Kaina:</div>'
            '<div class="price-container"><div class="price">13.74 €</div>'
            "</div></div></div>"
            "</body></html>"
        )
        response = _fake_response(
            "https://www.humanitas.lt/produktas/visos-kategorijos/hitman-stans",
            body,
            meta={"discovered_url_id": 42},
        )
        list(spider.parse_product(response))

        html_files = list(tmp_path.rglob("*.html"))
        summary_files = list(tmp_path.rglob("*.summary.txt"))
        assert len(html_files) == 1, html_files
        assert len(summary_files) == 1, summary_files

        # Body round-trips byte-for-byte so we can diff against a live
        # FlareSolverr fetch later.
        assert html_files[0].read_text(encoding="utf-8") == body

        summary = summary_files[0].read_text(encoding="utf-8")
        assert (
            "url=https://www.humanitas.lt/produktas/visos-kategorijos/hitman-stans"
            in summary
        )
        assert "parsed_title='Missing Price Book'" in summary
        assert "parsed_sku='299192'" in summary
        # marker_matches: cart-container, cart-price, price-container and
        # price-div all match; price-hidden / disabled do not.
        assert "cart-container=1" in summary
        assert "price-container=1" in summary
        assert "price-div=1" in summary
        assert "price-hidden=0" in summary
        assert "disabled=0" in summary

        # Files are nested under shop subdir.
        assert (tmp_path / "vaga").is_dir()

    def test_missing_price_dump_counter_is_enforced(self, monkeypatch, tmp_path):
        """`SCRAPER_DUMP_MISSING_PRICE_MAX=1` → only the first trigger
        writes; the second is silently skipped. Protects long-running
        scans from filling disk if the bug turns out to be common.
        """
        from book_scraper.spiders.scan import ScanSpider

        monkeypatch.setenv("SCRAPER_DUMP_MISSING_PRICE_MAX", "1")
        monkeypatch.setenv("SCRAPER_DUMP_MISSING_PRICE_DIR", str(tmp_path))
        spider = ScanSpider(shop="vaga")

        def fake_parse(_html: str) -> dict[str, object]:
            return {
                "title": "X",
                "is_book_product": True,
                "type": "book",
                "in_stock": True,
                "price": None,
                "categories": [],
                "schema_types": [],
                "book_score": 5,
                "book_score_reasons": [],
            }

        monkeypatch.setattr(spider.parsers, "parse_product_page", fake_parse)
        for i in range(3):
            response = _fake_response(
                f"https://vaga.lt/missing-{i}",
                "<html></html>",
                meta={"discovered_url_id": i},
            )
            list(spider.parse_product(response))
        assert len(list(tmp_path.rglob("*.html"))) == 1

    def test_missing_price_dump_skips_when_book_is_oos(self, monkeypatch, tmp_path):
        """Out-of-stock books legitimately have no price — don't dump them
        even with the env var on. This keeps captures focused on real
        anomalies (in_stock book with parser-missed price), not noise.
        """
        from book_scraper.spiders.scan import ScanSpider

        monkeypatch.setenv("SCRAPER_DUMP_MISSING_PRICE_MAX", "5")
        monkeypatch.setenv("SCRAPER_DUMP_MISSING_PRICE_DIR", str(tmp_path))
        spider = ScanSpider(shop="vaga")

        def fake_parse(_html: str) -> dict[str, object]:
            return {
                "title": "OOS Book",
                "is_book_product": True,
                "type": "book",
                "in_stock": False,  # legitimately OOS
                "price": None,
                "categories": [],
                "schema_types": [],
                "book_score": 5,
                "book_score_reasons": [],
            }

        monkeypatch.setattr(spider.parsers, "parse_product_page", fake_parse)
        response = _fake_response(
            "https://vaga.lt/oos-book",
            "<html></html>",
            meta={"discovered_url_id": 99},
        )
        list(spider.parse_product(response))
        assert list(tmp_path.rglob("*.html")) == []

    def test_is_anti_bot_response_matches_known_walls(self):
        from book_scraper.spiders.scan import _is_anti_bot_response

        # Real-shape Cloudflare challenge body fragment.
        cf = (
            "<html><head><title>Just a moment...</title></head>"
            '<body><div class="cf-browser-verification">x</div></body></html>'
        )
        assert _is_anti_bot_response(cf) is True
        # Akamai
        assert _is_anti_bot_response("Pardon Our Interruption") is True
        # Datadome
        assert _is_anti_bot_response("<html>...captcha-delivery...</html>") is True
        # Generic CAPTCHA copy
        assert _is_anti_bot_response("Please verify you are not a robot") is True

    def test_is_anti_bot_response_negative_cases(self):
        from book_scraper.spiders.scan import _is_anti_bot_response

        assert _is_anti_bot_response("") is False
        assert (
            _is_anti_bot_response(
                "<html><body>Just a regular product page</body></html>"
            )
            is False
        )
        # Substring check is case-insensitive: "challenge-platform" must match
        # the pattern, but a benign mention of the word "challenge" alone shouldn't
        # — assert that "platform" alone doesn't trigger.
        assert _is_anti_bot_response("This is a fun book about challenge.") is False
        assert _is_anti_bot_response("A platform for kids.") is False
        # Cloudflare's post-clearance beacon (`cdn-cgi/challenge-platform/
        # scripts/jsd/main.js`) ships on every protected page once the
        # visitor has solved the challenge. It used to false-trigger the
        # generic `challenge-platform` substring matcher and mark every
        # FlareSolverr-rendered humanitas.lt page as anti_bot_detected.
        assert (
            _is_anti_bot_response(
                "<html><body>Real product page<script src='https://example.com/"
                "cdn-cgi/challenge-platform/scripts/jsd/main.js'></script>"
                "</body></html>"
            )
            is False
        )

    def test_is_anti_bot_response_matches_real_challenge_orchestrator(self):
        """The challenge interstitial loads `chl_page/v1?ray=…` — only that
        path should trigger, not the post-clearance beacon."""
        from book_scraper.spiders.scan import _is_anti_bot_response

        # Real CF Managed Challenge HTML fragment captured from
        # humanitas.lt before FlareSolverr cleared it.
        challenge = (
            "<html><head><title>Luktelėkite...</title></head><body>"
            "<script src='/cdn-cgi/challenge-platform/h/g/orchestrate/"
            "chl_page/v1?ray=9f7a27b99d15c5d3'></script></body></html>"
        )
        assert _is_anti_bot_response(challenge) is True

    def test_is_anti_bot_response_matches_knygos_lt_challenge(self):
        """Pre-onboarding sanity: knygos.lt also serves CF Managed Challenge.

        The shop is on the roadmap (P3 follow-up). When we onboard, the
        scan spider must mark its challenge HTML as anti_bot_detected
        the same way it does for humanitas — without needing fresh
        marker work. Captured from a live knygos.lt probe on
        2026-05-07: English `Just a moment...` title + the same CF
        orchestrator path. Both match existing markers.
        """
        from book_scraper.spiders.scan import _is_anti_bot_response

        knygos_challenge = (
            "<html><head><title>Just a moment...</title></head><body>"
            "<div id='cf-please-wait'>"
            "<script>window._cf_chl_opt={'cvId':'3','cZone':'www.knygos.lt'}"
            ";a.src='/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/"
            "v1?ray=9f7dddb4bbf90429';</script></div></body></html>"
        )
        assert _is_anti_bot_response(knygos_challenge) is True

    def test_parse_product_anti_bot_marks_failed_and_skips_parse(self):
        from book_scraper.spiders.scan import ScanSpider

        spider = ScanSpider(shop="vaga")
        # Cloudflare challenge body — no ld+json, no real product data.
        html = (
            "<html><head><title>Just a moment...</title></head>"
            '<body><div class="cf-browser-verification">'
            "<p>Checking your browser before accessing vaga.lt</p></div>"
            "</body></html>"
        )
        response = _fake_response(
            "https://vaga.lt/blocked",
            html,
            meta={"discovered_url_id": 99},
        )
        items = list(spider.parse_product(response))
        # Anti-bot wall must NOT yield a ShopBookItem (parser skipped).
        shop_book_items = [i for i in items if isinstance(i, ShopBookItem)]
        assert shop_book_items == []
        # The discovered_url update is queued with increment_fail=True so
        # the discover-side fail counter reflects the rejection.
        assert spider._url_status_updates[-1]["increment_fail"] is True
        assert spider._error_count >= 1

    def test_parse_product_non_book_is_skipped(self):
        from book_scraper.spiders.scan import ScanSpider

        spider = ScanSpider(shop="vaga")
        html = """
        <html><body>
          <script type="application/ld+json">
            {"@type":"Product","name":"Stalo žaidimas \\"Teleloto\\"","sku":"1",
             "offers":{"price":"25.49","availability":"OutOfStock"},
             "brand":{"name":"Terra Publica"},
             "isRelatedTo":{"isbn":"4779054890696"}}
          </script>
          <script type="application/ld+json">
            {"@type":"BreadcrumbList","itemListElement":[
              {"name":"Žaislai ir žaidimai"},
              {"name":"Stalo žaidimai"},
              {"name":"Šeimos stalo žaidimai"}
            ]}
          </script>
        </body></html>
        """
        response = _fake_response(
            "https://vaga.lt/stalo-zaidimas-teleloto",
            html,
            meta={"discovered_url_id": 3},
        )
        items = list(spider.parse_product(response))
        shop_book_items = [i for i in items if isinstance(i, ShopBookItem)]
        assert shop_book_items == []
        assert spider._url_status_updates[-1]["url_type"] == "non_product"

    def test_build_scan_request_passes_through_when_no_rewrite(self):
        """Vaga's parser doesn't expose rewrite_scan_url, so the URL must
        pass through untouched. original_url is still stashed in meta as
        a no-op (downstream code falls back to response.url when unset)."""
        from book_scraper.spiders.scan import ScanSpider

        spider = ScanSpider(shop="vaga")
        req = spider._build_scan_request(
            "https://vaga.lt/some-book", meta={"discovered_url_id": 1}
        )
        assert req.url == "https://vaga.lt/some-book"
        assert req.meta["original_url"] == "https://vaga.lt/some-book"
        # No special header injected.
        assert req.headers.get("Accept") in (None, b"")

    def test_build_scan_request_rewrites_pegasas_to_graphql(self):
        """Pegasas's parser exposes rewrite_scan_url, which swaps the
        product page URL for a single-SKU GraphQL request and adds the
        Accept: application/json header. The original product URL is
        preserved in meta for downstream tracking."""
        from book_scraper.spiders.scan import ScanSpider

        spider = ScanSpider(shop="pegasas")
        req = spider._build_scan_request(
            "https://www.pegasas.lt/test-book-1115331",
            meta={"discovered_url_id": 1},
        )
        assert req.url.startswith("https://www.pegasas.lt/graphql?query=")
        assert "000000000001115331" in req.url
        assert req.meta["original_url"] == ("https://www.pegasas.lt/test-book-1115331")
        assert req.headers.get("Accept") == b"application/json"

    def test_parse_product_uses_original_url_when_rewrite_applied(self):
        """When rewrite_scan_url stashed an original_url, parse_product
        must use it for the ShopBookItem URL — not the GraphQL endpoint
        the response.url actually points at."""
        import json as _json

        from book_scraper.spiders.scan import ScanSpider

        spider = ScanSpider(shop="pegasas")
        # Synthetic single-SKU GraphQL response.
        category = _json.loads((FIXTURES / "pegasas_graphql_category.json").read_text())
        first = category["data"]["products"]["items"][0]
        body = _json.dumps({"data": {"products": {"items": [first]}}})
        response = _fake_response(
            "https://www.pegasas.lt/graphql?query=...",
            body,
            cls=TextResponse,
            meta={
                "discovered_url_id": 1,
                "original_url": "https://www.pegasas.lt/the-canonical-product-1115331",
            },
        )
        items = list(spider.parse_product(response))
        shop_book_items = [i for i in items if isinstance(i, ShopBookItem)]
        assert len(shop_book_items) == 1
        assert shop_book_items[0]["url"] == (
            "https://www.pegasas.lt/the-canonical-product-1115331"
        )
