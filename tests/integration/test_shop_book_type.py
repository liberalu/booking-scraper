from book_scraper.db.models import Shop, ShopBook
from book_scraper.db.repo import _infer_shop_book_type, upsert_shop_book


def test_infer_shop_book_type_maps_audiobook():
    assert _infer_shop_book_type("audiobook") == "audio"
    assert _infer_shop_book_type("audio") == "audio"
    assert _infer_shop_book_type("AUDIOBOOK") == "audio"


def test_infer_shop_book_type_defaults_book():
    assert _infer_shop_book_type(None) == "book"
    assert _infer_shop_book_type("paperback") == "book"
    assert _infer_shop_book_type("hardcover") == "book"
    assert _infer_shop_book_type("book") == "book"
    assert _infer_shop_book_type("n/a") == "book"


def _make_shop(db_session):
    shop = Shop(name="vaga", base_url="https://vaga.lt")
    db_session.add(shop)
    db_session.flush()
    return shop


def test_upsert_shop_book_sets_type_audio_for_audiobook(db_session):
    shop = _make_shop(db_session)
    shop_book, _created, _, _ = upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/audio",
        title="Some Audio Book",
        format="audiobook",
    )
    assert shop_book.type == "audio"


def test_upsert_shop_book_sets_type_book_by_default(db_session):
    shop = _make_shop(db_session)
    shop_book, _created, _, _ = upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/paper",
        title="Paper Book",
        format="paperback",
    )
    assert shop_book.type == "book"


def test_upsert_shop_book_rederives_type_on_format_change(db_session):
    shop = _make_shop(db_session)
    upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/x",
        title="X",
        format="paperback",
    )
    # A later, corrected scrape re-classifies this shop_book as audio.
    shop_book, _, _, _ = upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/x",
        title="X",
        format="audiobook",
    )
    assert shop_book.type == "audio"


def test_priceitem_path_leaves_type_alone(db_session):
    """A lightweight price-only upsert (format=None) must not
    accidentally reset type back to book on an existing audio row."""
    shop = _make_shop(db_session)
    upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/a",
        title="A",
        format="audiobook",
    )
    upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/a",
        title="A",
        format=None,
    )
    shop_book = db_session.query(ShopBook).filter_by(url="https://vaga.lt/a").one()
    assert shop_book.type == "audio"
