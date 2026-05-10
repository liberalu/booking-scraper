# Testing Patterns

**Analysis Date:** 2026-05-10

## Test Framework

**Runner:** pytest 9.0+
- Config: `pyproject.toml` under `[tool.pytest.ini_options]`
- `testpaths = ["tests"]`

**Async support:** pytest-asyncio 0.25+

**Coverage:** pytest-cov 7.0+

**Run Commands:**
```bash
uv run pytest -v                              # Run all tests
uv run pytest tests/unit/ -v                  # Unit tests only (no DB)
uv run pytest tests/integration/ -v           # Integration tests only
make coverage                                 # Coverage with term-missing report
uv run pytest --cov=book_scraper --cov-report=html  # HTML coverage report
uv run pytest tests/integration/test_dashboard_routes.py -v  # Smoke test
```

## Test File Organization

**Split:**
- `tests/unit/` — fast, no database, no network
- `tests/integration/` — require real PostgreSQL on port 5433

**Naming:**
- `tests/unit/test_<module>_<submodule>.py` — e.g. `test_vaga_parsers.py`, `test_validation_pipeline.py`
- `tests/integration/test_<feature>.py` — e.g. `test_db_repo.py`, `test_postgres_pipeline.py`

**Fixtures file:** `tests/conftest.py` — shared `engine` and `db_session` fixtures; imported automatically by pytest

**HTML fixtures:**
```
tests/fixtures/
├── vaga_sitemap.xml
├── vaga_category_page.html
├── vaga_product_page.html
├── pegasas_graphql_category.json
├── pegasas_lupasearch_page1.json
├── humanitas/
│   └── index_page.html
├── almalittera/
├── ibiblioteka/
├── knygos/
└── patogupirkti/
```
Loaded via `Path(__file__).parent.parent / "fixtures"` — absolute path resolution relative to the test file.

## Test Structure

**Suite Organization:**

Unit tests use a mix of top-level functions and class groupings:
```python
# Class grouping (used for larger test suites)
class TestDiscoverSpiderInit:
    def test_requires_shop_arg(self): ...
    def test_requires_valid_strategy(self): ...
    def test_creates_with_valid_args(self): ...

# Top-level functions (common for simple/focused tests)
def test_parse_sitemap_urls():
    ...
def test_parse_category_page():
    ...
```

Integration tests group by feature class:
```python
@pytest.mark.integration
class TestPostgresPipelineShopBooks:
    def test_process_shop_book_item_creates_shop_book_and_price(self, pipeline, db_session): ...
```

**Fixture pattern (unit tests):**
```python
@pytest.fixture
def pipeline():
    return ValidationPipeline()

def test_valid_shop_book_passes(pipeline):
    item = ShopBookItem(url="https://vaga.lt/book", shop_name="vaga", title="Book", price="9.99")
    result = pipeline.process_item(item)
    assert ItemAdapter(result)["price"] == "9.99"
```

**Parametrize pattern:**
```python
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("HTTPS://Vaga.LT/Book", "https://vaga.lt/Book"),
        ("https://vaga.lt/book#section", "https://vaga.lt/book"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected
```

## Database Fixture (Integration)

**Session isolation strategy:** SAVEPOINT-nested-transaction pattern in `tests/conftest.py`:

```python
@pytest.fixture(scope="session")
def engine():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()

@pytest.fixture()
def db_session(engine):
    """Rollback-isolated session using the SAVEPOINT-nested-transaction pattern.
    
    session.commit() inside a test only releases a SAVEPOINT — the
    outer transaction stays open and is rolled back at teardown.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()
```

- `engine` fixture is `scope="session"` — created once, schema built/torn down once
- `db_session` fixture is function-scoped — new rollback-isolated session per test
- `session.commit()` inside tests releases the SAVEPOINT but does NOT commit the outer transaction
- Tests that need back-to-back commits in one test work because each commit releases one SAVEPOINT and the SAVEPOINT listener auto-restarts a fresh one

**Test DB URL:** `postgresql+psycopg2://postgres:postgres@localhost:5433/book_scraper_test`

Referenced as `tests.conftest.TEST_DATABASE_URL` for tests that need to construct their own connections.

## Mocking

**Framework:** `unittest.mock` from stdlib — `MagicMock` and `patch`

**Patterns:**

Mock external dependencies (Scrapy crawler, reactor, DB engine) — not internal business logic:
```python
from unittest.mock import MagicMock, patch

@pytest.fixture
def crawler() -> MagicMock:
    c = MagicMock()
    c.settings.getfloat.return_value = 0
    c.settings.getint.return_value = 0
    c.spider = MagicMock(_run_id=None)
    return c

def test_in_flight_requests_suppress_stall(crawler: MagicMock) -> None:
    ext = StallDetector(crawler, stall_timeout=1.0)
    ext._last_activity -= 2.0
    with patch("twisted.internet.reactor", create=True) as mock_reactor:
        mock_reactor.callLater = MagicMock()
        ext._check_stall()
        crawler.engine.close_spider.assert_not_called()
```

Patching `create_engine` to inspect call arguments without spinning up a real connection:
```python
def test_engine_has_fail_fast_connect_args():
    captured: dict = {}
    def capture(url, **kwargs):
        captured.update(kwargs)
        return MagicMock()
    with patch("book_scraper.db.session.create_engine", side_effect=capture):
        get_engine(TEST_DATABASE_URL)
    connect_args = captured.get("connect_args", {})
    assert connect_args.get("connect_timeout") == 5
```

**What to mock:**
- Scrapy `Crawler` and `Settings` objects (too complex to instantiate)
- `twisted.internet.reactor` in extension tests
- File system paths when testing config loading with `tmp_path`
- `create_engine` when testing connection argument configuration

**What NOT to mock:**
- The database itself — integration tests use real PostgreSQL (test DB on port 5433)
- Parser functions — tested directly against HTML/JSON fixtures
- `ValidationPipeline` or `PostgresPipeline` — instantiated directly in tests

## Fixtures and Factories

**HTML/JSON test data:** Stored in `tests/fixtures/` as real HTML/JSON snapshots from live sites:
```python
FIXTURES = Path(__file__).parent.parent / "fixtures"

def test_parse_category_page():
    html = (FIXTURES / "vaga_category_page.html").read_text()
    result = parse_category_page(html)
    ...
```

**Pytest fixtures for parsers:**
```python
@pytest.fixture
def graphql_text() -> str:
    return (FIXTURES / "pegasas_graphql_category.json").read_text()

@pytest.fixture
def lupasearch_text() -> str:
    return (FIXTURES / "pegasas_lupasearch_page1.json").read_text()
```

**Inline HTML for targeted unit tests:** When testing a specific parser behavior, construct minimal HTML inline rather than using full fixtures:
```python
def test_parse_product_page_price_new_special_overrides_jsonld():
    ld = '{"@type":"Book","name":"X","sku":"1","offers":{"price":"26.14",...}}'
    html_doc = (
        '<html><body><script type="application/ld+json">' + ld + '</script>'
        '<div class="product-price-wrapper prices">'
        '<span class="price-new special"> 15,80€ </span></div>'
        "</body></html>"
    )
    data = parse_product_page(html_doc)
    assert data["price"] == "15.80"
```

**Fake objects for unit tests:**
```python
class FakeStats:
    def __init__(self):
        self.values = {}
    def inc_value(self, key: str) -> None:
        self.values[key] = self.values.get(key, 0) + 1
```

**SimpleNamespace for config stubs:**
```python
def _config(sitemap_url="https://vaga.lt/sitemap.xml", ...):
    return SimpleNamespace(
        discover=SimpleNamespace(
            sitemap=SimpleNamespace(url=sitemap_url),
            ...
        )
    )
```

**Pipeline fixture pattern (integration):**
```python
@pytest.fixture
def pipeline(engine, db_session):
    p = PostgresPipeline(database_url=TEST_DATABASE_URL)
    p.session = db_session  # inject the rollback-isolated session
    p.shop_cache = {}
    return p
```

## Coverage

**Requirements:** No enforced minimum, but Scrapy lifecycle methods exempt via `# pragma: no cover`

**Exclude patterns (from `pyproject.toml`):**
```toml
[tool.coverage.report]
show_missing = true
exclude_lines = [
    "if __name__",
    "pragma: no cover",
]
```

**Exempt modules:** `flaresolverr_middleware.py`, `download_handler.py`, `middlewares.py`, `extensions.py` — entire files or class bodies marked `# pragma: no cover` because Scrapy/Twisted lifecycle cannot be unit tested without the full reactor

**View Coverage:**
```bash
make coverage                                      # terminal report with missing lines
uv run pytest --cov=book_scraper --cov-report=html # HTML report in htmlcov/
```

## Test Types

**Unit Tests (`tests/unit/`):**
- Scope: Single module or function, no DB, no network
- Parser tests: Load HTML/JSON fixtures from `tests/fixtures/`, call parser function, assert result dict
- Pipeline tests: Instantiate `ValidationPipeline` directly, pass `ShopBookItem`/`PriceItem`, assert raises or field values
- Spider tests: Build fake Scrapy responses using `scrapy.http.HtmlResponse` with `Request`, call spider methods, assert yielded items/requests
- Config tests: Load real TOML files or patch `CONFIG_DIR`, validate `ShopConfig` and `DefaultConfig`

**Integration Tests (`tests/integration/`):**
- Scope: Real PostgreSQL at `localhost:5433`, full pipeline or service layer
- DB repo tests: Call repo functions with `db_session` fixture, assert model state
- Pipeline tests: Wire `PostgresPipeline` to `db_session`, process items, query DB to verify rows
- Service tests: Call `DiscoverService`/`ScanService`/`MatchService`, assert `scrape_runs`/`scrape_url_items` rows
- Dashboard tests: FastAPI `TestClient`, assert HTTP status and response body
- Lifecycle tests: Simulate stall/resume/retry scenarios using real DB state

**Optional E2E Tests:**
- `tests/integration/test_humanitas_flaresolverr.py` — hits real FlareSolverr + humanitas.lt
- Opt-in via environment variable: `RUN_FLARESOLVERR_TESTS=1`
- Skipped by default with `pytest.mark.skipif(os.environ.get("RUN_FLARESOLVERR_TESTS") != "1", ...)`

## Common Patterns

**Async Spider Testing:**
```python
import asyncio

async def _collect_async(async_gen):
    """Collect all items from an async generator."""
    return [item async for item in async_gen]

def test_start_yields_sitemap_url():
    spider = DiscoverSpider(shop="vaga", strategy="sitemap")
    requests = asyncio.run(_collect_async(spider.start()))
    assert len(requests) == 1
    assert "sitemap" in requests[0].url
```

**Fake Scrapy Response:**
```python
def _fake_response(url: str, body: str, cls=HtmlResponse, meta=None):
    """Build a fake Scrapy response with optional request meta."""
    request = Request(url=url, meta=meta or {})
    return cls(url=url, body=body, encoding="utf-8", request=request)
```

**Error Testing with DropItem:**
```python
def test_shop_book_item_without_title_dropped(pipeline):
    item = ShopBookItem(url="https://vaga.lt/book", shop_name="vaga")
    with pytest.raises(DropItem, match="Missing title"):
        pipeline.process_item(item)
```

**Integration test with DB assertion:**
```python
def test_upsert_shop_book_creates_new(db_session):
    shop = upsert_shop(db_session, name="vaga", base_url="https://vaga.lt")
    shop_book, *_ = upsert_shop_book(
        db_session,
        shop_id=shop.id,
        url="https://vaga.lt/test-book",
        title="Test Book",
    )
    assert shop_book.id is not None
    assert shop_book.match_status == "unmatched"
```

**Pytest markers:**
- `@pytest.mark.integration` — marks integration test classes/functions (requires DB)
- `@pytest.mark.skipif(condition, reason=...)` — opt-in external-service tests

## Test Data Guidelines

- Use `vaga` as the default shop name in unit tests (it has all three strategies configured)
- Use URL `https://vaga.lt/book` as the canonical dummy product URL
- Use `"vaga.lt/test-book"` patterns for unique URLs in integration tests to avoid conflicts
- Publisher `"Šviesa"` and shop `"vaga"` are shared across tests — the SAVEPOINT isolation prevents conflicts but be aware of the coupling
- Prices are stored/compared as `Decimal` in the DB and as decimal strings (`"9.99"`) in items

---

*Testing analysis: 2026-05-10*
