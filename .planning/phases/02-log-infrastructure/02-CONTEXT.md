# Phase 2: Log Infrastructure — Context

**Phase:** 2 — Log Infrastructure
**Milestone:** v1.2 — Observability
**Created:** 2026-05-13
**Status:** Context captured; ready for planning

---

## Domain

Stand up Grafana + Loki + Promtail alongside the existing compose stack so all log sources — dashboard stdout, scraper stdout, `/var/log/scraper.log` (cron output), `/var/log/scrapy_runs/spawn-*.log` (per-spawn files) — are queryable in one place. Register Postgres as a Grafana data source so the same UI can also pull `scrape_runs` / `scrape_run_events` / `validation_issues`.

Dashboard panels and queries belong to **Phase 3**; this phase only delivers the substrate. Code-side observability fixes (reconcile_runs, reaper logging, heartbeat row-vanish handling, etc.) belong to **Phase 4**.

## Requirements Covered

| ID | Description |
|---|---|
| LOGINFRA-01 | docker-compose.yml gains Grafana / Loki / Promtail services with healthchecks |
| LOGINFRA-02 | Promtail tails container stdout via Docker socket; tags `service` label |
| LOGINFRA-03 | Promtail tails `/var/log/scraper.log` and `/var/log/scrapy_runs/*.log`; spawn-log filename parsed into `role` + `shop` |
| LOGINFRA-04 | Loki retains ≥ 7 days of logs under default disk budget |
| LOGINFRA-05 | Grafana provisions Loki as a data source on first start |
| LOGINFRA-06 | Grafana provisions Postgres as a data source |
| LOGINFRA-07 | Grafana at `http://localhost:3000`; admin credentials documented in CLAUDE.md |

## Decisions

### Compose layout

- **Locked:** Add Loki / Promtail / Grafana to the existing `docker-compose.yml`. Always-on; `docker compose up -d` brings the full stack up. Personal-project posture: one file, one command, predictable.
- **Why not a profile or a split file:** Easy to forget the profile flag; split files add a second invocation pattern the operator has to remember. Cost of an always-on observability stack (~200 MB RAM) is negligible against operator confusion if it's offline when needed.
- **Rebuild contract:** No `docker compose build` step — Loki / Promtail / Grafana use upstream official images. `docker compose up -d` pulls them. CLAUDE.md's post-task checklist gets a one-line addendum referencing the new services. No image pinning in v1.2 — accept upstream `:latest` (or `:main` for Loki) for now; if breakage happens, address in a follow-up.

### Promtail → container stdout

- **Locked:** Docker socket discovery — Promtail mounts `/var/run/docker.sock` read-only and uses `docker_sd_configs`. Auto-discovers all containers. No per-service `logging:` block. No external plugins.
- **Precedent:** The dashboard service already mounts `/var/run/docker.sock:/var/run/docker.sock` for `containers[].exec_run` (book_scraper/dashboard/routes/api.py:611). Promtail's mount has the same blast radius — no new attack surface.
- **Rejected:** Docker's `loki` logging driver — requires `docker plugin install`, harder to reproduce on a fresh checkout, per-service config noise.
- **Rejected:** Log-to-file scraping per service — would require code changes in scraper + dashboard to redirect stdout, plus volume mounts; high churn for low gain.

### Promtail labels (cardinality contract)

| Label | Values | Source |
|---|---|---|
| `service` | `dashboard` / `scraper` / `postgres` / `flaresolverr` | Compose service name from Docker SD metadata |
| `level` | `INFO` / `WARNING` / `ERROR` (and `DEBUG` for completeness) | Pipeline stage: regex on log line |
| `role` | `operator` / `stall-resume` / `cron-chain` / `reconcile-restart` | Filename regex on `/var/log/scrapy_runs/spawn-*.log` |
| `shop` | `vaga` / `pegasas` / `humanitas` (extensible) | Filename regex on `/var/log/scrapy_runs/spawn-*.log` |

- **Hard rule:** `run_id` MUST stay in log **content**, not as a Loki label. Loki labels must be low-cardinality (bounded ~hundreds); `run_id` grows unbounded and would blow up the index. Filter by content via `|= "run_id=427"` in LogQL. Document this in the Promtail config comments so a future contributor doesn't add it.
- **Note for Phase 4:** Code-side fix CODEOBS-02 should write `run_id=N shop=X phase=Y close_reason=Z` as space-separated `key=value` pairs in the dashboard log line — this is Loki-idiomatic and lets LogQL `| logfmt` extract fields cheaply.

## Claude's Discretion — sensible defaults

These weren't worth discussing in detail; defaults below stand unless the planner finds a reason to deviate.

| Topic | Default | Notes |
|---|---|---|
| Loki retention | 7 days explicit (`compactor.retention_enabled: true`, `limits_config.retention_period: 168h`) | Meets LOGINFRA-04. Filesystem chunks (no S3) — fine for personal scale. |
| Loki schema | TSDB (Loki ≥ 3.0 default) | Modern, single-binary mode |
| Grafana admin | `admin` / `admin` default; Grafana prompts to change on first login | Personal-project, single operator. CLAUDE.md documents the URL + login. |
| Grafana auth | Anonymous access OFF; admin login required | Defense in depth even on localhost |
| Postgres data source role | Reuse `postgres/postgres` (matches dev compose creds) | Read-only role is a future cleanup; not worth a migration in v1.2 |
| Provisioning layout | `monitoring/` at repo root, with subdirs `monitoring/grafana/provisioning/{datasources,dashboards}/`, `monitoring/loki/loki-config.yml`, `monitoring/promtail/promtail-config.yml` | Standard Grafana convention. Mounted into containers via compose. |
| Dashboard JSON | Provisioning dir gets a minimal "placeholder" dashboard in Phase 2 (so the provisioning path is wired and tested); real dashboards land in Phase 3 | Phase boundary cleanly separates "infra works" from "panels are useful" |
| Healthchecks | All three services get HTTP healthchecks (`/ready` for Loki, `/api/health` for Grafana, `/ready` for Promtail) | Required by LOGINFRA-01 |
| Network | All services on the default compose network | Service-name resolution works (`http://loki:3100` etc.) |
| Resource limits | None in v1.2 | Personal scale — `docker stats` is enough. Add limits if it ever bites. |

## Codebase Context

### Reusable assets

| Asset | Where | How used in this phase |
|---|---|---|
| `scraper_logs` named volume | docker-compose.yml | Mounted read-only into Promtail at `/var/log` for file scraping (mirrors dashboard's existing read-only mount) |
| `spawn_logging.py` filename convention | `book_scraper/spawn_logging.py:85-86` | Promtail filename regex must match `spawn-YYYYMMDD-HHMMSSffffff-<role>-<shop>.log` |
| Compose service-name DNS | All services | `loki:3100` resolves between services; no port-mapping juggling |
| Dashboard's docker-socket mount precedent | `docker-compose.yml:75-77` | Same posture for Promtail — read-only mount of `/var/run/docker.sock` |

### Patterns to follow

- **CLAUDE.md post-task checklist:** Every infra change documents its rebuild/restart contract. v1.2 addendum: "Observability stack changes (Grafana provisioning, Promtail config, Loki config): `docker compose up -d loki promtail grafana` is enough — no rebuild."
- **Test hook:** No integration tests for compose itself in this project; existing posture is "smoke-test by `docker compose up -d` + check the URL." Phase 2 verification follows that.

### Things to NOT touch in this phase

- `book_scraper/dashboard/` — Phase 3 might add a "View in Grafana" link, but Phase 2 stays infra-only.
- `book_scraper/extensions.py`, `reconcile_runs.py`, `reaper.py` — that's Phase 4.
- Log format / log line content — Phase 4 problem (CODEOBS-02 specifies the format).

## Canonical Refs

| File | Why |
|---|---|
| `docker-compose.yml` | Where new services land |
| `book_scraper/spawn_logging.py` | Filename convention Promtail must parse |
| `CLAUDE.md` | Post-task rebuild rules + new URL + creds documentation lands here |
| `.planning/REQUIREMENTS.md` | LOGINFRA-01..07 are the contract |
| `.planning/ROADMAP.md` | Phase 2 success criteria |
| Upstream docs (for the planner): Grafana provisioning (`https://grafana.com/docs/grafana/latest/administration/provisioning/`), Loki TSDB single-binary (`https://grafana.com/docs/loki/latest/setup/install/docker/`), Promtail `docker_sd_configs` (`https://grafana.com/docs/loki/latest/send-data/promtail/configuration/#docker_sd_configs`) | Reference for config syntax |

## Deferred Ideas

Captured for the roadmap backlog; not in scope for this phase.

- **Loki object-storage backend (S3 / MinIO)** for >1-month retention — covered by OBS-AUTO-02 in REQUIREMENTS.md.
- **Grafana alert rules + notifier** — covered by OBS-AUTO-01.
- **Per-shop SLO dashboards** — covered by OBS-AUTO-03.
- **Bind-mounting `scraper_logs` to `./logs/`** for direct host-side access — possible future cleanup; not needed once Grafana is the primary log viewer.
- **Pinning image versions** — defer until first breaking change forces it.

## Out of Scope (for this phase, not the milestone)

- Dashboard JSON content (Phase 3 — the placeholder dashboard verifies provisioning works)
- Code-side log line changes (Phase 4 — CODEOBS-01..08)
- Any alerting / notifier wiring (deferred to OBS-AUTO-01)

## Success Criteria (recap from ROADMAP.md)

1. `docker compose up -d` brings up loki, promtail, grafana alongside the existing stack with no manual setup
2. Grafana at `http://localhost:3000` shows Loki + Postgres as provisioned data sources
3. A Loki query for `{service="dashboard"}` returns lines from the dashboard container in real time
4. A Loki query for `{service="scraper"}` returns lines from both cron stdout (via Docker socket) and `/var/log/scraper.log` (via file scrape)
5. A Loki query for `{role="operator", shop="vaga"}` returns lines from per-spawn log files
6. Loki retains at least 7 days of log history under default disk budget

---
*Captured: 2026-05-13 via /gsd:discuss-phase 2*
