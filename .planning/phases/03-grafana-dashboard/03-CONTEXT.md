# Phase 3 — Grafana Dashboard CONTEXT

**Phase:** 03-grafana-dashboard
**Domain:** Replace the placeholder dashboard with "Scrape runs overview" — one failed-runs SQL panel from Postgres + three log panels from Loki (dashboard / scraper / per-spawn), all cross-filterable by shop / phase / run_id / time range. Pre-provisioned: zero manual import.
**Milestone:** v1.2 Observability
**Date:** 2026-05-13

## Carried forward from prior phases

- **Personal-project posture** — simple, off-the-shelf, no over-engineering. Verified through v1.0–v1.1 (PROJECT.md Key Decisions).
- **Single compose file, always-on observability** — Loki/Promtail/Grafana run alongside the rest of the stack (Phase 2 02-CONTEXT decision).
- **Label cardinality contract** — only `service`, `level`, `role`, `shop` are Loki labels. `run_id` is **forbidden as a label** — filter via LogQL `|= "run_id=<id>"` instead (Phase 2; documented in `monitoring/promtail/promtail-config.yml` header + CLAUDE.md guardrail section).
- **Phase 4 (CODEOBS-02) commitment** — reaper will emit `key=value` log lines so `| logfmt` works downstream. Dashboard queries can rely on this.

## Decisions

### Architecture

- **A1. Single dashboard, vertical stack layout.** No tabs, no rows, no folders. One JSON file, ~4 panels.
  - Top: failed-runs table (`h: 8`)
  - Below: 3 log panels stacked (`h: 6` each)
  - Total height ~26 grid rows. Fits on a laptop with scroll.
- **A2. Replace `monitoring/grafana/dashboards/placeholder.json` with a new file `monitoring/grafana/dashboards/scrape-runs-overview.json`.** Delete the placeholder JSON in the same commit. Provisioning's `disableDeletion: true` means Grafana keeps the old record, but the file swap renames it.
- **A3. Hand-author the dashboard JSON, don't UI-build-then-export.** UI exports embed environment-specific UIDs and timestamps, which break re-provisioning. Hand-author gives reviewable diffs and stable behavior.

### Failed-runs panel (DASH-02)

- **F1. Inclusion rule:** SQL `WHERE status = 'failed' OR (status = 'completed' AND error_count > 0)`. This catches the run-#427-style heartbeat-timeout case AND silent partial-completes. Excludes `running` / `paused` / `stopping` (those are in-flight, not historic).
- **F2. Columns** in left-to-right order: `run_id`, `shop`, `phase`, `status`, `close_reason`, `started_at`, `finished_at`, `urls_processed`. No `error_count` column (keep table narrow); error visibility comes from the close_reason value.
- **F3. Sort:** `ORDER BY finished_at DESC NULLS FIRST` so still-running failures (no `finished_at`) bubble to the top.
- **F4. Time range:** honors the dashboard's global `${__from}` / `${__to}`. No panel-local override. SQL: `WHERE finished_at BETWEEN $__timeFrom() AND $__timeTo() OR finished_at IS NULL`.
- **F5. Color coding:** Grafana value-mapping rule on `close_reason` — `heartbeat_timeout` / `stall_timeout` / `manual_kill` / `orphan_on_boot` highlighted in red; `stopped_by_operator` / `stop_timeout` in amber; everything else (including `finished` with errors) default.
- **F6. Shop column:** joins `shops` table on `shop_id` to render the shop NAME, not the integer. SQL pattern:
  ```sql
  SELECT r.id AS run_id, s.name AS shop, r.phase, r.status, r.close_reason,
         r.started_at, r.finished_at, r.urls_processed
    FROM scrape_runs r JOIN shops s ON s.id = r.shop_id
   WHERE (r.status = 'failed' OR (r.status = 'completed' AND r.error_count > 0))
     AND (r.finished_at BETWEEN $__timeFrom() AND $__timeTo()
          OR r.finished_at IS NULL)
   ORDER BY r.finished_at DESC NULLS FIRST
   LIMIT 100;
  ```

### run_id → time range drill-in (success criterion #4)

- **D1. Constraint:** Grafana template variables CANNOT programmatically change the dashboard's time range. This is a long-standing platform limitation, not a config gap.
- **D2. Mechanism:** **Data link on the failed-runs panel** opens the same dashboard with URL query params:
  ```
  ?var-run_id=${__data.fields.run_id}
  &from=${__data.fields.started_at}
  &to=${__data.fields.finished_at}
  ```
  Grafana respects URL `from`/`to` params and updates the dashboard time range on navigation. Clicking a row drills in.
- **D3. `run_id` template variable** — type `Text Box` (not `Query`). Default empty. When empty, log panels show ALL lines in time range (no `|= "run_id=..."` filter). When populated, log panels add `|= "run_id=$run_id"` to their query.
- **D4. Phase 4 dependency:** for the drill-in to surface meaningful content, log lines need to carry `run_id=<N>` as a substring. Phase 4's CODEOBS-02 (reaper logs each killed run with run_id) and CODEOBS-05 (spawn lines include source run_id) deliver this. Until Phase 4 ships, drill-in works but log panels are sparse.

### Variable selectors (DASH-06)

- **V1. `shop`** — type `Query`, datasource `Postgres`, SQL `SELECT name FROM shops ORDER BY name`. Multi-value: yes. `All` option: yes (default).
- **V2. `phase`** — type `Custom`, fixed list: `discover, discover_sitemap, discover_categories, discover_full_crawl, discover_graphql, discover_lupasearch, scan, validate, match`. Multi-value: yes. `All` option: yes (default).
- **V3. `run_id`** — type `Text Box`. Default empty.
- **V4. Time range** — built-in Grafana selector. Default `now-24h..now`. Quick ranges: 1h, 6h, 24h, 7d, 30d.
- **V5. Variable order in the toolbar:** shop, phase, run_id (left to right).

### Log panels (DASH-03, DASH-04, DASH-05)

- **L1. Three Logs panels** (Grafana panel type `logs`, NOT `time series`):
  - "Dashboard logs" — `{service="dashboard"} |~ "$__interpolation_for_shop_phase_runid"` — see L4
  - "Scraper logs (cron + reconcile)" — `{service="scraper", role="cron"} | ...`
  - "Per-spawn logs" — `{service="scraper", role=~"operator|stall-resume|cron-chain|reconcile-restart", shop=~"$shop"} | ...`
- **L2. Panel options:** `showTime: true`, `wrapLogMessage: true`, `dedupStrategy: none`, `sortOrder: Descending` (newest at top), `enableLogDetails: true`.
- **L3. Level styling:** Grafana auto-colors lines based on the `level` label (already extracted by Promtail). No extra config needed.
- **L4. Variable interpolation in LogQL queries:**
  - `shop` variable → applies only to the per-spawn panel (`shop=~"$shop"` regex on the label). Multi-value joined with `|`. Empty `All` resolves to `.*`.
  - `phase` variable → applies only to the per-spawn panel via `role` (since `role` is the closest proxy — phase isn't a Loki label). Operator-triggered runs of all phases share `role=operator`; cron-triggered runs use `role=cron-chain`. Phase variable is **not used in the `containers` or `scraper_log_file` jobs' queries** — those don't have `phase` available. Note this limitation in the dashboard description.
  - `run_id` variable → `|= "run_id=$run_id"` substring filter on ALL three log panels. Empty value: drop the filter (use `${run_id:lucene}` is not needed; just omit when empty via two query variants).

### Data source UID stability

- **U1. Hardcode UIDs in provisioning YAML:**
  - `monitoring/grafana/provisioning/datasources/loki.yml` adds `uid: loki`.
  - `monitoring/grafana/provisioning/datasources/postgres.yml` adds `uid: postgres-bookscraper`.
- **U2. Dashboard JSON refers to data sources by `{ "type": "loki", "uid": "loki" }` and `{ "type": "postgres", "uid": "postgres-bookscraper" }`.** Never by name lookup. This survives Grafana restart and re-provisioning.
- **U3. Migration note:** the existing Phase 2 deployment auto-assigned UIDs. Setting explicit UIDs in the YAML will replace existing data sources on next `docker compose restart grafana`. Saved queries in the UI referencing the old UIDs will break — acceptable for a personal project with one placeholder dashboard.

### Dashboard JSON metadata

- **M1. uid:** `scrape-runs-overview` (stable; Phase 4 dashboards can data-link to this UID).
- **M2. title:** `Scrape runs overview`
- **M3. tags:** `["observability", "phase-3"]`
- **M4. refresh:** empty string (no auto-refresh). Operator triggers refresh manually.
- **M5. schemaVersion:** 39 (Grafana 10.4+ baseline; forward-compatible with 11.x).
- **M6. time:** `{ "from": "now-24h", "to": "now" }`.
- **M7. timezone:** `browser`.

## Out of Scope (for this phase)

- Alerting rules / notifier configs — explicit v1.2 out-of-scope; deferred to OBS-AUTO-01.
- Per-shop SLO dashboards — premature.
- A separate "Validate phase" dashboard — overview covers it via the phase variable.
- Drill-in DETAIL view (e.g., one-run timeline with all events) — could be a future Phase 3.5 if the data link UX isn't enough.
- Loki rate-limit tuning (the 429 backfill issue noted in 02-SUMMARY.md) — separate cleanup.
- Phase 4 code changes — covered by Phase 4 plan.

## Deferred Ideas

- **Run timeline panel** — annotate failed-runs table with a Grafana annotation source pulling `scrape_run_events`. Real value but adds a second SQL query type. Defer to a v1.2 polish pass after Phase 4 ships.
- **`error_count` heatmap** — visual rate of errors per shop per day. Nice for trend spotting; needs designing. Backlog candidate.
- **One-click "Continue run" button** — Grafana panel-action plugin or a custom Text panel with a link to `/api/runs/{run_id}/resume`. Cool but requires the dashboard process route, which already exists at `http://localhost:8000`. Out of scope here.

## Canonical refs

- `.planning/REQUIREMENTS.md` (DASH-01..06)
- `.planning/ROADMAP.md` (Phase 3 success criteria)
- `.planning/phases/02-log-infrastructure/02-SUMMARY.md` (Phase 2 outcome — known limitations)
- `monitoring/grafana/provisioning/datasources/loki.yml` (existing — needs uid added)
- `monitoring/grafana/provisioning/datasources/postgres.yml` (existing — needs uid added)
- `monitoring/grafana/provisioning/dashboards/dashboards.yml` (existing — `disableDeletion: true`, no changes needed)
- `monitoring/grafana/dashboards/placeholder.json` (to be deleted)
- `book_scraper/dashboard/queries.py` line 38 (`DEAD_RUN_SECONDS`) and around line 299 (`mark_stale_runs` close_reason vocabulary)
- `book_scraper/db/models.py` (scrape_runs schema; shops table)
- CLAUDE.md "Observability label cardinality (Loki)" subsection — the contract the dashboard MUST honor

## Open questions for downstream

- **Test strategy for Grafana provisioning** — Phase 2 had a runtime smoke test (curl). Phase 3 needs a similar gate that the dashboard JSON validates AND renders. Planner decides: hit `/api/dashboards/uid/scrape-runs-overview` and confirm 200 + correct uid? Or use Grafana's `/api/dashboards/db/scrape-runs-overview` health endpoint? Defer the exact verification approach to plan-phase.
- **Datasource UID hot-swap** — explicit `uid:` in an existing provisioned datasource: does Grafana 11+ update in place, or create a new one and leave the old? Researcher / planner verifies during execution; if it's destructive, the migration note in U3 above gets a SUMMARY warning.

---
*CONTEXT defined 2026-05-13 after gray-area analysis. Approved with "no preference" — controller made the calls per personal-project posture.*
