# Lithuanian Book Price Scraper

## What This Is

A multi-shop Lithuanian book price scraper that discovers, scrapes, and stores book metadata and pricing from vaga.lt, pegasas.lt, and humanitas.lt. Data lives in PostgreSQL; a FastAPI + Jinja2 dashboard surfaces run history, pricing trends, and data quality issues. Built for a single operator — no auth, no multi-tenancy.

## Core Value

Accurate, up-to-date book pricing and metadata across all three shops, surfaced through a dashboard that exposes data quality issues before they become hard-to-diagnose problems.

## Requirements

### Validated

- ✓ vaga.lt: discover via sitemap/categories/full_crawl, scan product pages — existing
- ✓ pegasas.lt: discover via GraphQL (full metadata) + LupaSearch (fast rescan), scan is no-op — existing
- ✓ humanitas.lt: discover via categories + FlareSolverr, scan product pages through FlareSolverr — existing
- ✓ PostgreSQL schema: shops, shop_books, prices, discovered_urls, scrape_url_items, scrape_runs — existing
- ✓ FastAPI dashboard with run history, pricing, shop detail, validation issues — existing
- ✓ Fault tolerance: stall detection, auto-resume, per-shop DB settings override — existing
- ✓ validation_issues table: stores data quality findings per shop_book — existing

### Active

- [ ] Validate phase: a fourth pipeline phase that runs DB-only checks over shop_books rows and writes validation_issues, surfaced in the dashboard

### Out of Scope

- Match phase (linking shop_books to canonical books) — future milestone, schema exists but logic not implemented
- Multi-tenancy / auth — single-operator tool, by design
- Mobile app — web dashboard only

## Context

- 493 commits over 35 days (2026-04-05 to 2026-05-10)
- Three shops onboarded, pipeline proven in production
- Fault tolerance infrastructure mature (stall detector, single-row restart, auto-resume)
- FlareSolverr sidecar required for humanitas; docker-compose managed
- OrbStack proxy gotcha: httpx must use `trust_env=False`; docker builds need cleared proxy env vars
- Spec already written: `docs/superpowers/specs/2026-05-10-shop-books-validate-phase-design.md`

## Constraints

- **Tech stack**: Python 3.12+, Scrapy asyncio reactor, SQLAlchemy 2.0, FastAPI, PostgreSQL — locked by existing codebase
- **Testing**: Real PostgreSQL on port 5433 (no mocks), tests/unit/ and tests/integration/ split
- **Style**: strict mypy, ruff (line-length 88), pre-commit hooks
- **Deployment**: Docker compose; rebuild required after code changes

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Generic spiders with shop-specific parsers loaded dynamically | Avoids spider-per-shop explosion; new shops need only parsers.py | ✓ Good |
| Prices table append-only | Preserves price history for trend analysis | ✓ Good |
| FlareSolverr for humanitas instead of headless browser in spider | Isolates Cloudflare bypass complexity into a sidecar | ✓ Good |
| Single-row restart for stall recovery | Reduces DB churn and avoids double-counting | ✓ Good |
| Validate phase is read-mostly, DB-only, no auto-fix | Keeps validate safe to run anytime; operator decides remediation | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-10 after initialization (brownfield, 3 shops live)*
