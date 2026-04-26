"""Typed configuration models validated with Pydantic."""

from pydantic import BaseModel, Field


class AttributeRule(BaseModel):
    """Optional per-key validation rule.

    `enum` restricts values to a fixed set. `pattern` is a regex the
    value must fully match. Both are optional and, if both given, both
    are enforced.
    """

    enum: list[str] | None = None
    pattern: str | None = None


class AttributesConfig(BaseModel):
    """Per-shop attribute schema.

    When present, every attribute key scraped from a shop_book must be in
    `allowed_keys`; unknown keys fire a validation issue. Individual
    keys can further restrict their values with `enum` or `pattern`.
    When the whole section is omitted the feature is opt-out — all
    attributes pass through unchecked.
    """

    allowed_keys: list[str] = Field(default_factory=list)
    rules: dict[str, AttributeRule] = Field(default_factory=dict)

    @classmethod
    def from_toml(cls, data: dict[str, object]) -> "AttributesConfig":
        """Split the flat TOML form `{allowed_keys, format={enum=..}, ..}`
        into the structured `{allowed_keys, rules}` shape the pipeline
        uses. TOML subtables under `[attributes.X]` arrive as sibling
        keys in the parent dict.
        """
        allowed = data.get("allowed_keys") or []
        rules: dict[str, AttributeRule] = {}
        for key, value in data.items():
            if key == "allowed_keys":
                continue
            if isinstance(value, dict):
                rules[key] = AttributeRule.model_validate(value)
        assert isinstance(allowed, list)
        return cls(allowed_keys=[str(k) for k in allowed], rules=rules)


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
    # Tear down + recreate the httpx.AsyncClient every N requests to
    # bound TIME_WAIT pile-up (client side) and cumulative connection
    # tracking (server side). vaga.lt walls at ~100; 80 is a safe
    # default below that. Tune per shop via [scraping] in the TOML.
    httpx_client_reset_after_requests: int = 80


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
    attributes: AttributesConfig | None = None


class ScrapyConfig(BaseModel):
    download_delay: float = 1.0
    concurrent_requests_per_domain: int = 1
    robotstxt_obey: bool = True


class DatabaseConfig(BaseModel):
    url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/book_scraper"


class DefaultConfig(BaseModel):
    scrapy: ScrapyConfig = ScrapyConfig()
    database: DatabaseConfig = DatabaseConfig()
