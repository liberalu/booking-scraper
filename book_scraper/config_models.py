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


class GraphQLConfig(BaseModel):
    """Discovery via Magento 2 GraphQL API (for JS-rendered / PWA shops).

    `category_ids` is required and non-empty. The query emits a
    `category_id: { in: [...] }` filter so a single discovery run can
    sweep multiple categories — used by pegasas.lt to scope to the
    Lithuanian-language subtree (~38–45k items) instead of the global
    catalogue (~640k including English drop-shipping).

    `subdivide_factor` / `subdivide_min_page_size` control adaptive
    page-size shrinkage on backend failures: if a request at the
    configured `page_size` returns a 5xx, the spider subdivides the
    failed range into `subdivide_factor` smaller requests at
    `page_size / subdivide_factor` (clamped to `subdivide_min_page_size`).
    Magento's full-page cache misses on deep pages can OOM/503 under
    concurrency=2 + pageSize=50, but pageSize=10 stays cheap.
    """

    category_ids: list[str] = Field(min_length=1)
    page_size: int = 100
    max_age_hours: int = 168
    subdivide_factor: int = 5
    subdivide_min_page_size: int = 5


class LupaSearchConfig(BaseModel):
    """Discovery via the LupaSearch JSON API (third-party search index).

    POST endpoint with a flat product shape including price, stock,
    `is_new`, `is_book`/`is_audio_book`/`is_ebook`, and per-item
    `category_ids`. Lacks ISBN/year/pages — use this for cheap rescans
    and new-arrivals detection, not as the primary metadata source.
    """

    endpoint: str
    category_ids: list[str] = Field(min_length=1)
    page_size: int = 42
    max_age_hours: int = 168
    extra_filters: dict[str, list[str]] | None = None


class DiscoverConfig(BaseModel):
    url_include_pattern: str | None = None
    sitemap: SitemapConfig | None = None
    categories: CategoriesConfig | None = None
    full_crawl: FullCrawlConfig | None = None
    graphql: GraphQLConfig | None = None
    lupasearch: LupaSearchConfig | None = None


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
