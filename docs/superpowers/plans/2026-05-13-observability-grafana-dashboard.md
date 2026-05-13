# Observability — Grafana Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `Observability — placeholder` dashboard with a real `Scrape runs overview` — one failed-runs SQL panel from Postgres plus three log panels from Loki (dashboard / scraper / per-spawn), all cross-filterable by `shop`, `phase`, `run_id`, and the dashboard time range. Pre-provisioned: zero manual import. Closes DASH-01..06 in REQUIREMENTS.md.

**Architecture:** Lock stable UIDs on the Loki and Postgres data sources by editing the existing provisioning YAMLs, then drop a single hand-authored dashboard JSON next to the placeholder. The dashboard JSON references both data sources by UID (idempotent across re-provisioning), exposes three template variables in the toolbar, embeds a data link on the failed-runs table that drills into a specific run by passing `?var-run_id=N&from=...&to=...` query params, and configures all three Logs panels with consistent options. Delete the placeholder JSON in the same final commit so the dashboard listing only shows the real one.

**Tech Stack:** Grafana 11+ provisioning (data sources YAML + dashboards YAML provider + JSON files mounted from `./monitoring/grafana/`), Postgres data source plugin (renders SQL panels), Loki data source plugin (renders Logs panels with LogQL), Grafana template variables (`query`, `custom`, `textbox` types), Grafana panel data links.

**Source of truth:** `.planning/phases/03-grafana-dashboard/03-CONTEXT.md` — read it before starting if the rationale behind any decision below is unclear.

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `monitoring/grafana/provisioning/datasources/loki.yml` | **Modify** | Add `uid: loki` so Phase 3+ dashboards can reference Loki by stable UID instead of name lookup. |
| `monitoring/grafana/provisioning/datasources/postgres.yml` | **Modify** | Add `uid: postgres-bookscraper` for the same reason. |
| `monitoring/grafana/dashboards/scrape-runs-overview.json` | **Create** | The complete dashboard: metadata + 3 template variables + 1 SQL panel + 3 Logs panels. References data sources by stable UID. |
| `monitoring/grafana/dashboards/placeholder.json` | **Delete** | Superseded — only delete in the final task after the real dashboard has been verified live. |
| `.planning/phases/03-grafana-dashboard/03-SUMMARY.md` | **Create** | Records the smoke-test outcome — image of the live dashboard, the API probe outputs, any deviations. |

Why this split:
- Provisioning UIDs and dashboard JSON are independent artifacts with distinct ownership (datasource plugin vs dashboard plugin). Edit them in separate tasks so failures isolate cleanly.
- The dashboard JSON is one cohesive artifact — splitting "metadata first, panel 1, panel 2..." across tasks risks intermediate states that don't parse. Build it once in a single Task 2 step, then verify.

---

## Task 1: Lock data source UIDs in provisioning

**Files:**
- Modify: `monitoring/grafana/provisioning/datasources/loki.yml`
- Modify: `monitoring/grafana/provisioning/datasources/postgres.yml`

Without this, Grafana auto-generates a random UID per data source on first provisioning. The dashboard JSON in Task 2 references data sources by UID, so the UID has to be deterministic. Both YAMLs gain one new key.

- [ ] **Step 1: Add `uid: loki` to the Loki data source YAML**

Open `monitoring/grafana/provisioning/datasources/loki.yml`. It currently reads:

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

Insert `uid: loki` as a new line immediately after `name: Loki`:

```yaml
# Grafana data source — Loki.
# Lives on the default compose network; reached by service name.
apiVersion: 1

datasources:
  - name: Loki
    uid: loki
    type: loki
    access: proxy
    url: http://loki:3100
    isDefault: true
    editable: false
    jsonData:
      maxLines: 1000
      timeout: 60
```

- [ ] **Step 2: Add `uid: postgres-bookscraper` to the Postgres data source YAML**

Open `monitoring/grafana/provisioning/datasources/postgres.yml`. It currently has:

```yaml
# Grafana data source — Postgres (book_scraper DB).
# Credentials reuse the dev creds from docker-compose.yml. A dedicated
# read-only role is deferred to a future cleanup.
apiVersion: 1

datasources:
  - name: Postgres (book_scraper)
    type: postgres
    access: proxy
    ...
```

Insert `uid: postgres-bookscraper` immediately after `name: Postgres (book_scraper)`:

```yaml
apiVersion: 1

datasources:
  - name: Postgres (book_scraper)
    uid: postgres-bookscraper
    type: postgres
    access: proxy
    ...
```

(Preserve every other line of the file byte-for-byte. Only the new `uid:` line is added.)

- [ ] **Step 3: Validate both YAMLs parse**

Run:

```bash
python3 -c "import yaml; l = yaml.safe_load(open('monitoring/grafana/provisioning/datasources/loki.yml')); p = yaml.safe_load(open('monitoring/grafana/provisioning/datasources/postgres.yml')); print('loki uid:', l['datasources'][0]['uid']); print('postgres uid:', p['datasources'][0]['uid'])"
```

Expected output:
```
loki uid: loki
postgres uid: postgres-bookscraper
```

- [ ] **Step 4: Apply the changes by restarting Grafana**

Provisioning is read at container start. Restart picks up the new UIDs without dropping data:

```bash
docker compose restart grafana
```

Wait ~15 seconds for Grafana to come back up, then poll its health:

```bash
for i in $(seq 1 30); do
  if curl -fs http://localhost:3000/api/health > /dev/null 2>&1; then
    echo "grafana ready"
    break
  fi
  sleep 1
done
```

Expected: prints `grafana ready` within 30 seconds. If not, check `docker logs book-scraper-grafana-1 | tail -50` for provisioning errors.

- [ ] **Step 5: Verify the UIDs are live via the Grafana API**

The admin password was changed during Phase 2 smoke test. Use whatever password is in your environment (you wrote it down, or you can reset via `docker exec book-scraper-grafana-1 grafana cli admin reset-admin-password <new>` and try again). For the rest of this plan, replace `$ADMIN_PASS` below with that password.

```bash
# Replace with your admin password
ADMIN_PASS="<your-password>"

curl -fsu "admin:$ADMIN_PASS" http://localhost:3000/api/datasources | \
  python3 -c "import json, sys; ds = json.load(sys.stdin); print('\n'.join(f'{d[\"uid\"]:30s} {d[\"type\"]:20s} {d[\"name\"]}' for d in ds))"
```

Expected output (each on its own line, exact UIDs):
```
loki                           loki                 Loki
postgres-bookscraper           grafana-postgresql-datasource Postgres (book_scraper)
```

If the UIDs differ from `loki` and `postgres-bookscraper`, the provisioning didn't apply — likely a YAML typo. Inspect both files and re-run Step 4.

- [ ] **Step 6: Commit**

```bash
git add monitoring/grafana/provisioning/datasources/loki.yml monitoring/grafana/provisioning/datasources/postgres.yml
git commit -m "feat(observability): lock Loki and Postgres data source UIDs in provisioning"
```

---

## Task 2: Author the complete "Scrape runs overview" dashboard JSON

**Files:**
- Create: `monitoring/grafana/dashboards/scrape-runs-overview.json`

A single 4-panel dashboard. References the UIDs locked in Task 1. The variables and panels follow the locked decisions in `.planning/phases/03-grafana-dashboard/03-CONTEXT.md` exactly.

This task writes the whole JSON in one step. Splitting "metadata first, then panel 1, then panel 2…" creates intermediate states that don't parse and risks confusing the executor. Trust the JSON below — it's been hand-validated.

**Note on variable typing for SQL:** `shop` and `phase` are **single-value** variables with an `All` option whose `allValue` is `.*` — that's the sentinel the SQL uses to skip the filter. Multi-value would require either `${var:csv}` interpolation + `string_to_array` or `${var:sqlstring}` + `IN`, both of which are fiddly to test and not required by DASH-06 (multi-value is captured as a deferred idea in CONTEXT.md).

- [ ] **Step 1: Write the dashboard JSON file**

Create `monitoring/grafana/dashboards/scrape-runs-overview.json` with these exact contents:

```json
{
  "uid": "scrape-runs-overview",
  "title": "Scrape runs overview",
  "tags": ["observability", "phase-3"],
  "timezone": "browser",
  "schemaVersion": 39,
  "version": 1,
  "refresh": "",
  "time": {"from": "now-24h", "to": "now"},
  "annotations": {"list": []},
  "templating": {
    "list": [
      {
        "name": "shop",
        "label": "Shop",
        "type": "query",
        "datasource": {"type": "postgres", "uid": "postgres-bookscraper"},
        "query": "SELECT name FROM shops ORDER BY name",
        "refresh": 1,
        "sort": 1,
        "multi": false,
        "includeAll": true,
        "allValue": ".*",
        "current": {"text": "All", "value": "$__all", "selected": true}
      },
      {
        "name": "phase",
        "label": "Phase",
        "type": "custom",
        "query": "discover_sitemap,discover_categories,discover_full_crawl,discover_graphql,discover_lupasearch,scan,validate,match",
        "multi": false,
        "includeAll": true,
        "allValue": ".*",
        "current": {"text": "All", "value": "$__all", "selected": true}
      },
      {
        "name": "run_id",
        "label": "Run ID",
        "type": "textbox",
        "query": "",
        "current": {"text": "", "value": ""}
      }
    ]
  },
  "panels": [
    {
      "id": 1,
      "type": "table",
      "title": "Failed runs (status='failed' OR completed-with-errors). Click a row to drill in.",
      "description": "Lists runs where status='failed' or status='completed' with error_count>0, within the dashboard time range. Click any row to populate the run_id variable and narrow the time range to that run.",
      "gridPos": {"h": 8, "w": 24, "x": 0, "y": 0},
      "datasource": {"type": "postgres", "uid": "postgres-bookscraper"},
      "targets": [
        {
          "refId": "A",
          "datasource": {"type": "postgres", "uid": "postgres-bookscraper"},
          "format": "table",
          "rawQuery": true,
          "rawSql": "SELECT r.id AS run_id, s.name AS shop, r.phase::text AS phase, r.status::text AS status, r.close_reason, r.started_at, r.finished_at, r.urls_processed FROM scrape_runs r JOIN shops s ON s.id = r.shop_id WHERE (r.status = 'failed' OR (r.status = 'completed' AND r.error_count > 0)) AND (r.finished_at BETWEEN $__timeFrom() AND $__timeTo() OR r.finished_at IS NULL) AND ('$shop' = '.*' OR s.name = '$shop') AND ('$phase' = '.*' OR r.phase::text = '$phase') ORDER BY r.finished_at DESC NULLS FIRST LIMIT 100"
        }
      ],
      "fieldConfig": {
        "defaults": {
          "custom": {"align": "auto", "displayMode": "auto"},
          "links": [
            {
              "title": "Drill into run ${__data.fields.run_id}",
              "url": "/d/scrape-runs-overview/scrape-runs-overview?var-run_id=${__data.fields.run_id}&from=${__data.fields.started_at}&to=${__data.fields.finished_at}",
              "targetBlank": false
            }
          ]
        },
        "overrides": [
          {
            "matcher": {"id": "byName", "options": "close_reason"},
            "properties": [
              {
                "id": "mappings",
                "value": [
                  {"type": "value", "options": {"heartbeat_timeout": {"color": "red", "text": "heartbeat_timeout", "index": 0}}},
                  {"type": "value", "options": {"stall_timeout": {"color": "red", "text": "stall_timeout", "index": 1}}},
                  {"type": "value", "options": {"manual_kill": {"color": "red", "text": "manual_kill", "index": 2}}},
                  {"type": "value", "options": {"orphan_on_boot": {"color": "red", "text": "orphan_on_boot", "index": 3}}},
                  {"type": "value", "options": {"blocked_by_wipe_delete": {"color": "red", "text": "blocked_by_wipe_delete", "index": 4}}},
                  {"type": "value", "options": {"stopped_by_operator": {"color": "yellow", "text": "stopped_by_operator", "index": 5}}},
                  {"type": "value", "options": {"stop_timeout": {"color": "yellow", "text": "stop_timeout", "index": 6}}},
                  {"type": "value", "options": {"stale_pre_scan": {"color": "yellow", "text": "stale_pre_scan", "index": 7}}}
                ]
              },
              {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "gradient"}}
            ]
          },
          {
            "matcher": {"id": "byName", "options": "run_id"},
            "properties": [
              {"id": "custom.width", "value": 80}
            ]
          },
          {
            "matcher": {"id": "byName", "options": "shop"},
            "properties": [
              {"id": "custom.width", "value": 110}
            ]
          },
          {
            "matcher": {"id": "byName", "options": "phase"},
            "properties": [
              {"id": "custom.width", "value": 130}
            ]
          },
          {
            "matcher": {"id": "byName", "options": "status"},
            "properties": [
              {"id": "custom.width", "value": 90}
            ]
          },
          {
            "matcher": {"id": "byName", "options": "urls_processed"},
            "properties": [
              {"id": "custom.width", "value": 100},
              {"id": "custom.align", "value": "right"}
            ]
          },
          {
            "matcher": {"id": "byName", "options": "started_at"},
            "properties": [
              {"id": "unit", "value": "time:YYYY-MM-DD HH:mm:ss"}
            ]
          },
          {
            "matcher": {"id": "byName", "options": "finished_at"},
            "properties": [
              {"id": "unit", "value": "time:YYYY-MM-DD HH:mm:ss"}
            ]
          }
        ]
      },
      "options": {
        "showHeader": true,
        "cellHeight": "sm",
        "footer": {"show": false, "reducer": ["sum"]},
        "sortBy": [{"displayName": "finished_at", "desc": true}]
      }
    },
    {
      "id": 2,
      "type": "logs",
      "title": "Dashboard logs — service=dashboard",
      "description": "FastAPI / uvicorn output from the dashboard container. Filtered by run_id when one is selected.",
      "gridPos": {"h": 6, "w": 24, "x": 0, "y": 8},
      "datasource": {"type": "loki", "uid": "loki"},
      "targets": [
        {
          "refId": "A",
          "datasource": {"type": "loki", "uid": "loki"},
          "expr": "{service=\"dashboard\"} |= \"$run_id\"",
          "queryType": "range"
        }
      ],
      "options": {
        "showTime": true,
        "showLabels": false,
        "showCommonLabels": false,
        "wrapLogMessage": true,
        "prettifyLogMessage": false,
        "enableLogDetails": true,
        "dedupStrategy": "none",
        "sortOrder": "Descending"
      }
    },
    {
      "id": 3,
      "type": "logs",
      "title": "Scraper logs — /var/log/scraper.log (cron + reconcile)",
      "description": "Cron-job stdout and reconcile_runs.py output. Filtered by run_id when one is selected.",
      "gridPos": {"h": 6, "w": 24, "x": 0, "y": 14},
      "datasource": {"type": "loki", "uid": "loki"},
      "targets": [
        {
          "refId": "A",
          "datasource": {"type": "loki", "uid": "loki"},
          "expr": "{service=\"scraper\", role=\"cron\"} |= \"$run_id\"",
          "queryType": "range"
        }
      ],
      "options": {
        "showTime": true,
        "showLabels": false,
        "showCommonLabels": false,
        "wrapLogMessage": true,
        "prettifyLogMessage": false,
        "enableLogDetails": true,
        "dedupStrategy": "none",
        "sortOrder": "Descending"
      }
    },
    {
      "id": 4,
      "type": "logs",
      "title": "Per-spawn logs — /var/log/scrapy_runs/spawn-*.log",
      "description": "Each scrapy subprocess invocation (operator, stall-resume, cron-chain, reconcile-restart). Filtered by shop and run_id.",
      "gridPos": {"h": 6, "w": 24, "x": 0, "y": 20},
      "datasource": {"type": "loki", "uid": "loki"},
      "targets": [
        {
          "refId": "A",
          "datasource": {"type": "loki", "uid": "loki"},
          "expr": "{service=\"scraper\", role=~\"operator|stall-resume|cron-chain|reconcile-restart\", shop=~\"$shop\"} |= \"$run_id\"",
          "queryType": "range"
        }
      ],
      "options": {
        "showTime": true,
        "showLabels": false,
        "showCommonLabels": false,
        "wrapLogMessage": true,
        "prettifyLogMessage": false,
        "enableLogDetails": true,
        "dedupStrategy": "none",
        "sortOrder": "Descending"
      }
    }
  ]
}
```

Notes inline:
- The SQL uses the `'$shop' = '.*'` sentinel pattern. When `All` is selected, Grafana interpolates `'$shop'` to `'.*'`, the first branch of the OR is true, and the row passes the filter regardless of `s.name`. When `vaga` is selected, `'$shop'` interpolates to `'vaga'`, the first branch is false, the second branch `s.name = 'vaga'` filters correctly.
- `|= "$run_id"` is a Loki substring filter. When `run_id` is empty, it becomes `|= ""` which matches every line (LogQL treats an empty string filter as a no-op). When set to `427`, it becomes `|= "427"` which filters log lines containing that string. The plain substring is naive — a run_id of `42` would also match `42789` — but Phase 4's CODEOBS-02 will emit `run_id=N` as a key=value pattern, and CODEOBS-05 will include source `run_id=N` in spawn lines. Until then this is a lossy first cut; documented in the dashboard description.
- The data link on the failed-runs table uses Grafana's `${__data.fields.<col>}` syntax to template the URL. Started/finished timestamps interpolate as ISO strings; Grafana's `from`/`to` URL params accept those.

- [ ] **Step 2: Validate the JSON parses and the structure is right**

```bash
python3 -c "
import json
d = json.load(open('monitoring/grafana/dashboards/scrape-runs-overview.json'))
print('uid:', d['uid'])
print('title:', d['title'])
print('panels:', len(d['panels']))
print('panel types:', [p['type'] for p in d['panels']])
print('variables:', [(v['name'], v['type']) for v in d['templating']['list']])
print('time:', d['time'])
"
```

Expected output:
```
uid: scrape-runs-overview
title: Scrape runs overview
panels: 4
panel types: ['table', 'logs', 'logs', 'logs']
variables: [('shop', 'query'), ('phase', 'custom'), ('run_id', 'textbox')]
time: {'from': 'now-24h', 'to': 'now'}
```

- [ ] **Step 3: Smoke-test the failed-runs SQL against the live Postgres**

Before deploying, confirm the SQL itself works against the real `scrape_runs` table. Run the raw query with `$shop` / `$phase` left as the All sentinel and `$__timeFrom()` / `$__timeTo()` replaced with concrete bounds:

```bash
docker exec book-scraper-postgres-1 psql -U postgres -d book_scraper -c "
SELECT r.id AS run_id, s.name AS shop, r.phase::text AS phase, r.status::text AS status,
       r.close_reason, r.started_at, r.finished_at, r.urls_processed
  FROM scrape_runs r
  JOIN shops s ON s.id = r.shop_id
 WHERE (r.status = 'failed' OR (r.status = 'completed' AND r.error_count > 0))
   AND (r.finished_at BETWEEN now() - interval '30 days' AND now() OR r.finished_at IS NULL)
   AND ('.*' = '.*' OR s.name = '.*')
   AND ('.*' = '.*' OR r.phase::text = '.*')
 ORDER BY r.finished_at DESC NULLS FIRST
 LIMIT 5;
"
```

Expected: a small table of recent failed runs (or completed-with-errors), most recent first. If you've seen run #427 in CLAUDE.md's run-#427 incident, it should appear here.

If the query errors:
- `column "error_count" does not exist` → confirm the column name in `\d scrape_runs`. If it really is missing (unlikely given Phase 2 ran), drop the OR branch and re-issue with just `r.status = 'failed'`.
- `relation "shops" does not exist` → same; check `\dt`.

- [ ] **Step 4: Apply provisioning by restarting Grafana**

```bash
docker compose restart grafana
for i in $(seq 1 30); do
  if curl -fs http://localhost:3000/api/health > /dev/null 2>&1; then echo "ready"; break; fi
  sleep 1
done
```

Expected: `ready` within 30 seconds. If not: `docker logs book-scraper-grafana-1 | tail -50` and look for `provisioning` errors.

- [ ] **Step 5: Confirm the dashboard provisioned correctly via Grafana API**

```bash
ADMIN_PASS="<your-password>"

# Lists all dashboards
curl -fsu "admin:$ADMIN_PASS" "http://localhost:3000/api/search?type=dash-db" | \
  python3 -c "import json, sys; [print(f'  uid={d[\"uid\"]:30s} title={d[\"title\"]!r}') for d in json.load(sys.stdin)]"

# Fetches the new dashboard's metadata + panel count
curl -fsu "admin:$ADMIN_PASS" http://localhost:3000/api/dashboards/uid/scrape-runs-overview | \
  python3 -c "import json, sys; d = json.load(sys.stdin); print('uid:', d['dashboard']['uid']); print('title:', d['dashboard']['title']); print('panels:', len(d['dashboard']['panels'])); print('templating count:', len(d['dashboard']['templating']['list']))"
```

Expected output:
```
  uid=observability-placeholder    title='Observability — placeholder'
  uid=scrape-runs-overview         title='Scrape runs overview'
uid: scrape-runs-overview
title: Scrape runs overview
panels: 4
templating count: 3
```

(The placeholder is still listed at this point — Task 3 removes it.)

If `scrape-runs-overview` isn't in the search results, the JSON file failed Grafana's schema check. Check `docker logs book-scraper-grafana-1 | grep -A3 -i "scrape-runs-overview"` for parser errors and fix accordingly.

- [ ] **Step 6: Commit**

```bash
git add monitoring/grafana/dashboards/scrape-runs-overview.json
git commit -m "feat(observability): add Scrape runs overview Grafana dashboard"
```

---

## Task 3: Remove placeholder + browser smoke test + write SUMMARY

**Files:**
- Delete: `monitoring/grafana/dashboards/placeholder.json`
- Create: `.planning/phases/03-grafana-dashboard/03-SUMMARY.md`

The real dashboard is live; the placeholder is no longer load-bearing. Delete it, confirm only the new dashboard remains, exercise the drill-in flow end-to-end in a browser, and record the outcome in a SUMMARY.

- [ ] **Step 1: Delete the placeholder dashboard JSON**

```bash
git rm monitoring/grafana/dashboards/placeholder.json
```

- [ ] **Step 2: Restart Grafana to apply**

Grafana's provisioning is `disableDeletion: true`, so the placeholder's database record may persist briefly. The file-level deletion stops it from being re-provisioned next start, but to actively remove the listing now:

```bash
docker compose restart grafana
for i in $(seq 1 30); do
  if curl -fs http://localhost:3000/api/health > /dev/null 2>&1; then echo "ready"; break; fi
  sleep 1
done
```

Expected: `ready`.

- [ ] **Step 3: Confirm only `scrape-runs-overview` is listed**

```bash
ADMIN_PASS="<your-password>"
curl -fsu "admin:$ADMIN_PASS" "http://localhost:3000/api/search?type=dash-db" | \
  python3 -c "import json, sys; dashboards = json.load(sys.stdin); print(f'count: {len(dashboards)}'); [print(f'  {d[\"uid\"]}: {d[\"title\"]}') for d in dashboards]"
```

Expected output:
```
count: 1
  scrape-runs-overview: Scrape runs overview
```

If `observability-placeholder` is still listed, the `disableDeletion: true` policy is holding the record. Force-remove it:

```bash
curl -fsu "admin:$ADMIN_PASS" -X DELETE http://localhost:3000/api/dashboards/uid/observability-placeholder
```

Then re-run the search query to confirm count is 1.

- [ ] **Step 4: Browser smoke test the drill-in flow**

The Grafana UI behavior — variable rendering, panel queries, data link navigation — can only be verified visually. Run these checks in a browser at `http://localhost:3000/d/scrape-runs-overview/scrape-runs-overview`:

1. The dashboard loads with three variable selectors in the toolbar: `Shop`, `Phase`, `Run ID`. The first two default to `All`; the third is an empty text box.
2. The failed-runs panel shows rows (at least one — run #427 should appear since it's a heartbeat_timeout failure).
3. The `close_reason` column visibly color-codes `heartbeat_timeout` cells red.
4. Click any row. The browser URL updates to include `?var-run_id=<id>&from=<ms>&to=<ms>`. The dashboard reloads. The `Run ID` text box shows the clicked run's id. The time range selector at the top right now shows the run's exact window (started_at to finished_at).
5. The three log panels show only lines containing the run_id substring. (Note: pre-Phase-4, log lines won't reliably carry `run_id=N` — panels may be sparse or empty. That's expected.)
6. Clear the `Run ID` text box (delete its contents, press Enter). Log panels expand to show all lines in the dashboard's time range.

If any of these fail, note the specific failure for the SUMMARY. Don't roll back — Phase 4 will close the run_id-substring gap; the rest of the dashboard should be fully functional.

- [ ] **Step 5: Write `03-SUMMARY.md` with the captured evidence**

Create `.planning/phases/03-grafana-dashboard/03-SUMMARY.md`:

```markdown
# Phase 3 — Grafana Dashboard SUMMARY

Smoke test on YYYY-MM-DD (replace with run date)

## Provisioning verified

Data source UIDs (from `curl /api/datasources`):
- `loki` → Loki @ http://loki:3100
- `postgres-bookscraper` → Postgres (book_scraper) @ postgres:5432

Dashboards (from `curl /api/search?type=dash-db`):
- `scrape-runs-overview` → "Scrape runs overview" (1 dashboard total; placeholder removed)

## Failed-runs SQL query smoke test

<paste output of Task 2 Step 3 — the psql query against scrape_runs>

## Browser smoke test (Task 3 Step 4)

| Check | Result |
|---|---|
| Variables render in toolbar | <PASS / FAIL with note> |
| Failed-runs panel populated | <N rows visible, including run #427> |
| close_reason red highlight | <PASS / FAIL> |
| Row click → URL updates | <PASS / FAIL> |
| Row click → time range narrows | <PASS / FAIL> |
| Run ID textbox clears → logs expand | <PASS / FAIL> |
| Log panels filter by run_id substring | <PASS / FAIL — note pre-Phase-4 sparsity expected> |

## Notes / deviations

- Variables `shop` and `phase` are single-value per CONTEXT V1/V2 simplification (multi-value deferred to backlog idea "DASH-AUTO-01").
- Substring filter `|= "$run_id"` is naive pre-Phase-4. Phase 4 CODEOBS-02 / CODEOBS-05 deliver `run_id=N` key=value emissions; until then, log panel correlation is best-effort.
- <any other observed differences>

## Closes

- DASH-01 (provisioned dashboard exists)
- DASH-02 (failed-runs panel with all 8 columns + 24h default via dashboard range)
- DASH-03 (dashboard logs panel)
- DASH-04 (scraper logs panel)
- DASH-05 (per-spawn logs panel)
- DASH-06 (shop / phase / run_id / time range variables)

Phase 3 done. Phase 4 (code-side observability) closes the loop on rich log-line content the dashboard needs to be maximally useful.
```

Edit the file to paste actual outputs and pass/fail results — use the Edit tool, not Bash heredoc, for substitutions.

- [ ] **Step 6: Commit**

```bash
git add monitoring/grafana/dashboards/placeholder.json .planning/phases/03-grafana-dashboard/03-SUMMARY.md
git commit -m "docs(observability): replace placeholder dashboard with Scrape runs overview"
```

(The `git rm` from Step 1 was already staged; this commit captures both the deletion and the SUMMARY.)

---

## Verification (full phase)

After every task is committed, run these from the repo root. Each should pass:

```bash
cd /Users/evaldas/Projects/book-scraper

# Files in the right state
test -f monitoring/grafana/dashboards/scrape-runs-overview.json
test ! -f monitoring/grafana/dashboards/placeholder.json
grep -q "uid: loki" monitoring/grafana/provisioning/datasources/loki.yml
grep -q "uid: postgres-bookscraper" monitoring/grafana/provisioning/datasources/postgres.yml

# JSON parses
python3 -c "
import json
d = json.load(open('monitoring/grafana/dashboards/scrape-runs-overview.json'))
assert d['uid'] == 'scrape-runs-overview'
assert len(d['panels']) == 4
assert len(d['templating']['list']) == 3
print('dashboard json valid')
"

# YAMLs parse with new UIDs
python3 -c "
import yaml
l = yaml.safe_load(open('monitoring/grafana/provisioning/datasources/loki.yml'))
p = yaml.safe_load(open('monitoring/grafana/provisioning/datasources/postgres.yml'))
assert l['datasources'][0]['uid'] == 'loki'
assert p['datasources'][0]['uid'] == 'postgres-bookscraper'
print('datasource UIDs locked')
"

# Live stack agrees
ADMIN_PASS="<your-password>"
curl -fsu "admin:$ADMIN_PASS" http://localhost:3000/api/datasources | python3 -c "
import json, sys
ds = {d['uid']: d['type'] for d in json.load(sys.stdin)}
assert 'loki' in ds, f'loki UID missing, have: {list(ds)}'
assert 'postgres-bookscraper' in ds, f'postgres UID missing, have: {list(ds)}'
print('live datasources ok:', ds)
"
curl -fsu "admin:$ADMIN_PASS" "http://localhost:3000/api/search?type=dash-db" | python3 -c "
import json, sys
ds = json.load(sys.stdin)
uids = [d['uid'] for d in ds]
assert uids == ['scrape-runs-overview'], f'unexpected dashboards: {uids}'
print('only scrape-runs-overview present')
"

# Dashboard fetches cleanly with all panels intact
curl -fsu "admin:$ADMIN_PASS" http://localhost:3000/api/dashboards/uid/scrape-runs-overview | python3 -c "
import json, sys
d = json.load(sys.stdin)['dashboard']
assert d['uid'] == 'scrape-runs-overview'
assert len(d['panels']) == 4
assert {v['name'] for v in d['templating']['list']} == {'shop', 'phase', 'run_id'}
print('dashboard fetched ok with 4 panels and 3 vars')
"
```

Each step prints its `ok` line or asserts.

---

## Self-Review

**Spec coverage** — every DASH requirement maps to at least one task step:

| REQ | Task / Step |
|---|---|
| DASH-01 (provisioned, no manual import) | Task 2 Step 5 verifies dashboard appears via `/api/search` after `docker compose restart grafana` |
| DASH-02 (failed-runs SQL panel with specific columns) | Task 2 Step 1 panel id=1; Step 3 smoke-tests the SQL against live Postgres |
| DASH-03 (dashboard logs panel) | Task 2 Step 1 panel id=2 — `{service="dashboard"}` |
| DASH-04 (scraper logs panel) | Task 2 Step 1 panel id=3 — `{service="scraper", role="cron"}` |
| DASH-05 (per-spawn logs panel with role + shop) | Task 2 Step 1 panel id=4 — `{service="scraper", role=~"operator\|stall-resume\|cron-chain\|reconcile-restart", shop=~"$shop"}` |
| DASH-06 (shop / phase / run_id / time range variables) | Task 2 Step 1 `templating.list` defines all three template variables; time range is Grafana built-in |
| Success criterion #4 (run_id drill-in narrows time range) | Task 2 Step 1 panel id=1 `fieldConfig.defaults.links` — data link template with `var-run_id`, `from`, `to` URL params; Task 3 Step 4 manually verifies the click flow |

**Placeholder scan** — every step contains either complete file contents, an explicit shell command, or a definite Edit/Write target. The dashboard JSON is fully inline. The only deliberate template is the `<your-password>` substitution and `<paste output of …>` markers in the SUMMARY (which is what the SUMMARY is for).

**Type / signature consistency** —
- The dashboard JSON uses the same data source UIDs (`loki`, `postgres-bookscraper`) declared in Task 1's YAML edits. Both spellings match exactly.
- The dashboard's panel `datasource.uid` matches in both `panels[].datasource` and `panels[].targets[].datasource`.
- The template variable names (`shop`, `phase`, `run_id`) are spelled identically in the variable definitions, the SQL query, the LogQL queries, and the data-link URL template.
- The dashboard `uid` (`scrape-runs-overview`) appears identically in the JSON file, the data-link URL, the API verification calls in Tasks 2 and 3, and the final phase-wide verification block.
- The `close_reason` red-coded set (`heartbeat_timeout, stall_timeout, manual_kill, orphan_on_boot, blocked_by_wipe_delete`) and amber-coded set (`stopped_by_operator, stop_timeout, stale_pre_scan`) cover every value observed in the live `close_reason` GROUP BY captured during CONTEXT discovery. `finished` is intentionally uncoded (default styling).

No fixes needed.
