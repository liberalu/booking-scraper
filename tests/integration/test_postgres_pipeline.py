"""Integration tests for PostgresPipeline — hits real PostgreSQL."""

import pytest

from book_scraper.db.models import Price, ShopBook
from book_scraper.items import DiscoveredUrlItem, PriceItem, ShopBookItem
from book_scraper.pipelines import PostgresPipeline

TEST_DATABASE_URL = (
    "postgresql+psycopg2://postgres:postgres@localhost:5433/book_scraper_test"
)


@pytest.fixture
def pipeline(engine, db_session):
    p = PostgresPipeline(database_url=TEST_DATABASE_URL)
    p.session = db_session
    p.shop_cache = {}
    return p


@pytest.mark.integration
class TestPostgresPipelineShopBooks:
    def test_process_shop_book_item_creates_shop_book_and_price(
        self, pipeline, db_session
    ):
        item = ShopBookItem(
            url="https://vaga.lt/test-book",
            shop_name="vaga",
            title="Test Book",
            author="Author Name",
            isbn="9781234567890",
            price="12.99",
            price_original="19.99",
            in_stock=True,
        )
        result = pipeline.process_item(item)
        assert result is item

        shop_book = (
            db_session.query(ShopBook)
            .filter_by(url="https://vaga.lt/test-book")
            .first()
        )
        assert shop_book is not None
        assert shop_book.title == "Test Book"

        prices = db_session.query(Price).filter_by(shop_book_id=shop_book.id).all()
        assert len(prices) == 1
        assert str(prices[0].price) == "12.99"

    def test_process_shop_book_without_price_skips_price_insert(
        self, pipeline, db_session
    ):
        item = ShopBookItem(
            url="https://vaga.lt/no-price-book",
            shop_name="vaga",
            title="No Price Book",
        )
        pipeline.process_item(item)

        shop_book = (
            db_session.query(ShopBook)
            .filter_by(url="https://vaga.lt/no-price-book")
            .first()
        )
        assert shop_book is not None

        prices = db_session.query(Price).filter_by(shop_book_id=shop_book.id).all()
        assert len(prices) == 0

    def test_year_conversion_valid(self, pipeline, db_session):
        item = ShopBookItem(
            url="https://vaga.lt/year-book",
            shop_name="vaga",
            title="Year Book",
            year="2024",
        )
        pipeline.process_item(item)

        shop_book = (
            db_session.query(ShopBook)
            .filter_by(url="https://vaga.lt/year-book")
            .first()
        )
        assert shop_book.year == 2024

    def test_year_conversion_invalid(self, pipeline, db_session):
        item = ShopBookItem(
            url="https://vaga.lt/bad-year",
            shop_name="vaga",
            title="Bad Year",
            year="not-a-year",
        )
        pipeline.process_item(item)

        shop_book = (
            db_session.query(ShopBook).filter_by(url="https://vaga.lt/bad-year").first()
        )
        assert shop_book.year is None


@pytest.mark.integration
class TestPostgresPipelinePrices:
    def test_process_price_item(self, pipeline, db_session):
        item = PriceItem(
            url="https://vaga.lt/price-book",
            shop_name="vaga",
            title="Price Book",
            price="8.50",
            in_stock=True,
        )
        pipeline.process_item(item)

        shop_book = (
            db_session.query(ShopBook)
            .filter_by(url="https://vaga.lt/price-book")
            .first()
        )
        assert shop_book is not None

        prices = db_session.query(Price).filter_by(shop_book_id=shop_book.id).all()
        assert len(prices) == 1
        assert str(prices[0].price) == "8.50"


@pytest.mark.integration
class TestPostgresPipelineDiscoveredUrls:
    def test_process_discovered_url_item(self, pipeline, db_session):
        item = DiscoveredUrlItem(
            url="https://vaga.lt/new-book",
            shop_name="vaga",
            source="sitemap",
        )
        result = pipeline.process_item(item)
        assert result is item


@pytest.mark.integration
class TestPostgresPipelineShopCache:
    def test_shop_cached_after_first_lookup(self, pipeline, db_session):
        item = PriceItem(
            url="https://vaga.lt/cache-test",
            shop_name="vaga",
            price="1.00",
            in_stock=True,
        )
        pipeline.process_item(item)
        assert "vaga" in pipeline.shop_cache
