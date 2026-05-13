# Phase 2: Log Infrastructure — Discussion Log

**Captured:** 2026-05-13
**Mode:** discuss (default)
**Areas selected by operator:** Compose layout, Promtail → container stdout
**Areas skipped (Claude's discretion with defaults):** Retention + credentials, Provisioning + config layout

For human reference only — downstream agents read `02-CONTEXT.md`, not this file.

---

## Area: Compose layout

### Q1 — How should the observability stack be wired into compose?

**Options presented:**
- Add to existing `docker-compose.yml` (Recommended)
- Separate `docker-compose.observability.yml` (opt-in via `-f` or `include:`)
- Compose profile (`profiles: [observability]`)

**Operator selected:** Add to existing `docker-compose.yml`.

**Notes:** Personal-project posture wins — one file, one command. Profile flag is forgettable; split file is a second pattern to remember. Always-on cost (~200 MB RAM) is fine.

### Q2 — Rebuild/restart contract

**Options presented:**
- Just `docker compose up -d` (Recommended) — upstream images, no build
- Pin image versions in compose

**Operator selected:** Just `docker compose up -d`.

**Notes:** Accept upstream `:latest` for v1.2. If breakage happens, pin in a follow-up.

---

## Area: Promtail → container stdout

### Q1 — How should Promtail read container stdout?

**Options presented:**
- Docker socket mount + `docker_sd_configs` (Recommended)
- Docker `loki` logging driver
- Log to file, scrape file

**Operator selected:** Docker socket mount.

**Notes:** Same blast radius as the dashboard's existing `/var/run/docker.sock` mount (api.py:611). No new attack surface. Logging driver requires plugin install; file-based requires per-service code changes.

### Q2 — What labels should Promtail attach?

**Options presented:**
- `service` (always)
- `level` (parse from log)
- `role` + `shop` (for /var/log/scrapy_runs/*)
- `container_id` / `docker_image`

**Operator selected:** "what do u suggest" — asked for Claude's recommendation.

**Claude recommended (and locked in):** `service`, `level`, `role`, `shop`. Skipped `container_id` (low value, `service` covers it).

**Notes:** Hard rule established — `run_id` stays in log content, NOT a label. Loki labels must be low-cardinality; `run_id` would explode the index. Use `|= "run_id=N"` LogQL filter for run-specific queries. Documented in CONTEXT.md as a guardrail for Phase 4's CODEOBS-02 log line format.

---

## Areas Skipped (Claude's discretion)

The following weren't worth a back-and-forth; defaults captured in `02-CONTEXT.md` under "Claude's Discretion":

- **Retention + credentials:** Loki 7d explicit; Grafana admin/admin with first-login prompt; Postgres data source reuses `postgres/postgres` dev creds.
- **Provisioning + config layout:** `monitoring/` at repo root with subdirs for Grafana / Loki / Promtail configs. Standard Grafana convention.

If the planner finds reason to deviate from any default, raise it in PLAN.md.

---

## Deferred Ideas (captured for backlog)

None new from this discussion — the milestone-level backlog (alerts, object-storage retention, SLO dashboards, image pinning) already covers everything that came up.

---

## Decision Outcomes

All locked decisions feed `02-CONTEXT.md` `## Decisions` section directly. Researcher (none spawned — research disabled) and planner read CONTEXT.md, not this file.
