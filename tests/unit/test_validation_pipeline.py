import pytest
from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem

from book_scraper.items import PriceItem, ShopBookItem
from book_scraper.pipelines import ValidationPipeline, _is_valid_isbn


class FakeStats:
    def __init__(self):
        self.values = {}

    def inc_value(self, key: str) -> None:
        self.values[key] = self.values.get(key, 0) + 1


@pytest.fixture
def stats():
    return FakeStats()


@pytest.fixture
def pipeline(stats):
    return ValidationPipeline(stats=stats)


def test_valid_shop_book_passes(pipeline):
    item = ShopBookItem(
        url="https://vaga.lt/book", shop_name="vaga", title="Book", price="9.99"
    )
    result = pipeline.process_item(item)
    assert ItemAdapter(result)["price"] == "9.99"


def test_shop_book_without_title_dropped(pipeline):
    item = ShopBookItem(url="https://vaga.lt/book", shop_name="vaga")
    with pytest.raises(DropItem, match="Missing title"):
        pipeline.process_item(item)


def test_invalid_price_dropped(pipeline):
    item = PriceItem(url="https://vaga.lt/book", shop_name="vaga", price="abc")
    with pytest.raises(DropItem, match="Invalid price"):
        pipeline.process_item(item)


def test_price_normalized_to_decimal_string(pipeline):
    item = PriceItem(url="https://vaga.lt/book", shop_name="vaga", price="16.32")
    result = pipeline.process_item(item)
    assert ItemAdapter(result)["price"] == "16.32"


def test_price_original_normalized(pipeline):
    item = PriceItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        price="10.00",
        price_original="15.50",
    )
    result = pipeline.process_item(item)
    assert ItemAdapter(result)["price_original"] == "15.50"


def test_invalid_price_original_set_to_none(pipeline):
    item = PriceItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        price="10.00",
        price_original="invalid",
    )
    result = pipeline.process_item(item)
    assert ItemAdapter(result)["price_original"] is None


def test_none_price_passes_through(pipeline):
    item = ShopBookItem(url="https://vaga.lt/book", shop_name="vaga", title="Book")
    result = pipeline.process_item(item)
    assert ItemAdapter(result).get("price") is None


def test_none_price_original_left_alone(pipeline):
    item = ShopBookItem(
        url="https://vaga.lt/book", shop_name="vaga", title="Book", price="10.00"
    )
    result = pipeline.process_item(item)
    assert ItemAdapter(result).get("price_original") is None


# --- ISBN validation ---


@pytest.mark.parametrize(
    "isbn",
    [
        "9780306406157",  # valid ISBN-13
        "978-0-306-40615-7",  # ISBN-13 with dashes
        "0306406152",  # valid ISBN-10
        "0-306-40615-2",  # ISBN-10 with dashes
        "080442957X",  # ISBN-10 ending in X
    ],
)
def test_valid_isbn(isbn):
    assert _is_valid_isbn(isbn) is True


@pytest.mark.parametrize(
    "isbn",
    [
        "4779054890696",  # EAN barcode, not ISBN
        "4742023094050",  # EAN barcode
        "1234567890123",  # 13 digits but not 978/979
        "0306406153",  # invalid check digit
        "abc",  # not numeric
        "",  # empty
    ],
)
def test_invalid_isbn(isbn):
    assert _is_valid_isbn(isbn) is False


def test_ean_barcode_cleared_from_shop_book(pipeline):
    item = ShopBookItem(
        url="https://vaga.lt/product",
        shop_name="vaga",
        title="Board Game",
        isbn="4779054890696",
    )
    result = pipeline.process_item(item)
    assert ItemAdapter(result).get("isbn") is None


def test_valid_isbn_kept_in_shop_book(pipeline):
    item = ShopBookItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        title="A Book",
        isbn="9780306406157",
    )
    result = pipeline.process_item(item)
    assert ItemAdapter(result)["isbn"] == "9780306406157"


def test_none_isbn_left_alone(pipeline):
    item = ShopBookItem(url="https://vaga.lt/book", shop_name="vaga", title="Book")
    result = pipeline.process_item(item)
    assert ItemAdapter(result).get("isbn") is None


# --- Year validation ---


def test_valid_year_kept(pipeline):
    item = ShopBookItem(
        url="https://vaga.lt/book", shop_name="vaga", title="Book", year=2024
    )
    result = pipeline.process_item(item)
    assert ItemAdapter(result)["year"] == 2024


def test_year_out_of_range_cleared(pipeline):
    item = ShopBookItem(
        url="https://vaga.lt/book", shop_name="vaga", title="Book", year=20
    )
    result = pipeline.process_item(item)
    assert ItemAdapter(result).get("year") is None


def test_year_pages_swap(pipeline):
    item = ShopBookItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        title="Book",
        year=216,
        properties={"pages": 2024},
    )
    result = pipeline.process_item(item)
    adapter = ItemAdapter(result)
    assert adapter["year"] == 2024
    assert adapter["properties"]["pages"] == 216


def test_description_keeps_text_after_a_mixed_line_break(pipeline):
    # markdownify drops everything after a `<br/>` that follows a `<br>` in one
    # paragraph — an html.parser artifact, so normalise the self-closing form.
    item = ShopBookItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        title="Book",
        description="<p>One<br>Two<br/>Three</p>",
    )
    result = pipeline.process_item(item)

    assert ItemAdapter(result)["description"] == "One  \nTwo  \nThree"


def test_year_as_string_is_not_a_swap(pipeline, stats):
    # _validate_year turns "2024" into 2024; comparing by identity read that
    # as a year/pages swap and filed an issue for a perfectly good year.
    item = ShopBookItem(
        url="https://vaga.lt/book", shop_name="vaga", title="Book", year="2024"
    )
    result = pipeline.process_item(item)

    assert ItemAdapter(result)["year"] == 2024
    assert "validation/year_pages_swap" not in stats.values


def test_year_pages_no_swap_when_pages_not_year(pipeline):
    item = ShopBookItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        title="Book",
        year=320,
        properties={"pages": 500},
    )
    result = pipeline.process_item(item)
    adapter = ItemAdapter(result)
    assert adapter.get("year") is None
    assert adapter["properties"]["pages"] == 500


def test_none_year_left_alone(pipeline):
    item = ShopBookItem(url="https://vaga.lt/book", shop_name="vaga", title="Book")
    result = pipeline.process_item(item)
    assert ItemAdapter(result).get("year") is None


def test_future_year_cleared(pipeline):
    item = ShopBookItem(
        url="https://vaga.lt/book", shop_name="vaga", title="Book", year=2099
    )
    result = pipeline.process_item(item)
    assert ItemAdapter(result).get("year") is None


# --- Text field stripping ---


def test_title_stripped(pipeline):
    item = ShopBookItem(url="https://vaga.lt/book", shop_name="vaga", title="  Book  ")
    result = pipeline.process_item(item)
    assert ItemAdapter(result)["title"] == "Book"


def test_author_whitespace_only_becomes_none(pipeline):
    item = ShopBookItem(
        url="https://vaga.lt/book", shop_name="vaga", title="Book", author="   "
    )
    result = pipeline.process_item(item)
    assert ItemAdapter(result).get("author") is None


# --- URL validation ---


def test_invalid_url_dropped(pipeline):
    item = ShopBookItem(url="not-a-url", shop_name="vaga", title="Book")
    with pytest.raises(DropItem, match="Invalid URL"):
        pipeline.process_item(item)


def test_missing_url_dropped(pipeline):
    item = ShopBookItem(shop_name="vaga", title="Book")
    with pytest.raises(DropItem, match="Invalid URL"):
        pipeline.process_item(item)


# --- Stats tracking ---


def test_invalid_isbn_increments_stat(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p", shop_name="vaga", title="X", isbn="4779054890696"
    )
    pipeline.process_item(item)
    assert stats.values["validation/invalid_isbn"] == 1


def test_invalid_year_increments_stat(pipeline, stats):
    item = ShopBookItem(url="https://vaga.lt/p", shop_name="vaga", title="X", year=20)
    pipeline.process_item(item)
    assert stats.values["validation/invalid_year"] == 1


def test_year_swap_increments_stat(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="X",
        year=216,
        properties={"pages": 2024},
    )
    pipeline.process_item(item)
    assert stats.values["validation/year_pages_swap"] == 1


def test_valid_data_no_stats(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Book",
        isbn="9780306406157",
        year=2024,
        price="9.99",
    )
    pipeline.process_item(item)
    assert stats.values == {}


# --- Issue buffering ---


def test_issues_buffered_with_details(pipeline):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Good Title",
        isbn="4779054890696",
        price="9.99",
    )
    pipeline.process_item(item)
    assert len(pipeline.issues) == 1
    issue = pipeline.issues[0]
    assert issue["url"] == "https://vaga.lt/p"
    assert issue["field"] == "isbn"
    assert issue["issue"] == "invalid_isbn"
    assert issue["raw_value"] == "4779054890696"


def test_drain_issues_clears_buffer(pipeline):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Good Title",
        isbn="BAD",
        price="9.99",
    )
    pipeline.process_item(item)
    issues = pipeline.drain_issues()
    assert len(issues) == 1
    assert pipeline.issues == []


def test_valid_item_no_issues(pipeline):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Book",
        year=2024,
        price="9.99",
    )
    pipeline.process_item(item)
    assert pipeline.issues == []


# --- Price anomaly checks ---


def test_zero_price_flagged(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p", shop_name="vaga", title="Book", price="0.00"
    )
    pipeline.process_item(item)
    assert stats.values.get("validation/zero_price") == 1


def test_missing_price_flagged(pipeline, stats):
    item = ShopBookItem(url="https://vaga.lt/p", shop_name="vaga", title="Book")
    pipeline.process_item(item)
    assert stats.values.get("validation/missing_price") == 1


def test_price_higher_than_original_flagged(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Book",
        price="15.00",
        price_original="10.00",
    )
    pipeline.process_item(item)
    assert stats.values.get("validation/price_higher_than_original") == 1


def test_normal_discount_not_flagged(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Book",
        price="8.00",
        price_original="10.00",
    )
    pipeline.process_item(item)
    assert "validation/price_higher_than_original" not in stats.values


# --- Content quality checks ---


def test_html_in_title_flagged(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Book <b>Title</b>",
        price="5.00",
    )
    pipeline.process_item(item)
    assert stats.values.get("validation/html_in_text") == 1


def test_html_in_description_allowed(pipeline, stats):
    # description intentionally stores sanitised rich HTML, so the
    # html_in_text check must not flag <p>...</p> there.
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Book",
        description="<p>Some text</p>",
        price="5.00",
    )
    pipeline.process_item(item)
    assert stats.values.get("validation/html_in_text") is None


def test_html_in_author_flagged(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Book",
        author="<span>Author</span>",
        price="5.00",
    )
    pipeline.process_item(item)
    assert stats.values.get("validation/html_in_text") == 1


@pytest.mark.parametrize(
    "author",
    [
        "L. Šernienė, M. Puzaitė",
        "Jane Smith; John Doe",
        "Alice & Bob",
        "Foo / Bar",
        "A and B",
        "A ir B",
        "Jane Smith",
    ],
)
def test_multi_author_no_longer_flagged(pipeline, stats, author):
    """multi_author validation was dropped in favour of the split in
    upsert_shop_book (shop_authors + shop_book_authors). The raw string no
    longer produces a validation issue regardless of separator count."""
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Book",
        author=author,
        price="5.00",
    )
    pipeline.process_item(item)
    assert stats.values.get("validation/multi_author") is None


def test_suspicious_title_too_short(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="X",
        price="5.00",
    )
    pipeline.process_item(item)
    assert stats.values.get("validation/suspicious_title") == 1


def test_suspicious_title_too_long(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="A" * 301,
        price="5.00",
    )
    pipeline.process_item(item)
    assert stats.values.get("validation/suspicious_title") == 1


def test_normal_title_not_flagged(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Normal Book Title",
        price="5.00",
    )
    pipeline.process_item(item)
    assert "validation/suspicious_title" not in stats.values


# --- Format consistency checks ---


def test_audiobook_with_pages_flagged(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Book",
        format="audiobook",
        properties={"pages": 200},
        price="5.00",
    )
    pipeline.process_item(item)
    assert stats.values.get("validation/format_mismatch") == 1


def test_book_with_duration_flagged(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Book",
        format="paperback",
        properties={"duration": "3h"},
        price="5.00",
    )
    pipeline.process_item(item)
    assert stats.values.get("validation/format_mismatch") == 1


def test_audiobook_with_duration_not_flagged(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Book",
        format="audiobook",
        properties={"duration": "3h"},
        price="5.00",
    )
    pipeline.process_item(item)
    assert "validation/format_mismatch" not in stats.values


def test_book_with_pages_not_flagged(pipeline, stats):
    item = ShopBookItem(
        url="https://vaga.lt/p",
        shop_name="vaga",
        title="Book",
        format="hardcover",
        properties={"pages": 200},
        price="5.00",
    )
    pipeline.process_item(item)
    assert "validation/format_mismatch" not in stats.values
