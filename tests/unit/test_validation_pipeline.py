import pytest
from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem

from book_scraper.items import ListingItem, PriceItem
from book_scraper.pipelines import ValidationPipeline


@pytest.fixture
def pipeline():
    return ValidationPipeline()


def test_valid_listing_passes(pipeline):
    item = ListingItem(
        url="https://vaga.lt/book", shop_name="vaga", title="Book", price="9.99"
    )
    result = pipeline.process_item(item, spider=None)
    assert ItemAdapter(result)["price"] == "9.99"


def test_listing_without_title_dropped(pipeline):
    item = ListingItem(url="https://vaga.lt/book", shop_name="vaga")
    with pytest.raises(DropItem, match="Missing title"):
        pipeline.process_item(item, spider=None)


def test_invalid_price_dropped(pipeline):
    item = PriceItem(url="https://vaga.lt/book", shop_name="vaga", price="abc")
    with pytest.raises(DropItem, match="Invalid price"):
        pipeline.process_item(item, spider=None)


def test_price_normalized_to_decimal_string(pipeline):
    item = PriceItem(url="https://vaga.lt/book", shop_name="vaga", price="16.32")
    result = pipeline.process_item(item, spider=None)
    assert ItemAdapter(result)["price"] == "16.32"


def test_price_original_normalized(pipeline):
    item = PriceItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        price="10.00",
        price_original="15.50",
    )
    result = pipeline.process_item(item, spider=None)
    assert ItemAdapter(result)["price_original"] == "15.50"


def test_invalid_price_original_set_to_none(pipeline):
    item = PriceItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        price="10.00",
        price_original="invalid",
    )
    result = pipeline.process_item(item, spider=None)
    assert ItemAdapter(result)["price_original"] is None


def test_none_price_passes_through(pipeline):
    item = ListingItem(url="https://vaga.lt/book", shop_name="vaga", title="Book")
    result = pipeline.process_item(item, spider=None)
    assert ItemAdapter(result).get("price") is None


def test_none_price_original_left_alone(pipeline):
    item = ListingItem(
        url="https://vaga.lt/book", shop_name="vaga", title="Book", price="10.00"
    )
    result = pipeline.process_item(item, spider=None)
    assert ItemAdapter(result).get("price_original") is None
