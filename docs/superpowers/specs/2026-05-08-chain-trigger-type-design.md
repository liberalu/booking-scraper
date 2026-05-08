# Chain Trigger Type Design

**Goal:** Enforce exclusive triggers (cron OR chain, not both) and surface trigger type in the Schedules UI and per-run history.

**Architecture:** Two changes — server-side auto-disable when a chain is assigned, and a new `triggered_by` column on `scrape_runs` so every run records how it started. The UI adds a trigger type badge on the Schedules table and in run history.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0, Alembic, FastAPI, React JSX (CDN Babel), PostgreSQL

---

## Behaviour

### Exclusive triggers

When job A's `chain_to_job_id` is set to point at job B:
- If B has `enabled=True`, the API automatically sets B's `enabled=False` (disables its cron).
- Clearing a chain (`clear_chain=True`) does NOT re-enable the target — the operator re-enables manually if needed.
- Changing chain from B to C: disable C if enabled; leave B's enabled state as-is.

### Trigger type on runs

Every `scrape_runs` row records how the spider was started via a new nullable `triggered_by` column:
- `"cron"` — spawned by cron via `generate_crontab.py`
- `"chain"` — spawned by `CronChainTrigger` after a predecessor finished
- `"manual"` — spawned by the dashboard "Run now" button or API
- `NULL` — legacy rows created before this feature

### Schedules table — Trigger badge

Each job row shows a trigger type indicator computed client-side from the job list:
- `⏱ cron` — job has `enabled=True` and is not a chain target
- `→ chain` — another job's `chain_to_id` equals this job's id
- `⏱ + →` (warning) — both apply (cron enabled AND is a chain target); should not happen after auto-disable but shown if somehow data is inconsistent

A job is a chain target if `jobs.some(j => j.chain_to_id === this.id)` — no extra API call.

### Schedule detail — Run history

The run history table on the schedule detail page gains a `Trigger` column showing a small badge: `cron`, `chain`, or `manual`. Null/unknown runs show `—`.

---

## File Map

| File | Change |
|------|--------|
| `alembic/versions/2026_05_08_add_triggered_by_to_scrape_runs.py` | Migration: add `triggered_by` varchar nullable column |
| `book_scraper/db/models.py` | Add `triggered_by: Mapped[str \| None]` to `ScrapeRun` |
| `book_scraper/dashboard/routes/api.py` | `api_cron_update`: auto-disable chain target if enabled; `api_cron_detail` runs list: include `triggered_by`; `_spawn_scrapy_in_container`: accept + pass `triggered_by` arg; `api_create_run`: pass `triggered_by="manual"` |
| `scripts/generate_crontab.py` | Add `-a triggered_by=cron` to every scrapy command |
| `book_scraper/extensions.py` | `CronChainTrigger._spawn_chain_subprocess`: pass `-a triggered_by=chain` |
| `book_scraper/pipelines.py` (or reconcile) | Store `triggered_by` spider arg on `ScrapeRun` at run creation |
| `book_scraper/dashboard/static/hifi/hf-other.jsx` | Schedules table: add Trigger badge column |
| `book_scraper/dashboard/static/hifi/hf-more-details.jsx` | Schedule detail run history: add Trigger badge column |

---

## Data Flow

1. `generate_crontab.py` → cron fires scrapy with `-a triggered_by=cron -a cron_job_id=N`
2. `CronChainTrigger` → spawns scrapy with `-a triggered_by=chain -a cron_job_id=N`
3. Dashboard "Run now" → `_spawn_scrapy_in_container(..., triggered_by="manual")`
4. Spider arg `triggered_by` is read in the reconcile/pipeline layer and stored on `scrape_runs.triggered_by`
5. `GET /api/cron/{id}/detail` returns `triggered_by` per run in the `runs` list
6. Frontend renders badge: `cron` → blue, `chain` → accent, `manual` → neutral

---

## What is NOT in scope

- Re-enabling a chain target's cron when the chain is cleared (manual step)
- Detecting transitive chains for the trigger badge (direct pointer only)
- Changing the `StallDetector` auto-resume spawn (those are not chain-triggered)
