import re
from collections.abc import AsyncGenerator, Generator
from typing import Any

import scrapy
from scrapy import signals

from book_scraper.config import load_shop_config
from book_scraper.db.repo import (
    get_pending_scrape_url_items,
    get_stable_discovered_urls,
    insert_scrape_url_item,
    mark_scrape_url_item_done,
    reset_processing_scrape_url_items,
)
from book_scraper.db.session import get_session_factory
from book_scraper.items import DiscoveredUrlItem, ShopBookItem
from book_scraper.services.discover import DiscoverService
from book_scraper.spiders.registry import load_parsers
from book_scraper.url_utils import normalize_url

# Common pagination param names used across shops. Captured group is
# the param name itself so the substitution preserves it. Pattern is
# anchored after `?` or `&` so a `homepage=…` couldn't accidentally
# match. Listed alternation is intentionally narrow — extend when a
# new shop's pagination param shows up.
_PAGE_PARAM_RE = re.compile(r"(?<=[?&])(cntnt01page|page)=\d+")


def _next_categories_page_url(
    response_url: str,
    strategy_conf: Any,
    next_page: int,
) -> str:
    """Derive the next categories page URL from the response URL.

    Scaling from "single template `.format(page=N)`" to "list of
    templates that paginate independently" is cleanest done by
    operating on the response URL itself: the resolved URL already
    carries the language filter / category id / etc. that the seed
    template baked in, so we just need to bump the page number in
    place. Falls back to template formatting when the response URL
    doesn't carry a recognised pagination param (covers paths that
    were enqueued without `?cntnt01page=` or `?page=` in the URL —
    e.g. tests).
    """
    if _PAGE_PARAM_RE.search(response_url):
        return _PAGE_PARAM_RE.sub(lambda m: f"{m.group(1)}={next_page}", response_url)
    # Fallback: format the first configured template directly. Used
    # by tests / single-URL shops where `response.url` happens to
    # not carry a pagination param yet (page 1 with no explicit
    # `?page=1`). Pre-list-URL behaviour preserved here.
    templates: list[str] = strategy_conf.url_templates()
    return templates[0].format(page=next_page)


class DiscoverSpider(scrapy.Spider):
    name = "discover"

    def __init__(
        self,
        shop: str | None = None,
        strategy: str = "sitemap",
        max_pages: str | int = "",
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        if not shop:
            raise ValueError("Missing required argument: shop (e.g., -a shop=vaga)")
        self.shop_name = shop
        self.strategy = strategy
        # 0 / empty → no cap. Applies to `categories` (page count) and
        # `full_crawl` (per-host link follow count). Sitemap is a single
        # request so the cap is a no-op there.
        self._max_pages: int = int(max_pages) if str(max_pages).strip() else 0
        self.conf = load_shop_config(shop)
        self.parsers = load_parsers(shop)
        self.allowed_domains = [
            self.conf.shop.base_url.replace("https://", "").replace("http://", "")
        ]
        # LupaSearch is a third-party search index (e.g. api.lupasearch.com)
        # — allow its host so the offsite middleware doesn't drop requests.
        ls_conf = getattr(self.conf.discover, "lupasearch", None)
        if ls_conf is not None:
            from urllib.parse import urlparse

            host = urlparse(ls_conf.endpoint).netloc
            if host and host not in self.allowed_domains:
                self.allowed_domains.append(host)

        # Load URL filter pattern
        discover_conf = self.conf.discover
        pattern = discover_conf.url_include_pattern
        self.url_pattern: re.Pattern[str] | None = (
            re.compile(pattern) if pattern else None
        )

        # Load strategy-specific config
        _valid_strategies = {
            "sitemap",
            "categories",
            "full_crawl",
            "graphql",
            "lupasearch",
            "ibiblioteka_api",
        }
        if strategy not in _valid_strategies:
            raise ValueError(f"Strategy '{strategy}' not configured for shop '{shop}'")
        strategy_conf = getattr(discover_conf, strategy, None)
        if strategy_conf is None:
            raise ValueError(f"Strategy '{strategy}' not configured for shop '{shop}'")
        self.strategy_conf: Any = strategy_conf

        # TOML max_pages fallback: when the operator didn't pass
        # `-a max_pages=N` on the CLI, fall back to the strategy's
        # configured cap (currently exposed on CategoriesConfig). Acts
        # as a safety net against runaway chained pagination during
        # cron-triggered runs where no CLI override is supplied.
        # Explicit CLI `-a max_pages=` always wins, including
        # `-a max_pages=0` which means "no cap, override the TOML".
        if not str(max_pages).strip() and self._max_pages == 0:
            toml_cap = getattr(strategy_conf, "max_pages", None)
            if isinstance(toml_cap, int) and toml_cap > 0:
                self._max_pages = toml_cap

        self._run_id: int | None = None
        self._shop_id: int | None = None
        self._urls_processed: int = 0
        self._urls_filtered: int = 0
        # URLs discovered this run, used for change detection on the
        # sitemap strategy (sitemap is comprehensive per shop).
        self._sitemap_urls: set[str] = set()
        # full_crawl-only: normalized URL → url_type for already-classified
        # discovered_urls rows. Loaded once at spider start; consulted in
        # parse_full_crawl to skip enqueueing scan jobs for stable URLs.
        self._stable_urls: dict[str, str] = {}
        # Set when handle_start_error or parse_categories already reported a
        # more specific zero-yield cause — avoids duplicate noise from the
        # generic closed() check.
        self._zero_yield_suppressed: bool = False

        # Per-process flag — set to True after the end-of-run retry sweep
        # has run once, so the second idle tick lets the spider close
        # cleanly. Resets per process; on restart, the new process gets
        # its own flag and may sweep again (bounded by attempts < cap).
        self._end_of_run_retry_done: bool = False

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):  # type: ignore[no-untyped-def]
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.spider_idle, signal=signals.spider_idle)
        return spider

    def _url_passes_filter(self, url: str) -> bool:
        if self.url_pattern is None:
            return True
        return bool(self.url_pattern.match(url))

    async def start(self) -> AsyncGenerator[scrapy.Request, None]:
        database_url = (
            self.settings.get("DATABASE_URL") if hasattr(self, "settings") else None
        )

        if not database_url:
            # Test / no-DB path: preserve the legacy behavior of yielding the
            # strategy's seed URL directly, so unit tests that call start()
            # without a database keep working.
            yield self._legacy_seed_request()
            return

        session_factory = get_session_factory(database_url)
        session = session_factory()
        try:
            service = DiscoverService(session)
            plan = service.prepare_discover(
                self.shop_name,
                self.conf.shop.base_url,
                self.strategy,
                self.conf,
            )
            self._run_id = plan.run_id
            self._shop_id = plan.shop_id

            reset_processing_scrape_url_items(session, plan.run_id)
            url_items = get_pending_scrape_url_items(session, plan.run_id)
            if self.strategy == "full_crawl":
                # Snapshot URLs already classified recently so the spider
                # can skip queueing scan jobs for them mid-crawl. Loaded
                # once here — full_crawl is rare and manual, the brief
                # staleness during a long run is acceptable.
                self._stable_urls = get_stable_discovered_urls(session, plan.shop_id)
            session.commit()
        finally:
            session.close()

        for item in url_items:
            yield self._build_request_for_url_item(
                item["url"],
                item["url_type"],
                item_id=item["id"],
                page=1 if item["url_type"] == "category_page" else None,
            )

    def _legacy_seed_request(self) -> scrapy.Request:
        """Build the strategy's seed Request without touching the DB.

        Used only by unit tests that call ``start()`` on a spider constructed
        outside the Scrapy crawler pipeline.
        """
        if self.strategy == "sitemap":
            return scrapy.Request(
                self.strategy_conf.url,
                callback=self.parse_sitemap,
                errback=self.handle_start_error,
            )
        if self.strategy in ("categories", "graphql"):
            if self.strategy == "graphql":
                from book_scraper.spiders.graphql_urls import build_graphql_page_url

                url = build_graphql_page_url(
                    self.conf.shop.base_url, self.strategy_conf, page=1
                )
            else:
                # Legacy / test path: emit the FIRST seed URL only.
                # Production path goes through DiscoverService which
                # enqueues every URL in the list; tests calling
                # `_legacy_seed_request` directly only exercise one
                # template at a time.
                templates = self.strategy_conf.url_templates()
                url = templates[0].format(page=1)
            return scrapy.Request(
                url,
                callback=self.parse_categories,
                errback=self.handle_start_error,
                meta={"page": 1},
                headers={"Accept": "application/json"}
                if self.strategy == "graphql"
                else {},
            )
        if self.strategy == "lupasearch":
            from book_scraper.spiders.lupasearch_urls import (
                build_lupasearch_post_request_kwargs,
                build_lupasearch_seed_url,
            )

            seed_url = build_lupasearch_seed_url(self.strategy_conf)
            kwargs = build_lupasearch_post_request_kwargs(seed_url)
            return scrapy.Request(
                seed_url,
                callback=self.parse_lupasearch_page,
                errback=self.handle_start_error,
                meta={"page": 1},
                **kwargs,
            )
        if self.strategy == "ibiblioteka_api":
            from book_scraper.spiders.ibiblioteka_api_urls import (
                build_ibiblioteka_post_request_kwargs,
                build_ibiblioteka_seed_urls,
            )

            # Test path: yield only the first year-band seed.
            seed_url = build_ibiblioteka_seed_urls(self.strategy_conf)[0]
            kwargs = build_ibiblioteka_post_request_kwargs(seed_url)
            return scrapy.Request(
                seed_url,
                callback=self.parse_ibiblioteka_page,
                errback=self.handle_start_error,
                meta={"page": 1},
                **kwargs,
            )
        # full_crawl
        return scrapy.Request(
            self.strategy_conf.start_url,
            callback=self.parse_full_crawl,
            errback=self.handle_start_error,
        )

    def _build_request_for_url_item(
        self,
        url: str,
        url_type: str,
        *,
        item_id: int | None = None,
        page: int | None = None,
    ) -> scrapy.Request:
        """Reconstruct a scrapy.Request for a queued URL.

        The DB-backed queue stores URLs and url_types only — no method,
        body, or headers — so any non-GET strategy (currently just
        LupaSearch's POST) needs its outbound request rebuilt from the
        URL alone. For LupaSearch the seed URL carries offset/limit/
        category_ids in its query string; the helper below decodes those
        back into the JSON body the API expects.

        Used by start(), spider_idle(), and parse_categories' next-page
        yield so the same reconstruction logic applies regardless of
        which entry path is currently scheduling the request.
        """
        meta: dict[str, Any] = {"url_type": url_type}
        if item_id is not None:
            meta["scrape_url_item_id"] = item_id
        if page is not None:
            meta["page"] = page

        if url_type == "lupasearch_page":
            from book_scraper.spiders.lupasearch_urls import (
                build_lupasearch_post_request_kwargs,
            )

            kwargs = build_lupasearch_post_request_kwargs(url)
            return scrapy.Request(
                url,
                callback=self.dispatch,
                errback=self.handle_start_error,
                meta=meta,
                **kwargs,
            )

        if url_type == "ibiblioteka_page":
            from book_scraper.spiders.ibiblioteka_api_urls import (
                build_ibiblioteka_post_request_kwargs,
            )

            kwargs = build_ibiblioteka_post_request_kwargs(url)
            return scrapy.Request(
                url,
                callback=self.dispatch,
                errback=self.handle_start_error,
                meta=meta,
                **kwargs,
            )

        headers: dict[str, str] = {}
        if url_type == "category_page" and self.strategy == "graphql":
            headers["Accept"] = "application/json"

        return scrapy.Request(
            url,
            callback=self.dispatch,
            errback=self.handle_start_error,
            meta=meta,
            headers=headers,
        )

    def dispatch(self, response: scrapy.http.Response) -> Generator[Any, None, None]:
        """Route a downloaded response to the correct parser based on url_type."""
        url_type = response.meta.get("url_type") or "crawl"
        try:
            if url_type == "sitemap":
                yield from self.parse_sitemap(response)
            elif url_type == "category_page":
                yield from self.parse_categories(response)
            elif url_type == "lupasearch_page":
                yield from self.parse_lupasearch_page(response)
            elif url_type == "ibiblioteka_page":
                yield from self.parse_ibiblioteka_page(response)
            else:
                # "crawl" or "product" — both handled by full_crawl parser,
                # which already branches on whether the URL is a product page.
                yield from self.parse_full_crawl(response)
        finally:
            item_id = response.meta.get("scrape_url_item_id")
            if item_id is not None and self._run_id is not None:
                database_url = self.settings.get("DATABASE_URL")
                factory = get_session_factory(database_url)
                session = factory()
                try:
                    # Sub-page subdivision retries: a depth=1 page that
                    # itself returned 5xx is a real failure — the
                    # subdivision handler can't recurse further, so we
                    # mark the URL as failed (retryable reason) so the
                    # next Continue/auto-resume cycle picks it up.
                    if response.meta.get("subdivision_5xx_failed"):
                        from book_scraper.db.repo import (
                            mark_scrape_url_item_failed,
                        )

                        mark_scrape_url_item_failed(
                            session,
                            item_id,
                            http_status=response.status,
                            error_reason="subdivision_5xx",
                        )
                    else:
                        # full_crawl sets final_url_type after parsing so
                        # the queue row reflects what the page actually
                        # turned out to be (product / non_product), not
                        # the placeholder "unknown" we inserted with.
                        mark_scrape_url_item_done(
                            session,
                            item_id,
                            url_type=response.meta.get("final_url_type"),
                        )
                    session.commit()
                finally:
                    session.close()

    def spider_idle(self, spider) -> None:  # type: ignore[no-untyped-def]
        """Mid-run pickup + one-shot end-of-run retry sweep.

        Mirrors `ScanSpider.spider_idle` — queue empty triggers the
        retry pass over failed items with attempts < RETRY_CAP. Sweep
        is gated by `_end_of_run_retry_done` so it runs once per
        process. Mid-run dual-write pickup behaviour preserved.
        """
        if self._run_id is None:
            return
        database_url = self.settings.get("DATABASE_URL")
        retry_cap = self.settings.getint("RETRY_CAP", 3)
        factory = get_session_factory(database_url)
        session = factory()
        try:
            reset_processing_scrape_url_items(session, self._run_id)
            new_items = get_pending_scrape_url_items(session, self._run_id)
            if not new_items and not self._end_of_run_retry_done:
                from book_scraper.db.repo import (
                    fetch_retryable_failed_items,
                    reset_failed_items_to_pending,
                )

                eligible = fetch_retryable_failed_items(
                    session, self._run_id, cap=retry_cap
                )
                if eligible:
                    reset_failed_items_to_pending(session, [it.id for it in eligible])
                    new_items = get_pending_scrape_url_items(session, self._run_id)
                self._end_of_run_retry_done = True
            session.commit()
        finally:
            session.close()

        if not new_items:
            return

        from scrapy.exceptions import DontCloseSpider

        engine = self.crawler.engine
        assert engine is not None
        for item in new_items:
            req = self._build_request_for_url_item(
                item["url"],
                item["url_type"],
                item_id=item["id"],
            )
            engine.crawl(req)
        raise DontCloseSpider

    def handle_start_error(self, failure: Any) -> None:
        """Surface discovery fetch failures as validation issues.

        Without this a 4xx/5xx/timeout on the first category or sitemap
        request leaves the run silently "completed with 0 URLs", which
        hides broken URL patterns for hours at a time.
        """
        request = failure.request
        status_obj = getattr(failure.value, "response", None)
        # `status_obj` may be either a Twisted/Scrapy Response (with
        # `.status`) or an httpx.Response (with `.status_code`). The
        # FlaresolverrMiddleware path raises httpx exceptions whose
        # `.response` is the httpx.Response. Pre-fix this errback
        # crashed with `AttributeError: 'Response' object has no
        # attribute 'status'` on every FS 500, leaving the spider to
        # stall instead of failing fast (verified during humanitas
        # multi-seed smoke 2026-05-07).
        http_status: int | None = None
        if status_obj is not None:
            http_status = getattr(status_obj, "status", None) or getattr(
                status_obj, "status_code", None
            )
        detail = f"{type(failure.value).__name__}"
        if http_status is not None:
            detail = f"HTTP {http_status}"
        self._report_validation(
            "discover_fetch_failed",
            "url",
            str(request.url),
            detail,
        )
        self._zero_yield_suppressed = True
        self.logger.error(
            "Discover %s failed to fetch %s: %s",
            self.strategy,
            request.url,
            detail,
        )

    def _report_validation(
        self,
        issue: str,
        field: str,
        url: str,
        raw_value: str = "",
    ) -> None:
        """Report a validation issue to the ValidationPipeline."""
        crawler = getattr(self, "crawler", None)
        vp = getattr(crawler, "validation_pipeline", None) if crawler else None
        if vp is not None:
            vp._warn(issue, field, url, raw_value)
        else:
            self.logger.warning(
                "Validation [%s] field=%s url=%s %s",
                issue,
                field,
                url,
                raw_value,
            )

    def _enqueue_url(self, url: str, url_type: str) -> int | None:
        """Dual-write helper: insert a queue item and return its id.

        No-op (returns None) when ``_run_id`` is None — unit tests construct
        the spider without a run and call the callbacks directly.
        """
        if self._run_id is None or self._shop_id is None:
            return None
        database_url = (
            self.settings.get("DATABASE_URL") if hasattr(self, "settings") else None
        )
        if not database_url:
            return None
        factory = get_session_factory(database_url)
        session = factory()
        try:
            item = insert_scrape_url_item(
                session,
                run_id=self._run_id,
                shop_id=self._shop_id,
                discovered_url_id=None,
                url=url,
                url_type=url_type,
            )
            session.commit()
            return item.id
        finally:
            session.close()

    def parse_sitemap(
        self, response: scrapy.http.Response
    ) -> Generator[DiscoveredUrlItem, None, None]:
        urls: list[str] = self.parsers.parse_sitemap_urls(response.text)
        self.logger.info("Found %d URLs in sitemap", len(urls))

        # Check for duplicates
        seen: set[str] = set()
        duplicates = 0
        for url in urls:
            if url in seen:
                duplicates += 1
            else:
                seen.add(url)
        if duplicates:
            self._report_validation(
                "duplicate_sitemap_url",
                "url",
                response.url,
                f"{duplicates} duplicates in {len(urls)} URLs",
            )

        for url in seen:
            if self._url_passes_filter(url):
                self._urls_processed += 1
                self._sitemap_urls.add(url)
                yield DiscoveredUrlItem(
                    url=url, shop_name=self.shop_name, source="sitemap"
                )
            else:
                self._urls_filtered += 1

    def _emit_products(
        self, products: list[dict[str, Any]]
    ) -> Generator[DiscoveredUrlItem | ShopBookItem, None, None]:
        """Yield DiscoveredUrlItem + ShopBookItem rows from a parser result.

        Shared between `parse_categories` (HTML/GraphQL) and
        `parse_lupasearch_page` (LupaSearch JSON) so both sources go
        through one place — including the properties merge that
        preserves parser-emitted dicts.
        """
        base_url: str = self.conf.shop.base_url
        for product in products:
            url = product.get("url")
            if url and not url.startswith("http"):
                url = base_url + url
            if not url:
                continue

            if not self._url_passes_filter(url):
                self._urls_filtered += 1
                continue

            self._urls_processed += 1
            yield DiscoveredUrlItem(
                url=url, shop_name=self.shop_name, source="category"
            )

            # Yield product data when we have at least a title and price.
            if not (product.get("title") and product.get("price")):
                continue

            # Merge parser-emitted properties with top-level extras.
            # Parser dicts win when both supply the same key (parsers
            # know more than the generic fallback below).
            props: dict[str, object] = {}
            parser_props = product.get("properties")
            if isinstance(parser_props, dict):
                props.update(parser_props)
            for key in ("pages", "cover_type", "duration", "narrator", "translator"):
                if product.get(key) is not None and key not in props:
                    props[key] = product[key]

            yield ShopBookItem(
                url=url,
                shop_name=self.shop_name,
                title=product["title"],
                author=product.get("author"),
                price=product.get("price"),
                price_original=product.get("price_original"),
                in_stock=product.get("in_stock", True),
                type=product.get("type"),
                sku=product.get("sku"),
                isbn=product.get("isbn"),
                publisher=product.get("publisher"),
                year=product.get("year"),
                format=product.get("format"),
                description=product.get("description"),
                image_url=product.get("image_url"),
                categories=product.get("categories", []),
                properties=props or None,
            )

    def parse_categories(
        self, response: scrapy.http.Response
    ) -> Generator[DiscoveredUrlItem | ShopBookItem | scrapy.Request, None, None]:
        # Adaptive subdivision: if the backend returned 5xx, don't try to
        # parse — instead reschedule the same range as N smaller-pageSize
        # requests. Concurrency=2 + cold full-page-cache on Magento can
        # produce transient 503s on deeper pages; pageSize/5 is light
        # enough to slip through.
        if self.strategy == "graphql" and 500 <= response.status < 600:
            yield from self._subdivide_failed_graphql_page(response)
            return

        result: dict[str, Any] = self.parsers.parse_category_page(response.text)
        # Backwards compat: shops that haven't migrated to the
        # {products, total} contract may still return a bare list.
        if isinstance(result, list):
            products: list[dict[str, Any]] = result
            total: int | None = None
        else:
            products = list(result.get("products") or [])
            total = result.get("total")

        if not products:
            # If we hit an empty response on page 1, the upstream URL
            # pattern is probably broken — warn so the next run isn't
            # another silent "completed with 0 URLs" outcome.
            page_meta = response.meta.get("page", 0)
            if page_meta == 1:
                self._report_validation(
                    "discover_empty_first_page",
                    "url",
                    response.url,
                    f"page 1 returned 0 products (len={len(response.text)})",
                )
                self._zero_yield_suppressed = True
            return  # No more pages

        yield from self._emit_products(products)

        # Sub-pages (subdivision_depth>=1) are subordinate retries: they
        # cover a slice of a previously-failed normal page, so we MUST
        # NOT paginate from them — the parent failed-page handler is
        # responsible for enqueueing the next normal page.
        is_subpage = False
        if self.strategy == "graphql":
            from book_scraper.spiders.graphql_urls import parse_graphql_page_url

            is_subpage = parse_graphql_page_url(response.url)["subdivision_depth"] >= 1
        if is_subpage:
            return

        current_page = response.meta.get("page") or 1

        # Multi-seed shops (categories url = [...], e.g. humanitas) paginate
        # each seed independently; _enqueue_remaining_pages can only walk one
        # template, so treat total as unknown and chain per seed.
        if (
            total is not None
            and self.strategy != "graphql"
            and len(self.strategy_conf.url_templates()) > 1
        ):
            total = None

        # Upfront pagination: when the parser exposes a real total, the
        # first page enqueues every remaining page at once so Scrapy can
        # actually run them in parallel under concurrent_requests_per_domain.
        # Without this, pages chain serially (page+1 yielded only after
        # page parses) and concurrency never engages on discover.
        if current_page == 1 and total is not None and total > 0:
            yield from self._enqueue_remaining_pages(total)
            return

        # Fallback for shops without a total (e.g. vaga's HTML scrape):
        # chain page+1 each time, exactly as before.
        if total is not None:
            # Upfront mode: every page is already in the queue; nothing
            # to do once we've emitted products.
            return

        next_page = current_page + 1
        if self._max_pages and next_page > self._max_pages:
            self.logger.info("max_pages cap: stopping at page %d", self._max_pages)
            return
        if self.strategy == "graphql":
            from book_scraper.spiders.graphql_urls import build_graphql_page_url

            next_url = build_graphql_page_url(
                self.conf.shop.base_url, self.strategy_conf, page=next_page
            )
        else:
            next_url = _next_categories_page_url(
                response.url, self.strategy_conf, next_page
            )

        new_item_id = self._enqueue_url(next_url, "category_page")
        yield self._build_request_for_url_item(
            next_url, "category_page", item_id=new_item_id, page=next_page
        )

    def _enqueue_remaining_pages(
        self, total: int
    ) -> Generator[scrapy.Request, None, None]:
        """Enqueue pages 2..N upfront so concurrency can engage.

        Called from the first-page parser once we know `total`. The
        DB-backed queue's unique constraint on (run_id, url) and
        `insert_scrape_url_item`'s idempotent semantics mean it's safe
        even if the failure handler later tries to enqueue the same
        page+1 — the second insert returns the existing row, and
        Scrapy's dupefilter drops the duplicate fetch.
        """
        page_size = self.strategy_conf.page_size
        last_page = (total + page_size - 1) // page_size  # ceil
        # Honour --max-pages caps in dev runs.
        if self._max_pages:
            last_page = min(last_page, self._max_pages)
        for page in range(2, last_page + 1):
            if self.strategy == "graphql":
                from book_scraper.spiders.graphql_urls import build_graphql_page_url

                next_url = build_graphql_page_url(
                    self.conf.shop.base_url, self.strategy_conf, page=page
                )
            else:
                # Single-template shops only (vaga): parse_categories
                # nulls the total for multi-seed shops before calling
                # us, so formatting templates[0] is always correct here.
                templates = self.strategy_conf.url_templates()
                next_url = templates[0].format(page=page)
            new_item_id = self._enqueue_url(next_url, "category_page")
            yield self._build_request_for_url_item(
                next_url, "category_page", item_id=new_item_id, page=page
            )

    def _emit_subdivided_event(
        self,
        *,
        outcome: str,
        page: int,
        page_size: int,
        depth: int,
        http_status: int,
        sub_count: int,
        sub_size: int | None,
    ) -> None:
        """Append a `subdivided` row to scrape_run_events.

        Surfaces each subdivision (and each depth=1 micro-range
        failure) on the run's Timeline card so operators can see when
        the spider had to adapt to a struggling backend, instead of
        the run going silent until the next stall.
        """
        if self._run_id is None:
            return
        database_url = (
            self.settings.get("DATABASE_URL") if hasattr(self, "settings") else None
        )
        if not database_url:
            return
        try:
            from book_scraper.db import scrape_run_events as run_event_types
            from book_scraper.db.repo import emit_scrape_run_event

            session = get_session_factory(database_url)()
            try:
                emit_scrape_run_event(
                    session,
                    self._run_id,
                    run_event_types.SUBDIVIDED,
                    payload={
                        "outcome": outcome,
                        "page": page,
                        "page_size": page_size,
                        "depth": depth,
                        "http_status": http_status,
                        "sub_count": sub_count,
                        "sub_size": sub_size,
                    },
                    actor=run_event_types.ACTOR_SYSTEM,
                )
                session.commit()
            finally:
                session.close()
        except Exception:
            self.logger.exception(
                "Failed to emit subdivided event for page %d (depth %d)",
                page,
                depth,
            )

    def _subdivide_failed_graphql_page(
        self, response: scrapy.http.Response
    ) -> Generator[scrapy.Request, None, None]:
        """Reschedule a 5xx-failed GraphQL page as N smaller-pageSize requests.

        Magento's full-page cache misses on deep pages can produce
        transient 503s when fetched at pageSize=50 under concurrency
        pressure. Splitting that range into N pageSize=10 requests
        gives the backend time to materialise lighter result sets,
        and lets us continue pagination instead of stalling on one bad
        page. If the failing request is *already* a sub-divided retry
        (`_sub=1` in the URL), we don't recurse further — log + skip
        + still enqueue the next normal page so pagination survives.
        """
        from book_scraper.spiders.graphql_urls import (
            build_graphql_page_url,
            parse_graphql_page_url,
        )

        url_meta = parse_graphql_page_url(response.url)
        page = url_meta["page"] or response.meta.get("page", 1)
        page_size = url_meta["page_size"] or self.strategy_conf.page_size
        depth = url_meta["subdivision_depth"]

        self._report_validation(
            "discover_backend_5xx",
            "url",
            response.url,
            f"HTTP {response.status} on page {page} (size {page_size}, depth {depth})",
        )

        if depth >= 1:
            # Already a subdivided retry — don't recurse further. Tag
            # the response so dispatch's finally marks the URL as
            # `failed` with reason `subdivision_5xx` (a retryable
            # reason) instead of silently `done`. The next Continue
            # or auto-resume picks it up and tries the same range
            # again, hopefully with the backend recovered.
            response.meta["subdivision_5xx_failed"] = True
            self.logger.warning(
                "Subdivided page %d (size %d) also returned %d; "
                "marking as retryable failure",
                page,
                page_size,
                response.status,
            )
            self._emit_subdivided_event(
                outcome="micro_range_failed",
                page=page,
                page_size=page_size,
                depth=depth,
                http_status=response.status,
                sub_count=0,
                sub_size=None,
            )
        else:
            factor = max(2, int(self.strategy_conf.subdivide_factor))
            min_size = max(1, int(self.strategy_conf.subdivide_min_page_size))
            sub_size = max(min_size, page_size // factor)
            # Items covered by the failed page: [(page-1)*page_size, page*page_size).
            # In sub-page coordinates that's pages (page-1)*ratio+1 .. page*ratio.
            ratio = page_size // sub_size
            if ratio < 1:
                ratio = 1
            first_sub = (page - 1) * ratio + 1
            self.logger.info(
                "Subdividing failed page %d (size %d) into %d × pageSize=%d",
                page,
                page_size,
                ratio,
                sub_size,
            )
            for i in range(ratio):
                sub_page = first_sub + i
                sub_url = build_graphql_page_url(
                    self.conf.shop.base_url,
                    self.strategy_conf,
                    page=sub_page,
                    page_size_override=sub_size,
                    subdivision_depth=1,
                )
                new_id = self._enqueue_url(sub_url, "category_page")
                yield self._build_request_for_url_item(
                    sub_url, "category_page", item_id=new_id, page=sub_page
                )
            self._emit_subdivided_event(
                outcome="subdivided",
                page=page,
                page_size=page_size,
                depth=depth,
                http_status=response.status,
                sub_count=ratio,
                sub_size=sub_size,
            )

        # Continue normal pagination — but only for depth==0. When a
        # sub-page (depth>=1) fails, the parent failed-page handler
        # already enqueued the next normal page, so we'd double-enqueue.
        if depth >= 1:
            return
        normal_page = page + 1
        if self._max_pages and normal_page > self._max_pages:
            return
        next_url = build_graphql_page_url(
            self.conf.shop.base_url, self.strategy_conf, page=normal_page
        )
        next_id = self._enqueue_url(next_url, "category_page")
        yield self._build_request_for_url_item(
            next_url, "category_page", item_id=next_id, page=normal_page
        )

    def parse_lupasearch_page(
        self, response: scrapy.http.Response
    ) -> Generator[DiscoveredUrlItem | ShopBookItem | scrapy.Request, None, None]:
        """Parse a LupaSearch JSON response and schedule remaining pages.

        On the first page we enqueue *every* remaining page upfront, so
        concurrent_requests_per_domain actually engages. Subsequent
        pages just emit products — the queue already has the rest.
        """
        from book_scraper.spiders.lupasearch_urls import (
            advance_lupasearch_url,
            parse_lupasearch_url_offsets,
        )

        result: dict[str, Any] = self.parsers.parse_lupasearch_response(response.text)
        products: list[dict[str, Any]] = result.get("products") or []
        total = int(result.get("total") or 0)

        if not products:
            page = response.meta.get("page", 0)
            if page == 1:
                self._report_validation(
                    "discover_empty_first_page",
                    "url",
                    response.url,
                    f"page 1 returned 0 products (len={len(response.text)})",
                )
                self._zero_yield_suppressed = True
            return

        yield from self._emit_products(products)

        offset, limit = parse_lupasearch_url_offsets(response.url)

        # Upfront pagination fires only on the literal first page (offset
        # 0). Deriving from the URL offset rather than `meta["page"]`
        # makes resume safe: a previously-failed page=N request that
        # gets re-dispatched on a fresh run has no `page` meta, but its
        # URL still carries offset=N*limit, so we don't mistake it for
        # page 1 and re-enqueue everything past it.
        if offset == 0 and total > 0 and limit > 0:
            next_offset = limit
            page = 2
            while next_offset < total:
                if self._max_pages and page > self._max_pages:
                    return
                next_url = advance_lupasearch_url(response.url, next_offset)
                new_item_id = self._enqueue_url(next_url, "lupasearch_page")
                yield self._build_request_for_url_item(
                    next_url, "lupasearch_page", item_id=new_item_id, page=page
                )
                next_offset += limit
                page += 1
            return

        # offset > 0: the queue was already filled by the first-page
        # upfront pagination; nothing more to do.
        return

    def parse_ibiblioteka_page(
        self, response: scrapy.http.Response
    ) -> Generator[DiscoveredUrlItem | ShopBookItem | scrapy.Request, None, None]:
        """Parse an ibiblioteka.lt POST /detailed-search JSON response.

        Emits a DiscoveredUrlItem for each book's detail endpoint URL, then
        chains to the next page via pageStartIndex if this page was full.
        The scan spider fetches each detail URL and calls parse_product_page.
        """
        from book_scraper.spiders.ibiblioteka.parsers import (
            parse_ibiblioteka_search_response,
        )
        from book_scraper.spiders.ibiblioteka_api_urls import (
            advance_ibiblioteka_url,
            parse_ibiblioteka_url_params,
        )

        result: dict[str, Any] = parse_ibiblioteka_search_response(response.text)
        products: list[dict[str, Any]] = result.get("products") or []

        if not products:
            page = response.meta.get("page", 0)
            if page == 1:
                self._report_validation(
                    "discover_empty_first_page",
                    "url",
                    response.url,
                    f"page 1 returned 0 products (len={len(response.text)})",
                )
                self._zero_yield_suppressed = True
            return

        # Emit DiscoveredUrlItem only — the BookItem with full metadata
        # comes from the scan phase via parse_product_page (which now
        # returns BookItem-shaped dict tagged _emit_as='book').
        for product in products:
            url = product.get("url")
            if not url:
                continue
            self._urls_processed += 1
            yield DiscoveredUrlItem(
                url=url, shop_name=self.shop_name, source="category"
            )

        psi, ps, _yf, _yt = parse_ibiblioteka_url_params(response.url)
        n = len(products)

        # If the page was full, there may be more — chain to next page.
        # The server hard-caps at pageStartIndex ~9 900; stop there.
        if n < ps or psi + n >= 9900:
            return

        current_page = response.meta.get("page") or 1
        if self._max_pages and current_page >= self._max_pages:
            return

        next_psi = psi + n
        next_url = advance_ibiblioteka_url(response.url, next_psi)
        new_item_id = self._enqueue_url(next_url, "ibiblioteka_page")
        yield self._build_request_for_url_item(
            next_url,
            "ibiblioteka_page",
            item_id=new_item_id,
            page=current_page + 1,
        )

    def parse_full_crawl(
        self, response: scrapy.http.Response
    ) -> Generator[DiscoveredUrlItem | ShopBookItem | scrapy.Request, None, None]:
        """Follow all internal links, yield product URLs and parse product data."""
        base_url: str = self.conf.shop.base_url
        seen: set[str] = getattr(self, "_seen_urls", set())
        self._seen_urls = seen

        # Classify the current page from its parse result. The final type
        # is read by `dispatch` after this generator exhausts and passed
        # to `mark_scrape_url_item_done` so the queue row reflects what
        # the page actually was, not what we guessed pre-fetch. Run this
        # BEFORE the max_pages early-return: the response is already
        # fetched so we should always label it correctly, even when the
        # outgoing-link budget is exhausted.
        current_url = response.url.split("?")[0]
        if self._url_passes_filter(current_url):
            data = self.parsers.parse_product_page(response.text)
            if data.get("is_book_product") or data.get("title"):
                response.meta["final_url_type"] = "product"
                props: dict[str, object] = {}
                for key in (
                    "pages",
                    "cover_type",
                    "duration",
                    "narrator",
                    "translator",
                ):
                    if data.get(key) is not None:
                        props[key] = data[key]
                yield ShopBookItem(
                    url=current_url,
                    shop_name=self.shop_name,
                    type=data.get("type"),
                    title=data["title"],
                    author=data.get("author"),
                    sku=data.get("sku"),
                    isbn=data.get("isbn"),
                    publisher=data.get("publisher"),
                    year=data.get("year"),
                    format=data.get("format"),
                    description=data.get("description"),
                    image_url=data.get("image_url"),
                    categories=data.get("categories", []),
                    properties=props or None,
                    price=data.get("price"),
                    price_original=data.get("price_original"),
                    in_stock=data.get("in_stock"),
                )
            else:
                response.meta["final_url_type"] = "non_product"
        else:
            # URL was followed only as a crawl frontier (filter excluded it).
            response.meta["final_url_type"] = "non_product"

        # Stop walking outgoing links once the per-host follow budget is hit.
        # Already-fetched responses still get classified above; we just don't
        # enqueue any more new URLs.
        if self._max_pages and len(seen) >= self._max_pages:
            return

        for link in response.css("a::attr(href)").getall():
            if not link.startswith("http"):
                link = response.urljoin(link)

            if not link.startswith(base_url):
                continue
            if link in seen:
                continue
            seen.add(link)

            # Cross-run dedup: if discovered_urls already classified this
            # URL recently (product/non_product/unreachable), skip the
            # scan-job insert but still follow the link so we discover any
            # new outgoing URLs from it.
            normalized = normalize_url(link)
            if normalized in self._stable_urls:
                yield scrapy.Request(
                    link,
                    callback=self.parse_full_crawl,
                    dont_filter=False,
                )
                continue

            is_product = self._url_passes_filter(link)
            if is_product:
                self._urls_processed += 1
                yield DiscoveredUrlItem(
                    url=link, shop_name=self.shop_name, source="full_crawl"
                )

            # Insert as "unknown" — the real type is set after the page is
            # fetched and parsed (see `final_url_type` above + dispatch).
            new_item_id = self._enqueue_url(link, "unknown")
            yield scrapy.Request(
                link,
                callback=self.dispatch
                if new_item_id is not None
                else self.parse_full_crawl,
                dont_filter=False,
                meta={
                    "scrape_url_item_id": new_item_id,
                    "url_type": "unknown",
                },
            )

    def closed(self, reason: str) -> None:
        if self._urls_filtered:
            self._report_validation(
                "url_pattern_filtered",
                "url",
                "",
                f"{self._urls_filtered} URLs excluded by pattern",
            )
            self.logger.info(
                "URL filter: %d passed, %d filtered",
                self._urls_processed,
                self._urls_filtered,
            )

        if self._run_id is None:
            return

        database_url = (
            self.settings.get("DATABASE_URL") if hasattr(self, "settings") else None
        )
        if not database_url:
            return

        finalized = False
        try:
            factory = get_session_factory(database_url)
            session = factory()
            try:
                # Change detection and zero-yield checks still live here because
                # they need spider-local state (_sitemap_urls, _urls_processed,
                # _zero_yield_suppressed). finish_discover handles the generic
                # parts: status, urls_processed, cron last_run_at, cleanup.
                status = "completed" if reason == "finished" else "failed"
                if (
                    status == "completed"
                    and self.strategy == "sitemap"
                    and self._sitemap_urls
                    and self._shop_id is not None
                ):
                    from book_scraper.db.repo import mark_shop_books_inactive

                    deactivated = mark_shop_books_inactive(
                        session,
                        shop_id=self._shop_id,
                        active_urls=self._sitemap_urls,
                    )
                    if deactivated:
                        self.logger.info(
                            "Change detection: marked %d shop_book(s) inactive",
                            deactivated,
                        )

                if (
                    status == "completed"
                    and self._urls_processed == 0
                    and not self._zero_yield_suppressed
                    and self._shop_id is not None
                ):
                    from book_scraper.db.models import DiscoveredUrl

                    prior_count = (
                        session.query(DiscoveredUrl)
                        .filter(DiscoveredUrl.shop_id == self._shop_id)
                        .count()
                    )
                    if prior_count > 0:
                        self._report_validation(
                            "discover_zero_yield",
                            "run",
                            self.conf.shop.base_url,
                            f"phase=discover_{self.strategy}, "
                            f"shop had {prior_count} URLs pre-run",
                        )

                session.commit()

                DiscoverService(session).finish_discover(
                    self._run_id,
                    self._urls_processed,
                    reason,
                )
                finalized = True
            finally:
                session.close()
        except Exception:
            self.logger.exception(
                "Spider close: discover finalize failed; using failsafe"
            )

        # Failsafe: if anything above blew up (poisoned session, DB blip)
        # the run row is still 'running'. Finalize it via a fresh session.
        if not finalized:
            from book_scraper.db.repo import finalize_run_failsafe

            status = "completed" if reason == "finished" else "failed"
            finalize_run_failsafe(database_url, self._run_id, status, reason)
