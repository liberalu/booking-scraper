"""Verify that 5xx responses synthesized by HttpxMiddleware flow through
Scrapy's RetryMiddleware as expected.

Follow-up #5 reported that pegasas 503s observed in run 266 finished in
~5s rather than the ~15-30s expected from RETRY_TIMES=2 with backoff.
This test exercises the request → 503 response → RetryMiddleware path
end-to-end (no network, mocked httpx) and asserts that a new Request is
produced for retry.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from scrapy import Request
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.http import HtmlResponse
from scrapy.settings import Settings

from book_scraper.download_handler import HttpxMiddleware


def _make_httpx_middleware() -> HttpxMiddleware:
    return HttpxMiddleware(
        timeout=5.0,
        user_agent="test",
        database_url=None,
        download_delay=0.01,
        autothrottle_enabled=False,
        autothrottle_start_delay=0.01,
        autothrottle_max_delay=1.0,
        client_reset_after_requests=1000,
    )


def _make_retry_middleware() -> RetryMiddleware:
    settings = Settings(
        {
            "RETRY_ENABLED": True,
            "RETRY_TIMES": 2,
            "RETRY_HTTP_CODES": [500, 502, 503, 504],
            "RETRY_PRIORITY_ADJUST": -1,
            "RETRY_EXCEPTIONS": [],
        }
    )
    mw = RetryMiddleware(settings)
    # _retry needs crawler.spider for stats access
    spider = MagicMock()
    crawler = MagicMock()
    stats = MagicMock()
    stats.inc_value = MagicMock()
    crawler.stats = stats
    crawler.settings = settings
    crawler.spider = spider
    spider.crawler = crawler
    mw.crawler = crawler
    return mw


def test_503_synthesized_by_httpx_triggers_retry_middleware() -> None:
    """The synthesized HtmlResponse must carry status=503 so that
    RetryMiddleware.process_response returns a new Request copy."""
    httpx_mw = _make_httpx_middleware()

    # Mock the underlying httpx client to return a 503.
    fake_response = MagicMock()
    fake_response.url = "https://example.com/q?x=1"
    fake_response.status_code = 503
    fake_response.headers = {}
    fake_response.content = b""
    fake_response.encoding = "utf-8"
    httpx_mw.client.get = AsyncMock(return_value=fake_response)

    request = Request("https://example.com/q?x=1")

    response = asyncio.run(httpx_mw.process_request(request))
    try:
        assert isinstance(response, HtmlResponse)
        assert response.status == 503

        retry_mw = _make_retry_middleware()
        result = retry_mw.process_response(request, response)
        # If RetryMiddleware fired, result is a new Request (retry).
        # If it returned the original response, retry was skipped.
        assert isinstance(result, Request), (
            "RetryMiddleware did not retry a 503 response — "
            "follow-up #5's hypothesis confirmed if this fails."
        )
        assert result.meta.get("retry_times") == 1
    finally:
        asyncio.run(httpx_mw._close())


def test_dont_retry_meta_skips_retry() -> None:
    """Sanity: when meta.dont_retry=True, RetryMiddleware must not retry.
    Confirms RetryMiddleware behaviour is not silently broken."""
    request = Request("https://example.com/q?x=1", meta={"dont_retry": True})
    response = HtmlResponse(
        url="https://example.com/q?x=1", status=503, request=request
    )

    retry_mw = _make_retry_middleware()
    result = retry_mw.process_response(request, response)
    assert result is response  # no retry, original response returned


def test_retry_exhausts_after_max_retry_times() -> None:
    """RETRY_TIMES=2 means 1 original + 2 retries. The 3rd 503 must
    flow through to the spider as the original response (None from
    _retry signals 'give up')."""
    request = Request("https://example.com/q?x=1", meta={"retry_times": 2})
    response = HtmlResponse(
        url="https://example.com/q?x=1", status=503, request=request
    )

    retry_mw = _make_retry_middleware()
    result = retry_mw.process_response(request, response)
    assert result is response  # retries exhausted


def test_httpx_timeout_exception_triggers_retry() -> None:
    """The fix for follow-up #5: extending RETRY_EXCEPTIONS with
    httpx.TimeoutException makes timeouts on the HttpxMiddleware path
    retry the same way Twisted-side timeouts always have. Without this,
    cold-cache backend hangs lost their retry budget silently."""
    import httpx

    settings = Settings(
        {
            "RETRY_ENABLED": True,
            "RETRY_TIMES": 2,
            "RETRY_HTTP_CODES": [500, 502, 503, 504],
            "RETRY_PRIORITY_ADJUST": -1,
            # Mirror the addition in book_scraper/settings.py so this
            # test survives independent of project settings load order.
            "RETRY_EXCEPTIONS": [
                "httpx.TimeoutException",
                "httpx.ConnectError",
            ],
        }
    )
    retry_mw = RetryMiddleware(settings)
    spider = MagicMock()
    crawler = MagicMock()
    crawler.stats = MagicMock()
    crawler.stats.inc_value = MagicMock()
    crawler.settings = settings
    crawler.spider = spider
    spider.crawler = crawler
    retry_mw.crawler = crawler

    request = Request("https://example.com/q?x=1")
    exc = httpx.TimeoutException("read timeout")

    result = retry_mw.process_exception(request, exc)
    assert isinstance(result, Request)
    assert result.meta.get("retry_times") == 1


def test_httpx_connect_error_triggers_retry() -> None:
    """Same as the timeout case: connection-refused / DNS-fail cases
    on the httpx path should also flow through RetryMiddleware."""
    import httpx

    settings = Settings(
        {
            "RETRY_ENABLED": True,
            "RETRY_TIMES": 2,
            "RETRY_HTTP_CODES": [500, 502, 503, 504],
            "RETRY_PRIORITY_ADJUST": -1,
            "RETRY_EXCEPTIONS": [
                "httpx.TimeoutException",
                "httpx.ConnectError",
            ],
        }
    )
    retry_mw = RetryMiddleware(settings)
    crawler = MagicMock()
    crawler.stats = MagicMock()
    crawler.stats.inc_value = MagicMock()
    crawler.settings = settings
    spider = MagicMock()
    spider.crawler = crawler
    crawler.spider = spider
    retry_mw.crawler = crawler

    request = Request("https://example.com/q?x=1")
    result = retry_mw.process_exception(
        request, httpx.ConnectError("Name or service not known")
    )
    assert isinstance(result, Request)
