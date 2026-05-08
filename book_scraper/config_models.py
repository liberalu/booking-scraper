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
    # `url` accepts either a single template string OR a list of
    # template strings. Single is the common case (vaga, default
    # humanitas); a list lets a shop walk multiple seed URLs that
    # paginate independently — used by humanitas to combine the
    # `Lithuanian` server-side filter with `Lithuanian-English` so
    # bilingual LT books aren't missed (~1.6 % of the LT catalogue).
    # Each element must contain a `{page}` placeholder; pagination
    # across list entries chains independently from response.url
    # substitution rather than re-formatting from a single template,
    # so each filter walks its own page sequence.
    url: str | list[str]
    max_age_hours: int = 672
    # Safety cap on chained pagination. The discover spider chains
    # page+1 until it sees an empty page; if a CF rate-limit blip or a
    # transient empty response misreads as "end of catalogue" we'd be
    # fine, but the inverse — pagination that quietly *never* ends —
    # would burn FlareSolverr quota indefinitely. None disables the cap
    # (per-CLI `-a max_pages=N` still works); set to a generous integer
    # in the shop TOML to bound runaway runs. The cap applies *per seed
    # URL* — a list of N seeds with max_pages=3 walks up to N×3 pages.
    # Mirrors the `-a max_pages` CLI override that takes precedence
    # when supplied.
    max_pages: int | None = None

    def url_templates(self) -> list[str]:
        """Always return the configured URL(s) as a list for uniform handling."""
        return [self.url] if isinstance(self.url, str) else list(self.url)


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


class IbibliotekaApiConfig(BaseModel):
    """Discovery via the ibiblioteka.lt national library JSON API.

    POST endpoint returning Lithuanian books from LIBIS (the national
    bibliographic catalogue). No auth required. Pagination via
    ``pageStartIndex``; each year-band query returns up to ~10 000 records.

    ``year_from`` / ``year_to`` define the inclusive/exclusive publication
    year window. The spider splits this into per-year bands automatically
    so concurrent_requests_per_domain engages across years.
    """

    year_from: int = 1990
    year_to: int = 2027  # exclusive upper bound
    page_size: int = 100
    max_age_hours: int = 168 * 4  # national library: resync monthly


class DiscoverConfig(BaseModel):
    url_include_pattern: str | None = None
    sitemap: SitemapConfig | None = None
    categories: CategoriesConfig | None = None
    full_crawl: FullCrawlConfig | None = None
    graphql: GraphQLConfig | None = None
    lupasearch: LupaSearchConfig | None = None
    ibiblioteka_api: IbibliotekaApiConfig | None = None


class ScanConfig(BaseModel):
    rescrape: bool = False


class MatchConfig(BaseModel):
    """Per-shop match settings.

    `trust` ranks shops when synthesizing shop_inferred books — the
    highest-trust shop's title/year/format/etc. wins. Publisher is NOT
    trust-ranked: it sticks to the first writer.
    """
    trust: int = 50


class FlaresolverrConfig(BaseModel):
    """Route every request for this shop through a FlareSolverr sidecar.

    FlareSolverr runs a patched Chromium that solves Cloudflare's
    Managed Challenge / Turnstile and returns the rendered HTML +
    `cf_clearance` cookie. Used for shops where the challenge actively
    rejects automated browsers (verified via patchright + real Brave
    on humanitas.lt: cookie jar empty, error variant of the challenge
    page returned). When the block is present, every request for the
    shop goes through FS instead of httpx.

    `endpoint` defaults to the `flaresolverr` Docker service name on
    the compose network; override for local runs against a host-mapped
    port (e.g. ``http://localhost:8191/v1``).

    `session_ttl_minutes` controls how often we destroy and recreate
    the FS session so the underlying Chromium re-mints `cf_clearance`
    before the existing one expires (~30 min wall).
    """

    endpoint: str = "http://flaresolverr:8191/v1"
    max_timeout_ms: int = 120_000
    session_ttl_minutes: int = 25


class ShopSection(BaseModel):
    name: str
    base_url: str


class ShopConfig(BaseModel):
    shop: ShopSection
    scraping: ScrapingConfig = ScrapingConfig()
    discover: DiscoverConfig = DiscoverConfig()
    scan: ScanConfig = ScanConfig()
    match: MatchConfig = MatchConfig()
    flaresolverr: FlaresolverrConfig | None = None
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
