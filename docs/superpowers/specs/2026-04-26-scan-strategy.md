# Scan strategy (vaga.lt)

**Status:** Active — current behaviour as of 2026-04-26.

## Goal

For every URL in `discovered_urls` for the shop, fetch the page once
per scan run, classify it as a book product or not, and (if it's a
book) extract title / author / ISBN / price / etc. The same URL may
be re-scraped on a later run.

## Pipeline

1. **`ScanService.prepare_scan`** ([book_scraper/services/scan.py](book_scraper/services/scan.py))
   - Either resumes the most recent `running` scan run that still has
     pending `scrape_url_items` (crash recovery), or marks any stale
     `running` runs as `failed` and creates a new run.
   - For a new run, computes the URL set:
     - Pulls all `discovered_urls` for the shop.
     - In the default (non-rescrape) mode, drops URLs that already have
       a `shop_book` row (already scraped at least once). With
       `rescrape=true` every URL is re-fetched.
   - Inserts one `scrape_url_items` row per URL with `status=pending`.
2. **Spider start** ([book_scraper/spiders/scan.py](book_scraper/spiders/scan.py))
   - Loads pending items, yields a `scrapy.Request` for each. Optional
     `max_urls` cap for dev / smoke runs.
3. **HttpxMiddleware** ([book_scraper/download_handler.py](book_scraper/download_handler.py))
   - Returns the response directly from httpx, bypassing Twisted
     (vaga.lt's HTTP/1.1 server hangs Twisted after ~120 requests).
   - Marks the row `processing` + `claimed_at = now` the moment the
     request goes out.
   - 60 s hard ceiling via `asyncio.wait_for` so a single chunked-
     trickle response can't burn minutes. httpx's per-stage `read`
     timeout resets on every chunk, so it doesn't bound total time.
4. **`parse_product` / `handle_error`** record `received_at` (real
   response time), pass HTTP status, error reason, and outcome (book
   vs non_product) to `flush_progress`.
5. **`ScanService.flush_progress`** flushes batches of 50 URLs to:
   - `scrape_url_items` — terminal status (`done` / `failed`),
     `done_at`, `http_status`, `error_reason`, `url_type`.
   - `discovered_urls` — `last_checked_at`, `last_http_status`,
     `fail_count`.
   - `url_classifications` — `book_score`, `is_book_product`.
6. **`ScanService.finish_scan`** flushes any remaining queued updates,
   sets the run's terminal state, updates the matching cron job's
   `last_run_at`. `scrape_url_items` rows are kept (per-URL run history
   is the source of truth for the run detail page).

## Status semantics (`scrape_url_items.status`)

- `pending` — queued, request not yet dispatched.
- `processing` — request in flight; `claimed_at` set, `done_at` null.
- `done` — page fetched successfully (HTTP 2xx). Includes both books
  *and* non-products. The page was scraped — not finding a book is a
  successful outcome for that URL, not a failure. `error_reason` is
  null; `url_type` is `product` or `non_product`.
- `failed` — fetch failed: 4xx/5xx response, transport error, or hard
  timeout. `error_reason` carries the cause (`http_404`, `http_503`,
  `request_error:TimeoutError`, etc.).

## Throttling

| Setting | Value | Why |
|---|---|---|
| `CONCURRENT_REQUESTS_PER_DOMAIN` | 1 | vaga.lt silently throttles bursts; with 4 concurrent we measured ~0.6 resp/min before stall, with 1 we got ~39 resp/min. |
| `DOWNLOAD_DELAY` | 2.0 s | Pair with concurrency=1 to give the server breathing room. |
| `AUTOTHROTTLE_ENABLED` | true | Adapts delay based on observed latency. |
| `AUTOTHROTTLE_START_DELAY` | 2.0 s | |
| `AUTOTHROTTLE_MAX_DELAY` | 30 s | Cap on adaptive backoff. |
| `AUTOTHROTTLE_TARGET_CONCURRENCY` | 1.0 | Match `CONCURRENT_REQUESTS_PER_DOMAIN`. |
| Hard request timeout | 60 s | `asyncio.wait_for` ceiling above httpx's per-stage timeouts. |
| `DOWNLOAD_TIMEOUT` | 15 s | Per-stage timeout passed to httpx. |
| `STALL_TIMEOUT` | 60 s | Force shutdown if no responses for 60 s ([book_scraper/extensions.py](book_scraper/extensions.py)). |

## HTTP headers

- `User-Agent: Mozilla/5.0 ...` (browser-shaped — vaga.lt serves a
  noticeably degraded path for `User-Agent: Scrapy/...`: 0.76 s vs
  2.02 s TTFB on the same URL).
- `Accept: text/html,application/xhtml+xml,...`.
- `Accept-Language: lt,en;q=0.9`.
- `Connection: close` — vaga.lt blocks reused connections after ~150
  requests, so we force a fresh TCP+TLS each request.

## Failure handling

- **Stall watchdog** ([extensions.py](book_scraper/extensions.py))
  closes the spider if no response for 60 s. Before invoking
  `engine.close_spider`, it marks the run `failed` from a fresh DB
  session so a poisoned pipeline session can't leave a zombie row.
- **Boot-time orphan reaper** (`mark_orphan_runs_failed` at scraper
  container start) flips any `running` rows belonging to dead
  processes.
- **Dashboard reaper task** ([book_scraper/dashboard/reaper.py](book_scraper/dashboard/reaper.py))
  runs every 5 min, fails any run whose heartbeat is older than 30 min.
- Every transition to `failed` also inserts a `scrape_run_failed`
  validation issue so the run surfaces on `/validation`.

## Resumability

- A run that didn't finish — process killed, host restarted, stall
  shutdown — leaves `scrape_url_items` rows in `pending` /
  `processing` state.
- Next `prepare_scan` call sees the `running` row with pending items,
  resumes it (does NOT create a new run), and `processing` rows are
  reset to `pending` via `reset_processing_scrape_url_items`.
- `urls_total` reflects the original plan; `urls_processed` is only
  incremented for successful book extractions, so the dashboard's
  `progress` column is computed as `(done + failed) / urls_total`
  from the live `scrape_url_items` breakdown rather than from
  `urls_processed`.
