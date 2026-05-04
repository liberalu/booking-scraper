"""Integration tests for HttpxMiddleware.spider_opened DB path."""

import asyncio

import pytest
from sqlalchemy.orm import Session

from book_scraper.db.models import Shop, ShopSettings
from book_scraper.download_handler import HttpxMiddleware


def _make_middleware() -> HttpxMiddleware:
    # database_url must be non-None so spider_opened doesn't short-circuit,
    # but the actual URL is unused — _session_factory is monkeypatched.
    return HttpxMiddleware(
        timeout=15.0,
        user_agent="test",
        database_url="postgresql://unused-monkeypatched",
        download_delay=2.0,
        autothrottle_enabled=True,
        autothrottle_start_delay=2.0,
        autothrottle_max_delay=30.0,
        autothrottle_target_concurrency=1.0,
        client_reset_after_requests=80,
    )


def _seed_settings(
    db_session: Session, shop_id: int, rows: list[tuple[str, str, str]]
) -> None:
    for key, value, type_hint in rows:
        existing = (
            db_session.query(ShopSettings)
            .filter(ShopSettings.shop_id == shop_id, ShopSettings.key == key)
            .first()
        )
        if existing:
            existing.value = value
        else:
            db_session.add(
                ShopSettings(shop_id=shop_id, key=key, value=value, type=type_hint)
            )
    db_session.flush()  # visible within this session; rolled back after test


class _MockSpider:
    shop_name = "vaga"


def _ensure_vaga(db_session: Session) -> Shop:
    shop = db_session.query(Shop).filter(Shop.name == "vaga").first()
    if shop is None:
        shop = Shop(name="vaga", base_url="https://vaga.lt")
        db_session.add(shop)
        db_session.flush()
    return shop


@pytest.mark.integration
def test_spider_opened_applies_db_rate_settings(db_session: Session) -> None:
    shop = _ensure_vaga(db_session)
    _seed_settings(
        db_session,
        shop.id,
        [
            ("download_delay", "1.5", "float"),
            ("concurrent_requests_per_domain", "3", "int"),
        ],
    )

    mw = _make_middleware()
    mw._session_factory = lambda: db_session  # share test transaction
    try:
        mw.spider_opened(_MockSpider())
        assert mw._download_delay == 1.5
        assert mw._autothrottle_start == 1.5
        assert mw._max_concurrency == 3
        assert mw._host_slots == {}
        assert mw._host_current_delay == {}
    finally:
        asyncio.run(mw._close())


@pytest.mark.integration
def test_spider_opened_clamps_values(db_session: Session) -> None:
    shop = _ensure_vaga(db_session)
    _seed_settings(
        db_session,
        shop.id,
        [
            ("download_delay", "999.0", "float"),
            ("concurrent_requests_per_domain", "0", "int"),
        ],
    )

    mw = _make_middleware()
    mw._session_factory = lambda: db_session
    try:
        mw.spider_opened(_MockSpider())
        assert mw._download_delay == 60.0
        assert mw._max_concurrency == 1
    finally:
        asyncio.run(mw._close())


@pytest.mark.integration
def test_spider_opened_unknown_shop_falls_back_to_scrapy_globals(
    db_session: Session,
) -> None:
    """Shop has no TOML and no DB rows: middleware keeps the Scrapy
    globals it was instantiated with."""
    mw = _make_middleware()
    mw._session_factory = lambda: db_session

    class _UnknownShop:
        shop_name = "nonexistent_shop_xyz"

    try:
        mw.spider_opened(_UnknownShop())
        assert mw._download_delay == 2.0
        assert mw._max_concurrency == 1
    finally:
        asyncio.run(mw._close())


@pytest.mark.integration
def test_spider_opened_uses_toml_when_no_db_rows(db_session: Session) -> None:
    """Precedence chain: DB → TOML → Scrapy globals. With no DB rows
    for vaga, the TOML [scraping] values must be applied. vaga.toml
    sets download_delay=0.2 and concurrent_requests_per_domain=8 —
    both differ from the Scrapy globals (2.0 / 1) so a regression
    falling back to globals would be visible."""
    _ensure_vaga(db_session)
    # No _seed_settings call — DB is empty for vaga.

    mw = _make_middleware()
    mw._session_factory = lambda: db_session
    try:
        mw.spider_opened(_MockSpider())
        # TOML values, not the Scrapy globals (2.0 / 1).
        assert mw._download_delay == 0.2
        assert mw._max_concurrency == 8
    finally:
        asyncio.run(mw._close())


@pytest.mark.integration
def test_spider_opened_db_overrides_toml_per_key(db_session: Session) -> None:
    """DB takes precedence over TOML key-by-key: a DB row for
    download_delay overrides the TOML value, but concurrent_requests
    (no DB row) still picks up TOML's setting."""
    shop = _ensure_vaga(db_session)
    _seed_settings(
        db_session,
        shop.id,
        [("download_delay", "1.5", "float")],
    )

    mw = _make_middleware()
    mw._session_factory = lambda: db_session
    try:
        mw.spider_opened(_MockSpider())
        assert mw._download_delay == 1.5  # DB wins
        assert mw._max_concurrency == 8  # TOML (no DB row) wins over global
    finally:
        asyncio.run(mw._close())


@pytest.mark.integration
def test_process_request_uses_post_when_request_method_post() -> None:
    """Regression for runs 310..317: HttpxMiddleware used to always call
    client.get() regardless of request.method. LupaSearch is a POST
    endpoint with the filter payload in the body — sending GET stripped
    the filter and returned the unfiltered catalog (707k items vs 13k
    LT-only), inflating the queue by ~50x.

    This test exercises the dispatch path with a Request(method='POST',
    body=b'...') and asserts the middleware called client.post with the
    body forwarded."""
    from unittest.mock import AsyncMock, MagicMock

    from scrapy import Request

    mw = _make_middleware()
    fake_response = MagicMock()
    fake_response.url = "https://api.example.com/q"
    fake_response.status_code = 200
    fake_response.headers = {}
    fake_response.content = b'{"total": 13603, "items": []}'
    fake_response.encoding = "utf-8"
    mw.client.post = AsyncMock(return_value=fake_response)
    mw.client.get = AsyncMock()  # should NOT be called

    body = b'{"filters":{"category_ids":["5107"]}}'
    request = Request(
        "https://api.example.com/q?offset=0",
        method="POST",
        body=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )

    try:
        result = asyncio.run(mw.process_request(request))
        assert result.status == 200
        mw.client.post.assert_called_once()
        # Body must be forwarded so the endpoint sees the filter.
        post_kwargs = mw.client.post.call_args.kwargs
        assert post_kwargs["content"] == body
        # GET path must NOT have been taken.
        mw.client.get.assert_not_called()
    finally:
        asyncio.run(mw._close())


@pytest.mark.integration
def test_process_request_still_uses_get_for_default_method() -> None:
    """Ensure the POST branch didn't accidentally break the GET path."""
    from unittest.mock import AsyncMock, MagicMock

    from scrapy import Request

    mw = _make_middleware()
    fake_response = MagicMock()
    fake_response.url = "https://example.com/page"
    fake_response.status_code = 200
    fake_response.headers = {}
    fake_response.content = b"<html/>"
    fake_response.encoding = "utf-8"
    mw.client.get = AsyncMock(return_value=fake_response)
    mw.client.post = AsyncMock()  # should NOT be called

    request = Request("https://example.com/page")  # default method GET

    try:
        result = asyncio.run(mw.process_request(request))
        assert result.status == 200
        mw.client.get.assert_called_once()
        mw.client.post.assert_not_called()
    finally:
        asyncio.run(mw._close())
