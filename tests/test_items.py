import pytest
from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem

from book_scraper.items import ListingItem, PriceItem
from book_scraper.pipelines import ValidationPipeline


@pytest.fixture
def pipeline():
    return ValidationPipeline()


def test_valid_listing_item_passes(pipeline):
    item = ListingItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        shop_title="Test Book",
        price="9.99",
    )
    result = pipeline.process_item(item, spider=None)
    assert ItemAdapter(result)["price"] == "9.99"


def test_listing_item_without_title_dropped(pipeline):
    item = ListingItem(url="https://vaga.lt/book", shop_name="vaga")
    with pytest.raises(DropItem, match="Missing shop_title"):
        pipeline.process_item(item, spider=None)


def test_invalid_price_dropped(pipeline):
    item = PriceItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        price="not_a_number",
    )
    with pytest.raises(DropItem, match="Invalid price"):
        pipeline.process_item(item, spider=None)


def test_lithuanian_price_format(pipeline):
    item = PriceItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        price="16.32",
        price_original="24.39",
    )
    result = pipeline.process_item(item, spider=None)
    adapter = ItemAdapter(result)
    assert adapter["price"] == "16.32"
    assert adapter["price_original"] == "24.39"
