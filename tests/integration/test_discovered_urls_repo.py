import pytest

from book_scraper.db.models import DiscoveredUrl, ScrapeRun, Shop, ShopBook
from book_scraper.db.repo import (
    get_pending_scan_urls,
    link_discovered_url_to_shop_book,
    update_discovered_url_status,
    upsert_discovered_url,
)


def test_upsert_discovered_url_creates_new(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    result = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/book-1", source="sitemap"
    )
    assert result.url == "https://test.lt/book-1"
    assert result.source == "sitemap"
    assert result.url_type == "unknown"
    assert result.fail_count == 0


def test_upsert_discovered_url_ignores_duplicate(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    first = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/book-1", source="sitemap"
    )
    second = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/book-1", source="category"
    )
    assert first.id == second.id
    assert second.source == "sitemap"


def test_update_discovered_url_status_success(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    url_record = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/book-1", source="sitemap"
    )
    update_discovered_url_status(
        db_session, url_id=url_record.id, http_status=200, url_type="product"
    )
    db_session.refresh(url_record)
    assert url_record.last_http_status == 200
    assert url_record.url_type == "product"
    assert url_record.fail_count == 0
    assert url_record.last_checked_at is not None


def test_update_discovered_url_status_failure(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    url_record = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/book-1", source="sitemap"
    )
    update_discovered_url_status(
        db_session, url_id=url_record.id, http_status=404, increment_fail=True
    )
    db_session.refresh(url_record)
    assert url_record.last_http_status == 404
    assert url_record.fail_count == 1


def test_get_pending_scan_urls_filters_non_product(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/book-1", source="sitemap"
    )
    non_product = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/about", source="sitemap"
    )
    update_discovered_url_status(
        db_session, url_id=non_product.id, http_status=200, url_type="non_product"
    )

    pending = get_pending_scan_urls(db_session, shop_id=shop.id)
    urls = [u.url for u in pending]
    assert "https://test.lt/book-1" in urls
    assert "https://test.lt/about" not in urls


def test_get_pending_scan_urls_filters_high_fail_count(db_session):
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    url_record = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/dead", source="sitemap"
    )
    for _ in range(3):
        update_discovered_url_status(
            db_session, url_id=url_record.id, http_status=404, increment_fail=True
        )

    pending = get_pending_scan_urls(db_session, shop_id=shop.id)
    urls = [u.url for u in pending]
    assert "https://test.lt/dead" not in urls


def _make_shop(db_session, name: str = "test_shop") -> Shop:
    shop = Shop(name=name, base_url=f"https://{name}.lt")
    db_session.add(shop)
    db_session.flush()
    return shop


def _make_run(db_session, shop_id: int) -> ScrapeRun:
    run = ScrapeRun(shop_id=shop_id, phase="scan", status="running")
    db_session.add(run)
    db_session.flush()
    return run


def test_upsert_discovered_url_dedupes_by_normalized_url(db_session):
    """Raw URLs differing only by tracking params / case / trailing slash
    collapse to one row keyed by (shop_id, normalized_url)."""
    shop = _make_shop(db_session)
    first = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/Book", source="sitemap"
    )
    second = upsert_discovered_url(
        db_session,
        shop_id=shop.id,
        url="https://test.lt/Book/?utm_source=newsletter",
        source="category",
    )
    assert first.id == second.id
    assert second.normalized_url == "https://test.lt/Book"


def test_upsert_discovered_url_updates_last_seen_and_run(db_session):
    shop = _make_shop(db_session)
    run1 = _make_run(db_session, shop.id)
    first = upsert_discovered_url(
        db_session,
        shop_id=shop.id,
        url="https://test.lt/book-1",
        source="sitemap",
        run_id=run1.id,
    )
    first_last_seen = first.last_seen_at

    run2 = _make_run(db_session, shop.id)
    second = upsert_discovered_url(
        db_session,
        shop_id=shop.id,
        url="https://test.lt/book-1",
        source="category",
        run_id=run2.id,
    )
    assert first.id == second.id
    assert second.last_seen_run_id == run2.id
    assert second.last_seen_at >= first_last_seen


def test_link_discovered_url_to_shop_book_attaches_fk(db_session):
    shop = _make_shop(db_session)
    upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/b", source="sitemap"
    )
    shop_book = ShopBook(
        shop_id=shop.id, url="https://test.lt/b", title="Book", is_active=True
    )
    db_session.add(shop_book)
    db_session.flush()

    row = link_discovered_url_to_shop_book(
        db_session, shop_id=shop.id, url="https://test.lt/b", shop_book_id=shop_book.id
    )
    assert row is not None
    assert row.shop_book_id == shop_book.id

    # And the reverse relation loads the discovered row.
    db_session.refresh(shop_book)
    assert any(d.shop_book_id == shop_book.id for d in shop_book.discovered_urls)


def test_link_discovered_url_creates_row_when_missing(db_session):
    """A shop_book upserted without a matching discovered_url row (e.g.
    price-only category scrape before any sitemap run) still gets a
    backing discovered_url row for the relation."""
    shop = _make_shop(db_session)
    shop_book = ShopBook(
        shop_id=shop.id, url="https://test.lt/new", title="New", is_active=True
    )
    db_session.add(shop_book)
    db_session.flush()

    row = link_discovered_url_to_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://test.lt/new",
        shop_book_id=shop_book.id,
    )
    assert row is not None
    assert row.shop_book_id == shop_book.id
    assert row.normalized_url == "https://test.lt/new"


def test_unique_constraint_enforced_on_normalized_url(db_session):
    """Two raw URLs with the same normalization must not coexist."""
    import sqlalchemy.exc

    shop = _make_shop(db_session)
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://test.lt/dup",
            normalized_url="https://test.lt/dup",
            source="sitemap",
        )
    )
    db_session.flush()
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://test.lt/dup?utm_source=x",
            normalized_url="https://test.lt/dup",
            source="category",
        )
    )
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()
