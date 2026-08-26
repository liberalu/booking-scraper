# CLAUDE.md

> **The Python stack is gone.** This was a Scrapy project until 2026-08-26;
> it was ported to PHP, verified against the original by differential testing,
> and the original was removed. The last commit containing it is tagged
> `python-final`. Documents dated before then describe the Python
> implementation and are kept as history — don't take their file paths as
> current.

## Project Overview

Multi-shop Lithuanian book price scraper built with **roach-php** (crawler) and
**Laravel** (dashboard). Stores data in PostgreSQL. Onboarded shops:

- **vaga.lt** — OpenCart, HTML scraping (`sitemap` / `categories` / `full_crawl` strategies).
- **pegasas.lt** — Magento 2 PWA, scoped to the Lithuanian-language subtree (cats 5107/5125/6122). `graphql` strategy returns full metadata; `lupasearch` strategy is a fast supplementary index for daily price/stock rescans + new-arrivals detection (via `is_new`). Scan phase is a no-op (PWA pages have no parseable HTML — all data comes from discover).
- **humanitas.lt** — WordPress + WooCommerce + WPML, ~81k-book catalogue (mostly imported German/English academic + Lithuanian originals). Cloudflare **Managed Challenge** on every URL — bypassed via the **FlareSolverr** sidecar (`php/crawler/src/FlareSolverr.php`, opted in per-shop via the `[flaresolverr]` block in the TOML). Discovery uses the `categories` strategy paginated at `m575a2product_limit=1000` with `cntnt01page` (the 5000 server cap hangs FS Chromium on the 17 MB response); `parseProductPage` reads the `<div class="book-info">` block and gates non-LT books via `Leidinio kalba`. Cron: Sundays 02:00 discover → 04:00 scan. Coverage on calibration: 99.3% ISBN, 96.1% year, 92.7% format.

## Key Commands

The PHP 8.4 binary is pinned in `php/Makefile` (`roach-php` caps at 8.4 and
Homebrew's default `php` is 8.5). Outside make, use
`/opt/homebrew/opt/php@8.4/bin/php`.

```bash
make install                                  # composer install, all three projects
docker compose up -d postgres                 # the live database
docker compose --profile test up -d postgres-test   # the test database
php php/bin/migrate status --database=$DATABASE_URL  # schema state
php php/bin/migrate apply  --database=$DATABASE_URL  # apply php/schema

# Crawling. Writes to DATABASE_URL; pass --database to be explicit, and
# --dry-run to fetch and parse without persisting.
cd php/crawler
php bin/crawl discover --shop=vaga --strategy=sitemap
php bin/crawl discover --shop=vaga --strategy=categories       # + prices
php bin/crawl discover --shop=vaga --strategy=full_crawl       # follow internal links
php bin/crawl discover --shop=vaga --strategy=categories --max-pages=3
php bin/crawl scan --shop=vaga                                 # resumable
php bin/crawl scan --shop=vaga --max-urls=20                   # dev / smoke
php bin/crawl scan --shop=vaga --urls=https://vaga.lt/some-book
php bin/crawl discover --shop=pegasas --strategy=graphql       # full LT metadata, slow
php bin/crawl discover --shop=pegasas --strategy=lupasearch    # fast price/stock rescan
php bin/crawl discover --shop=humanitas --strategy=categories  # via FlareSolverr (~10 min)
php bin/validate --shop=vaga                                   # data-quality validator
php bin/match --shop=vaga                                      # steps 1 + 2
php bin/match --shop=vaga --synthesis                          # + step 3
docker compose up -d flaresolverr                              # required for humanitas

# Tests
make compose-build                            # build the image (clears the OrbStack proxy vars)
make compose-up                               # postgres + dashboard + reaper (no crawling)
make compose-up-scheduler                     # ...and the scheduler (STARTS CRAWLING)
make test                                     # library + crawler + dashboard
make test-offline                             # everything that needs no database
make lint                                     # php -l over every file
make fixture-db                               # rebuild the fixture-only database
make schema-gate                              # does php/schema still match the live schema?

# Dashboard
cd php/dashboard && php artisan serve --port=8002
php artisan runs:reap                         # fail runs whose heartbeat stopped
php artisan runs:schedule --dry-run           # what the schedules would fire now
php artisan runs:schedule --watch             # fire them (the thing that must stay up)

# Observability
open http://localhost:3000                                           # Grafana — admin/admin on first use
docker compose up -d loki alloy grafana                             # bring the stack up
docker compose restart grafana                                       # reload provisioning
docker compose restart alloy                                         # reload monitoring/alloy/config.alloy
curl -s 'http://localhost:3100/loki/api/v1/labels' | jq             # active Loki labels
curl -s 'http://localhost:12345/-/ready'                             # Alloy readiness
```

> **`make compose-up` does not crawl; `make compose-up-scheduler` does.** One
> image (`Dockerfile`), three services: `dashboard`, `scheduler`, `reaper`.
> Starting the scheduler fires every schedule whose window has passed, one per
> tick, against live shops — after downtime that is a backlog. Check with
> `docker compose run --rm scheduler php artisan runs:schedule --dry-run` first.
>
> There is deliberately no crawler service: a crawl is a child process of
> whoever asked for it, so restarting a container kills the crawls it started —
> the watchdog fails the run, the reaper cleans up, and the run is resumable.
> For a crawl by hand:
> `docker compose exec dashboard php ../crawler/bin/crawl scan --shop=vaga --max-urls=20`.

## Architecture

- **Crawler:** roach-php, synchronous (no event loop) — `php/crawler/`
- **Library:** framework-free, shared by crawler and dashboard — `php/src/`
- **DB:** PostgreSQL via Eloquent; migrations in `php/schema/`, applied by `php/bin/migrate`
- **Dashboard:** Laravel serving a JSON API plus the React SPA in `php/dashboard/public/static/hifi`
- **Config:** TOML files in `config/` (global defaults + per-shop overrides)
- **Package manager:** composer, three projects — `php/`, `php/crawler/`, `php/dashboard/`
- **Deployment:** CLI. Compose runs infrastructure only; there are no application images.

**Schema ownership.** Alembic owned the schema until the Python stack was
removed; `php/schema/0001_baseline.sql` is a dump of what it produced, and
`php/tools/schema_gate.sh` is what proves the baseline still reproduces the
live catalogue's schema — enums, partial unique indexes, CHECK expressions and
FK actions included. `bin/migrate` refuses a database that has an
`alembic_version` table and no PHP ledger unless `--adopt` is passed.

### Pipeline Phases

1. **Discover** (`discover` spider) — find URLs. Strategies: `sitemap`, `categories`, `full_crawl`, `graphql` (Magento), `lupasearch` (third-party search index, POST endpoint). GraphQL + LupaSearch can also yield full `ShopBookItem` data inline, so for Magento PWA shops the scan phase becomes a no-op.
2. **Scan** (`scan` spider) — scrape full product pages for discovered URLs. Resumable after crashes.
3. **Match** — not yet implemented (link shop_books to canonical books)

Spiders are generic — the shop is an argument: `php bin/crawl discover --shop=vaga --strategy=sitemap`.
Shop-specific parsing lives in `php/src/<Shop>/Parser.php`, resolved through
`ParserRegistry`.

### Run lifecycle & stall recovery

`Watchdog` (`php/crawler/src/Watchdog.php`) writes the heartbeat and detects
stalls. It runs in a **forked child**, not in-process: roach is synchronous, so
an in-process timer stops ticking during any blocking call and the dashboard's
reaper would kill a run that is merely slow. Parent → child signalling is the
mtime of a marker file — crude on purpose, because it survives a parent stuck
inside a blocking syscall, which is the case being detected.

It fires when nothing has touched that marker for `STALL_TIMEOUT` seconds
(default 180). `HEARTBEAT_INTERVAL_S` (default 5) is how often it ticks. On
stall:

1. Run flipped to `failed` with `resumable_after_failure=True` + `close_reason=stall_timeout`.
2. `RunFailsafe::finalize()` writes that from the child, on its own connection — the parent may be wedged.
3. The replacement process inherits the queue, which also resets retryable failures (`run_aborted` / `stuck_in_processing` / `subdivision_5xx`) to pending. `RunReconciler::RETRY_CAP` is 3.
4. Chain depth is tracked via `resumed_after_failure` events in `scrape_run_events`. Capped at `STALL_AUTO_RESUME_MAX` (default 10). When the cap hits, the run stays `failed` and waits for an operator click on Continue.

Adaptive subdivision: when a `discover_graphql` page returns 5xx, the spider reschedules the failed range as N smaller pageSize requests (`subdivide_factor` in the shop config, default 5). The depth=1 sub-page carries `_sub=1` in its URL so it can't recurse. Each subdivision is logged as a `subdivided` row on `scrape_run_events` (renders as ⊟ in the dashboard's Timeline card).

### Post-phase auto-trigger (match step 1 + validate after every scan/discover)

`PostPhase` (`php/crawler/src/PostPhase.php`) wires every successful `scan` or `discover` close into:

1. **Match step 1 (ISBN match) inline** — a single fast `UPDATE shop_books SET book_id = bi.book_id WHERE sb.isbn = bi.isbn AND sb.book_id IS NULL`, in the crawler process (no separate `scrape_runs` row). Links any newly-scraped shop_book to existing canonical books by ISBN within milliseconds.
2. **Validate as a subprocess** — spawns `bin/validate --shop=<shop>` as a fire-and-forget detached process (`CRAWLER_PHP_BINARY` overrides which PHP it uses; spawn logs go to `SPAWN_LOG_DIR`, default `/var/log/scrapy_runs`). Creates a regular `scrape_runs` row (phase=`validate`). Picks up data-quality changes immediately and auto-resolves stale issues via `resolve_gone_issues`.

Hooks both `scan` and `discover` because shops like pegasas/iBiblioteka yield `ShopBookItem`s in the discover phase (scan is a no-op for them).

Skipped when:
- The run closes with `reason != "finished"` (failures don't propagate noise).
- The spider's `cron_job_id` points to a job whose `chain_to_job_id` targets `match` or `validate` — yields to the cron chain to avoid double-firing.
- Env var `POST_PHASE_AUTO_TRIGGER=0` (legacy alias: `POST_SCAN_AUTO_TRIGGER=0`).

This means **you don't need to schedule `match` or `validate` cron jobs**. Match step 2 (author backfill) and step 3 (synthesis) only run during a full `match` phase — currently optional/manual. Step 3 is disabled by default via `MATCH_SYNTHESIS_ENABLED` (see below).

### Scheduling — `runs:schedule` is the only thing that fires cron_jobs

`cron_jobs` rows are written by the dashboard's Schedules page. Until the
Python stack was removed, `scripts/generate_crontab.py` rendered them into the
scraper container's crontab at boot. With no container, **`php artisan
runs:schedule --watch` is what turns a row into a crawl** — nothing else does,
and without it the schedule is inert while still looking configured.

Run it and `runs:reap --watch` under a supervisor. Neither is optional:
without the reaper, a crawl that dies without unwinding stays `running` and
blocks its shop.

| Decision | Where | Why |
|---|---|---|
| Which windows are due | `CronSchedule::due()` | Pure function of jobs + clock + what this process fired, so it is unit-tested without spawning |
| Expressions are **UTC** | `CronSchedule::previousDue()` | The container's cron was UTC — job 1 is `0 2 * * *` and its runs start at 02:00Z. Reading them locally would shift every schedule in the table. |
| At most `--max-per-tick` (2) fire per pass | `ScheduleRuns` | Nine windows were due the first time it ran. The rest stay due and drain over later ticks. |
| One scheduled crawl per **shop**, any phase | `ScheduleRuns::activePhase()` | A backlog would otherwise start patogupirkti's sitemap discover, category discover and scan together — three crawls against one shop, tripling the request rate its delay exists to cap. |
| `paused` does **not** count as busy | same | The reaper leaves paused runs alone by design, so they sit indefinitely (there is one on patogupirkti from May). Counting it would stop that shop's schedules permanently. |
| `last_run_at` is not written here | `RunLifecycle` writes it | One writer. Note what the column means: it is stamped for **every** cron job of that shop+phase, so a manual scan suppresses the next scheduled one. |
| Spawns go to the DASHBOARD's database | `CrawlSpawner::databaseUrl()` | Built from Laravel's config, i.e. `php/dashboard/.env` (`DB_*`/`DB_URL`) — **not** `DATABASE_URL`, which the crawler uses and the dashboard ignores. So a dashboard pointed at the test database can only start test-database crawls. |
| A failed spawn is not marked fired | `ScheduleRuns::$firedAt` | `last_run_at` is only stamped once the crawl boots, so without an in-process record a job whose spawn dies is re-fired every tick. Demonstrated: the fixture shop has no parser, so its spawn exits and the guard is what stops the loop. |

Chaining needs nothing here: `PostPhase` spawns `chain_to_job_id` when a run
closes. Chained jobs also keep their own expressions and are fired on them,
exactly as the crontab did.

`cron_jobs.args` holds Python's `-a key=value` syntax, because it was appended
raw to a `scrapy crawl` line. Only `rescrape=true` is in use (the twice-monthly
full scans) and it maps to `--mode=full`. Anything else is **reported and not
applied** — silently dropping a scheduled job's argument would run a crawl that
does something other than what the row asks for.

### Feature flags

| Env var | Default | Effect |
|---|---|---|
| `POST_PHASE_AUTO_TRIGGER` | `1` | Auto-runs match step 1 + validate after every scan/discover. Set `0` to disable. |
| `MATCH_SYNTHESIS_ENABLED` | `0` | When the full `match` phase runs, step 3 (canonical synthesis from shop data) is skipped. Set `1` to re-enable. Disabled because the per-row synthesis loop on shops with ~2.5k unmatched books blocks the reactor past the 60s heartbeat reaper, killing steps 1 + 2 mid-transaction. When Rule 1 (multi-shop consensus synthesis, see `docs/superpowers/specs/2026-05-18-data-quality-rules-design.md`) lands with batched commits, remove this flag. |

### Validator issue types (recent additions)

| Issue type | Severity | What it detects |
|---|---|---|
| `slug_diacritic_loss` | info | Slug has more `-`-separated alphabetic pieces than the title has words AND the title contains LT diacritics. Catches shops whose slug generator drops diacritics character-by-character (e.g. `Kalėdų pūga` → `kale-du-pu-ga`) instead of transliterating to `kaledu-puga`. Suppresses the broader `slug_title_mismatch` on the same book via supersession. |
| `non_product_active` | info | `shop_book.is_active=true` but all its `discovered_urls` are `non_product`. Auto-heals: validator flips `is_active=false` when the predicate matches, so the issue resolves on the next run. |
| `non_book_has_isbn` (refined) | info | `type='non_book'` with a 978/979-prefixed ISBN — but **excludes** legitimate non-book products whose categories include `žaislai` / `žaidimai` / `dėlionės` / `sąsiuviniai` / `kortelės` / `žemėlapiai` / `raštinės` / `hobio` / `mokyklinės` / `popieriaus` / `lavinamieji` / `stalo žaid…` (case- and diacritic-insensitive). |
| `format_is_dimensions` | info | `shop_books.format` looks like a dimension expression (`17x24`, `170 x 205 mm`). Driven by parser bugs — `format_from_cover_type` now drops dimension-only inputs to None instead of leaking them. |
| `url_aliases` (refined) | info | `discovered_urls` row with a different URL shape than the canonical `shop_books.url`. Now filters URL-encoding mismatches (`mi%C5%A1ku-x` vs `mišku-x`) and OpenCart legacy route URLs (`index.php?route=product/product&product_id=N`) — those are platform-level aliases, not data-quality issues. |

### `match_isbn_drift` is stale state, not a matcher bug

`match.py` linkage is **strictly ISBN-exact**:

- Step 1: `UPDATE shop_books SET book_id = bi.book_id WHERE sb.isbn = bi.isbn AND sb.book_id IS NULL`.
- Step 2 (`_step2_author_backfill`) writes only to `shop_authors.canonical_author_id` — never touches `shop_books.book_id`.
- Step 3 (`_step3_shop_inferred_synthesis`, gated by `MATCH_SYNTHESIS_ENABLED=0`) synthesises a new canonical from the shop_book's own ISBN, then re-runs step 1.

No code path can link a shop_book to a canonical whose ISBNs disagree. So when `match_isbn_drift` fires, **the matcher didn't make a bad link** — the shop_book's `isbn` mutated *after* the link was made, and step 1's `WHERE sb.book_id IS NULL` guard means it's never re-evaluated. Causes seen in production: FlareSolverr session race writing another product's metadata to the wrong row, EAN vs ISBN parser slips, a URL being re-listed to a different product by the shop.

**Operator fix** (also surfaced as actions on the issue detail page): Re-scrape URL to refresh the shop_book ISBN, or Unlink & re-match (`POST /api/shop-books/{id}/unlink-canonical` clears `book_id` so step 1 can re-link by the corrected ISBN). Don't go looking for a matcher bug.

### Validator filter gates (cheatsheet)

Every validator that queries `shop_books` applies mandatory pre-filters. Missing one is a silent noise regression.

**Don't hand-write these predicates — build the WHERE prefix with `_live_books_where()`** (`book_scraper/services/validate.py`). It is the single source of the gates; a check that writes its own is what caused the drift below.

| Gate | SQL predicate | Applies to |
|---|---|---|
| Active books only | `sb.is_active = true` | **Every** validator that reads `shop_books` — `_live_books_where()` always emits it. Structural duplicates need it on both sides of the pair (pass the `sb2` alias in the EXISTS sub-select). |
| In-stock books only | `sb.in_stock = true` | `_live_books_where(in_stock=True)` — price checks only (`active_no_price`, `in_stock_no_price`, `no_price_history`, `price_zero`); out-of-stock books legitimately have no price. |

Two regression guards keep this honest: a source-level check that `is_active = true` appears exactly once in the module (`tests/unit/test_validate_service_structural.py`), and an all-inactive-shop integration test asserting **no** validator fires on delisted rows (`tests/integration/test_validate_service.py`) — that one catches a new check that forgets the gate, which a grep cannot. Seven checks had drifted ungated until 2026-07-25 (`book_no_metadata`, `book_no_signals`, `price_zero`, `format_is_dimensions`, `non_book_has_isbn`, `orphan_no_url`, `url_aliases`).

New issue types must be added to `ISSUE_KEYS` (validate.py) **and** `ISSUE_DESCRIPTIONS` (dashboard/queries.py) — `run()` raises on an unregistered key, because a typo'd key makes `resolve_gone_issues` silently close the real backlog and open a bogus one.

**Structural duplicate validators** (`isbn_duplicate`, `title_author_duplicate`) require `is_active = true` on **both** sides of the duplicate pair, not just the flagged book. Otherwise deactivated shop_books generate spurious duplicate issues against their still-active counterparts. (`sku_duplicate` was deleted in 2026-08: `uq_shop_books_shop_sku` makes the state it looked for impossible, and it only looked alive because the model was missing that index so the test schema allowed it.)

### Per-shop runtime settings

Precedence chain at runtime, highest to lowest:

1. **`shop_settings` DB row** — operator override applied without a redeploy.
2. **`config/shops/<shop>.toml` `[scraping]` block** — per-shop config; restart required.
3. **Scrapy globals from `book_scraper/settings.py`** — final fallback.

`HttpxMiddleware.spider_opened` walks the chain key-by-key: a DB row for `download_delay` wins for that key, but `concurrent_requests_per_domain` still falls through to TOML when no DB row exists.

Keys consumed: `concurrent_requests_per_domain` (int), `download_delay` (float).

```sql
-- Live override during an incident (no restart needed):
INSERT INTO shop_settings (shop_id, key, value, type)
VALUES ((SELECT id FROM shops WHERE name='pegasas'),
        'concurrent_requests_per_domain', '2', 'int')
ON CONFLICT (shop_id, key) DO UPDATE SET value=EXCLUDED.value, type=EXCLUDED.type;
```

### Key Design Decisions

- Generic spiders (`DiscoverSpider`, `ScanSpider`) — shop-specific logic lives in `php/src/<Shop>/Parser.php`, resolved through `ParserRegistry`
- `discovered_urls` table tracks all found URLs per shop (accumulate-only, never deleted)
- `scrape_runs` table logs each run's phase/status for crash detection and resume
- `shop_books` table stores full product metadata (title, author, ISBN, publisher, year, pages, etc.) — one row per book-as-it-appears-in-a-shop
- `prices` table is append-only (one row per scrape per shop_book)
- `books` table is for canonical records (shop-independent) — populated by match phase
- Per-shop settings in `config/shops/<shop>.toml`, loaded at spider init time
- The React SPA is canonical at `php/dashboard/public/static/hifi`. It was a symlink into the Python tree while both stacks existed, so the differential compared the API alone.

### Database

- Main DB: `postgresql://postgres:postgres@localhost:5432/book_scraper`
- Test DB: `postgresql://postgres:postgres@localhost:5433/book_scraper_php_test`
- Fixture DB: `…/book_scraper_php_test_fixture` — built from nothing by `make fixture-db`, and what the frozen API shapes are taken over
- Both clusters run in Docker via `docker-compose.yml`; the test one is behind `--profile test`
- A fresh test database needs only `php php/bin/migrate apply` — every fixture is planted by the tests themselves

### Adding a New Shop

1. Create `config/shops/<shop>.toml` with discovery strategies and scraping settings
2. Create `php/src/<Shop>/Parser.php`
3. Expose `parseSitemapUrls()`, `parseCategoryPage()`, `parseProductPage()`, and register it in `ParserRegistry`. `parseCategoryPage` returns `['products' => [...], 'total' => int|null]` — `total` enables upfront pagination on the first page (the spider enqueues all remaining pages from `total`, so `concurrent_requests_per_domain` actually engages instead of chaining one page at a time). Return `total = null` for HTML-scrape shops where the count isn't reliably surfaced; the spider falls back to per-page chained pagination.
4. Add a fixture under `fixtures/` and a parser test
5. No new spider classes needed — the generic spiders resolve the parser by shop name
6. `ParserRegistryTest` asserts the registry and `config/shops/*.toml` list the same shops, so a TOML without a parser fails the suite rather than a crawl

See the `📖 New Bookstore Onboarding Guide` Notion page for a full checklist + the pitfalls section captured during the pegasas onboarding (Magento `category_id` filter is membership-based and leaks across language siblings; EAN ≠ ISBN; e-book detection via category id since Magento has no `is_ebook`; etc.).

## Testing

Three suites, all against real PostgreSQL on port 5433 — no mocks:

- **`php/`** (library, ~2,110 tests) — parsers, validator, matcher, repositories, run lifecycle. `--exclude-group db` runs the offline half.
- **`php/crawler/`** (~50) — spider emit rules, scheduling, watchdog, reconciler.
- **`php/dashboard/`** (7, but 320 assertions) — the two big goldens plus route smoke tests.

`make test` runs all three. Fixtures are planted by the tests and cleaned up
after: **a tool that leaves its fixtures behind breaks the next one**, which
happened repeatedly while the goldens were being frozen (13,339 findings left
in place, a sentinel run with a fixed id that survived reseeds, a re-matched
catalogue). If a golden moves for no apparent reason, look for litter first.

### The characterisation goldens

These are the port's evidence, frozen while the Python stack still existed to
disagree with. Each was written by a differential tool that compared both
implementations and would only freeze once they already agreed — so what these
replay is Python's behaviour captured, not PHP's output blessed.

| Golden | Replayed by | Covers |
|---|---|---|
| `dashboard/tests/golden/api_shapes.json` | `ApiShapeCharacterisationTest` | 79 GET endpoints: status + response type-skeleton |
| `dashboard/tests/golden/mutation_cases.json` | `MutationCharacterisationTest` | 100 write-route cases, in sequence |
| `tests/golden/validate_findings.json` | `ValidateServiceCharacterisationTest` | 34 findings across all 20 issue types |
| `tests/golden/match_linkage.json` | `MatchServiceCharacterisationTest` | ISBN linkage + author backfill |
| `tests/golden/validator_cases.json` | `ItemValidatorCharacterisationTest` | 46 item-validation cases |
| `tests/golden/validate_predicates.json` | `ValidateHelpersDifferentialTest` | 1,823 predicate cases |
| `tests/golden/reaper_*.json` | `ReaperCharacterisationTest` | per-fixture reap verdicts |
| `tests/golden/canonical_expected.json` | `CanonicalBookCharacterisationTest` | canonical upsert |

**They cannot be regenerated.** The tools that wrote them were Python and are
gone, so a golden that fails is a regression to explain, not a file to refresh.

**Which freezes the fixture too.** `SyntheticShop` is the input the API and
write-route goldens were recorded over, so changing what it plants invalidates
them — and nothing can re-verify the new shapes against Python. Add rows for a
new test's benefit and those two goldens start failing with no honest way to
update them. If a test needs different data, plant it in the test, inside a
transaction, the way `ScheduleRunsTest` plants its own running run.

Two rules they depend on, both learned the hard way:

- **A golden can only describe data that comes back the same way every time.**
  The API and write-route goldens are taken over a database built from nothing
  (`php/schema` + `SyntheticShop`), not over a copy of the live catalogue — a
  reseed once turned a field from `str` into `null` and failed the test with
  nothing having regressed.
- **`SyntheticShop`** (`php/src/Testing/SyntheticShop.php`) is the fixture: 27
  rows that fire all 20 issue types plus their suppression cases, a matchable
  book, a canonical that disagrees with its shop_book, run history, a failure
  streak and a second shop. It refuses to build against anything but the test
  cluster, and refuses if any of its ISBNs already belongs to a real canonical.

## Post-Task Checklist

After completing any task that changes code, suggest to the user:

1. `make test` — all three suites. There are no images to rebuild: the crawler
   and dashboard run from the CLI, so a code change is live immediately.
2. After a schema change, `make schema-gate` — it builds a scratch database
   from `php/schema` and diffs it against the live schema. This is the check
   that catches enums, partial unique indexes, CHECK expressions and FK
   actions; a missing partial unique index once made a dead validator check
   look alive for months.
3. After a schema change, also run a one-URL scan
   (`php bin/crawl scan --shop=vaga --urls=<one-url>`) to confirm the models
   still match what the database has.
4. After deploying single-row restarts (2026-05-09): on shops with large
   stale-failed backlogs (humanitas, patogupirkti), the first scan may
   trigger an end-of-run retry sweep over hundreds–thousands of URLs.
   Watch heartbeat during the first run; if the sweep extends past
   STALL_TIMEOUT, the run will restart cleanly (single-row, capped at
   STALL_AUTO_RESUME_MAX restarts). To grandfather stale failures as
   exhausted before the first run, run:
   `UPDATE scrape_url_items SET attempts=3 WHERE status='failed';`
5. **Observability stack changes** (`monitoring/`, Grafana provisioning, Alloy config, Loki config): no rebuild — just `docker compose up -d loki alloy grafana` (or `docker compose restart grafana` for provisioning-only edits, `docker compose restart alloy` for Alloy config changes). Upstream images are pulled, not built.

### Observability label cardinality (Loki)

The Loki index can only afford low-cardinality labels. The four allowed labels are:
- `service` — bounded set (dashboard, scraper, postgres, flaresolverr, loki, promtail, grafana). `scraper`/`dashboard` were container names; with no application images the crawler's spawn logs reach Loki through the `scraper_logs` volume instead.
- `level` — INFO / WARNING / ERROR / DEBUG / CRITICAL
- `role` — operator / stall-resume / cron-chain / reconcile-restart / cron
- `shop` — vaga / pegasas / humanitas / future shops

**Never promote `run_id` to a label.** It's unbounded and would explode the index. Filter via LogQL `|= "run_id=N"` instead. Phase 4 (CODEOBS-02) emits `key=value` log lines so `| logfmt` works.

### Counter drift probe (single-row restart era)

With single-row restarts, old + new processes can briefly write to the same
`scrape_runs` row during handover (~60s window). Aggregate counters can
drift by tens of items. To check whether drift has crossed cosmetic levels:

```sql
SELECT id, urls_processed, urls_total,
       urls_processed - urls_total AS drift
FROM scrape_runs
WHERE urls_total IS NOT NULL AND urls_processed > urls_total
ORDER BY drift DESC LIMIT 10;
```

Drift of 1–10 across the fleet: cosmetic, ignore.
Drift of 50+ on a single run: investigate (process fencing may be needed —
see spec's Architectural alternatives section).

### Don't `kill -9` a runaway crawl

If a loop spawned several crawls, **don't** mass-`kill -9` them. Detached
processes killed that way leave open TCP sockets, and on macOS the Docker
networking shim can wedge for 5–10 minutes when that happens inside a
container. SIGTERM first: `bin/crawl` installs a termination handler that stops
the watchdog and lets the run finalise, so `close_reason` is persisted instead
of the run being left `running` for the reaper to find.

1. `kill <pid>` (SIGTERM) and give it the `stop_grace_period` it needs — the
   close path finalises the run and aborts in-flight queue items.
2. `php artisan runs:reap` if a run was still left non-terminal.
3. Only then SIGKILL.

## Code Conventions

- PHP 8.4 (roach-php caps there), `declare(strict_types=1)` in every file
- `make lint` is `php -l` over every file. Pint is installed but **not** enforced: the codebase has never been pint-formatted, so running it would be a reformatting sweep, not a lint.
- Commit directly on main (personal project, no branches)
- Tests use real PostgreSQL (Docker on port 5433), not mocks
- Items are plain arrays, validated by `ItemValidator` (`php/src/Crawler/ItemValidator.php`)
- Comments of the form "port of `book_scraper/…`" record where a class came from. Those files are gone from the tree but present at the `python-final` tag.

## Specs and Plans

- **PHP port + Python removal:** `docs/superpowers/plans/2026-08-25-python-fixes-and-removal-plan.md` — the nine defects the differential found, and what phase 6 (freezing the evidence) cost. Read this before touching a golden.
- Design spec: `docs/superpowers/specs/2026-04-05-book-scraper-design.md`
- Implementation plan: `docs/superpowers/plans/2026-04-05-book-scraper-plan.md`
- Fault tolerance spec: `docs/superpowers/specs/2026-04-06-fault-tolerance-design.md`
- Fault tolerance plan: `docs/superpowers/plans/2026-04-06-fault-tolerance-plan.md`
- Dashboard redesign spec: `docs/superpowers/specs/2026-04-14-dashboard-redesign-design.md`
- Dashboard redesign plan: `docs/superpowers/plans/2026-04-14-dashboard-redesign-plan.md`
- vaga.lt strategy: Notion page "vaga.lt scraping strategy"
- pegasas.lt strategy: Notion page "pegasas.lt scraping strategy"
- Architecture: Notion page "Scraping Strategy & Architecture"
- Onboarding checklist + pitfalls: Notion page "📖 New Bookstore Onboarding Guide"
