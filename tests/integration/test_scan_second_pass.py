"""New URLs added to scrape_url_items mid-run are processed in the same run."""

from book_scraper.db.models import DiscoveredUrl, ScrapeUrlItem
from book_scraper.db.repo import insert_scrape_url_item, upsert_shop
from book_scraper.services.scan import ScanService


def test_insert_scrape_url_item_adds_pending_row(db_session):
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://vaga.lt/a",
            normalized_url="https://vaga.lt/a",
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()

    service = ScanService(db_session)
    plan = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)

    new_du = DiscoveredUrl(
        shop_id=shop.id,
        url="https://vaga.lt/b",
        normalized_url="https://vaga.lt/b",
        source="category",
        url_type="product",
        fail_count=0,
    )
    db_session.add(new_du)
    db_session.commit()

    item = insert_scrape_url_item(
        db_session,
        run_id=plan.run_id,
        shop_id=shop.id,
        discovered_url_id=new_du.id,
        url=new_du.url,
        url_type="product",
    )
    db_session.commit()

    assert item.status == "pending"
    assert (
        db_session.query(ScrapeUrlItem)
        .filter_by(run_id=plan.run_id, status="pending")
        .count()
        == 2
    )


def test_insert_scrape_url_item_is_idempotent(db_session):
    """Calling insert twice for the same (run_id, url) returns the existing row."""
    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://vaga.lt/a",
            normalized_url="https://vaga.lt/a",
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()

    service = ScanService(db_session)
    plan = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)

    first = insert_scrape_url_item(
        db_session, plan.run_id, shop.id, None, "https://vaga.lt/a", "product"
    )
    second = insert_scrape_url_item(
        db_session, plan.run_id, shop.id, None, "https://vaga.lt/a", "product"
    )
    db_session.commit()
    assert first.id == second.id
    assert (
        db_session.query(ScrapeUrlItem)
        .filter_by(run_id=plan.run_id, url="https://vaga.lt/a")
        .count()
        == 1
    )


def test_enqueue_new_url_from_service(db_session):
    """ScanService.enqueue_new_url queues an item and commits it."""
    from book_scraper.db.repo import upsert_discovered_url

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://vaga.lt/a",
            normalized_url="https://vaga.lt/a",
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()

    service = ScanService(db_session)
    plan = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)

    new_du = upsert_discovered_url(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/brand-new",
        source="category",
        run_id=plan.run_id,
    )
    service.enqueue_new_url(
        run_id=plan.run_id,
        shop_id=shop.id,
        discovered_url_id=new_du.id,
        url=new_du.url,
    )

    pending = (
        db_session.query(ScrapeUrlItem)
        .filter_by(run_id=plan.run_id, status="pending")
        .all()
    )
    assert {p.url for p in pending} == {
        "https://vaga.lt/a",
        "https://vaga.lt/brand-new",
    }


def test_get_pending_scrape_url_items_picks_up_mid_run_inserts(db_session):
    """After prepare_scan, inserting new items via insert_scrape_url_item
    makes them visible to get_pending_scrape_url_items."""
    from book_scraper.db.repo import (
        get_pending_scrape_url_items,
        insert_scrape_url_item,
    )

    shop = upsert_shop(db_session, "vaga", "https://vaga.lt")
    db_session.add(
        DiscoveredUrl(
            shop_id=shop.id,
            url="https://vaga.lt/a",
            normalized_url="https://vaga.lt/a",
            source="sitemap",
            url_type="product",
            fail_count=0,
        )
    )
    db_session.commit()

    service = ScanService(db_session)
    plan = service.prepare_scan("vaga", "https://vaga.lt", {}, rescrape=True)

    insert_scrape_url_item(
        db_session,
        run_id=plan.run_id,
        shop_id=shop.id,
        discovered_url_id=None,
        url="https://vaga.lt/mid-run",
        url_type="product",
    )
    db_session.commit()

    items = get_pending_scrape_url_items(db_session, plan.run_id)
    urls = {i["url"] for i in items}
    assert urls == {"https://vaga.lt/a", "https://vaga.lt/mid-run"}
