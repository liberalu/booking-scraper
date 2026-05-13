# Phase 2 — Log Infrastructure SUMMARY

Smoke test on 2026-05-13

## docker compose ps

```
NAME                           IMAGE                                      COMMAND                  SERVICE         CREATED         STATUS                   PORTS
book-scraper-dashboard-1       book-scraper-dashboard                     "/entrypoint.sh"         dashboard       11 hours ago    Up 11 hours              0.0.0.0:8000->8000/tcp
book-scraper-flaresolverr-1    ghcr.io/flaresolverr/flaresolverr:latest   "/usr/bin/dumb-init …"   flaresolverr    6 days ago      Up 3 days                0.0.0.0:8191->8191/tcp
book-scraper-grafana-1         grafana/grafana:latest                     "/run.sh"                grafana         5 minutes ago   Up 5 minutes (healthy)   0.0.0.0:3000->3000/tcp
book-scraper-loki-1            grafana/loki:latest                        "/usr/bin/loki -conf…"   loki            5 minutes ago   Up 5 minutes             0.0.0.0:3100->3100/tcp
book-scraper-postgres-1        postgres:16                                "docker-entrypoint.s…"   postgres        2 weeks ago     Up 3 days (healthy)      0.0.0.0:5432->5432/tcp
book-scraper-postgres-test-1   postgres:16                                "docker-entrypoint.s…"   postgres-test   2 weeks ago     Up 3 days                0.0.0.0:5433->5432/tcp
book-scraper-promtail-1        grafana/promtail:latest                    "/usr/bin/promtail -…"   promtail        5 minutes ago   Up 5 minutes
book-scraper-scraper-1         book-scraper-scraper                       "/entrypoint.sh"         scraper         2 days ago      Up 2 days
```

Note: `postgres-test` was already running before the smoke test (pre-existing dev container, not part of the observability stack).

## Endpoint probes

- Loki `/ready`: `ready` (HTTP 200)
- Promtail `/ready`: NOT directly probeable from host — port 9080 is not published in `docker-compose.yml` (no `ports:` entry for `promtail`). Promtail confirmed functional via log tail: actively sending batches to Loki (`client.go:419 component=client host=loki:3100`). Distroless image — no shell/wget/curl inside container to probe internally.
- Grafana `/api/health`:
```json
{
  "database": "ok",
  "version": "13.0.1+security-01",
  "commit": "9bbe672d"
}
```

## Loki ingestion

- `{service="dashboard"}` returned: 1 stream, 5 log lines (>= 1 ✓)
- Sample values:
```
INFO:     192.168.148.1:46148 - "GET /api/runs?page=1&per_page=30 HTTP/1.1" 200 OK
INFO:     192.168.148.1:46152 - "GET /api/runs?status=running&per_page=1 HTTP/1.1" 200 OK
```
- Note: smoke test used `/loki/api/v1/query_range` (5-minute window). The task spec used `/loki/api/v1/query` which returns HTTP 400 for log queries ("log queries are not supported as an instant query type"). `query_range` is the correct endpoint for log stream queries.

## Grafana data sources (`/api/datasources`)

```json
[
  {
    "name": "Loki",
    "type": "loki"
  },
  {
    "name": "Postgres (book_scraper)",
    "type": "grafana-postgresql-datasource"
  }
]
```

Note: Postgres plugin type is `grafana-postgresql-datasource` (actual Grafana plugin ID), not `postgres` as listed in the task spec. Functionally identical — this is the built-in PostgreSQL datasource plugin.

## Placeholder dashboard (`/api/search?query=placeholder`)

```json
[
  {
    "uid": "observability-placeholder",
    "title": "Observability — placeholder"
  }
]
```

## Images pulled

```
CONTAINER                 REPOSITORY          TAG       PLATFORM     IMAGE ID       SIZE      CREATED
book-scraper-grafana-1    grafana/grafana     latest    linux/arm64  f8a787bf1600   1.01GB    33 hours ago
book-scraper-loki-1       grafana/loki        latest    linux/arm64  0ba9300c423b   142MB     8 hours ago
book-scraper-promtail-1   grafana/promtail    latest    linux/arm64  9e9c0145954c   221MB     7 weeks ago
```

## Notes / deviations

1. **Readiness wait timed out (120s)**: `scraper` and `dashboard` containers have no Docker healthcheck (no `HEALTHCHECK` in their Dockerfiles), so `docker inspect --format '{{.State.Health.Status}}'` returns empty string rather than `healthy`. The wait loop treated them as not ready. In practice both were up and serving traffic throughout. Workaround: check `.State.Status == "running"` for these two as well.

2. **Promtail port not published**: `docker-compose.yml` has no `ports:` entry for `promtail`, so `curl http://localhost:9080/ready` fails with connection refused. Promtail is a distroless image (no wget/curl) so internal exec-probe also fails. Functionality confirmed via `docker logs` — Promtail is actively shipping batches to Loki (429 rate-limit responses from Loki confirm Loki is receiving them).

3. **Loki ingestion rate limit (429)**: At startup, Promtail slurped large backlogs from all running containers (~1 MB/batch, ~17k lines/batch). Loki's default single-tenant ingestion cap of 4 MB/sec was exceeded. Batches are retried and data eventually lands — confirmed by successful `query_range` returning dashboard logs. For production, consider raising `ingestion_rate_mb` in the Loki config or adding a `read_from_tail: true` / `max_backfill_age` limit in Promtail to skip old container log history on first start.

4. **`/loki/api/v1/query` vs `query_range`**: The task spec's step 9 uses `/query`, which returns HTTP 400 for log stream queries. Correct endpoint is `/query_range` with `start`/`end` params. Used `query_range` with a 5-minute window — returned 1 stream with 5 values.

Phase 2 done. Phase 3 replaces the placeholder with the real Scrape runs overview.
