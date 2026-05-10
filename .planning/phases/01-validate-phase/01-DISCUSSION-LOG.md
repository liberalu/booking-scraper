# Phase 1: Validate Phase - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-10
**Phase:** 1-Validate Phase
**Areas discussed:** Entrypoint shape

---

## Entrypoint Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Scrapy spider | `scrapy crawl validate -a shop=X` — consistent with discover/scan; scrape_runs row created by existing spider lifecycle hooks | ✓ |
| Plain async function | `uv run python -m book_scraper.services.validate vaga` — no Scrapy overhead; creates scrape_runs directly via SQLAlchemy | |
| Both — CLI wrapper + Scrapy | Plain function for cron/scripts, thin Scrapy spider for dashboard trigger consistency | |

**User's choice:** Scrapy spider

---

## scrape_runs Lifecycle (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Manage scrape_runs directly | spider_opened creates the run row, spider_closed marks it complete — skips PostgresPipeline entirely | |
| Yield a synthetic item | Yield one summary item so PostgresPipeline can close the run row — reuses existing lifecycle | |
| You decide | Pick whichever integrates cleanest with the existing spider lifecycle | ✓ |

**User's choice:** Claude decides

---

## Stall Detection (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Disable stall detection for validate | Set STALL_TIMEOUT=0 or skip StallDetector via EXTENSIONS setting | |
| Run synchronously inside spider_opened | ValidateService runs before reactor starts; stall detection never triggers | |
| You decide | Pick whichever approach is simplest given the existing extension architecture | ✓ |

**User's choice:** Claude decides

---

## Not Discussed (user skipped)

- **stale_active cadence** — how to determine per-shop discover frequency for `stale_active` check
- **title_author_duplicate threshold** — title+author only vs. title+author+year
- **Trigger mechanism** — on-demand vs. auto-trigger after scan

These are noted in CONTEXT.md as "Unresolved — planner resolves" with spec recommendations.

---

## Claude's Discretion

- scrape_runs lifecycle: manage directly in spider_opened/spider_closed (no PostgresPipeline involvement)
- Stall detection: run ValidateService synchronously in spider_opened so no requests are ever yielded and stall timers never fire
- stale_active cadence default: use 14 days or parse TOML cron schedule if accessible

## Deferred Ideas

- Auto-trigger validate after scan completes — v2, cron integration
- `shops.discover_cadence_days` DB field for precise stale_active threshold — v2
- Validate in docker-compose cron schedule — out of scope for this phase
