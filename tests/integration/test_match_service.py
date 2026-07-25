"""Integration tests for MatchService steps 1 (ISBN match) and 2 (author backfill)."""
from sqlalchemy import select

from book_scraper.db.models import (
    Author,
    Book,
    BookAuthor,
    BookIsbn,
    Shop,
    ShopAuthor,
    ShopBook,
    ShopBookAuthor,
)
from book_scraper.services.match import MatchService


def _make_shop(session, name: str) -> Shop:
    shop = Shop(name=name, base_url=f"https://{name}.lt")
    session.add(shop)
    session.flush()
    return shop


def _make_book(session, libis_code: str, isbn: str) -> Book:
    book = Book(
        data_source="ibiblioteka", libis_code=libis_code, title=f"T-{libis_code}"
    )
    session.add(book)
    session.flush()
    session.add(BookIsbn(book_id=book.id, isbn=isbn, isbn_type="isbn13"))
    session.flush()
    return book


def test_step1_links_shop_book_by_isbn(db_session):
    shop = _make_shop(db_session, "vaga")
    book = _make_book(db_session, "LIBIS000000000001", "9780000000001")
    sb = ShopBook(
        shop_id=shop.id, url="https://vaga.lt/p/1", title="Same",
        isbn="9780000000001",
    )
    db_session.add(sb)
    db_session.commit()

    MatchService(db_session).run("vaga")

    db_session.expire_all()
    sb = db_session.execute(select(ShopBook).where(ShopBook.id == sb.id)).scalar_one()
    assert sb.book_id == book.id
    assert sb.match_status == "matched"
    assert sb.match_method == "isbn"


def test_step1_skips_already_matched(db_session):
    shop = _make_shop(db_session, "vaga")
    _make_book(db_session, "LIBIS000000000002", "9780000000002")
    other_book = _make_book(db_session, "LIBIS000000000003", "9780000000003")
    sb = ShopBook(
        shop_id=shop.id, url="https://vaga.lt/p/2", title="Same",
        isbn="9780000000002", book_id=other_book.id, match_status="matched",
    )
    db_session.add(sb)
    db_session.commit()

    MatchService(db_session).run("vaga")

    db_session.expire_all()
    sb = db_session.execute(select(ShopBook).where(ShopBook.id == sb.id)).scalar_one()
    assert sb.book_id == other_book.id


def test_step1_only_affects_named_shop(db_session):
    shop_v = _make_shop(db_session, "vaga")
    shop_p = _make_shop(db_session, "pegasas")
    book = _make_book(db_session, "LIBIS000000000004", "9780000000004")
    sb_v = ShopBook(
        shop_id=shop_v.id, url="https://vaga.lt/p/3", title="V", isbn="9780000000004"
    )
    sb_p = ShopBook(
        shop_id=shop_p.id, url="https://pegasas.lt/p/3", title="P", isbn="9780000000004"
    )
    db_session.add_all([sb_v, sb_p])
    db_session.commit()

    MatchService(db_session).run("vaga")

    db_session.expire_all()
    assert db_session.execute(
        select(ShopBook).where(ShopBook.id == sb_v.id)
    ).scalar_one().book_id == book.id
    assert db_session.execute(
        select(ShopBook).where(ShopBook.id == sb_p.id)
    ).scalar_one().book_id is None


def test_step2_links_shop_authors_to_canonical(db_session):
    shop = _make_shop(db_session, "vaga")
    book = _make_book(db_session, "LIBIS000000000005", "9780000000005")
    canonical = Author(
        name="Mildažytė, Edita",
        normalized_name="mildazyte edita",
        libis_code="LNB:Hd0;=BC",
    )
    db_session.add(canonical)
    db_session.flush()
    db_session.add(BookAuthor(
        book_id=book.id, author_id=canonical.id, role="author", position=0
    ))
    db_session.flush()

    sb = ShopBook(
        shop_id=shop.id, url="https://vaga.lt/p/4", title="Same", isbn="9780000000005"
    )
    db_session.add(sb)
    db_session.flush()
    shop_author = ShopAuthor(name="Edita Mildažytė", normalized_name="edita mildažytė")
    db_session.add(shop_author)
    db_session.flush()
    db_session.add(ShopBookAuthor(
        shop_book_id=sb.id, author_id=shop_author.id, position=0
    ))
    db_session.commit()

    MatchService(db_session).run("vaga")

    db_session.expire_all()
    sa = db_session.execute(
        select(ShopAuthor).where(ShopAuthor.id == shop_author.id)
    ).scalar_one()
    assert sa.canonical_author_id == canonical.id


def test_step2_does_not_pair_translator_at_position_0(db_session):
    """If book_authors has both author@0 and translator@0, the join must
    only pair the shop_author (always primary) with author@0."""
    shop = _make_shop(db_session, "vaga")
    book = _make_book(db_session, "LIBIS000000000006", "9780000000006")
    primary = Author(name="A, A", normalized_name="a a")
    translator = Author(name="T, T", normalized_name="t t")
    db_session.add_all([primary, translator])
    db_session.flush()
    db_session.add_all([
        BookAuthor(book_id=book.id, author_id=primary.id, role="author", position=0),
        BookAuthor(book_id=book.id, author_id=translator.id, role="translator", position=0),
    ])
    sb = ShopBook(
        shop_id=shop.id, url="https://vaga.lt/p/5", title="X", isbn="9780000000006"
    )
    db_session.add(sb)
    db_session.flush()
    shop_author = ShopAuthor(name="A A", normalized_name="a a (shop)")
    db_session.add(shop_author)
    db_session.flush()
    db_session.add(ShopBookAuthor(
        shop_book_id=sb.id, author_id=shop_author.id, position=0
    ))
    db_session.commit()

    MatchService(db_session).run("vaga")

    db_session.expire_all()
    sa = db_session.execute(
        select(ShopAuthor).where(ShopAuthor.id == shop_author.id)
    ).scalar_one()
    assert sa.canonical_author_id == primary.id


def test_step3_synthesizes_shop_inferred_after_two_shops(db_session, monkeypatch):
    """Two shops carry the same ISBN, no canonical match -> create shop_inferred book."""
    monkeypatch.setattr(
        "book_scraper.services.match.MATCH_SYNTHESIS_ENABLED", True
    )

    sv = _make_shop(db_session, "vaga")
    sp = _make_shop(db_session, "pegasas")
    isbn = "9780000000007"

    sb_v = ShopBook(
        shop_id=sv.id, url="https://vaga.lt/p/sa", title="Vaga Title",
        isbn=isbn, publisher="Vaga Publisher", year=2024,
    )
    sb_p = ShopBook(
        shop_id=sp.id, url="https://pegasas.lt/p/sa", title="Pegasas Title",
        isbn=isbn, publisher="Pegasas Publisher", year=2024,
    )
    db_session.add_all([sb_v, sb_p])
    db_session.commit()

    svc = MatchService(db_session)
    svc.shop_trust = {"vaga": 100, "pegasas": 90}
    svc.run("vaga")

    db_session.expire_all()
    rows = db_session.execute(
        select(Book).join(BookIsbn).where(BookIsbn.isbn == isbn)
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].data_source == "shop_inferred"
    assert rows[0].title == "Vaga Title"


def test_step3_publisher_is_first_writer_not_highest_trust(db_session, monkeypatch):
    """Sticky publisher: the FIRST shop's publisher persists even when
    a higher-trust shop also has the ISBN."""
    monkeypatch.setattr(
        "book_scraper.services.match.MATCH_SYNTHESIS_ENABLED", True
    )
    import datetime

    from book_scraper.db.models import Publisher

    sp = _make_shop(db_session, "pegasas")
    sv = _make_shop(db_session, "vaga")
    isbn = "9780000000008"

    sb_p = ShopBook(
        shop_id=sp.id, url="https://pegasas.lt/p/sb", title="P",
        isbn=isbn, publisher="Pegasas Publisher",
        first_seen_at=datetime.datetime(2024, 1, 1, tzinfo=datetime.UTC),
    )
    db_session.add(sb_p)
    db_session.commit()
    sb_v = ShopBook(
        shop_id=sv.id, url="https://vaga.lt/p/sb", title="V",
        isbn=isbn, publisher="Vaga Publisher",
        first_seen_at=datetime.datetime(2024, 6, 1, tzinfo=datetime.UTC),
    )
    db_session.add(sb_v)
    db_session.commit()

    svc = MatchService(db_session)
    svc.shop_trust = {"vaga": 100, "pegasas": 90}
    svc.run("vaga")

    db_session.expire_all()
    book = db_session.execute(
        select(Book).join(BookIsbn).where(BookIsbn.isbn == isbn)
    ).scalar_one()
    pub = db_session.execute(
        select(Publisher).where(Publisher.id == book.publisher_id)
    ).scalar_one()
    assert pub.name == "Pegasas Publisher"
