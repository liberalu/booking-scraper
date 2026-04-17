from book_scraper.db.models import Listing, Shop
from book_scraper.db.repo import _infer_listing_type, upsert_listing


def test_infer_listing_type_maps_audiobook():
    assert _infer_listing_type("audiobook") == "audio"
    assert _infer_listing_type("audio") == "audio"
    assert _infer_listing_type("AUDIOBOOK") == "audio"


def test_infer_listing_type_defaults_book():
    assert _infer_listing_type(None) == "book"
    assert _infer_listing_type("paperback") == "book"
    assert _infer_listing_type("hardcover") == "book"
    assert _infer_listing_type("book") == "book"
    assert _infer_listing_type("n/a") == "book"


def _make_shop(db_session):
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    return shop


def test_upsert_listing_sets_type_audio_for_audiobook(db_session):
    shop = _make_shop(db_session)
    listing, _created, _, _ = upsert_listing(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/audio",
        title="Some Audio Book",
        format="audiobook",
    )
    assert listing.type == "audio"


def test_upsert_listing_sets_type_book_by_default(db_session):
    shop = _make_shop(db_session)
    listing, _created, _, _ = upsert_listing(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/paper",
        title="Paper Book",
        format="paperback",
    )
    assert listing.type == "book"


def test_upsert_listing_rederives_type_on_format_change(db_session):
    shop = _make_shop(db_session)
    upsert_listing(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/x",
        title="X",
        format="paperback",
    )
    # A later, corrected scrape re-classifies this listing as audio.
    listing, _, _, _ = upsert_listing(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/x",
        title="X",
        format="audiobook",
    )
    assert listing.type == "audio"


def test_priceitem_path_leaves_type_alone(db_session):
    """A lightweight price-only upsert (format=None) must not
    accidentally reset type back to book on an existing audio row."""
    shop = _make_shop(db_session)
    upsert_listing(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/a",
        title="A",
        format="audiobook",
    )
    upsert_listing(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/a",
        title="A",
        format=None,
    )
    listing = db_session.query(Listing).filter_by(url="https://vaga.lt/a").one()
    assert listing.type == "audio"
