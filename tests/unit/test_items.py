import pytest
from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem

from book_scraper.items import PriceItem, ShopBookItem
from book_scraper.pipelines import ValidationPipeline


@pytest.fixture
def pipeline():
    return ValidationPipeline()


def test_valid_shop_book_item_passes(pipeline):
    item = ShopBookItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        title="Test Book",
        price="9.99",
    )
    result = pipeline.process_item(item)
    assert ItemAdapter(result)["price"] == "9.99"


def test_shop_book_item_without_title_dropped(pipeline):
    item = ShopBookItem(url="https://vaga.lt/book", shop_name="vaga")
    with pytest.raises(DropItem, match="Missing title"):
        pipeline.process_item(item)


def test_invalid_price_dropped(pipeline):
    item = PriceItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        price="not_a_number",
    )
    with pytest.raises(DropItem, match="Invalid price"):
        pipeline.process_item(item)


def test_lithuanian_price_format(pipeline):
    item = PriceItem(
        url="https://vaga.lt/book",
        shop_name="vaga",
        price="16.32",
        price_original="24.39",
    )
    result = pipeline.process_item(item)
    adapter = ItemAdapter(result)
    assert adapter["price"] == "16.32"
    assert adapter["price_original"] == "24.39"
