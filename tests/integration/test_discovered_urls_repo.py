from book_scraper.db.models import Shop
from book_scraper.db.repo import (
    get_pending_scan_urls,
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
