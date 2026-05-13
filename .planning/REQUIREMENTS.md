# Requirements: Lithuanian Book Price Scraper

**Defined:** 2026-05-10
**Core Value:** Accurate, up-to-date book pricing and metadata across all three shops, surfaced through a dashboard that exposes data quality issues before they become hard-to-diagnose problems.

## v1.1 Requirements (shipped)

### Validate Phase

- [x] **VAL-01**: Validate phase runs DB-only checks over shop_books rows and writes validation_issues per shop
- [x] **VAL-02**: Validate phase gets its own scrape_runs row (phase='validate') so it appears in dashboard run history
- [x] **VAL-03**: Structural duplicate checks: isbn_duplicate, title_author_duplicate, sku_duplicate
- [x] **VAL-04**: Slug-title mismatch check using zero-token-overlap threshold
- [x] **VAL-05**: Data completeness checks: active_no_price, in_stock_no_price, book_no_metadata, no_price_history
- [x] **VAL-06**: Data correctness checks: year_out_of_range, price_zero, format_is_dimensions
- [x] **VAL-07**: Classification consistency checks: book_no_signals, non_book_has_isbn, non_product_active
- [x] **VAL-08**: Staleness/lifecycle checks: stale_active, unreachable_active, orphan_no_url
- [x] **VAL-09**: Match phase readiness checks: unmatched_has_isbn, match_isbn_drift
- [x] **VAL-10**: Relationship integrity checks: url_aliases, product_url_non_book
- [x] **VAL-11**: Each check deduplicates by (shop_book_id, field) to avoid duplicate rows on re-run
- [x] **VAL-12**: Operator can trigger validate run from dashboard shop detail page
- [x] **VAL-13**: scrape_phase enum extended with 'validate' value
- [x] **VAL-14**: Alembic migration adds validation_issues table (if not already exists)

## v1.2 Requirements (current — Observability)

### Log Infrastructure

- [ ] **LOGINFRA-01**: docker-compose.yml gains Grafana, Loki, Promtail services with healthchecks; survive `docker compose up -d` without manual config
- [ ] **LOGINFRA-02**: Promtail tails dashboard + scraper container stdout via the Docker socket and tags lines with a `service` label (`dashboard` / `scraper` / `postgres` / `flaresolverr`)
- [ ] **LOGINFRA-03**: Promtail tails `/var/log/scraper.log` and `/var/log/scrapy_runs/*.log` via the `scraper_logs` volume mounted read-only; spawn-log filename parsed into `role` and `shop` labels
- [ ] **LOGINFRA-04**: Loki retains logs for at least 7 days under default disk budget
- [ ] **LOGINFRA-05**: Grafana provisions Loki as a data source on first start (no manual setup)
- [ ] **LOGINFRA-06**: Grafana provisions Postgres as a data source pointing at the `book_scraper` DB
- [ ] **LOGINFRA-07**: Grafana available at `http://localhost:3000` with documented admin credentials in CLAUDE.md

### Grafana Dashboard

- [ ] **DASH-01**: A "Scrape runs overview" dashboard is provisioned on first start — no manual import required
- [ ] **DASH-02**: Recent failed runs panel: SQL panel on Postgres listing run_id, shop, phase, close_reason, started_at, finished_at, sorted descending by `finished_at`, last 24h default
- [ ] **DASH-03**: Dashboard logs panel filtered by `service=dashboard`, log-level highlighting (ERROR/WARNING)
- [ ] **DASH-04**: Scraper logs panel filtered by `service=scraper` (cron + reconcile stdout)
- [ ] **DASH-05**: Per-spawn logs panel filtered by Promtail-parsed `role` and `shop` labels, selectable per shop
- [ ] **DASH-06**: Dashboard exposes variable selectors for `shop`, `phase`, `run_id`, time range — all panels respect them

### Code-side Observability

- [ ] **CODEOBS-01**: `reconcile_runs._spawn_restart` writes stdout/stderr via `open_spawn_log("reconcile-restart", shop)` (replaces `subprocess.DEVNULL`); container-boot resumes leave a per-spawn log file
- [ ] **CODEOBS-02**: Dashboard reaper logs each killed run individually with `run_id`, `shop`, `phase`, `close_reason` — not just an aggregate count
- [ ] **CODEOBS-03**: `HeartbeatExtension._write_heartbeat` returning None (row vanished) triggers a WARNING log and tears down the spider via `_signal_stop`
- [ ] **CODEOBS-04**: `StallDetector._check_stall` warning line includes request count, last URL, in-flight count broken down by domain, scheduler queue size
- [ ] **CODEOBS-05**: `_spawn_scrapy_in_container` log line carries the source `run_id` when invoked from rerun / retry-failures / continue endpoints
- [ ] **CODEOBS-06**: `CronChainTrigger.spider_closed` emits a `chain_skipped` event to `scrape_run_events` when parent reason ≠ "finished"
- [ ] **CODEOBS-07**: Cron health-check window shortened to 6h and runs 4×/day (was 24h, 1×/day) so silent overnight failures surface within ≤6h
- [ ] **CODEOBS-08**: SQLAlchemy engine emits pool telemetry (overflow / wait / checkout-timeout events) at WARNING via event listeners

## Future Requirements (post-v1.2)

### Validate Phase Automation

- **VAL-AUTO-01**: Validate triggered automatically after each scan completes (cron integration)
- **VAL-AUTO-02**: Per-shop discover cadence field in shops table for stale_active threshold

### Observability v2

- **OBS-AUTO-01**: Grafana alert rules with notifier config (email or Slack) for repeated heartbeat_timeout, zero completed runs in N hours, validation_issue spikes
- **OBS-AUTO-02**: Log retention extended via Loki object-storage backend (S3/MinIO) for >1 month history
- **OBS-AUTO-03**: Per-shop SLO dashboard (uptime, completion rate, p95 scrape duration) — once SLOs are defined

## Out of Scope (v1.2)

| Feature | Reason |
|---------|--------|
| Auto-fix of validation issues | Validate only flags; operator decides remediation — by design (carried from v1.1) |
| Match phase implementation | Separate future milestone (carried from v1.1) |
| Cross-shop duplicate detection | Different shops may legitimately carry same books (carried from v1.1) |
| Alerts / notifications | Visibility-only milestone; alerting is its own design problem (routing, paging, dedup) |
| Log retention beyond Loki defaults (~1 week) | Adequate for personal-project incident response; longer retention deferred to OBS-AUTO-02 |
| Per-shop SLO dashboards | Premature — no SLOs defined yet |
| Custom dashboard /logs page | Superseded by Grafana stack; would duplicate effort |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| VAL-01..14 | Phase 1 (v1.1) | Complete |
| LOGINFRA-01..07 | TBD | Pending |
| DASH-01..06 | TBD | Pending |
| CODEOBS-01..08 | TBD | Pending |

**Coverage:**
- v1.1 requirements: 14 total, 14 mapped, 0 unmapped ✓
- v1.2 requirements: 21 total, 0 mapped (roadmap pending) ⚠

---
*Requirements defined: 2026-05-10*
*Last updated: 2026-05-13 after v1.2 (Observability) milestone definition*
