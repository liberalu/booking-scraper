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
def test_spider_opened_no_settings_is_noop(db_session: Session) -> None:
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
