# Roadmap: Lithuanian Book Price Scraper

**Milestone:** v1.2 — Observability
**Created:** 2026-05-13
**Status:** Phases 2, 3, 4 shipped — v1.2 Observability milestone COMPLETE

---

## Milestones

- ✓ **v1.1 — Validate Phase** (completed 2026-05-10) — see [archive below](#archive)
- ◆ **v1.2 — Observability** (in progress) — Phases 2-4

---

## Phases

### Phase 2: Log Infrastructure

**Goal:** Stand up Grafana + Loki + Promtail alongside the existing compose stack and ingest every log source (container stdout + file-based scraper logs) so log lines are queryable in one place. Postgres registered as a Grafana data source for SQL panels.

**Requirements:** LOGINFRA-01, LOGINFRA-02, LOGINFRA-03, LOGINFRA-04, LOGINFRA-05, LOGINFRA-06, LOGINFRA-07

**Plans:** 3 plans, 2 waves

**Wave 1** *(parallel)*
- [x] 02-01-PLAN.md — Add Loki/Promtail/Grafana to docker-compose.yml + healthchecks + `monitoring/` dir scaffolding (LOGINFRA-01)
- [x] 02-02-PLAN.md — Loki single-binary config (TSDB, 7d retention) + Promtail config (docker_sd + 2 file scrape jobs with regex labels) (LOGINFRA-02, 03, 04)

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 02-03-PLAN.md — Grafana provisioning (Loki+Postgres data sources) + placeholder dashboard + CLAUDE.md addendum + end-to-end smoke test (LOGINFRA-05, 06, 07)

**Executed:** 2026-05-13 via `docs/superpowers/plans/2026-05-13-observability-log-infrastructure.md` (8 tasks, 9 commits ed7bce8..ad86745). Smoke test results: `.planning/phases/02-log-infrastructure/02-SUMMARY.md`.

**Success Criteria:**
1. `docker compose up -d` brings up loki, promtail, grafana alongside the existing stack with no manual setup
2. Grafana at `http://localhost:3000` shows Loki + Postgres as provisioned data sources
3. A Loki query for `{service="dashboard"}` returns lines from the dashboard container in real time
4. A Loki query for `{service="scraper"}` returns lines from both cron stdout (via Docker socket) and `/var/log/scraper.log` (via file scrape)
5. A Loki query for `{role="operator", shop="vaga"}` returns lines from per-spawn log files
6. Loki retains at least 7 days of log history under default disk budget

**Canonical refs:**
- `docker-compose.yml` (existing)
- `book_scraper/spawn_logging.py` (per-spawn log naming convention to parse)
- `CLAUDE.md` (post-task checklist conventions)

---

### Phase 3: Grafana Dashboard

**Goal:** Ship a pre-provisioned Grafana dashboard "Scrape runs overview" that an operator can open and use immediately — failed-runs SQL panel from Postgres + three log panels (dashboard / scraper / per-spawn) cross-filtered by shop, phase, run_id, and time range. Zero manual import.

**Requirements:** DASH-01, DASH-02, DASH-03, DASH-04, DASH-05, DASH-06

**Plans:** TBD (created via `/gsd:plan-phase 3`)

**Success Criteria:**
1. First `docker compose up -d` after the phase ships → Grafana already has the "Scrape runs overview" dashboard, no manual JSON import
2. The Recent failed runs panel lists run #427 (or any failed run) with run_id, shop, phase, close_reason, timestamps
3. Selecting `shop=vaga` in the dashboard variable filters all three log panels and the failed-runs SQL panel to vaga only
4. Selecting a specific `run_id` narrows the time range automatically to that run's `started_at..finished_at` window
5. The investigation flow that took multiple `docker exec` + DB queries today is achievable in under 30 seconds in Grafana

**Canonical refs:**
- Phase 2 outputs (Loki / Postgres provisioned)
- `book_scraper/dashboard/queries.py` (DEAD_RUN_SECONDS + close_reason vocabulary)

---

### Phase 4: Code-side Observability Fixes

**Goal:** Close the 8 silent-failure gaps identified in the audit so the data that powers Phase 3's dashboard is actually rich enough to diagnose with — reconcile_runs gets a log file, the reaper names what it kills, the heartbeat doesn't ghost-tick after row vanish, stalls report state, spawns carry source run_id, cron chains record skipped events, cron health-check runs 4×/day, and the SQLAlchemy pool reports overflow.

**Requirements:** CODEOBS-01, CODEOBS-02, CODEOBS-03, CODEOBS-04, CODEOBS-05, CODEOBS-06, CODEOBS-07, CODEOBS-08

**Plans:** TBD (created via `/gsd:plan-phase 4`)

**Success Criteria:**
1. A simulated container restart with an orphaned `running` row produces a per-spawn log file in `/var/log/scrapy_runs/` (CODEOBS-01 verifiable)
2. A run reaped via heartbeat_timeout produces a dashboard log line carrying `run_id`, `shop`, `phase`, `close_reason` (CODEOBS-02)
3. Deleting a `scrape_runs` row while its spider is alive triggers a WARNING and the spider exits within one heartbeat interval (CODEOBS-03)
4. A stall trigger writes a single log line containing request count, last URL, in-flight count per domain, and scheduler queue size (CODEOBS-04)
5. Operator-triggered rerun produces a log line including the source run_id alongside phase/shop/log-path (CODEOBS-05)
6. A failed cron-chain parent produces a `chain_skipped` event in `scrape_run_events` (CODEOBS-06)
7. Cron health-check runs at 09:00 / 15:00 / 21:00 / 03:00 UTC (CODEOBS-07)
8. Triggering pool exhaustion in a test produces a WARNING log line (CODEOBS-08)

**Canonical refs:**
- `book_scraper/scripts/reconcile_runs.py`
- `book_scraper/extensions.py` (HeartbeatExtension, StallDetector, CronChainTrigger)
- `book_scraper/dashboard/reaper.py`
- `book_scraper/dashboard/queries.py` (`mark_stale_runs`)
- `book_scraper/dashboard/routes/api.py` (`_spawn_scrapy_in_container`)
- `scripts/cron_health_check.py`
- `book_scraper/db/session.py`

---

## Backlog

- Match phase — link shop_books to canonical books table (separate milestone, v1.4 candidate)
- More shops — almalittera, knygos, tytoalba (v1.3 candidate, fixtures partially in working tree)
- Auto-trigger validate after scan — cron integration (v2)
- Per-shop discover cadence field for stale_active threshold (v2)
- Grafana alert rules + notifier config (post-v1.2 — OBS-AUTO-01)
- Loki object-storage backend for >1-month retention (post-v1.2 — OBS-AUTO-02)
- Per-shop SLO dashboards (post-v1.2 — OBS-AUTO-03)

---

## Archive

### Phase 1: Validate Phase (v1.1 — completed 2026-05-10)

**Goal:** Add a fourth pipeline phase that runs DB-only checks over shop_books rows, writes validation_issues, and surfaces findings in the dashboard — closing the gap where silent data quality failures went undetected until manual postmortem.

**Requirements:** VAL-01..14 (all complete)

**Plans:**
- [x] 01-01-PLAN.md — Alembic migration: add 'validate' to scrape_phase enum (VAL-13, VAL-14)
- [x] 01-02-PLAN.md — ValidateService skeleton + ValidateSpider (VAL-01..04, VAL-11)
- [x] 01-03-PLAN.md — Extended check groups + integration tests (VAL-05..10, VAL-11)
- [x] 01-04-PLAN.md — Dashboard integration: API allowlist + New Run modal (VAL-12)

**Canonical refs:** `docs/superpowers/specs/2026-05-10-shop-books-validate-phase-design.md`
