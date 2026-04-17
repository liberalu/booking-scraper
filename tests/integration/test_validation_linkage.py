import pytest
import sqlalchemy.exc

from book_scraper.db.models import (
    DiscoveredUrl,
    Listing,
    ScrapeRun,
    Shop,
    ValidationIssue,
)
from book_scraper.db.repo import bulk_insert_validation_issues


def _setup(db_session):
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    run = ScrapeRun(shop_id=shop.id, phase="scan", status="running")
    db_session.add(run)
    db_session.flush()
    return shop, run


def test_bulk_insert_resolves_listing_fk(db_session):
    shop, run = _setup(db_session)
    listing = Listing(shop_id=shop.id, url="https://vaga.lt/b", title="B")
    db_session.add(listing)
    db_session.flush()

    bulk_insert_validation_issues(
        db_session,
        [
            {
                "scrape_run_id": run.id,
                "url": "https://vaga.lt/b",
                "field": "price",
                "issue": "missing_price",
                "raw_value": None,
            }
        ],
        shop_id=shop.id,
    )
    db_session.flush()

    issue = db_session.query(ValidationIssue).one()
    assert issue.listing_id == listing.id
    assert issue.discovered_url_id is None


def test_bulk_insert_falls_back_to_discovered_url_fk(db_session):
    shop, run = _setup(db_session)
    du = DiscoveredUrl(
        shop_id=shop.id,
        url="https://vaga.lt/unlisted",
        normalized_url="https://vaga.lt/unlisted",
        source="sitemap",
    )
    db_session.add(du)
    db_session.flush()

    bulk_insert_validation_issues(
        db_session,
        [
            {
                "scrape_run_id": run.id,
                "url": "https://vaga.lt/unlisted",
                "field": "url",
                "issue": "http_4xx",
                "raw_value": "404",
            }
        ],
        shop_id=shop.id,
    )
    db_session.flush()

    issue = db_session.query(ValidationIssue).one()
    assert issue.listing_id is None
    assert issue.discovered_url_id == du.id


def test_bulk_insert_leaves_both_null_when_no_match(db_session):
    """A sitemap-duplicate issue reports a shop-wide URL without a
    corresponding listing or discovered_url row. Both FKs stay NULL."""
    shop, run = _setup(db_session)

    bulk_insert_validation_issues(
        db_session,
        [
            {
                "scrape_run_id": run.id,
                "url": "https://vaga.lt/sitemap.xml",
                "field": "url",
                "issue": "duplicate_sitemap_url",
                "raw_value": "2 duplicates",
            }
        ],
        shop_id=shop.id,
    )
    db_session.flush()

    issue = db_session.query(ValidationIssue).one()
    assert issue.listing_id is None
    assert issue.discovered_url_id is None


def test_check_constraint_forbids_both_fks(db_session):
    shop, run = _setup(db_session)
    listing = Listing(shop_id=shop.id, url="https://vaga.lt/x", title="X")
    du = DiscoveredUrl(
        shop_id=shop.id,
        url="https://vaga.lt/x",
        normalized_url="https://vaga.lt/x",
        source="sitemap",
    )
    db_session.add_all([listing, du])
    db_session.flush()

    db_session.add(
        ValidationIssue(
            scrape_run_id=run.id,
            url="https://vaga.lt/x",
            field="title",
            issue="suspicious_title",
            listing_id=listing.id,
            discovered_url_id=du.id,
        )
    )
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        db_session.flush()


def test_relationships_load(db_session):
    shop, run = _setup(db_session)
    listing = Listing(shop_id=shop.id, url="https://vaga.lt/y", title="Y")
    db_session.add(listing)
    db_session.flush()

    bulk_insert_validation_issues(
        db_session,
        [
            {
                "scrape_run_id": run.id,
                "url": "https://vaga.lt/y",
                "field": "price",
                "issue": "missing_price",
                "raw_value": None,
            }
        ],
        shop_id=shop.id,
    )
    db_session.flush()

    issue = db_session.query(ValidationIssue).one()
    assert issue.listing is not None
    assert issue.listing.id == listing.id
    assert issue.discovered_url is None
