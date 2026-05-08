from datetime import UTC, datetime, timedelta

import pytest

from book_scraper.db.models import DiscoveredUrl, ScrapeRun, Shop, ShopBook
from book_scraper.db.repo import (
    get_pending_scan_urls,
    get_stable_discovered_urls,
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


def test_get_stable_discovered_urls_returns_classified_recent(db_session):
    """Returns URLs classified product/non_product/unreachable with a
    recent last_checked_at; excludes 'unknown' and stale rows."""
    shop = Shop(name="test_shop", base_url="https://test.lt")
    db_session.add(shop)
    db_session.flush()

    # product, fresh — included
    p = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/product", source="sitemap"
    )
    update_discovered_url_status(
        db_session, url_id=p.id, http_status=200, url_type="product"
    )
    # non_product, fresh — included
    np = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/about", source="sitemap"
    )
    update_discovered_url_status(
        db_session, url_id=np.id, http_status=200, url_type="non_product"
    )
    # unreachable, fresh — included (3 failures auto-promotes)
    un = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/dead", source="sitemap"
    )
    for _ in range(3):
        update_discovered_url_status(
            db_session, url_id=un.id, http_status=404, increment_fail=True
        )
    # unknown, fresh — excluded (not yet classified)
    upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/pending", source="sitemap"
    )
    # product, never checked — excluded (last_checked_at is NULL)
    upsert_discovered_url(
        db_session,
        shop_id=shop.id,
        url="https://test.lt/never-checked",
        source="sitemap",
        shop_book_id=None,
    )
    # product, stale (>7d) — excluded
    stale = upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/stale", source="sitemap"
    )
    update_discovered_url_status(
        db_session, url_id=stale.id, http_status=200, url_type="product"
    )
    db_session.refresh(stale)
    stale.last_checked_at = datetime.now(UTC) - timedelta(days=10)
    db_session.flush()

    result = get_stable_discovered_urls(db_session, shop_id=shop.id)
    assert "https://test.lt/product" in result
    assert result["https://test.lt/product"] == "product"
    assert result["https://test.lt/about"] == "non_product"
    assert result["https://test.lt/dead"] == "unreachable"
    assert "https://test.lt/pending" not in result
    assert "https://test.lt/never-checked" not in result
    assert "https://test.lt/stale" not in result


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


def test_link_discovered_url_marks_partial_when_isbn_missing(db_session):
    """is_partial=True on a fresh row should land url_type=product_partial,
    so the delta scan picks it up for an ISBN-fill scan."""
    shop = _make_shop(db_session)
    shop_book = ShopBook(
        shop_id=shop.id, url="https://test.lt/p", title="Partial", is_active=True
    )
    db_session.add(shop_book)
    db_session.flush()

    row = link_discovered_url_to_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://test.lt/p",
        shop_book_id=shop_book.id,
        is_partial=True,
    )
    assert row is not None
    assert row.url_type == "product_partial"


def test_link_discovered_url_promotes_unknown_to_partial(db_session):
    """An existing url_type=unknown row should promote to product_partial
    when the linking call says the data is partial."""
    shop = _make_shop(db_session)
    upsert_discovered_url(
        db_session, shop_id=shop.id, url="https://test.lt/p2", source="sitemap"
    )
    shop_book = ShopBook(
        shop_id=shop.id, url="https://test.lt/p2", title="P2", is_active=True
    )
    db_session.add(shop_book)
    db_session.flush()

    row = link_discovered_url_to_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://test.lt/p2",
        shop_book_id=shop_book.id,
        is_partial=True,
    )
    assert row is not None
    assert row.url_type == "product_partial"


def test_link_discovered_url_promotes_partial_to_product_when_filled(db_session):
    """A row that started product_partial should advance to product
    when a subsequent non-partial call lands (e.g. scan filled ISBN)."""
    shop = _make_shop(db_session)
    shop_book = ShopBook(
        shop_id=shop.id, url="https://test.lt/p3", title="P3", is_active=True
    )
    db_session.add(shop_book)
    db_session.flush()

    # First pass: discovered with partial data.
    link_discovered_url_to_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://test.lt/p3",
        shop_book_id=shop_book.id,
        is_partial=True,
    )
    # Second pass: full data this time.
    row = link_discovered_url_to_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://test.lt/p3",
        shop_book_id=shop_book.id,
        is_partial=False,
    )
    assert row is not None
    assert row.url_type == "product"


def test_link_discovered_url_partial_does_not_demote_product(db_session):
    """A complete `product` row must not be demoted by a later partial
    call — full data is sticky."""
    shop = _make_shop(db_session)
    shop_book = ShopBook(
        shop_id=shop.id, url="https://test.lt/p4", title="P4", is_active=True
    )
    db_session.add(shop_book)
    db_session.flush()

    # First pass: full data, lands at product.
    link_discovered_url_to_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://test.lt/p4",
        shop_book_id=shop_book.id,
        is_partial=False,
    )
    # Second pass: a lighter source (e.g. lupasearch) revisits the URL
    # without ISBN. Must not undo the previous full classification.
    row = link_discovered_url_to_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://test.lt/p4",
        shop_book_id=shop_book.id,
        is_partial=True,
    )
    assert row is not None
    assert row.url_type == "product"


def test_get_urls_already_scraped_excludes_product_partial(db_session):
    """The delta scan's 'already done' filter must not include
    product_partial rows — that's the whole point of the new value."""
    from book_scraper.db.repo import get_urls_already_scraped

    shop = _make_shop(db_session)
    full_book = ShopBook(
        shop_id=shop.id, url="https://test.lt/full", title="F", is_active=True
    )
    partial_book = ShopBook(
        shop_id=shop.id, url="https://test.lt/partial", title="P", is_active=True
    )
    db_session.add_all([full_book, partial_book])
    db_session.flush()
    link_discovered_url_to_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://test.lt/full",
        shop_book_id=full_book.id,
        is_partial=False,
    )
    link_discovered_url_to_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://test.lt/partial",
        shop_book_id=partial_book.id,
        is_partial=True,
    )

    already = get_urls_already_scraped(db_session, shop.id)
    assert "https://test.lt/full" in already
    assert "https://test.lt/partial" not in already


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
