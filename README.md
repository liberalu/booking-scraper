# Book Price Scraper

Multi-shop book price comparison for Lithuanian e-shops. Scrapes book data and
prices, stores them in PostgreSQL, tracks price changes over time, and reports
data-quality problems it finds in its own output.

> This was a Scrapy project until 2026-08-26. It was ported to PHP, verified
> against the original by differential testing — identical input through both
> implementations, outputs compared — and the original was then removed. The
> last commit containing it is tagged `python-final`; the frozen fixtures and
> goldens preserve the comparison evidence.

## Architecture

One Laravel application, and it is the repository:

| Directory | What it is |
|---|---|
| `app/Parsers/`, `app/Repositories/`, `app/Services/`, `app/Runs/` | Domain parsing, persistence, use cases, and run lifecycle. |
| `app/Crawler/` | The crawler: roach-php spiders, watchdog, scheduling. |
| `app/Http/Requests/`, `app/DTO/` | Validated HTTP input and framework-neutral request/response values. |
| `app/Queries/`, `app/Services/` | Read models and business operations used by thin controllers. |
| `app/Http/Controllers/`, `routes/` | HTTP adapters for the JSON API and React SPA. |
| `bin/` | The CLI entry points: `crawl`, `validate`, `match`, `migrate`. |

These were three composer projects under `php/`, wired together with path
repositories, until 2026-08-26. `config/` holds both Laravel's `*.php` config
and the shops' TOML; Laravel only ever loads the former.

Per-shop behaviour is configuration plus one parser class; the spiders
themselves are generic.

### Pipeline phases

| Phase | Command | What it does |
|---|---|---|
| Discover | `php artisan crawler:run discover --shop=vaga --strategy=sitemap` | Find product URLs |
| Discover | `php artisan crawler:run discover --shop=vaga --strategy=categories` | Find URLs and extract current prices |
| Discover | `php artisan crawler:run discover --shop=vaga --strategy=full_crawl` | Follow every internal link from one seed |
| Discover | `php artisan crawler:run discover --shop=pegasas --strategy=graphql` | Magento GraphQL: full metadata, slow |
| Discover | `php artisan crawler:run discover --shop=pegasas --strategy=lupasearch` | Third-party search index: fast price/stock rescan |
| Scan | `php artisan crawler:run scan --shop=vaga` | Scrape full product pages, resumable after a crash |
| Validate | `bin/validate --shop=vaga` | 20 data-quality checks over what was scraped |
| Match | `bin/match --shop=vaga` | Link shop books to canonical books by ISBN, backfill authors |

Schedules live in `cron_jobs` and are fired by `artisan runs:schedule`, which
replaced the crontab the Python container rendered at boot. Expressions are
read as UTC, which is what that crontab used.

For the Magento PWA shops the scan phase is a no-op — those product pages are a
React shell, so discovery yields the full record inline.

A successful scan or discover triggers match step 1 and a validate run on its
own (`PostPhase`), so neither needs scheduling.

### Shops

| Shop | Platform | Protection | Rows today |
|---|---|---|---|
| [patogupirkti.lt](https://patogupirkti.lt) | — | none | 50,604 |
| [vaga.lt](https://vaga.lt) | OpenCart | none | 19,605 |
| [pegasas.lt](https://pegasas.lt) | Magento 2 PWA | none | 17,416 |
| [humanitas.lt](https://humanitas.lt) | WooCommerce + WPML | Cloudflare Managed Challenge | 13,846 |
| ibiblioteka.lt | API | none | canonical records only |
| almalittera.lt | — | none | configured, not yet crawled |

Humanitas goes through the FlareSolverr sidecar, opted into per shop by a
`[flaresolverr]` block in its TOML.

## Quick start

Requires PHP 8.4 (roach-php caps there — Homebrew's default `php` is 8.5, so
the Makefile pins `/opt/homebrew/opt/php@8.4/bin/php`), composer, and Docker.

```bash
make install                                        # install PHP dependencies
docker compose up -d postgres                       # the live database
php bin/migrate apply --database=postgresql://postgres:postgres@localhost:5432/book_scraper
```

Then crawl something:

```bash
php artisan crawler:run discover --shop=vaga --strategy=sitemap
php artisan crawler:run scan --shop=vaga --max-urls=20         # a small first run
```

`crawler:run` writes to whatever `DATABASE_URL` points at, so `--database` is
offered explicitly and `--dry-run` fetches and parses without persisting.

The dashboard:

```bash
php artisan serve --port=8002
```

Or in compose, which is how it is meant to run:

```bash
make compose-build          # build the image (clears the OrbStack proxy vars)
make compose-up             # postgres + dashboard + reaper
make compose-up-scheduler   # ...and the scheduler. THIS STARTS CRAWLING.
```

`make compose-up` is safe any time: nothing crawls on its own. Adding the
scheduler fires every schedule whose window has passed, one per tick, against
live shops — after downtime that is a backlog. Check it first with
`docker compose run --rm scheduler php artisan runs:schedule --dry-run`.

Outside compose, the same two commands have to stay running for the system to
look after itself:

```bash
php artisan runs:schedule --watch    # fires the schedules in cron_jobs
php artisan runs:reap --watch        # fails runs whose process died
```

Without the first, the Schedules page still accepts schedules and nothing ever
fires them. Without the second, a crawl that dies without unwinding stays
`running` and blocks its shop. `runs:schedule --dry-run` reports what it would
fire without spawning anything.

Note the database each side reads: `crawler:run` takes `DATABASE_URL`, but the
dashboard — and therefore the scheduler, and the crawls it spawns — takes
Laravel's `DB_*` / `DB_URL` from `.env`. `DATABASE_URL` is
ignored there. The crawls a scheduler starts always go to the database that
dashboard is reading, which is deliberate: an operator looking at the test
database cannot start a crawl against the live one.

## Tests

```bash
docker compose --profile test up -d postgres-test
php bin/migrate apply --database=postgresql://postgres:postgres@localhost:5433/book_scraper_php_test
make test            # library + crawler + dashboard
make test-offline    # everything that needs no database
```

Real PostgreSQL, no mocks. Every fixture is planted by the tests themselves, so
an empty database with the schema applied is all they need — nothing has to be
copied in from the live catalogue.

Eight of those tests replay **characterisation goldens**: recordings of what the
Python stack did, frozen while it still existed, and only ever written when both
implementations already agreed. They cannot be regenerated — the tools that
wrote them were Python. A golden that fails is a regression to explain, not a
file to refresh. `CLAUDE.md` lists them.

## Project structure

```
config/
    default.toml              # global settings (delays, DB URL)
    shops/<shop>.toml         # per-shop URLs, strategies, concurrency

app/
    Books/                    # shop-neutral classification rules
    Parsers/<Shop>/           # per-shop parsing, testable without a spider
    Repositories/             # all PostgreSQL reads/writes, split by concern
    Services/                 # domain and API application services
    Runs/                     # lifecycle, failsafe, resume policy, scan lock
    Crawler/                  # roach-php spiders, watchdog, scheduling
    Http/Controllers/Api/     # thin Laravel request adapters
bin/                          # crawl, validate, match and schema entry points
database/schema/              # schema applied by bin/migrate
tests/Support/                # synthetic database fixtures and helpers
tests/golden/                 # immutable characterisation goldens
tests/fixtures/               # saved HTML/JSON parser inputs
public/static/hifi/           # built React dashboard
monitoring/                   # Loki, Alloy, Grafana provisioning
docs/                         # port history and current follow-ups
```

## Database

25 tables. The ones that matter most:

- `discovered_urls` — every URL ever found, per shop. Accumulate-only.
- `shop_books` — one row per book as it appears in one shop.
- `prices` — append-only, one row per scrape per shop book.
- `books` + `book_isbns` — canonical, shop-independent records.
- `scrape_runs` + `scrape_url_items` — run bookkeeping, crash detection, resume.
- `validation_issues` — what the validator found, with a lifecycle.

Schema changes go in `database/schema/` and are applied by `bin/migrate`.
There are no Laravel migrations because `artisan migrate` lacks that
migrator's production guards.
`make schema-gate` builds a scratch database from the baseline and diffs it
against the live schema — that is what catches enums, partial unique indexes,
CHECK expressions and FK actions.

## Configuration

`config/default.toml` holds global defaults; `config/shops/<shop>.toml`
overrides them per shop. At runtime the precedence is: a `shop_settings` row in
the database (an operator override, no restart needed), then the shop's TOML,
then the global default.

## Deployment

Compose builds one application image and runs it as the dashboard, scheduler,
and reaper services, alongside PostgreSQL, FlareSolverr, Loki, Alloy, and
Grafana. Published service ports are loopback-only by default; the dashboard
has no authentication, so do not widen its bind address without adding an
authenticated reverse proxy.
