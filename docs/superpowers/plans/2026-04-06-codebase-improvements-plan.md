# Codebase Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix scan resume/revisit semantics, introduce typed config models, consolidate the dual scan execution paths, and add pre-commit/CI/dependency-audit tooling.

**Architecture:** Add `--rescrape` flag to the scan spider so it can optionally revisit already-known product URLs. Replace raw dict config access with Pydantic `ShopConfig` / `DefaultConfig` models validated at load time. Remove the standalone httpx `run_scan.py` script (Scrapy spider is the canonical path). Add `.pre-commit-config.yaml`, GitHub Actions CI, and `deptry`/`pip-audit` dev deps.

**Tech Stack:** Python 3.12, Scrapy, Pydantic v2, SQLAlchemy 2.0, PostgreSQL, uv, ruff, mypy, pytest, GitHub Actions, pre-commit

---

## File Structure

### New files
- `book_scraper/config_models.py` — Pydantic models: `ScrapingConfig`, `SitemapConfig`, `CategoriesConfig`, `FullCrawlConfig`, `DiscoverConfig`, `ScanConfig`, `ShopSection`, `ShopConfig`, `ScrapyConfig`, `DatabaseConfig`, `DefaultConfig`
- `.pre-commit-config.yaml` — pre-commit hooks (ruff, mypy)
- `.github/workflows/ci.yml` — GitHub Actions: lint + test with PostgreSQL service

### Modified files
- `book_scraper/config.py` — return typed models instead of raw dicts
- `book_scraper/spiders/scan.py` — accept `rescrape` arg, pass to service
- `book_scraper/services/scan.py` — `prepare_scan()` gains `rescrape: bool` param, skips `get_urls_already_scraped` filter when True
- `book_scraper/spiders/discover.py` — consume `ShopConfig` model instead of raw dict
- `book_scraper/settings.py` — use `DefaultConfig` model
- `pyproject.toml` — add `deptry`, `pip-audit`, `pre-commit` to dev deps; pin `requires-python = ">=3.12,<3.14"`
- `Makefile` — add `audit` and `deps` targets
- `config/shops/vaga.toml` — add `[scan]` section with `rescrape = false`
- `config/default.toml` — no changes needed (already valid)
- `tests/unit/test_config.py` — test typed model loading
- `tests/unit/test_config_models.py` (new) — test Pydantic models in isolation
- `tests/integration/test_scan_service.py` — add rescrape=True test case

### Deleted files
- `book_scraper/scripts/run_scan.py` — standalone httpx scanner (duplicates Scrapy spider)

---

## Task 1: Fix Scan Resume/Rescrape Semantics

### Task 1a: Add `rescrape` parameter to ScanService

**Files:**
- Modify: `book_scraper/services/scan.py`
- Test: `tests/integration/test_scan_service.py`

- [ ] **Step 1: Write the failing test for rescrape=True**

Add to `tests/integration/test_scan_service.py`:

```python
def test_rescrape_includes_already_done_urls(self, db_session):
    shop = upsert_shop(db_session, name="rescrape_shop", base_url="https://rs.lt")
    url1 = upsert_discovered_url(db_session, shop.id, "https://rs.lt/book-1", "sitemap")
    upsert_discovered_url(db_session, shop.id, "https://rs.lt/book-2", "sitemap")

    # Mark book-1 as already scraped
    update_discovered_url_status(
        db_session, url_id=url1.id, http_status=200, url_type="product"
    )
    db_session.flush()

    service = ScanService(db_session)
    plan = service.prepare_scan("rescrape_shop", "https://rs.lt", {}, rescrape=True)

    urls = [u.url for u in plan.urls_to_scrape]
    assert "https://rs.lt/book-1" in urls
    assert "https://rs.lt/book-2" in urls
    assert plan.urls_skipped == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_scan_service.py::TestScanServicePrepareScan::test_rescrape_includes_already_done_urls -v`
Expected: FAIL — `prepare_scan()` doesn't accept `rescrape` param

- [ ] **Step 3: Implement rescrape parameter in ScanService**

Edit `book_scraper/services/scan.py` — add `rescrape: bool = False` param to `prepare_scan()`:

```python
def prepare_scan(
    self,
    shop_name: str,
    base_url: str,
    shop_config: dict[str, Any],
    rescrape: bool = False,
) -> ScanPlan:
    """Prepare a scan run: upsert shop, mark stale, check freshness,
    load pending URLs, filter already done, create run."""
    shop = upsert_shop(self.session, shop_name, base_url)

    mark_stale_runs_failed(self.session, shop.id, "scan")

    discover_config = shop_config.get("discover", {})
    warnings = check_discover_freshness(
        self.session, shop.id, shop_name, discover_config
    )

    pending_urls = get_pending_scan_urls(self.session, shop.id)

    if rescrape:
        urls_to_scrape = pending_urls
        urls_skipped = 0
    else:
        already_done = get_urls_already_scraped(self.session, shop.id)
        urls_to_scrape = [u for u in pending_urls if u.url not in already_done]
        urls_skipped = len(pending_urls) - len(urls_to_scrape)

    run = create_scrape_run(
        self.session, shop.id, "scan", urls_total=len(urls_to_scrape)
    )
    self.session.commit()

    return ScanPlan(
        run_id=run.id,
        urls_to_scrape=urls_to_scrape,
        urls_skipped=urls_skipped,
        freshness_warnings=warnings,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/integration/test_scan_service.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add book_scraper/services/scan.py tests/integration/test_scan_service.py
git commit -m "$(cat <<'EOF'
feat: add rescrape parameter to ScanService.prepare_scan

When rescrape=True, skip the already-scraped filter so all pending
URLs are re-scraped. Default remains False (resume semantics).
EOF
)"
```

### Task 1b: Wire `rescrape` flag into ScanSpider

**Files:**
- Modify: `book_scraper/spiders/scan.py`
- Modify: `config/shops/vaga.toml`

- [ ] **Step 1: Add `-a rescrape=true` argument to ScanSpider**

Edit `book_scraper/spiders/scan.py` — in `__init__`, add:

```python
def __init__(self, shop: str | None = None, rescrape: str = "false", **kwargs: Any):
    super().__init__(**kwargs)
    if not shop:
        raise ValueError("Missing required argument: shop (e.g., -a shop=vaga)")
    self.shop_name = shop
    self._rescrape = rescrape.lower() in ("true", "1", "yes")
    # ... rest unchanged
```

In the `start()` method, pass to `prepare_scan`:

```python
plan = service.prepare_scan(
    self.shop_name,
    self.conf["shop"]["base_url"],
    self.conf,
    rescrape=self._rescrape,
)
```

- [ ] **Step 2: Run existing tests to verify nothing breaks**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add book_scraper/spiders/scan.py
git commit -m "$(cat <<'EOF'
feat: add -a rescrape=true flag to scan spider

Usage: scrapy crawl scan -a shop=vaga -a rescrape=true
Passes through to ScanService.prepare_scan to skip already-scraped filter.
EOF
)"
```

---

## Task 2: Typed Config Layer (Pydantic Models)

### Task 2a: Create Pydantic config models

**Files:**
- Create: `book_scraper/config_models.py`
- Create: `tests/unit/test_config_models.py`

- [ ] **Step 1: Write tests for config models**

Create `tests/unit/test_config_models.py`:

```python
"""Unit tests for typed config models."""

import pytest

from book_scraper.config_models import (
    DefaultConfig,
    ShopConfig,
)


class TestShopConfig:
    def test_minimal_config(self):
        data = {
            "shop": {"name": "test", "base_url": "https://test.lt"},
        }
        config = ShopConfig.model_validate(data)
        assert config.shop.name == "test"
        assert config.shop.base_url == "https://test.lt"
        assert config.scraping.batch_size == 100  # default
        assert config.scraping.download_delay == 1.0  # default

    def test_full_vaga_config(self):
        data = {
            "shop": {"name": "vaga", "base_url": "https://vaga.lt"},
            "scraping": {
                "download_delay": 0.2,
                "concurrent_requests_per_domain": 8,
                "batch_size": 100,
                "batch_pause": 15,
                "max_retries": 2,
                "connect_timeout": 5,
                "read_timeout": 10,
                "hard_timeout": 30,
                "batch_timeout": 300,
            },
            "discover": {
                "sitemap": {
                    "url": "https://vaga.lt/sitemap.xml",
                    "max_age_hours": 168,
                },
                "categories": {
                    "url": "https://vaga.lt/knygos?limit=100&page={page}",
                    "max_age_hours": 672,
                },
                "full_crawl": {"start_url": "https://vaga.lt"},
            },
        }
        config = ShopConfig.model_validate(data)
        assert config.scraping.download_delay == 0.2
        assert config.scraping.concurrent_requests_per_domain == 8
        assert config.discover.sitemap is not None
        assert config.discover.sitemap.url == "https://vaga.lt/sitemap.xml"
        assert config.discover.categories is not None
        assert config.discover.categories.max_age_hours == 672
        assert config.discover.full_crawl is not None
        assert config.discover.full_crawl.start_url == "https://vaga.lt"

    def test_invalid_config_missing_shop(self):
        with pytest.raises(Exception):
            ShopConfig.model_validate({"scraping": {}})

    def test_url_include_pattern(self):
        data = {
            "shop": {"name": "test", "base_url": "https://test.lt"},
            "discover": {
                "url_include_pattern": r"^https://test\.lt/[a-z]+-\d+$",
            },
        }
        config = ShopConfig.model_validate(data)
        assert config.discover.url_include_pattern is not None


class TestDefaultConfig:
    def test_minimal(self):
        data = {
            "scrapy": {"robotstxt_obey": True},
            "database": {"url": "postgresql+asyncpg://localhost/test"},
        }
        config = DefaultConfig.model_validate(data)
        assert config.scrapy.robotstxt_obey is True
        assert config.database.url == "postgresql+asyncpg://localhost/test"

    def test_defaults(self):
        config = DefaultConfig.model_validate({})
        assert config.scrapy.robotstxt_obey is True
        assert config.scrapy.download_delay == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config_models.py -v`
Expected: FAIL — `config_models` module doesn't exist

- [ ] **Step 3: Implement config models**

Create `book_scraper/config_models.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_config_models.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add book_scraper/config_models.py tests/unit/test_config_models.py
git commit -m "$(cat <<'EOF'
feat: add typed Pydantic config models

ShopConfig and DefaultConfig replace raw dict access with validated,
typed configuration. All fields have sensible defaults matching the
existing TOML values.
EOF
)"
```

### Task 2b: Wire typed config into loading functions

**Files:**
- Modify: `book_scraper/config.py`
- Modify: `tests/unit/test_config.py`

- [ ] **Step 1: Update tests to expect typed models**

Edit `tests/unit/test_config.py`:

```python
from book_scraper.config import CONFIG_DIR, load_default_config, load_shop_config
from book_scraper.config_models import DefaultConfig, ShopConfig


def test_load_default_config():
    config = load_default_config()
    assert isinstance(config, DefaultConfig)
    assert config.scrapy.robotstxt_obey is True
    assert config.database.url is not None


def test_load_default_config_missing_file(tmp_path):
    from unittest.mock import patch

    with patch("book_scraper.config.CONFIG_DIR", tmp_path / "nonexistent"):
        result = load_default_config()
        assert isinstance(result, DefaultConfig)
        # Returns defaults when file missing
        assert result.scrapy.robotstxt_obey is True


def test_load_shop_config():
    config = load_shop_config("vaga")
    assert isinstance(config, ShopConfig)
    assert config.shop.name == "vaga"
    assert config.scraping.batch_size == 100
    assert config.discover.sitemap is not None


def test_load_shop_config_missing_shop():
    with pytest.raises(FileNotFoundError):
        load_shop_config("nonexistent_shop")


def test_config_dir_points_to_config():
    assert CONFIG_DIR.name == "config"
    assert (CONFIG_DIR / "default.toml").exists()
```

Add `import pytest` at the top.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: FAIL — load functions still return dicts

- [ ] **Step 3: Update config.py to return typed models**

Replace `book_scraper/config.py`:

```python
import tomllib
from pathlib import Path

from book_scraper.config_models import DefaultConfig, ShopConfig

CONFIG_DIR = Path(__file__).parent.parent / "config"


def load_default_config() -> DefaultConfig:
    path = CONFIG_DIR / "default.toml"
    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return DefaultConfig.model_validate(data)
    return DefaultConfig()


def load_shop_config(shop_name: str) -> ShopConfig:
    path = CONFIG_DIR / "shops" / f"{shop_name}.toml"
    if not path.exists():
        raise FileNotFoundError(f"Shop config not found: {path}")
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return ShopConfig.model_validate(data)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add book_scraper/config.py tests/unit/test_config.py
git commit -m "$(cat <<'EOF'
refactor: config loaders return typed Pydantic models

load_default_config() returns DefaultConfig, load_shop_config() returns
ShopConfig. Missing shop config now raises FileNotFoundError instead of
returning empty dict.
EOF
)"
```

### Task 2c: Migrate spiders to use typed config

**Files:**
- Modify: `book_scraper/spiders/scan.py`
- Modify: `book_scraper/spiders/discover.py`
- Modify: `book_scraper/settings.py`
- Modify: `book_scraper/services/scan.py`

- [ ] **Step 1: Update ScanSpider to use ShopConfig attributes**

Edit `book_scraper/spiders/scan.py`:

Replace dict access patterns. The `__init__` becomes:

```python
def __init__(self, shop: str | None = None, rescrape: str = "false", **kwargs: Any):
    super().__init__(**kwargs)
    if not shop:
        raise ValueError("Missing required argument: shop (e.g., -a shop=vaga)")
    self.shop_name = shop
    self._rescrape = rescrape.lower() in ("true", "1", "yes")
    self.conf = load_shop_config(shop)
    self.parsers = load_parsers(shop)
    self.allowed_domains = [
        self.conf.shop.base_url.replace("https://", "").replace("http://", "")
    ]

    self._batch_size: int = self.conf.scraping.batch_size
    self._batch_pause: float = self.conf.scraping.batch_pause
    # ... rest of __init__ unchanged
```

In `start()`, update the `prepare_scan` call:

```python
plan = service.prepare_scan(
    self.shop_name,
    self.conf.shop.base_url,
    self.conf,
    rescrape=self._rescrape,
)
```

- [ ] **Step 2: Update DiscoverSpider to use ShopConfig attributes**

Edit `book_scraper/spiders/discover.py`:

```python
def __init__(
    self, shop: str | None = None, strategy: str = "sitemap", **kwargs: Any
):
    super().__init__(**kwargs)
    if not shop:
        raise ValueError("Missing required argument: shop (e.g., -a shop=vaga)")
    self.shop_name = shop
    self.strategy = strategy
    self.conf = load_shop_config(shop)
    self.parsers = load_parsers(shop)
    self.allowed_domains = [
        self.conf.shop.base_url.replace("https://", "").replace("http://", "")
    ]

    # Load URL filter pattern
    pattern = self.conf.discover.url_include_pattern
    self.url_pattern: re.Pattern[str] | None = (
        re.compile(pattern) if pattern else None
    )

    # Load strategy-specific config
    strategy_obj = getattr(self.conf.discover, strategy, None)
    if strategy_obj is None:
        raise ValueError(f"Strategy '{strategy}' not configured for shop '{shop}'")
    self.strategy_conf = strategy_obj
```

Update method bodies that access strategy_conf. In `start()`:

```python
if self.strategy == "sitemap":
    yield scrapy.Request(
        self.strategy_conf.url,
        callback=self.parse_sitemap,
        errback=self.handle_error,
    )
elif self.strategy == "categories":
    url = self.strategy_conf.url.format(page=1)
    yield scrapy.Request(
        url,
        callback=self.parse_categories,
        errback=self.handle_error,
        meta={"page": 1},
    )
elif self.strategy == "full_crawl":
    yield scrapy.Request(
        self.strategy_conf.start_url,
        callback=self.parse_full_crawl,
        errback=self.handle_error,
    )
```

In `parse_categories`, the pagination URL:

```python
next_url = self.strategy_conf.url.format(page=page)
```

In `parse_categories` and `parse_full_crawl`, base_url access:

```python
base_url: str = self.conf.shop.base_url
```

- [ ] **Step 3: Update ScanService to accept ShopConfig**

Edit `book_scraper/services/scan.py` — change `shop_config` param type:

```python
from book_scraper.config_models import ShopConfig

class ScanService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def prepare_scan(
        self,
        shop_name: str,
        base_url: str,
        shop_config: ShopConfig | dict[str, Any],
        rescrape: bool = False,
    ) -> ScanPlan:
        shop = upsert_shop(self.session, shop_name, base_url)
        mark_stale_runs_failed(self.session, shop.id, "scan")

        # Support both typed and dict config for backward compat in tests
        if isinstance(shop_config, dict):
            discover_config = shop_config.get("discover", {})
        else:
            discover_config = shop_config.discover
        warnings = check_discover_freshness(
            self.session, shop.id, shop_name, discover_config
        )

        pending_urls = get_pending_scan_urls(self.session, shop.id)

        if rescrape:
            urls_to_scrape = pending_urls
            urls_skipped = 0
        else:
            already_done = get_urls_already_scraped(self.session, shop.id)
            urls_to_scrape = [u for u in pending_urls if u.url not in already_done]
            urls_skipped = len(pending_urls) - len(urls_to_scrape)

        run = create_scrape_run(
            self.session, shop.id, "scan", urls_total=len(urls_to_scrape)
        )
        self.session.commit()

        return ScanPlan(
            run_id=run.id,
            urls_to_scrape=urls_to_scrape,
            urls_skipped=urls_skipped,
            freshness_warnings=warnings,
        )
```

Note: `check_discover_freshness` in repo.py currently expects a dict. We need to update it too — or keep the `if isinstance` check. Since `check_discover_freshness` iterates over strategy names, and `DiscoverConfig` is a Pydantic model, update it:

Edit `book_scraper/db/repo.py` — the `check_discover_freshness` function needs to handle both `DiscoverConfig` and dict. The simplest change: if it's a Pydantic model, convert to dict:

```python
def check_discover_freshness(
    session: Session,
    shop_id: int,
    shop_name: str,
    discover_config: Any,
) -> list[str]:
    # Normalize to dict for iteration
    if hasattr(discover_config, "model_dump"):
        config_dict = discover_config.model_dump(exclude_none=True)
    elif isinstance(discover_config, dict):
        config_dict = discover_config
    else:
        config_dict = {}
    # ... rest uses config_dict instead of discover_config
```

- [ ] **Step 4: Update settings.py to use DefaultConfig**

Edit `book_scraper/settings.py` — replace dict access:

```python
from book_scraper.config import load_default_config  # pragma: no cover

_config = load_default_config()  # pragma: no cover

BOT_NAME = "book_scraper"  # pragma: no cover
SPIDER_MODULES = ["book_scraper.spiders"]  # pragma: no cover
NEWSPIDER_MODULE = "book_scraper.spiders"  # pragma: no cover
TWISTED_REACTOR = (  # pragma: no cover
    "twisted.internet.asyncioreactor.AsyncioSelectorReactor"  # pragma: no cover
)  # pragma: no cover

ROBOTSTXT_OBEY = _config.scrapy.robotstxt_obey  # pragma: no cover
# ... (other settings unchanged)
DATABASE_URL = _config.database.url  # pragma: no cover
```

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS

- [ ] **Step 6: Run lint and type check**

Run: `uv run ruff check book_scraper/ tests/ && uv run mypy book_scraper/`
Expected: PASS (fix any issues)

- [ ] **Step 7: Commit**

```bash
git add book_scraper/spiders/scan.py book_scraper/spiders/discover.py book_scraper/services/scan.py book_scraper/settings.py book_scraper/db/repo.py
git commit -m "$(cat <<'EOF'
refactor: migrate spiders and services to typed ShopConfig

Spiders access config via typed attributes (conf.shop.base_url,
conf.scraping.batch_size) instead of dict .get() chains. ScanService
accepts both ShopConfig and dict for backward compat in tests.
EOF
)"
```

### Task 2d: Update test_config_strategies.py for typed config

**Files:**
- Modify: `tests/unit/test_config_strategies.py`

- [ ] **Step 1: Read and update the test file**

Read `tests/unit/test_config_strategies.py` to see current tests, then update assertions to use typed attribute access instead of dict access. For example `config.discover.sitemap.url` instead of `config["discover"]["sitemap"]["url"]`.

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/unit/test_config_strategies.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_config_strategies.py
git commit -m "fix: update config strategy tests for typed models"
```

---

## Task 3: Remove Standalone httpx Scanner

**Files:**
- Delete: `book_scraper/scripts/run_scan.py`
- Modify: `book_scraper/scripts/watchdog.sh` — update to use Scrapy spider instead of run_scan.py

- [ ] **Step 1: Verify no Python imports reference run_scan.py**

Run: `grep -r "run_scan" book_scraper/ tests/ --include="*.py"`
Expected: No matches (only the file itself)

- [ ] **Step 2: Delete run_scan.py**

```bash
rm book_scraper/scripts/run_scan.py
```

- [ ] **Step 3: Update watchdog.sh to use Scrapy spider**

Edit `book_scraper/scripts/watchdog.sh` — replace line 25:

From:
```bash
    PYTHONPATH=. uv run python book_scraper/scripts/run_scan.py "$SHOP" &
```

To:
```bash
    uv run scrapy crawl scan -a shop="$SHOP" &
```

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore: remove standalone httpx scanner (run_scan.py)

The Scrapy scan spider is the canonical execution path. The standalone
httpx script duplicated scan logic and config access patterns. Removed
to consolidate to a single scan implementation.
EOF
)"
```

---

## Task 4: Pre-commit Hooks

**Files:**
- Create: `.pre-commit-config.yaml`
- Modify: `pyproject.toml` (add pre-commit to dev deps)

- [ ] **Step 1: Add pre-commit to dev dependencies**

Edit `pyproject.toml` — add to `[project.optional-dependencies] dev`:

```toml
[project.optional-dependencies]
dev = [
    "ruff>=0.11",
    "mypy>=1.15",
    "pytest>=8.0",
    "pytest-asyncio>=0.25",
    "pytest-cov>=7.0",
    "pre-commit>=4.0",
]
```

- [ ] **Step 2: Create .pre-commit-config.yaml**

Create `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.11.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

- [ ] **Step 3: Sync deps and verify**

Run: `uv sync --all-extras`
Run: `uv run pre-commit run --all-files`
Expected: PASS (all files already formatted/linted)

- [ ] **Step 4: Commit**

```bash
git add .pre-commit-config.yaml pyproject.toml uv.lock
git commit -m "$(cat <<'EOF'
chore: add pre-commit hooks for ruff lint and format
EOF
)"
```

---

## Task 5: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create CI workflow**

```bash
mkdir -p .github/workflows
```

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --all-extras
      - run: uv run ruff check book_scraper/ tests/
      - run: uv run ruff format --check book_scraper/ tests/
      - run: uv run mypy book_scraper/

  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: book_scraper_test
        ports:
          - 5433:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 5s
          --health-timeout 5s
          --health-retries 5
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --all-extras
      - run: uv run pytest -v

  deps:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --all-extras
      - run: uv run deptry book_scraper/
      - run: uv run pip-audit
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "$(cat <<'EOF'
ci: add GitHub Actions workflow with lint, test, and dep audit

Runs ruff, mypy, pytest (with PostgreSQL 16 service on port 5433),
deptry, and pip-audit on push/PR to main.
EOF
)"
```

---

## Task 6: Dependency Audit Tooling

**Files:**
- Modify: `pyproject.toml`
- Modify: `Makefile`

- [ ] **Step 1: Add deptry and pip-audit to dev deps**

Edit `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    "ruff>=0.11",
    "mypy>=1.15",
    "pytest>=8.0",
    "pytest-asyncio>=0.25",
    "pytest-cov>=7.0",
    "pre-commit>=4.0",
    "deptry>=0.22",
    "pip-audit>=2.7",
]
```

- [ ] **Step 2: Add Makefile targets**

Edit `Makefile` — add to `.PHONY` line and add targets:

```makefile
.PHONY: lint format test build ci crawl coverage coverage-html audit deps

# ... existing targets ...

audit:
	uv run pip-audit

deps:
	uv run deptry book_scraper/
```

Update the `ci` target to include deps check:

```makefile
ci: lint test deps
```

- [ ] **Step 3: Sync and verify**

Run: `uv sync --all-extras`
Run: `uv run deptry book_scraper/`
Run: `uv run pip-audit`

Fix any issues reported (unused deps, known vulnerabilities).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock Makefile
git commit -m "$(cat <<'EOF'
chore: add deptry and pip-audit for dependency hygiene

deptry detects unused/missing deps, pip-audit checks for known
vulnerabilities. Both run in CI and via `make audit` / `make deps`.
EOF
)"
```

---

## Task 7: Pin Python Version Range

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Pin requires-python to exclude 3.14**

Edit `pyproject.toml`:

```toml
requires-python = ">=3.12,<3.14"
```

This prevents accidentally running on Python 3.14 where Pydantic V1 compat warnings appear and behavior may differ.

- [ ] **Step 2: Sync and run tests**

Run: `uv sync --all-extras`
Run: `uv run pytest -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "$(cat <<'EOF'
chore: pin Python to >=3.12,<3.14

Avoids Pydantic V1 compatibility warnings on Python 3.14 and ensures
we test on supported versions only.
EOF
)"
```

---

## Task 8: Final Verification

- [ ] **Step 1: Run full lint suite**

Run: `uv run ruff check book_scraper/ tests/ && uv run ruff format --check book_scraper/ tests/ && uv run mypy book_scraper/`
Expected: PASS

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS

- [ ] **Step 3: Run dependency checks**

Run: `uv run deptry book_scraper/ && uv run pip-audit`
Expected: PASS (or only known/acceptable issues)

- [ ] **Step 4: Verify pre-commit works**

Run: `uv run pre-commit run --all-files`
Expected: PASS

- [ ] **Step 5: Update CLAUDE.md with new commands**

Add to the Key Commands section:

```bash
uv run scrapy crawl scan -a shop=vaga -a rescrape=true   # Re-scrape all known product URLs
make audit                                                 # Check for vulnerable dependencies
make deps                                                  # Check for unused/missing dependencies
uv run pre-commit run --all-files                          # Run pre-commit hooks
```

- [ ] **Step 6: Commit CLAUDE.md update**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with new commands"
```
