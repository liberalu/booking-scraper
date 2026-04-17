from book_scraper.db.models import ListingAuthor, ShopAuthor
from book_scraper.db.repo import upsert_listing, upsert_shop


def _insert_listing(db_session, *, author):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    listing, _, _, _ = upsert_listing(
        db_session,
        shop_id=shop.id,
        url=f"https://vaga.lt/x-{author or 'none'}",
        title="T",
        author=author,
    )
    db_session.flush()
    return listing


def _author_names(db_session, listing_id):
    rows = (
        db_session.query(ShopAuthor.name)
        .join(ListingAuthor, ListingAuthor.author_id == ShopAuthor.id)
        .filter(ListingAuthor.listing_id == listing_id)
        .order_by(ListingAuthor.position)
        .all()
    )
    return [r[0] for r in rows]


def test_single_author_creates_one_row(db_session):
    listing = _insert_listing(db_session, author="Jane Smith")
    assert _author_names(db_session, listing.id) == ["Jane Smith"]


def test_multi_author_splits_on_comma(db_session):
    listing = _insert_listing(db_session, author="L. Šernienė, M. Puzaitė")
    assert _author_names(db_session, listing.id) == [
        "L. Šernienė",
        "M. Puzaitė",
    ]


def test_multi_author_splits_on_various_separators(db_session):
    listing = _insert_listing(
        db_session, author="Alice & Bob; Carol / Dan and Eve ir Frank"
    )
    assert _author_names(db_session, listing.id) == [
        "Alice",
        "Bob",
        "Carol",
        "Dan",
        "Eve",
        "Frank",
    ]


def test_deduplicates_on_normalized_name(db_session):
    a = _insert_listing(db_session, author="Jane Smith")
    b = _insert_listing(db_session, author=" jane  smith ")
    rows_a = _author_names(db_session, a.id)
    rows_b = _author_names(db_session, b.id)
    assert rows_a == ["Jane Smith"]
    assert len(rows_b) == 1
    # Only one shop_authors row for "jane smith" regardless of casing/space.
    count = (
        db_session.query(ShopAuthor)
        .filter_by(normalized_name="jane smith")
        .count()
    )
    assert count == 1


def test_author_none_does_not_create_rows(db_session):
    listing = _insert_listing(db_session, author=None)
    assert _author_names(db_session, listing.id) == []


def test_rescrape_adds_new_and_removes_missing(db_session):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    upsert_listing(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/x",
        title="T",
        author="Alice & Bob",
    )
    db_session.flush()
    # Re-scrape with a different set of authors.
    listing, _, _, _ = upsert_listing(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/x",
        title="T",
        author="Alice & Carol",
    )
    db_session.flush()
    assert _author_names(db_session, listing.id) == ["Alice", "Carol"]
