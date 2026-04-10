# Docker + Monitoring Dashboard Design

## Overview

Containerize the book scraper and add a web-based monitoring dashboard. The scraper runs on a cron schedule inside Docker and can also be triggered from the dashboard UI. The dashboard shows scrape run history, validation issues, price trends, inventory stats, and live logs.

## Architecture

Three Docker Compose services sharing a network:

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  postgres    │     │  scraper    │     │  dashboard   │
│  PostgreSQL  │◄────│  Scrapy +   │     │  FastAPI +   │
│  port 5432   │     │  cron       │     │  HTMX        │
│              │◄────│             │     │  port 8000   │──► browser
└─────────────┘     └─────────────┘     └─────────────┘
       ▲                                       │
       └───────────────────────────────────────┘
                    reads DB
```

- **postgres** — PostgreSQL 16, persistent volume, unchanged from current setup
- **scraper** — Python 3.12 slim, installs production deps only, runs cron + Scrapy. Alembic migrations run on startup.
- **dashboard** — Same base image as scraper (multi-stage or shared), runs FastAPI with uvicorn on port 8000. Read-only DB access plus ability to trigger scraper runs via `docker exec`.

Single `Dockerfile` with two targets (build stages): `scraper` and `dashboard`. Both share the same base with project deps installed. Different entrypoints.

## Docker Details

### Dockerfile (multi-stage)

```
# Base stage: Python 3.12 slim + uv + production deps
FROM python:3.12-slim AS base
  - Install uv
  - Copy pyproject.toml + uv.lock
  - uv sync (production only, no dev deps)
  - Copy book_scraper/, alembic/, config/

# Scraper stage
FROM base AS scraper
  - Install cron
  - Copy crontab file
  - Entrypoint: run alembic upgrade head, then start cron foreground

# Dashboard stage
FROM base AS dashboard
  - Copy book_scraper/dashboard/
  - Install fastapi, uvicorn, jinja2 (added to deps)
  - Entrypoint: uvicorn book_scraper.dashboard.app:app --host 0.0.0.0 --port 8000
```

### docker-compose.yml additions

```yaml
services:
  postgres:
    # unchanged

  scraper:
    build:
      context: .
      target: scraper
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/book_scraper

  dashboard:
    build:
      context: .
      target: dashboard
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://postgres:postgres@postgres:5432/book_scraper
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock  # to trigger scraper runs
```

### Cron Schedule

```cron
0 2 * * *  cd /app && PYTHONPATH=. uv run scrapy crawl discover -a shop=vaga -a strategy=sitemap >> /var/log/scraper.log 2>&1
0 3 * * *  cd /app && PYTHONPATH=. uv run scrapy crawl scan -a shop=vaga >> /var/log/scraper.log 2>&1
```

### Health Check

Postgres gets a health check (`pg_isready`) so scraper/dashboard wait for it.

## Dashboard

### Tech Stack

- **FastAPI** — API and server-rendered HTML
- **Jinja2** — HTML templates
- **HTMX** — interactive updates without JS framework (polling, form submission, SSE)
- **Chart.js** — price trend charts (loaded from CDN)
- **Pico CSS** — minimal classless CSS framework (loaded from CDN)

### New Dependencies

Add to `pyproject.toml` under a `dashboard` optional extra:
- `fastapi>=0.115`
- `uvicorn>=0.34`
- `jinja2>=3.1`

### Code Structure

```
book_scraper/dashboard/
    __init__.py
    app.py              # FastAPI app, mounts routes
    routes/
        __init__.py
        overview.py     # GET /
        runs.py         # GET /runs, GET /runs/{id}, POST /runs/trigger
        validation.py   # GET /validation, GET /validation/{issue_type}
        prices.py       # GET /prices, GET /api/prices/{listing_id}
        inventory.py    # GET /inventory
        logs.py         # GET /logs, GET /api/logs/stream (SSE)
    templates/
        base.html       # Layout: nav, head (HTMX + Chart.js + Pico CSS CDN)
        overview.html
        runs.html
        run_detail.html
        validation.html
        validation_detail.html
        prices.html
        inventory.html
        logs.html
    queries.py          # SQL query functions (read-only, using existing session factory)
```

### Pages

#### `/` — Overview
- Stat cards: total listings, active listings, with ISBN, total price records
- Last 5 scrape runs table (phase, status, duration, items)
- Validation summary from latest run (issue type counts)

#### `/runs` — Scrape Runs
- Paginated table: id, phase, status, started_at, duration, items_added/updated, error_count, validation_issues count
- Click row → `/runs/{id}`
- "Run Now" panel with buttons:
  - Discover (sitemap)
  - Discover (categories)
  - Scan
  - Rescrape all
- Each button POSTs to `/runs/trigger` with `phase` param
- Trigger endpoint uses Docker SDK (`docker` Python package) to `exec` into the scraper container and run the appropriate scrapy command in background
- Button shows spinner via HTMX, polls run status until complete

#### `/runs/{id}` — Run Detail
- Run metadata card (phase, status, started_at, finished_at, duration, urls_total, urls_processed, items_added, items_updated, errors_4xx, errors_5xx)
- Validation issues table for this run: url (clickable), field, issue, raw_value
- Filterable by issue type via dropdown

#### `/validation` — Validation Issues
- Summary table: issue type, total count across all runs, count in latest run
- Click issue type → `/validation/{issue_type}` with list of affected URLs
- Trend indicator: up/down arrow comparing latest run to previous

#### `/prices` — Price Trends
- Search box (title or URL, debounced via HTMX)
- Search results as clickable list
- Selected listing shows Chart.js line chart (price + price_original over time)
- Table: biggest price drops and spikes in last 7 days

#### `/inventory` — Inventory Stats
- Format breakdown: pie chart (hardcover/paperback/audiobook/book/other)
- Data completeness: bar chart (listings with isbn, author, year, publisher)
- Active vs inactive: simple count
- Total discovered URLs vs scraped listings

#### `/logs` — Live Logs
- When a scrape is running: SSE stream from `/api/logs/stream` showing real-time log output
- When idle: last 100 lines from `scrapy_errors.log`
- Auto-scroll to bottom, pause button

### Run Trigger Mechanism

The dashboard needs to start scraper commands. Options considered:
- **Docker SDK** — dashboard mounts Docker socket, creates exec in scraper container
- **Shared volume + file watcher** — too fragile
- **HTTP API on scraper** — adds unnecessary complexity

Using Docker SDK (`docker` Python package). The dashboard:
1. POST `/runs/trigger` with `{"command": "discover_sitemap" | "discover_categories" | "scan" | "rescrape"}`
2. Dashboard finds the scraper container by service name
3. Runs `docker exec -d scraper uv run scrapy crawl ...` in detached mode
4. Returns immediately, frontend polls `/runs` for status updates via HTMX

### Queries Module

`book_scraper/dashboard/queries.py` contains read-only SQL functions:
- `get_overview_stats(session)` → dict with listing counts, price count
- `get_recent_runs(session, limit)` → list of ScrapeRun
- `get_run_detail(session, run_id)` → ScrapeRun + validation issues
- `get_validation_summary(session)` → issue type counts
- `get_validation_by_type(session, issue_type)` → list of ValidationIssue
- `get_price_history(session, listing_id)` → list of Price
- `search_listings(session, query)` → list of Listing (title ILIKE)
- `get_price_changes(session, days)` → biggest drops/spikes
- `get_inventory_stats(session)` → format counts, completeness stats
- `get_latest_run_id(session)` → int or None (for validation summary)

All functions use the existing SQLAlchemy models and session factory.

## What Changes in Existing Code

- `pyproject.toml` — add `dashboard` optional extra with fastapi, uvicorn, jinja2
- `docker-compose.yml` — add scraper and dashboard services, add healthcheck to postgres
- New `Dockerfile` at project root
- New `cron/scraper-crontab` file
- New `book_scraper/dashboard/` package (all new files)
- `docker` Python package added to dashboard deps (for run trigger)

No changes to existing scraper code, models, or pipelines.

## Testing

- Dashboard routes: unit tests with FastAPI TestClient, mock DB queries
- Queries: integration tests against test DB (same pattern as existing tests)
- Docker: manual `docker compose up --build` and verify
