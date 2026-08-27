# Book Price Scraper

Multi-shop book price comparison for Lithuanian e-shops. Scrapes book data and
prices, stores them in PostgreSQL, tracks price changes over time, and reports
data-quality problems it finds in its own output.

> This was a Scrapy project until 2026-08-26. It was ported to PHP, verified
> against the original by differential testing — identical input through both
> implementations, outputs compared — and the original was then removed. The
> last commit containing it is tagged `python-final`. See
> [the removal plan](docs/superpowers/plans/2026-08-25-python-fixes-and-removal-plan.md)
> for the nine defects the comparison found and how the evidence was preserved.

## Architecture

One Laravel application, and it is the repository:

| Directory | What it is |
|---|---|
| `app/Parsers/`, `app/Repositories/`, `app/Services/`, `app/Runs/` | The domain: parsers, repositories, validator, matcher, run lifecycle. |
| `app/Crawler/` | The crawler: roach-php spiders, watchdog, scheduling. |
| `app/Http/`, `routes/api.php` | The JSON API, plus the React SPA served from `public/static/hifi`. |
| `bin/` | The CLI entry points: `crawl`, `validate`, `match`, `migrate`. |

These were three composer projects under `php/`, wired together with path
repositories, until 2026-08-26. `config/` holds both Laravel's `*.php` config
and the shops' TOML; Laravel only ever loads the former.

Per-shop behaviour is configuration plus one parser class; the spiders
themselves are generic.

### Pipeline phases

| Phase | Command | What it does |
|---|---|---|
| Discover | `bin/crawl discover --shop=vaga --strategy=sitemap` | Find product URLs |
| Discover | `bin/crawl discover --shop=vaga --strategy=categories` | Find URLs and extract current prices |
| Discover | `bin/crawl discover --shop=vaga --strategy=full_crawl` | Follow every internal link from one seed |
| Discover | `bin/crawl discover --shop=pegasas --strategy=graphql` | Magento GraphQL: full metadata, slow |
| Discover | `bin/crawl discover --shop=pegasas --strategy=lupasearch` | Third-party search index: fast price/stock rescan |
| Scan | `bin/crawl scan --shop=vaga` | Scrape full product pages, resumable after a crash |
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
make install                                        # composer install, all three projects
docker compose up -d postgres                       # the live database
php bin/migrate apply --database=postgresql://postgres:postgres@localhost:5432/book_scraper
```

Then crawl something:

```bash
php bin/crawl discover --shop=vaga --strategy=sitemap
php bin/crawl scan --shop=vaga --max-urls=20         # a small first run
```

`bin/crawl` writes to whatever `DATABASE_URL` points at, so `--database` is
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

Note the database each side reads: `bin/crawl` takes `DATABASE_URL`, but the
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

php/
    src/                      # the library
        <Shop>/Parser.php     # per-shop parsing, testable without a spider
        Services/             # ValidateService, MatchService
        Repository/           # shop books, canonical books
        Runs/                 # reaper, failsafe, resume policy, scan lock
        Testing/              # SyntheticShop, FixtureDatabase — fixtures as code
    crawler/                  # roach-php spiders, watchdog, scheduling
    dashboard/                # Laravel API + the React SPA under public/static
    schema/0001_baseline.sql  # the whole schema; applied by bin/migrate
    tools/schema_gate.sh      # does the baseline still match the live schema?
    tests/golden/             # characterisation goldens

fixtures/                     # saved HTML/JSON for parser tests
monitoring/                   # Loki, Alloy, Grafana provisioning
docs/                         # specs, plans, follow-ups
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
(`database/migrations/` is deliberately empty — `artisan migrate` has none of
that migrator's guards, and `.env` points at the live catalogue.)
`make schema-gate` builds a scratch database from the baseline and diffs it
against the live schema — that is what catches enums, partial unique indexes,
CHECK expressions and FK actions.

## Configuration

`config/default.toml` holds global defaults; `config/shops/<shop>.toml`
overrides them per shop. At runtime the precedence is: a `shop_settings` row in
the database (an operator override, no restart needed), then the shop's TOML,
then the global default.

## Deployment

Compose runs infrastructure only — postgres, flaresolverr, loki, alloy,
grafana. The crawler and dashboard run from the CLI; there are no application
images yet. Packaging them is phase 2 of the removal plan.
