"""Typed configuration models validated with Pydantic."""

from pydantic import BaseModel


class ScrapingConfig(BaseModel):
    download_delay: float = 1.0
    concurrent_requests_per_domain: int = 1
    batch_size: int = 100
    batch_pause: float = 10.0
    max_retries: int = 2
    connect_timeout: float = 5.0
    read_timeout: float = 10.0
    hard_timeout: float = 30.0
    batch_timeout: float = 300.0


class SitemapConfig(BaseModel):
    url: str
    max_age_hours: int = 168


class CategoriesConfig(BaseModel):
    url: str
    max_age_hours: int = 672


class FullCrawlConfig(BaseModel):
    start_url: str


class DiscoverConfig(BaseModel):
    url_include_pattern: str | None = None
    sitemap: SitemapConfig | None = None
    categories: CategoriesConfig | None = None
    full_crawl: FullCrawlConfig | None = None


class ScanConfig(BaseModel):
    rescrape: bool = False


class ShopSection(BaseModel):
    name: str
    base_url: str


class ShopConfig(BaseModel):
    shop: ShopSection
    scraping: ScrapingConfig = ScrapingConfig()
    discover: DiscoverConfig = DiscoverConfig()
    scan: ScanConfig = ScanConfig()


class ScrapyConfig(BaseModel):
    download_delay: float = 1.0
    concurrent_requests_per_domain: int = 1
    robotstxt_obey: bool = True


class DatabaseConfig(BaseModel):
    url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/book_scraper"


class DefaultConfig(BaseModel):
    scrapy: ScrapyConfig = ScrapyConfig()
    database: DatabaseConfig = DatabaseConfig()
