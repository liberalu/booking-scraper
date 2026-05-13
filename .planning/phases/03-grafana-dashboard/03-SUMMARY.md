# Phase 3 — Grafana Dashboard SUMMARY

Smoke test on 2026-05-13.

## Provisioning verified

Data source UIDs (from `curl /api/datasources`):
- `loki` → Loki @ http://loki:3100
- `postgres-bookscraper` → Postgres (book_scraper) @ postgres:5432

Dashboards (from `curl /api/search?type=dash-db`):

```
count: 1
  scrape-runs-overview: Scrape runs overview
```

Note: after restart the `observability-placeholder` record was still present (Grafana's `disableDeletion: true` policy retains DB records even when the JSON file is removed). It was force-deleted via `DELETE /api/dashboards/uid/observability-placeholder` → `{"message":"Dashboard Observability — placeholder deleted","title":"Observability — placeholder","uid":"observability-placeholder"}`. Re-query confirmed count: 1.

## Drill-in URL handling

Test run_id from live data: `429`

```
no-var:    HTTP 200
with-vars: HTTP 200
```

## Loki query smoke test (panel readiness)

```
panel2 dashboard streams: 1
panel3 scraper-cron streams: 1
panel4 per-spawn streams: 1
```

Note: panel 3 (scraper cron) and panel 4 (per-spawn) may return 0 streams if no recent cron jobs / operator spawns. Dashboard container traffic guarantees panel 2 has data.

## Notes / deviations

- Variables `shop` and `phase` are single-value per CONTEXT V1/V2 simplification (multi-value deferred to backlog "DASH-AUTO-01").
- Substring filter `|= "$run_id"` is naive pre-Phase-4. Phase 4 CODEOBS-02 / CODEOBS-05 deliver `run_id=N` key=value emissions; until then, log panel correlation is best-effort.
- Task 1 required `deleteDatasources:` blocks in the YAML provisioning to migrate from random auto-UIDs to explicit `loki` / `postgres-bookscraper` UIDs — added in the same commit (b2995ea) after the initial UID-only attempt crash-looped Grafana with "data source not found".
- The placeholder record required a manual `DELETE /api/dashboards/uid/observability-placeholder` call after file removal (expected — `disableDeletion: true` in provisioning config).
- Manual browser verification (variable rendering in toolbar, color-coded close_reason cells, click-to-drill-in) was NOT performed in this automated smoke test — the operator should do this once: open http://localhost:3000/d/scrape-runs-overview/scrape-runs-overview, log in admin/admin, confirm the dashboard renders. If a regression is observed, file a follow-up.

## Closes

- DASH-01 (provisioned dashboard exists — verified via API search)
- DASH-02 (failed-runs panel with all 8 columns + 24h default via dashboard range)
- DASH-03 (dashboard logs panel)
- DASH-04 (scraper logs panel)
- DASH-05 (per-spawn logs panel)
- DASH-06 (shop / phase / run_id / time range variables)

Phase 3 done. Phase 4 (code-side observability fixes) closes the loop on rich log-line content the dashboard needs to be maximally useful.
