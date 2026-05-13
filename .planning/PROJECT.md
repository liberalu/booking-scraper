# Lithuanian Book Price Scraper

## What This Is

A multi-shop Lithuanian book price scraper that discovers, scrapes, and stores book metadata and pricing from vaga.lt, pegasas.lt, and humanitas.lt. Data lives in PostgreSQL; a FastAPI + Jinja2 dashboard surfaces run history, pricing trends, and data quality issues. Built for a single operator — no auth, no multi-tenancy.

## Core Value

Accurate, up-to-date book pricing and metadata across all three shops, surfaced through a dashboard that exposes data quality issues before they become hard-to-diagnose problems.

## Current Milestone: v1.2 Observability

**Goal:** When a scrape run fails or behaves abnormally, the *what* and *why* are answerable from one UI in under 30 seconds — no `docker exec`, no DB queries by hand.

**Target features:**
- Unified log stack (Grafana + Loki + Promtail) ingesting all 5 log sources + Postgres data source
- Pre-built Grafana dashboard: failed-runs table + cross-filterable log panels by shop/phase/run_id/time
- Close 8 audit gaps in code-side observability (reconcile_runs DEVNULL, reaper logging, heartbeat row-vanish handling, StallDetector diagnostics, spawn source-run_id, cron-chain-skipped events, faster cron health-check, SQLAlchemy pool telemetry)

## Requirements

### Validated

- ✓ vaga.lt: discover via sitemap/categories/full_crawl, scan product pages — existing
- ✓ pegasas.lt: discover via GraphQL (full metadata) + LupaSearch (fast rescan), scan is no-op — existing
- ✓ humanitas.lt: discover via categories + FlareSolverr, scan product pages through FlareSolverr — existing
- ✓ PostgreSQL schema: shops, shop_books, prices, discovered_urls, scrape_url_items, scrape_runs — existing
- ✓ FastAPI dashboard with run history, pricing, shop detail, validation issues — existing
- ✓ Fault tolerance: stall detection, auto-resume, per-shop DB settings override — existing
- ✓ validation_issues table: stores data quality findings per shop_book — existing
- ✓ Validate phase: DB-only checks over shop_books rows, writes validation_issues, surfaced in dashboard — v1.1

### Active

- [ ] Unified log stack: Grafana + Loki + Promtail ingest all 5 log sources, Postgres registered as data source
- [ ] Grafana dashboard "Scrape runs overview" with failed-runs table + cross-filterable log panels
- [ ] Code-side observability fixes: 8 audit-identified gaps closed (silent failures become visible)

### Out of Scope

- Match phase (linking shop_books to canonical books) — future milestone, schema exists but logic not implemented
- Multi-tenancy / auth — single-operator tool, by design
- Mobile app — web dashboard only
- Alerts / notifications (email, Slack, PagerDuty) — visibility-only milestone; alerting is its own scope
- Log retention beyond Loki defaults (~1 week) — adequate for personal-project incident response window
- Per-shop SLO dashboards — premature; no SLOs defined

## Context

- 493 commits over 35 days (2026-04-05 to 2026-05-10)
- Three shops onboarded, pipeline proven in production
- Fault tolerance infrastructure mature (stall detector, single-row restart, auto-resume)
- FlareSolverr sidecar required for humanitas; docker-compose managed
- OrbStack proxy gotcha: httpx must use `trust_env=False`; docker builds need cleared proxy env vars
- Spec already written: `docs/superpowers/specs/2026-05-10-shop-books-validate-phase-design.md`
- v1.2 trigger: run #427 (validate/vaga, 2026-05-12) died as `heartbeat_timeout` with zero log trail — symptom of broader silent-failure surface area audited and prioritized into this milestone

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
| Validate phase is read-mostly, DB-only, no auto-fix | Keeps validate safe to run anytime; operator decides remediation | ✓ Good |
| Unified logging via Grafana + Loki + Promtail (not custom dashboard route) | Off-the-shelf time-range queries + label filtering scale better than hand-rolled SSE; works for v1.3+ shop count growth | — Pending |
| Visibility-only observability — no alerts in v1.2 | Alerting is its own design problem (routing, paging, deduplication); not worth bundling | — Pending |

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
*Last updated: 2026-05-13 after milestone v1.2 (Observability) initialization*
