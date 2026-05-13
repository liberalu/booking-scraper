# Observability — Log Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up Grafana + Loki + Promtail alongside the existing compose stack and ingest every log source (container stdout + `/var/log/scraper.log` + per-spawn files under `/var/log/scrapy_runs/`) so log lines are queryable from one UI. Register Postgres as a Grafana data source for SQL panels. Provision a placeholder dashboard so the provisioning path is exercised; the real "Scrape runs overview" dashboard is built in the next phase.

**Architecture:** Three new long-lived containers (Loki, Promtail, Grafana) added to `docker-compose.yml`. Promtail mounts the Docker socket for container-stdout scraping (Docker SD), the host `/var/lib/docker/containers/` directory for the JSON log files those services produce, and the existing `scraper_logs` named volume read-only to tail `/var/log/scraper.log` and `/var/log/scrapy_runs/spawn-*.log`. Grafana provisioning lives in `monitoring/` at the repo root, bind-mounted into the Grafana container. Loki and Promtail are Distroless images (no shell), so neither has a Compose healthcheck — readiness is verified by the smoke test's `curl` probes from the host. Grafana is Alpine-based and keeps its `/api/health` wget probe.

**Tech Stack:** Docker Compose (existing), `grafana/loki:latest` (TSDB schema, filesystem store, 7d retention via compactor), `grafana/promtail:latest` (Docker SD + two static file scrape jobs with regex-extracted labels), `grafana/grafana:latest` (Alpine; provisioned data sources + dashboard provider). Configs are YAML. Postgres data source reuses the dev creds already in `docker-compose.yml`.

---

## File Structure

| File | Created/Modified | Responsibility |
|---|---|---|
| `monitoring/loki/loki-config.yml` | Create | Loki single-binary config — TSDB schema, filesystem chunks, 7d retention compactor |
| `monitoring/promtail/promtail-config.yml` | Create | Three scrape jobs (`containers` via Docker SD, `scrapy_spawn_files` via file glob with regex labels, `scraper_log_file`) shipping to `loki:3100` |
| `monitoring/grafana/provisioning/datasources/loki.yml` | Create | Auto-register Loki as the default Grafana data source |
| `monitoring/grafana/provisioning/datasources/postgres.yml` | Create | Auto-register Postgres pointed at `book_scraper` DB |
| `monitoring/grafana/provisioning/dashboards/dashboards.yml` | Create | Tell Grafana to read JSON dashboards from `/var/lib/grafana/dashboards` on first start |
| `monitoring/grafana/dashboards/placeholder.json` | Create | Markdown-only "you're ready" panel — proves provisioning works; Phase 3 replaces it |
| `monitoring/{loki,promtail,...}/.gitkeep` × 5 | Create | Track empty directories so compose bind mounts resolve before configs land |
| `docker-compose.yml` | Modify (append-only) | Three new services + two new named volumes; existing services untouched |
| `CLAUDE.md` | Modify (append) | Operator-facing Grafana URL + credentials + observability rebuild rule + label-cardinality guardrail |

**Why this split:** Grafana provisioning, Promtail scrape config, and Loki retention config each have one responsibility. Compose changes are append-only so the diff stays auditable. Directory scaffolding is its own task because compose bind mounts fail if their targets don't exist — order matters.

---

## Task 1: Create the `monitoring/` directory scaffold

**Files:**
- Create: `monitoring/loki/.gitkeep`
- Create: `monitoring/promtail/.gitkeep`
- Create: `monitoring/grafana/provisioning/datasources/.gitkeep`
- Create: `monitoring/grafana/provisioning/dashboards/.gitkeep`
- Create: `monitoring/grafana/dashboards/.gitkeep`

Compose bind mounts fail with "no such file or directory" if their host targets don't exist. Creating these before touching `docker-compose.yml` means any later `docker compose up -d` is safe.

- [ ] **Step 1: Create the directories and tracking files**

Run from repo root:

```bash
mkdir -p monitoring/loki monitoring/promtail \
         monitoring/grafana/provisioning/datasources \
         monitoring/grafana/provisioning/dashboards \
         monitoring/grafana/dashboards
touch monitoring/loki/.gitkeep \
      monitoring/promtail/.gitkeep \
      monitoring/grafana/provisioning/datasources/.gitkeep \
      monitoring/grafana/provisioning/dashboards/.gitkeep \
      monitoring/grafana/dashboards/.gitkeep
```

- [ ] **Step 2: Verify the tree**

```bash
find monitoring -type d | sort
find monitoring -name .gitkeep | wc -l
```

Expected output:
```
monitoring
monitoring/grafana
monitoring/grafana/dashboards
monitoring/grafana/provisioning
monitoring/grafana/provisioning/dashboards
monitoring/grafana/provisioning/datasources
monitoring/loki
monitoring/promtail
       5
```

- [ ] **Step 3: Commit**

```bash
git add monitoring/
git commit -m "feat(observability): scaffold monitoring/ directory for compose bind mounts"
```

---

## Task 2: Append Loki + Promtail + Grafana services to `docker-compose.yml`

**Files:**
- Modify: `docker-compose.yml` (append-only — preserve every existing service byte-for-byte)

The existing services (`postgres`, `postgres-test`, `flaresolverr`, `scraper`, `dashboard`) plus their volume block stay exactly as they are. Three new services + two new named volumes get appended.

- [ ] **Step 1: Append three new services after the `dashboard:` block**

Open `docker-compose.yml`. Locate the end of the `dashboard:` service definition (the line `- scraper_logs:/var/log:ro` followed by a blank line, then the `volumes:` block at file scope). Insert the following YAML between the `dashboard:` service and the file-scope `volumes:` block. Two-space indent for the keys at services level:

```yaml
  loki:
    image: grafana/loki:latest
    restart: unless-stopped
    command: -config.file=/etc/loki/loki-config.yml
    ports:
      - "3100:3100"
    volumes:
      - ./monitoring/loki:/etc/loki:ro
      - loki_data:/loki
    # No healthcheck declared — Loki's official image is Distroless (no shell,
    # no wget) so the standard `CMD-SHELL wget /ready` pattern doesn't work.
    # Plan smoke test (Task 8) verifies Loki's `/ready` endpoint directly via
    # curl from the host. Other services use `depends_on: service_started`
    # to wait for the container to start (not health).

  promtail:
    image: grafana/promtail:latest
    restart: unless-stopped
    command: -config.file=/etc/promtail/promtail-config.yml
    depends_on:
      loki:
        condition: service_started
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      # Host containers dir for the docker_sd_configs __path__ rewrite —
      # Promtail tails the JSON-file logs Docker writes per container.
      # Without this mount the `containers` scrape job in
      # monitoring/promtail/promtail-config.yml resolves __path__ to
      # /var/lib/docker/containers/<id>/<id>-json.log and gets ENOENT
      # inside the Promtail container. On macOS Docker Desktop the path
      # is surfaced from the VM via the bind mount; works the same as
      # /var/run/docker.sock does for the `dashboard` service.
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - scraper_logs:/var/log:ro
      - ./monitoring/promtail:/etc/promtail:ro
    # No healthcheck — Distroless image, same reason as Loki. The Task 8
    # smoke test verifies end-to-end that lines reach Loki, which proves
    # Promtail is functional.

  grafana:
    image: grafana/grafana:latest
    restart: unless-stopped
    depends_on:
      loki:
        condition: service_started
      postgres:
        condition: service_healthy
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_AUTH_ANONYMOUS_ENABLED: "false"
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_INSTALL_PLUGINS: ""
    volumes:
      - ./monitoring/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./monitoring/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafana_data:/var/lib/grafana
    healthcheck:
      # Grafana's official image is Alpine-based and has wget. Probe the
      # internal /api/health endpoint — it returns {"database":"ok",...}
      # once the DB connection is established.
      test: ["CMD-SHELL", "wget -q -O- http://localhost:3000/api/health | grep -q '\"database\": \"ok\"'"]
      interval: 10s
      timeout: 5s
      retries: 6
      start_period: 30s
```

- [ ] **Step 2: Add two new named volumes**

Modify the file-scope `volumes:` block at the very bottom of `docker-compose.yml`. Before:

```yaml
volumes:
  pgdata:
  pgdata_test:
  scraper_logs:
```

After:

```yaml
volumes:
  pgdata:
  pgdata_test:
  scraper_logs:
  loki_data:
  grafana_data:
```

- [ ] **Step 3: Validate compose syntax**

```bash
docker compose config --quiet
echo "exit=$?"
```

Expected: `exit=0`. If non-zero, the compose file failed to parse — read the error and fix.

- [ ] **Step 4: Validate the new services and mounts via grep**

```bash
grep -c "^  loki:" docker-compose.yml
grep -c "^  promtail:" docker-compose.yml
grep -c "^  grafana:" docker-compose.yml
grep -c "/var/run/docker.sock:/var/run/docker.sock:ro" docker-compose.yml
grep -c "/var/lib/docker/containers:/var/lib/docker/containers:ro" docker-compose.yml
grep -c "scraper_logs:/var/log:ro" docker-compose.yml
grep -c "GF_AUTH_ANONYMOUS_ENABLED" docker-compose.yml
grep -c "^  postgres:" docker-compose.yml
grep -c "^  dashboard:" docker-compose.yml
```

Expected output:
```
1
1
1
1
1
2
1
1
1
```

(The `2` for `scraper_logs:/var/log:ro` is the dashboard + promtail count — both mount that volume read-only. Existing services still report 1 each.)

- [ ] **Step 5: Confirm Loki and Promtail have no healthcheck blocks**

```bash
awk '/^  loki:/,/^  [a-z]/' docker-compose.yml | grep -c '^    healthcheck:'
awk '/^  promtail:/,/^  [a-z]/' docker-compose.yml | grep -c '^    healthcheck:'
```

Expected output:
```
0
0
```

(`awk` extracts the block between `  loki:` and the next top-level service line; `grep` counts `healthcheck:` keys at the right indent. Both must be 0.)

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(observability): add loki, promtail, grafana services to docker-compose"
```

---

## Task 3: Write the Loki single-binary config

**Files:**
- Create: `monitoring/loki/loki-config.yml`

TSDB schema (v13), filesystem chunk store, 7d retention enforced by the compactor.

- [ ] **Step 1: Create the file**

Write `monitoring/loki/loki-config.yml` with these exact contents:

```yaml
# Loki single-binary config for the book-scraper observability stack.
#
# Design notes:
# - Single-binary mode: filesystem chunk store, no S3/MinIO, no Memberlist.
# - TSDB schema (Loki 3.0+ default).
# - 7-day retention enabled via the compactor (LOGINFRA-04).
# - auth_enabled: false — single-tenant deployment on a private compose network.

auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096
  log_level: info

common:
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    instance_addr: 127.0.0.1
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

storage_config:
  tsdb_shipper:
    active_index_directory: /loki/tsdb-index
    cache_location: /loki/tsdb-cache
  filesystem:
    directory: /loki/chunks

limits_config:
  # 7-day retention satisfies LOGINFRA-04.
  retention_period: 168h
  reject_old_samples: true
  reject_old_samples_max_age: 168h
  # Single-tenant defaults; keep modest to avoid surprise OOM on a personal machine.
  ingestion_rate_mb: 4
  ingestion_burst_size_mb: 6
  max_entries_limit_per_query: 5000

compactor:
  working_directory: /loki/compactor
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 150
  delete_request_store: filesystem

# Ruler / alertmanager intentionally absent — alerting deferred per CONTEXT.md.
```

- [ ] **Step 2: Validate the YAML parses**

```bash
python3 -c "import yaml; cfg = yaml.safe_load(open('monitoring/loki/loki-config.yml')); print('auth_enabled =', cfg['auth_enabled']); print('retention_period =', cfg['limits_config']['retention_period']); print('retention_enabled =', cfg['compactor']['retention_enabled']); print('schema =', cfg['schema_config']['configs'][0]['schema'])"
```

Expected output:
```
auth_enabled = False
retention_period = 168h
retention_enabled = True
schema = v13
```

- [ ] **Step 3: Commit**

```bash
git add monitoring/loki/loki-config.yml
git commit -m "feat(observability): add Loki single-binary config with 7d retention"
```

---

## Task 4: Write the Promtail config with three scrape jobs

**Files:**
- Create: `monitoring/promtail/promtail-config.yml`

Three jobs:
1. `containers` — Docker SD reads container stdout via `/var/run/docker.sock`, labels with `service`.
2. `scrapy_spawn_files` — globs `/var/log/scrapy_runs/spawn-*.log`, parses filename into `role` + `shop` labels.
3. `scraper_log_file` — `/var/log/scraper.log` (cron aggregate output).

The forbidden-label contract (`run_id` must NEVER become a label — it's unbounded; filter via LogQL `|= "run_id=N"`) is in a header comment so future edits don't drift.

- [ ] **Step 1: Create the file**

Write `monitoring/promtail/promtail-config.yml` with these exact contents:

```yaml
# Promtail config for the book-scraper observability stack.
#
# Three scrape jobs:
#   1. containers       — container stdout via docker_sd_configs
#   2. scrapy_spawn_files — /var/log/scrapy_runs/spawn-*.log via static_configs
#   3. scraper_log_file  — /var/log/scraper.log (cron-output aggregate)
#
# LABEL CARDINALITY CONTRACT:
#   Allowed labels:  service, level, role, shop
#   Forbidden:       run_id (would explode the index — use `|= "run_id=N"` in LogQL instead)
#                    container_id, docker_image (low filter value, high cardinality)

server:
  http_listen_port: 9080
  grpc_listen_port: 0
  log_level: info

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:

  # ─── 1. Container stdout (Docker service discovery) ───────────────────
  - job_name: containers
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 15s
    relabel_configs:
      # Use the compose service name as `service` label.
      - source_labels: ['__meta_docker_container_label_com_docker_compose_service']
        target_label: service
      # Drop containers without a compose service label (e.g., one-off `docker run`).
      - source_labels: [service]
        regex: '^$'
        action: drop
      # Promtail needs `__path__` to know where to read; docker_sd doesn't set it,
      # so resolve via the standard /var/lib/docker/containers/<id>/<id>-json.log path
      # that Docker writes by default. Source the container id from the meta label.
      - source_labels: ['__meta_docker_container_id']
        target_label: '__path__'
        replacement: '/var/lib/docker/containers/$1/$1-json.log'
    pipeline_stages:
      # Docker writes JSON-per-line; extract the actual log line.
      - json:
          expressions:
            output: log
            stream: stream
            timestamp: time
      - timestamp:
          source: timestamp
          format: RFC3339Nano
      - output:
          source: output
      # Parse level from common Python / uvicorn / scrapy formats.
      # Examples we hit: "INFO  [alembic.runtime.migration] ..."
      #                  "2026-05-12 16:58:58 [scrapy.core.engine] INFO: Spider closed"
      #                  "ERROR:    Application startup failed"
      - regex:
          expression: '(?P<level>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b'
      - labels:
          level:

  # ─── 2. Per-spawn scrapy log files ────────────────────────────────────
  # Filenames: spawn-YYYYMMDD-HHMMSSffffff-<role>-<shop>.log
  #   <role>: operator | stall-resume | cron-chain | reconcile-restart
  #   <shop>: vaga | pegasas | humanitas | knygos | almalittera | tytoalba | ...
  - job_name: scrapy_spawn_files
    static_configs:
      - targets:
          - localhost
        labels:
          service: scraper
          job: scrapy_spawn_files
          __path__: /var/log/scrapy_runs/spawn-*.log
    pipeline_stages:
      # Extract role + shop from the filename:
      #   spawn-YYYYMMDD-HHMMSSffffff-<role>-<shop>.log
      #   ↑8 digits ↑12 digits (HH+MM+SS=6 + microseconds=6)
      # `role` is greedy + may contain hyphens (e.g. `stall-resume`).
      # `shop` is bounded to no-hyphen chars (every current/backlog shop name
      # is hyphen-free), so the greedy role consumes up to the LAST hyphen
      # and shop is the trailing chunk.
      - regex:
          source: filename
          expression: '/spawn-\d{8}-\d{12}-(?P<role>[a-z0-9_-]+)-(?P<shop>[a-z0-9_]+)\.log$'
      - labels:
          role:
          shop:
      - regex:
          expression: '(?P<level>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b'
      - labels:
          level:

  # ─── 3. Cron-output aggregate file ────────────────────────────────────
  - job_name: scraper_log_file
    static_configs:
      - targets:
          - localhost
        labels:
          service: scraper
          role: cron
          job: scraper_log_file
          __path__: /var/log/scraper.log
    pipeline_stages:
      - regex:
          expression: '(?P<level>DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b'
      - labels:
          level:
```

- [ ] **Step 2: Validate the YAML parses and the structure is correct**

```bash
python3 -c "import yaml; cfg = yaml.safe_load(open('monitoring/promtail/promtail-config.yml')); assert len(cfg['scrape_configs']) == 3, 'must have 3 jobs'; assert cfg['clients'][0]['url'] == 'http://loki:3100/loki/api/v1/push', 'wrong loki url'; print('ok, jobs:', [j['job_name'] for j in cfg['scrape_configs']])"
```

Expected output:
```
ok, jobs: ['containers', 'scrapy_spawn_files', 'scraper_log_file']
```

- [ ] **Step 3: Write a regex smoke test as a temporary script**

The label-extraction regex is the most subtle part of this file. Test it before committing.

Create `/tmp/test_promtail_regex.py`:

```python
import re
import yaml

cfg = yaml.safe_load(open("monitoring/promtail/promtail-config.yml"))
job = [j for j in cfg["scrape_configs"] if j["job_name"] == "scrapy_spawn_files"][0]
pattern = [
    s["regex"]["expression"]
    for s in job["pipeline_stages"]
    if "regex" in s and "role" in s["regex"]["expression"]
][0]

tests = {
    "/var/log/scrapy_runs/spawn-20260512-165858302771-operator-vaga.log":
        ("operator", "vaga"),
    "/var/log/scrapy_runs/spawn-20260513-100000000000-stall-resume-humanitas.log":
        ("stall-resume", "humanitas"),
    "/var/log/scrapy_runs/spawn-20260513-100000000000-cron-chain-pegasas.log":
        ("cron-chain", "pegasas"),
    "/var/log/scrapy_runs/spawn-20260513-100000000000-reconcile-restart-vaga.log":
        ("reconcile-restart", "vaga"),
    "/var/log/scrapy_runs/spawn-20260513-100000000000-operator-tytoalba.log":
        ("operator", "tytoalba"),
}

failures = []
for path, (want_role, want_shop) in tests.items():
    m = re.search(pattern, path)
    if not m:
        failures.append(f"NO MATCH: {path}")
        continue
    got_role, got_shop = m.group("role"), m.group("shop")
    if (got_role, got_shop) != (want_role, want_shop):
        failures.append(
            f"WRONG SPLIT: {path}\n  want role={want_role!r} shop={want_shop!r}\n  got  role={got_role!r} shop={got_shop!r}"
        )

if failures:
    for f in failures:
        print("FAIL:", f)
    raise SystemExit(1)
print(f"OK — {len(tests)} regex cases pass")
```

- [ ] **Step 4: Run the smoke test**

```bash
python3 /tmp/test_promtail_regex.py
```

Expected output:
```
OK — 5 regex cases pass
```

If you see any `FAIL:` lines, the regex is wrong — fix the `expression:` line in `promtail-config.yml` and re-run.

- [ ] **Step 5: Clean up the temp script**

```bash
rm /tmp/test_promtail_regex.py
```

- [ ] **Step 6: Commit**

```bash
git add monitoring/promtail/promtail-config.yml
git commit -m "feat(observability): add Promtail config with 3 scrape jobs + label regex"
```

---

## Task 5: Provision Loki + Postgres as Grafana data sources

**Files:**
- Create: `monitoring/grafana/provisioning/datasources/loki.yml`
- Create: `monitoring/grafana/provisioning/datasources/postgres.yml`

Auto-registered on first Grafana startup — no manual UI clicks.

- [ ] **Step 1: Create the Loki data source file**

Write `monitoring/grafana/provisioning/datasources/loki.yml`:

```yaml
# Grafana data source — Loki.
# Lives on the default compose network; reached by service name.
apiVersion: 1

datasources:
  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    isDefault: true
    editable: false
    jsonData:
      maxLines: 1000
      timeout: 60
```

- [ ] **Step 2: Create the Postgres data source file**

Write `monitoring/grafana/provisioning/datasources/postgres.yml`:

```yaml
# Grafana data source — Postgres (book_scraper DB).
# Credentials reuse the dev creds from docker-compose.yml. A dedicated
# read-only role is deferred to a future cleanup.
apiVersion: 1

datasources:
  - name: Postgres (book_scraper)
    type: postgres
    access: proxy
    url: postgres:5432
    user: postgres
    secureJsonData:
      password: postgres
    jsonData:
      database: book_scraper
      sslmode: disable
      postgresVersion: 1600
      timescaledb: false
    editable: false
```

- [ ] **Step 3: Validate both YAMLs**

```bash
python3 -c "import yaml; yaml.safe_load(open('monitoring/grafana/provisioning/datasources/loki.yml')); yaml.safe_load(open('monitoring/grafana/provisioning/datasources/postgres.yml')); print('both valid')"
grep -c "url: http://loki:3100" monitoring/grafana/provisioning/datasources/loki.yml
grep -c "url: postgres:5432" monitoring/grafana/provisioning/datasources/postgres.yml
grep -c "database: book_scraper" monitoring/grafana/provisioning/datasources/postgres.yml
grep -c "secureJsonData:" monitoring/grafana/provisioning/datasources/postgres.yml
```

Expected:
```
both valid
1
1
1
1
```

- [ ] **Step 4: Commit**

```bash
git add monitoring/grafana/provisioning/datasources/
git commit -m "feat(observability): provision Loki and Postgres as Grafana data sources"
```

---

## Task 6: Provision the dashboard provider + placeholder dashboard

**Files:**
- Create: `monitoring/grafana/provisioning/dashboards/dashboards.yml`
- Create: `monitoring/grafana/dashboards/placeholder.json`

The provider config tells Grafana to load any `*.json` dashboard from `/var/lib/grafana/dashboards`. The placeholder is a markdown-only panel that proves provisioning works end-to-end — the next phase replaces it with the real "Scrape runs overview".

- [ ] **Step 1: Create the dashboard provider config**

Write `monitoring/grafana/provisioning/dashboards/dashboards.yml`:

```yaml
# Grafana dashboard provider — points at the bind-mounted dashboards directory.
# Drop a *.json file under monitoring/grafana/dashboards/ and it appears in
# Grafana on next reload (or immediately when allowUiUpdates=false +
# updateIntervalSeconds=10).
apiVersion: 1

providers:
  - name: book-scraper
    orgId: 1
    folder: ''
    type: file
    disableDeletion: true
    allowUiUpdates: false
    updateIntervalSeconds: 10
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: false
```

- [ ] **Step 2: Create the placeholder dashboard JSON**

Write `monitoring/grafana/dashboards/placeholder.json`:

```json
{
  "uid": "observability-placeholder",
  "title": "Observability — placeholder",
  "tags": ["placeholder", "phase-2"],
  "timezone": "browser",
  "schemaVersion": 39,
  "version": 1,
  "refresh": "",
  "time": {"from": "now-6h", "to": "now"},
  "templating": {"list": []},
  "annotations": {"list": []},
  "panels": [
    {
      "id": 1,
      "type": "text",
      "title": "Phase 2 placeholder",
      "gridPos": {"h": 8, "w": 24, "x": 0, "y": 0},
      "options": {
        "mode": "markdown",
        "content": "# Observability — placeholder\n\nPhase 2 (Log Infrastructure) successfully provisioned this dashboard, which means:\n\n- The dashboard provider config at `/etc/grafana/provisioning/dashboards/dashboards.yml` is being read.\n- The bind-mount `./monitoring/grafana/dashboards/` → `/var/lib/grafana/dashboards/` is working.\n- Both data sources (Loki, Postgres) are registered.\n\nPhase 3 will replace this dashboard with the real **Scrape runs overview** — failed-runs SQL panel from Postgres + cross-filterable log panels from Loki.\n\n_If you're seeing this in production, Phase 3 hasn't landed yet._"
      }
    }
  ]
}
```

- [ ] **Step 3: Validate both files**

```bash
python3 -c "import yaml; yaml.safe_load(open('monitoring/grafana/provisioning/dashboards/dashboards.yml')); import json; d = json.load(open('monitoring/grafana/dashboards/placeholder.json')); assert d['uid'] == 'observability-placeholder'; assert d['title'] == 'Observability — placeholder'; print('both valid, dashboard uid:', d['uid'])"
grep -c "path: /var/lib/grafana/dashboards" monitoring/grafana/provisioning/dashboards/dashboards.yml
```

Expected:
```
both valid, dashboard uid: observability-placeholder
1
```

- [ ] **Step 4: Commit**

```bash
git add monitoring/grafana/provisioning/dashboards/dashboards.yml monitoring/grafana/dashboards/placeholder.json
git commit -m "feat(observability): provision Grafana dashboard provider + placeholder JSON"
```

---

## Task 7: Document the operator-facing facts in `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` (append only — find the existing "Key Commands" block and the "Post-Task Checklist" section)

Two small additions: a commands block, a new checklist item, and a label-cardinality guardrail section. No existing content gets rewritten.

- [ ] **Step 1: Append observability commands to the existing "Key Commands" code block**

Open `CLAUDE.md`, find the `## Key Commands` section, locate the closing ` ``` ` of its code block (after the dashboard smoke test line). Insert these lines immediately before the closing fence:

```
# Observability (v1.2)
open http://localhost:3000                                           # Grafana — login admin/admin (change on first use)
docker compose up -d loki promtail grafana                          # bring observability stack up after compose changes
docker compose restart grafana                                       # reload Grafana provisioning (data sources, dashboards)
curl -s 'http://localhost:3100/loki/api/v1/labels' | jq             # list active Loki labels (sanity check)
curl -s 'http://localhost:3100/loki/api/v1/query?query={service="dashboard"}&limit=5' | jq  # last 5 dashboard lines
```

- [ ] **Step 2: Append a new checklist item + cardinality guardrail to the "Post-Task Checklist" section**

Find the `## Post-Task Checklist` section. It currently has items 1-4. Locate the end of item 4 (before the next `## ` top-level heading — likely `## Counter drift probe`). Insert this content immediately before that next heading:

```markdown
5. **Observability stack changes** (`monitoring/`, Grafana provisioning, Promtail config, Loki config): no rebuild — just `docker compose up -d loki promtail grafana` (or `docker compose restart grafana` for provisioning-only edits). Upstream images are pulled, not built.

### Observability label cardinality (Loki)

The Loki index can only afford low-cardinality labels. The four allowed labels are:
- `service` — bounded set (dashboard, scraper, postgres, flaresolverr, loki, promtail, grafana)
- `level` — INFO / WARNING / ERROR / DEBUG / CRITICAL
- `role` — operator / stall-resume / cron-chain / reconcile-restart / cron
- `shop` — vaga / pegasas / humanitas / future shops

**Never promote `run_id` to a label.** It's unbounded and would explode the index. Filter via LogQL `|= "run_id=N"` instead. Phase 4 (CODEOBS-02) emits `key=value` log lines so `| logfmt` works.
```

- [ ] **Step 3: Verify the additions**

```bash
grep -c "http://localhost:3000" CLAUDE.md
grep -c "docker compose up -d loki promtail grafana" CLAUDE.md
grep -c "Observability stack changes" CLAUDE.md
grep -c "Never promote" CLAUDE.md
grep -c "loki/api/v1/labels" CLAUDE.md
```

Expected:
```
1
1
1
1
1
```

- [ ] **Step 4: Confirm the diff is append-only**

```bash
git diff CLAUDE.md --stat
git diff CLAUDE.md | grep -c '^-[^-]' || echo "0 deletions"
```

Expected: the `--stat` line shows insertions only; `^-[^-]` count is `0` (or `echo "0 deletions"` fires).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(observability): document Grafana URL, commands, and label-cardinality guardrail"
```

---

## Task 8: End-to-end smoke test

**Files:** (none modified — this task verifies the stack from outside)

This is the functional gate for the phase. Bring everything up, wait for readiness, verify Loki + Promtail + Grafana respond, and confirm at least one dashboard log line landed in Loki via Promtail's Docker SD job.

- [ ] **Step 1: Pull the new images**

```bash
docker compose pull loki promtail grafana
```

Expected: each image downloads (one-time, ~200 MB total). Re-running on a warm cache is a near-instant no-op.

- [ ] **Step 2: Bring the full stack up**

OrbStack/Docker Desktop proxy vars can poison container env (per CLAUDE.md). Clear them before `up`:

```bash
HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy="" ALL_PROXY="" all_proxy="" docker compose up -d
```

Expected: 7 services start (postgres, flaresolverr, scraper, dashboard, loki, promtail, grafana). `postgres-test` stays stopped (it's under the `test` profile).

- [ ] **Step 3: Wait for readiness (mixed healthcheck + state strategy)**

```bash
deadline=$((SECONDS + 120))
services_with_healthcheck="postgres scraper dashboard grafana"
services_without_healthcheck="flaresolverr loki promtail"
while [ $SECONDS -lt $deadline ]; do
  all_ok=1
  for svc in $services_with_healthcheck; do
    state=$(docker inspect --format '{{.State.Health.Status}}' "book-scraper-${svc}-1" 2>/dev/null || echo "missing")
    if [ "$state" != "healthy" ]; then all_ok=0; break; fi
  done
  if [ $all_ok -eq 1 ]; then
    for svc in $services_without_healthcheck; do
      state=$(docker inspect --format '{{.State.Status}}' "book-scraper-${svc}-1" 2>/dev/null || echo "missing")
      if [ "$state" != "running" ]; then all_ok=0; break; fi
    done
  fi
  if [ $all_ok -eq 1 ]; then echo "all ready in $((120 - (deadline - SECONDS)))s"; break; fi
  sleep 5
done
```

Expected: prints `all ready in <N>s` within 120 seconds. If it times out, jump to the troubleshooting block at the bottom of this task.

- [ ] **Step 4: Confirm services are running**

```bash
docker compose ps --format json | jq -r '.[] | select(.State == "running") | .Service' | sort
```

Expected output (one per line, sorted):
```
dashboard
flaresolverr
grafana
loki
postgres
promtail
scraper
```

- [ ] **Step 5: Probe Loki's `/ready` endpoint**

```bash
curl -fs http://localhost:3100/ready
echo
```

Expected: `ready` (Loki signals readiness once its rings and the schema are loaded).

- [ ] **Step 6: Probe Promtail's `/ready` endpoint**

```bash
curl -fs http://localhost:9080/ready
echo
```

Expected: `Ready` (case matters — Promtail returns capital R).

- [ ] **Step 7: Probe Grafana's `/api/health`**

```bash
curl -fsu admin:admin http://localhost:3000/api/health | jq
```

Expected: a JSON object with `"database": "ok"`.

- [ ] **Step 8: Generate a dashboard log line so Promtail has something to ship**

```bash
curl -fs http://localhost:8000/ -o /dev/null
sleep 10  # give Promtail a chance to scrape + push
```

Expected: silent success (no error). The 10-second sleep is for Promtail's docker_sd refresh interval (15s) + tail/push latency.

- [ ] **Step 9: Query Loki for dashboard logs**

```bash
curl -fs --data-urlencode 'query={service="dashboard"}' --data-urlencode 'limit=5' \
  http://localhost:3100/loki/api/v1/query | tee /tmp/loki-smoke.json | jq '.data.result | length'
```

Expected: a number `>= 1` (at least one log line landed). If it prints `0`, the Docker SD job isn't finding container stdout — see troubleshooting below.

- [ ] **Step 10: Confirm Grafana sees both data sources**

```bash
curl -fsu admin:admin http://localhost:3000/api/datasources | jq '[.[] | {name, type}]'
```

Expected output:
```json
[
  {"name": "Loki", "type": "loki"},
  {"name": "Postgres (book_scraper)", "type": "postgres"}
]
```

- [ ] **Step 11: Confirm Grafana auto-provisioned the placeholder dashboard**

```bash
curl -fsu admin:admin "http://localhost:3000/api/search?query=placeholder" | jq '.[] | {uid, title}'
```

Expected output:
```json
{
  "uid": "observability-placeholder",
  "title": "Observability — placeholder"
}
```

- [ ] **Step 12: Open Grafana in the browser as a final eyeball check**

```bash
open http://localhost:3000
```

Login: `admin` / `admin`. Grafana prompts to change password — set anything you like. Navigate to "Dashboards" → "Observability — placeholder". Confirm the markdown panel renders.

- [ ] **Step 13: Commit the smoke-test outcome** (no code change; commits a phase SUMMARY)

```bash
cat > .planning/phases/02-log-infrastructure/02-SUMMARY.md <<'EOF'
# Phase 2 — Log Infrastructure SUMMARY

Smoke test on YYYY-MM-DD (replace with run date):

- All 7 services running. Compose ps:
  <paste output of step 4>

- Loki `/ready`: `ready`
- Promtail `/ready`: `Ready`
- Grafana `/api/health`: `"database": "ok"`
- Loki query `{service="dashboard"}`: N results (N >= 1)
- Grafana data sources: Loki + Postgres (book_scraper)
- Placeholder dashboard uid: `observability-placeholder`

Images pulled (paste exact tags):
- grafana/loki:latest → <digest>
- grafana/promtail:latest → <digest>
- grafana/grafana:latest → <digest>

Phase 2 done. Phase 3 replaces the placeholder with the real Scrape runs overview.
EOF

# Edit the file to paste actual output, then:
git add .planning/phases/02-log-infrastructure/02-SUMMARY.md
git commit -m "docs(observability): record phase 2 smoke-test outcome"
```

### Troubleshooting

If Step 3 times out (services never reach healthy/running):
- `docker compose logs loki promtail grafana | tail -100` — read for config parse errors
- For Loki/Promtail (Distroless, no compose healthcheck): the failure mode is CrashLoopBackOff. Config files in `monitoring/loki/` or `monitoring/promtail/` are most likely wrong — re-run Task 3 or Task 4 with the exact contents from this plan.
- For Grafana (has healthcheck): `docker inspect book-scraper-grafana-1 | jq '.[0].State.Health.Log'` for the last few healthcheck stderr blocks.

If Step 9 returns 0 results:
- Confirm Task 2's `/var/lib/docker/containers:/var/lib/docker/containers:ro` mount is actually on Promtail: `docker inspect book-scraper-promtail-1 | jq '.[0].Mounts | map(.Source + " -> " + .Destination)'`
- If the mount is missing, Task 2 wasn't applied correctly — re-run it.
- If the mount IS present but reads return no data: `docker exec book-scraper-promtail-1 ls /var/lib/docker/containers/` should list one directory per running container.
- Last resort: switch the `containers` scrape job to Docker's Loki logging driver (per-service `logging:` block in compose) instead of Promtail's `docker_sd_configs`. That's documented as the deferred mitigation and noted in `02-SUMMARY.md` if used.

If Step 10 doesn't show Postgres:
- `docker exec book-scraper-grafana-1 ls /etc/grafana/provisioning/datasources/` should list `loki.yml` and `postgres.yml`. If missing, the bind mount from Task 2 didn't survive Grafana restart — verify `docker inspect book-scraper-grafana-1 | jq '.[0].Mounts'`.

---

## Verification (full phase)

Run these from the repo root after every task is committed. All should pass.

```bash
# Files in the right places
test -f docker-compose.yml
test -f monitoring/loki/loki-config.yml
test -f monitoring/promtail/promtail-config.yml
test -f monitoring/grafana/provisioning/datasources/loki.yml
test -f monitoring/grafana/provisioning/datasources/postgres.yml
test -f monitoring/grafana/provisioning/dashboards/dashboards.yml
test -f monitoring/grafana/dashboards/placeholder.json

# Compose validates
docker compose config --quiet

# YAMLs parse
python3 -c "
import yaml
for p in [
    'monitoring/loki/loki-config.yml',
    'monitoring/promtail/promtail-config.yml',
    'monitoring/grafana/provisioning/datasources/loki.yml',
    'monitoring/grafana/provisioning/datasources/postgres.yml',
    'monitoring/grafana/provisioning/dashboards/dashboards.yml',
]:
    yaml.safe_load(open(p))
print('all YAMLs valid')
"

# Dashboard JSON valid
python3 -c "
import json
d = json.load(open('monitoring/grafana/dashboards/placeholder.json'))
assert d['uid'] == 'observability-placeholder'
print('placeholder.json valid')
"

# Stack responds end-to-end
curl -fs http://localhost:3100/ready && echo
curl -fs http://localhost:9080/ready && echo
curl -fsu admin:admin http://localhost:3000/api/health | jq -e '.database == "ok"' > /dev/null && echo "grafana ok"
curl -fsu admin:admin http://localhost:3000/api/datasources | jq -e 'map(.type) | (contains(["loki"]) and contains(["postgres"]))' > /dev/null && echo "datasources ok"
curl -fsu admin:admin "http://localhost:3000/api/search?query=placeholder" | jq -e '.[] | select(.uid == "observability-placeholder")' > /dev/null && echo "placeholder dashboard ok"
```

Expected: every line either silently succeeds or prints its `ok` confirmation.

---

## Self-Review

**Spec coverage** — every LOGINFRA requirement maps to at least one task:

| REQ | Task |
|---|---|
| LOGINFRA-01 | Tasks 1 + 2 (scaffold + compose services) |
| LOGINFRA-02 | Task 4 (Promtail `containers` job via Docker SD with `service` label) |
| LOGINFRA-03 | Task 4 (Promtail `scrapy_spawn_files` + `scraper_log_file` jobs with regex labels) |
| LOGINFRA-04 | Task 3 (Loki `retention_period: 168h` + compactor `retention_enabled: true`) |
| LOGINFRA-05 | Task 5 (Loki data source provisioning) |
| LOGINFRA-06 | Task 5 (Postgres data source provisioning) |
| LOGINFRA-07 | Tasks 7 + 8 (CLAUDE.md documentation + smoke test confirms `http://localhost:3000`) |

**Placeholder scan** — every `<action>` block contains either complete file contents or a complete shell command; no `TBD`, no `TODO`, no "add appropriate X". The only ellipsis-like content is `<paste output of step 4>` in Task 8 Step 13 — that's the operator pasting their actual smoke-test output into the SUMMARY, not a deferred decision.

**Type / signature consistency** —
- Promtail's `loki:3100` URL appears identically in (a) `clients[0].url` in `promtail-config.yml` (Task 4) and (b) the Grafana Loki data source `url:` (Task 5). Both correct.
- The `scraper_logs` named volume is mounted at `/var/log:ro` in (a) the existing `dashboard` service and (b) the new `promtail` service (Task 2). Identical.
- The `/var/lib/docker/containers:/var/lib/docker/containers:ro` mount is declared exactly once in Task 2 Step 1 and grep-verified in Task 2 Step 4.
- The regex `'/spawn-\d{8}-\d{12}-(?P<role>[a-z0-9_-]+)-(?P<shop>[a-z0-9_]+)\.log$'` appears in Task 4 Step 1 (config) and Task 4 Step 3 (smoke test) — identical text.
- The placeholder dashboard `uid: observability-placeholder` appears in Task 6 Step 2 (JSON) and Task 8 Step 11 (Grafana API check) — identical.

No fixes needed.
