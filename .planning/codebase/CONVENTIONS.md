# Coding Conventions

**Analysis Date:** 2026-05-10

## Naming Patterns

**Files:**
- Snake_case for all Python modules: `parsers.py`, `config_models.py`, `url_utils.py`
- Test files: `test_<module_name>.py` — mirrors the module being tested (e.g. `test_vaga_parsers.py`, `test_validation_pipeline.py`)
- Shop parsers always live at `book_scraper/spiders/<shop>/parsers.py`

**Functions:**
- Snake_case throughout: `parse_product_page()`, `upsert_shop_book()`, `normalize_isbn()`
- Private/internal helpers prefixed with underscore: `_validate_year()`, `_split_author_string()`, `_normalize_author()`, `_is_tracking()`
- Repo functions use verb+noun pattern: `upsert_shop()`, `insert_price()`, `find_resumable_run()`
- Parser functions named by output: `parse_category_page()`, `parse_product_page()`, `parse_sitemap_urls()`

**Variables:**
- Snake_case throughout
- `db_session` — always this name for SQLAlchemy sessions in test fixtures and services
- `shop_name` — the shop identifier string (not `shop` or `shop_id`)
- Avoid single-letter names except loop variables (`i`, `k`, `v`) and type parameters

**Types and Classes:**
- PascalCase for all classes: `ShopBook`, `ValidationPipeline`, `BookClassification`
- TypedDict names describe the shape: `CategoryPageResult`, `ProductPageResult`, `ShopBookFieldFilter`
- Dataclass names describe the concept: `BookClassification`, `DiscoverPlan`, `ScanPlan`
- Private NamedTuples prefixed with underscore: `_Signal`
- Enum-like constants in SCREAMING_SNAKE_CASE: `_MIN_YEAR`, `_MAX_YEAR`, `_SPIKE_THRESHOLD`

**Modules:**
- `book_scraper/db/` — ORM models, repo functions, session factory
- `book_scraper/spiders/` — spider classes, per-shop parsers, type contracts
- `book_scraper/services/` — business logic (discover/scan/match phases)
- `book_scraper/dashboard/` — FastAPI routes, queries, templates

## Code Style

**Formatter:** Ruff (configured in `pyproject.toml`)
- Line length: 88 characters
- Target: Python 3.12

**Linter:** Ruff with rules E, F, I, N, UP, B, SIM
- `E` — pycodestyle errors
- `F` — pyflakes
- `I` — isort (import ordering)
- `N` — pep8-naming
- `UP` — pyupgrade
- `B` — flake8-bugbear
- `SIM` — flake8-simplify
- Exception: `B008` (function call in default arg) is disabled for `book_scraper/dashboard/routes/*.py` (FastAPI `Depends(...)` pattern)

**Type Checker:** mypy with `strict = True`, Python 3.12

**Pre-commit hooks:** Ruff (lint + format) via `.pre-commit-config.yaml`

## Import Organization

Ruff `I` rules enforce isort-style grouping:

1. Standard library: `import re`, `from pathlib import Path`
2. Third-party: `import scrapy`, `from sqlalchemy.orm import Session`
3. Local: `from book_scraper.db.models import ShopBook`

**Pattern observed:**
```python
import logging
import re
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from book_scraper.db.models import ShopBook, ScrapeRun
from book_scraper.url_utils import normalize_url
```

**Future annotations:** `from __future__ import annotations` used in files with complex self-referential types (newer parser modules, dashboard routes). Not used universally — rely on Python 3.12 native union syntax (`X | Y`) in most files.

**Path aliases:** None. Always use full `book_scraper.*` import paths.

## Type Annotations

All function signatures are fully annotated — required by `mypy --strict`.

**Return types:** Always explicit, including `None`:
```python
def upsert_shop(session: Session, name: str, base_url: str) -> Shop: ...
def _validate_year(adapter: ItemAdapter) -> None: ...
def _split_author_string(raw: str | None) -> list[str]: ...
```

**Union types:** Use `X | Y` syntax (Python 3.10+ style), not `Optional[X]` or `Union[X, Y]`:
```python
def upsert_shop_book(...) -> tuple[ShopBook, bool, Decimal | None, list[dict[str, Any]]]: ...
```

**TypedDict for parser contracts:** Parser return shapes are typed as `TypedDict` in `book_scraper/spiders/parser_types.py`. Use these when returning from `parse_category_page` and `parse_product_page`.

**Dataclasses for service results:**
```python
@dataclass
class DiscoverPlan:
    run_id: int
    shop_id: int
```

**`Any` annotation:** Used deliberately in Scrapy item pipeline (`process_item(self, item: Any) -> Any`) because `ItemAdapter` works on heterogeneous types. Not a general escape hatch.

## Error Handling

**Patterns:**

- Scrapy pipeline errors raise `DropItem` with a descriptive message; the item is logged and discarded
- DB errors in `PostgresPipeline.process_item` are caught as `SQLAlchemyError`, rolled back, and re-raised as `DropItem` — this pattern keeps the session clean
- Config errors raise `FileNotFoundError` immediately on missing shop TOML
- Spider init errors raise `ValueError` with `match=` pattern expected by tests
- Network middleware uses `raise_for_status()` for HTTP errors; specific exceptions like `httpx.TimeoutException` are caught and re-raised explicitly
- `logger.exception()` used (not `logger.error()`) when catching unexpected exceptions in `except Exception` blocks — captures the traceback

**Example:**
```python
try:
    return self._process_item_inner(item)
except SQLAlchemyError as exc:
    self.session.rollback()
    self.shop_cache.clear()
    logger.error("PostgresPipeline: dropping %s item (%s) — DB error: %s", ...)
    raise DropItem(f"DB error for {url}: {exc.__class__.__name__}") from exc
```

## Logging

**Framework:** Python stdlib `logging`

**Pattern:** Module-level logger created with `logging.getLogger(__name__)`:
```python
logger = logging.getLogger(__name__)
```

Found in: `book_scraper/pipelines.py`, `book_scraper/db/repo.py`, `book_scraper/services/match.py`, `book_scraper/dashboard/queries.py`, etc.

**Log levels used:**
- `logger.warning()` — validation issues, recoverable anomalies
- `logger.error()` — pipeline item drops, DB write failures
- `logger.exception()` — unexpected `except Exception` catches (includes traceback)
- Scrapy's built-in `self.logger` used inside spider classes instead of module-level logger

**Format:** `"[issue_code] field=%s url=%s %s"` pattern in `ValidationPipeline._warn()` — structured fields as positional args to `logging.warning`.

## Comments

**Docstrings:**
- Module-level docstrings on test files describe what lifecycle track or feature is covered
- Class/function docstrings explain non-obvious contracts, not obvious logic
- Docstrings use single-line form for simple functions, multi-line with explanation for complex ones

**Inline comments:**
- Used liberally for non-obvious logic (e.g. why a SAVEPOINT pattern is used, why `shop_cache.clear()` is needed after rollback)
- TODOs are not present in production code — use issue tracker

**`# pragma: no cover`:**
- Applied to entire files for Scrapy lifecycle code that cannot be unit-tested (download handler, middleware, `flaresolverr_middleware.py`)
- Applied to `open_spider` / `close_spider` / `from_crawler` methods in pipeline classes
- Applied to `if __name__ == "__main__"` blocks

## Function Design

**Size:** Functions are decomposed into single-concern helpers. Example: `ValidationPipeline.process_item` dispatches to `_check_price_anomalies`, `_check_content_quality`, `_check_format_consistency`, `_check_attributes` — each is independently testable.

**Parameters:** Prefer explicit keyword arguments for DB repo functions with many params:
```python
upsert_shop_book(
    db_session,
    shop_id=shop.id,
    url="https://vaga.lt/test",
    title="Test Book",
)
```

**Return values:**
- Tuples for multi-value returns with stable shape: `tuple[ShopBook, bool, Decimal | None, list[dict[str, Any]]]`
- `None` return for pure side-effect functions
- Dataclass instances for service plan results

## Module Design

**Exports:** No barrel `__init__.py` files that re-export — import directly from the module:
```python
# Correct
from book_scraper.db.repo import upsert_shop, insert_price

# Incorrect — don't add to __init__.py for re-export
from book_scraper.db import upsert_shop
```

**Per-shop parsers:** Each shop has `book_scraper/spiders/<shop>/parsers.py` exporting `parse_sitemap_urls()`, `parse_category_page()`, `parse_product_page()`. The generic spider loads these dynamically via `book_scraper/spiders/registry.py`.

**Config models:** All configuration shapes are `pydantic.BaseModel` subclasses in `book_scraper/config_models.py`. TOML files are parsed and validated via `ShopConfig.model_validate()`.

**Scrapy items:** All items inherit from `scrapy.Item` using `scrapy.Field()`. Validated and transformed in `ValidationPipeline` before persisting via `PostgresPipeline`.

## Pydantic Usage

Pydantic V2 (`BaseModel`). Used exclusively for config models (`book_scraper/config_models.py`), not for item validation (that uses `ValidationPipeline`). Factory methods use `model_validate()` not `parse_obj()`.

---

*Convention analysis: 2026-05-10*
