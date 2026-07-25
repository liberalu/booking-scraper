# Codebase Review — 2026-04-16

## Scope

This review covers repository structure, architecture, quality controls, and maintainability for the current `booking-scraper` codebase.

Primary files reviewed:

- `README.md`
- `pyproject.toml`
- `book_scraper/spiders/discover.py`
- `book_scraper/pipelines.py`
- `book_scraper/db/repo.py`
- `book_scraper/services/scan.py`
- `tests/unit/test_spiders.py`

## High-level assessment

The project is in good shape for a single-shop production scraper that is designed to scale to multiple shops. The architecture is coherent (generic spiders + shop-specific parsers), persistence and fault-tolerance are thoughtfully handled (scrape run tracking and resumability), and the test split between unit/integration is practical.

## What is working well

1. **Clear architectural separation**
   - Generic spiders keep crawl orchestration centralized.
   - Shop-specific parsing is isolated in parser modules loaded via registry.
   - Database writes are consolidated in repository functions.

2. **Pragmatic run lifecycle handling**
   - Discover/scan run creation and completion status are explicit.
   - Stale runs are proactively marked failed before new runs start.

3. **Strong data quality posture**
   - Validation pipeline covers malformed prices, ISBN checks, suspicious content, URL validity, and year cleanup.
   - Validation issues are not just logged—they are structured and buffered for persistence.

4. **Sound quality tooling baseline**
   - Strict mypy, ruff lint/format, and a clear pytest structure support maintainability.

5. **Good test strategy**
   - Fast unit tests for spider/parser logic.
   - Integration tests exercise repository and pipeline behavior against real PostgreSQL.

## Risks and opportunities

1. **Potentially broad full-crawl behavior**
   - `parse_full_crawl` follows all internal links recursively and emits requests liberally.
   - This is useful for deep discovery, but can increase crawl cost and duplicate work without stronger bounds (path allow-lists, depth limits, or adaptive stopping).

2. **Repository layer mixes policy + persistence**
   - `upsert_listing` now handles both persistence and business-diff logic.
   - This works, but complexity in a single function may grow as change tracking expands.

3. **Validation and persistence coupling**
   - Discover spider reports validation via private pipeline method (`vp._warn(...)`).
   - Effective in practice, but fragile as an integration seam if pipeline internals evolve.

4. **Static year upper bound**
   - `_MAX_YEAR = 2030` will eventually become stale.
   - A dynamic upper bound (e.g., current year + 1) could reduce future maintenance.

5. **Config/schema evolution pressure**
   - The project is poised to add shops and matching logic.
   - Existing abstractions are solid, but long-term maintainability will benefit from stricter contracts for parser outputs and clearer typed interfaces between spiders/pipelines/repo.

## Recommended next actions (prioritized)

### P1 (near-term)

1. Add crawl guardrails for `full_crawl` strategy:
   - max depth
   - optional allow-list patterns
   - budget cap (max URLs per run)

2. Replace private pipeline callback usage with a small, explicit validation reporter interface (or Scrapy signal) to decouple spiders from pipeline internals.

3. Make year validation upper bound dynamic (`datetime.now().year + 1`) and test it.

### P2 (mid-term)

4. Split `upsert_listing` into smaller helpers:
   - identity lookup/create
   - field merge rules
   - change tracking
   - availability/heartbeat updates

5. Add a typed parser output protocol (or pydantic model) to harden multi-shop parser contracts before adding new shops.

### P3 (roadmap)

6. Add scan/discover run-level SLO metrics in dashboard views:
   - URLs discovered vs accepted
   - failure ratio
   - validation issues by type over time

7. Draft match-phase interfaces now (even if unimplemented) to avoid schema drift later.

## Conclusion

The codebase is well-structured and already shows production-oriented thinking (resumability, quality checks, DB-backed run state). The highest leverage improvements are around interface hardening and crawl governance, which will pay off immediately as additional shops and phases are introduced.
