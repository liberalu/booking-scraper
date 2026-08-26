# The PHP stack

> **This document was written during the port, while the Python stack was still
> here to be compared against — and it is kept in that voice, because the
> measurements are the evidence for the port and rewriting them in the past
> tense would blur what was actually checked.**
>
> Python was removed on 2026-08-26 (`python-final` is the last commit with it).
> Two consequences for reading this:
>
> - **Every `make *-diff` command below is gone.** They needed both stacks. What
>   replaced them is eight characterisation goldens the suite replays — frozen
>   from those same comparisons, and only ever written when both stacks already
>   agreed. `CLAUDE.md` lists them. They cannot be regenerated.
> - **`make golden` and `make seed-test-db` are gone too.** The goldens were
>   dumped from Python parsers, and seeding copied the live catalogue for the
>   differentials to run over. The suite now plants every fixture itself, from
>   code, and passes against an empty database with only the schema applied.
>
> The schema section is the exception that is still live: `tools/schema_gate.sh`
> compares PHP's baseline against the real catalogue's schema, which needs no
> Python and remains the gate on schema changes.

The crawler and dashboard. Formerly a rewrite running **beside** a Python
stack against the same Postgres; now the only implementation.

Three composer projects, not one — see the Guzzle note below for why:

| | |
|---|---|
| `.` | `book-scraper/php` — models, config, parsers, repositories, pipeline. No framework. |
| `crawler/` | roach-php crawler. Requires the library + roach. |
| `dashboard/` | Laravel API serving the existing React SPA. Requires the library. |

Status: **complete and verified against Python** — all six shop parsers, all
four phases, the validator, the matcher, the fault-tolerance layer, and every
dashboard endpoint including the 23 write routes. The differential found nine
defects in the process, all fixed in both stacks; see
`docs/superpowers/plans/2026-08-25-python-fixes-and-removal-plan.md`.

## Ground rules

**PHP owns the schema now.** `schema/0001_baseline.sql` is a dump of what
Alembic produced, and `bin/migrate` applies it. The guard survives the
handover: `apply()` refuses a database that has an `alembic_version` table and
no PHP ledger unless `--adopt` is passed, so the live catalogue cannot be
migrated by accident. `tools/schema_gate.sh` is what proves the baseline still
reproduces that catalogue's schema.

**One config source.** `Config` reads the same `config/default.toml` and
`config/shops/*.toml` as Python. Two drifting copies of `download_delay`
is a rate-limit incident waiting to happen.

**Nothing landed unverified against Python.** A port has no spec of its own —
its spec is the behaviour of the code it replaces. That is why the goldens
exist: the comparison is over, so the recordings are the spec now.

## Verification method

Rather than re-asserting the Python test suite by hand, each ported unit is
checked *differentially*: identical input through both implementations,
outputs compared.

| Unit | Check | Scale |
|---|---|---|
| `Vaga\Parser` | Output vs golden JSON dumped from the Python parser over the shared `tests/fixtures/` | 3 fixtures, full dict compared field by field |
| `UrlUtils` | Output vs Python `normalize_url` | 62-case corpus in CI; **809,757 production URLs** compared offline, 0 differences |
| `Casts\PostgresTextArray` | Round-trip through a real Postgres `text[]`, both directions | 9 shapes incl. embedded commas, quotes, backslashes |
| `Isbn`, `CoverType` | Behaviour parity on the signatures Python encodes | checksum + corruption fingerprints, LT cover labels |
| Crawler (end-to-end) | Rows written vs rows Python writes for the same URLs (`make crawl-diff`) | shop_books, attributes, authors, discovered_urls, price counts |
| Dashboard API | Payload vs the Python endpoint, fetched simultaneously (`make api-diff`) | 88 endpoint+filter combinations, incl. 404 bodies and CSV |
| Shop parsers | Output vs golden dumped from each Python parser over the shared fixtures | 6 shops, 20 fixtures |
| Dashboard mutations | Response *and* resulting database state vs Python's, on two clones of the test DB (`make mutation-diff`) | 101 cases across all 23 write routes |
| Discovery URL builders | Synthetic URLs and POST bodies vs Python's, byte for byte | 11 cases over graphql / lupasearch / ibiblioteka_api |
| Validation layer | Rewritten item + drop decision + issues recorded, on identical items (`make validator-diff`) | 46 cases, one per check plus the interactions |
| Description conversion | Output vs `markdownify(html, heading_style="ATX")` | 31 cases: fixtures, live pages, hand-built tag shapes |
| Canonical-book writer | Rows written from the same library record (`make canonical-diff`) | books + book_isbns + book_authors, keyed on source_url |
| Reaper | What each one does to identical zombie runs (`make reaper-diff`) | 5 run shapes × 6 tables |

These goldens were dumped from the Python implementations, and a git diff on
`tests/golden/` after re-dumping was the signal that Python behaviour had moved
and the PHP side needed the same change.

**That is no longer possible, by design.** The dumpers were Python. What is in
`tests/golden/` is the last recording of a stack that no longer exists, so a
failing golden means the PHP side changed — there is nothing else it can mean.

### What the harness could not see

Three gaps hid behind a green comparison, and each one is a lesson about the
method rather than about the code:

- **A table nobody compared.** `crawl_diff` diffed 11 of the schema's 25
  tables, so `shop_book_field_updates` — which the Python pipeline writes and
  the PHP one did not — never showed up. A differential is only as wide as its
  projection.
- **A column compared as a boolean.** The `shop_books` projection selected
  `description is not null as has_desc`, so it could not see that Python stored
  Markdown where PHP stored raw HTML. Production has **zero** HTML
  descriptions; every scraped book would have regressed.
- **A ported parser is not a ported consumer.** `Ibiblioteka\Parser` tags its
  output `_emit_as: 'book'` and was golden-tested against Python's. Nothing on
  the PHP side read that tag, so a library record — which has a title and does
  claim to be a book — sailed through the scan gate and would have been stored
  as a `shop_books` row.

All three are now compared: the projection covers every table a write can
touch, `description` is compared as text, and the canonical writer has its own
differential.

## Setup

roach-php supports PHP ≤ 8.4, so pin the runtime (Homebrew's default is
8.5, which composer will refuse):

```bash
brew install php@8.4 composer
```

```bash
cd php && PATH="/opt/homebrew/opt/php@8.4/bin:$PATH" composer install
```

## Tests

Three suites: the library here, `crawler/`, and `dashboard/`. `make test` runs
all three; `make test-offline` runs everything that needs no database.

```bash
docker compose --profile test up -d postgres-test
php bin/migrate apply --database=postgresql://postgres:postgres@localhost:5433/book_scraper_php_test
make test
```

**They need nothing but the schema.** Every fixture is planted by the tests
themselves — `Testing\SyntheticShop` builds a whole shop from code, and the
dashboard's goldens build a fixture-only database from
`schema/0001_baseline.sql` (`make fixture-db`). Verified: the full suite passes
against an empty database. That is what made removing Python a deletion rather
than a migration, and it is why `seed_test_db.py` never needed porting — it
existed to give the differentials realistic data.

### Fixtures get cleaned up, always

This cost more debugging than anything else while the goldens were being
frozen. A tool or test that leaves its fixtures behind breaks the next one, and
the failure surfaces somewhere unrelated:

- 13,339 validation findings left in place changed the first row of
  `/api/issues`, which failed a frozen API shape in another package.
- A sentinel run with a fixed id survived every reseed, became the newest run
  in the database, and put a half-populated `validate` row at the top of the
  dashboard's recent-runs list.
- A re-matched catalogue moved `/api/books?has_conflicts=true`.
- Three marked books moved the first row of every book list.

If a golden fails for no apparent reason, look for litter before looking at the
code.

### The test database

`book_scraper_php_test`, on port 5433, created by the `postgres-test` compose
service (`POSTGRES_DB`) and schema'd by `bin/migrate`. Plus
`book_scraper_php_test_fixture`, which `bin/fixture-db` drops and rebuilds from
nothing — that one is where the frozen API shapes and write-route cases are
taken, precisely because it holds no copy of the live catalogue and therefore
comes back identical every time.

Both refuse to be anywhere but the test cluster: `SyntheticShop` and
`FixtureDatabase` check the port first, because the real catalogue is the only
thing on 5432 and those classes drop and rebuild what they are pointed at.

## Schema

Alembic's 118 revisions are deliberately **not** re-expressed. `schema/0001_baseline.sql`
is `pg_dump --schema-only` of the live catalogue, kept verbatim: a dump cannot
drift from the schema it was dumped from, and hand-translating 12 enums, 5
unique indexes (4 of them partial) and 3 CHECK expressions is precisely where
a schema port loses fidelity. `alembic/` stays as read-only history.

```bash
make schema-gate                 # THE GATE: fresh DB from the baseline, diff to zero
make schema-gate-sabotage        # prove the gate can fail
make schema-baseline             # re-dump the baseline (reads the reference only)
make migrate-status MIGRATE_DATABASE_URL=postgresql://…:5433/somedb
make migrate        MIGRATE_DATABASE_URL=postgresql://…:5433/somedb
```

The migrator is `bin/migrate` + `src/Schema/Migrator.php`, ~200 lines, and
deliberately not `illuminate/database`'s: that one wants PHP migration classes
built out of the schema builder, and needs `illuminate/filesystem` plus an
event dispatcher that aren't installed. Plain `.sql` files applied in lexical
order, each in one transaction, each recorded in `public.php_schema_migrations`
— **the one table PHP owns.** The ledger is created by the migrator, not by
0001, so 0001 stays a byte-faithful dump; the gate excludes the ledger from
*both* sides of the diff, because an asymmetric exclusion is how a gate starts
comparing two different things.

Migrations live here, in `php/`, shared by crawler and dashboard — never in
`dashboard/database/migrations/`, whose `.gitkeep` explains why that directory
must stay empty.

### What stops it reaching production

- `bin/migrate` takes an explicit `--database=DSN` (or `DATABASE_URL`) and has
  **no** fall-through to `config/default.toml`, whose `[database].url` is
  production. A migrator that picks a target when you forgot to name one picks
  production.
- `apply()` refuses any database that has an `alembic_version` table and no PHP
  ledger: *Alembic owns this one.* A port-number check would not do — the
  Python test database is stamped too, and it lives on the test cluster.
  `--adopt` overrides it, which is cutover's switch and nothing else's.
- The gate refuses to create its scratch database on port 5432, and touches the
  reference with exactly one `pg_dump --schema-only`.

### The gate

`tools/schema_gate.sh` creates a scratch database on the test cluster, applies
the baseline into it with `bin/migrate`, dumps both it and the reference,
normalises, and diffs. Exit code is non-zero on any difference, so it is a gate
rather than a report. Currently **2,143 lines identical — 25 tables, 12 enums,
5 unique indexes, 3 check constraints.**

`REFERENCE_DATABASE_URL` defaults to production (read-only) and
`SCRATCH_CLUSTER_URL` to the test cluster. Neither `psql` nor `pg_dump` is on
this machine's PATH — both clusters are containers — so `tools/pg_client.sh`
borrows one, preferring a host binary, then `docker exec` into the test
cluster's container, then `docker run --rm postgres:16`.

**Normalisation is three rules and no more.** Two are cosmetic — psql's
`\restrict` / `\unrestrict` guards carry a random per-invocation token, and the
`-- Dumped by pg_dump version` header. The third is real, and it is why the
gate needs a normaliser at all: Postgres deparses one CHECK constraint two
equivalent ways, and the baseline is a restored dump by construction, so the
difference is permanent.

```
= ANY ((ARRAY['started'::character varying, …])::text[])          -- as SQLAlchemy emitted it
= ANY (ARRAY[('started'::character varying)::text, …])            -- as Postgres re-renders it
```

Both fold to `ANY (ARRAY['started'::character varying, …])`. The two
substitutions are pinned to those exact shapes — the outer strips `::text[]`
only where it is applied to an `ARRAY` inside `ANY (…)`, the inner strips
`::text` only where it is re-applied to an already-cast `character varying`
literal. A blanket "strip anything cast-shaped" would silence the false
positive *and* stop the gate catching real type changes, which is most of what
it exists for. `SchemaNormalizeTest` asserts both halves: the two renderings
converge, and a changed value, element type or array cast still differs.

### The gate has teeth

A gate that cannot fail proves nothing, and this repo has been caught by
exactly that twice — a test asserting `"price" in row` passed while every price
was `None`, and `sku_duplicate` looked covered because the test schema was
missing the partial unique index production has.

So `make schema-gate-sabotage` copies the baseline, deletes
`CREATE UNIQUE INDEX uq_shop_books_shop_sku` from the copy — the very index
whose absence made that dead check look alive — and requires the gate to exit
non-zero *and* name it. It does: exit 1, index named. The checked-in baseline
is never touched; the copy lives in a temp directory.

`SchemaMigratorTest` covers what the gate cannot — that applying twice applies
nothing twice, that an edited applied migration is reported as drift, that a
failed migration leaves no ledger row, and that the Alembic guard refuses and
`--adopt` overrides it. Each test gets its own throwaway database on the test
cluster.

### Production has one change Alembic never made

Measured while building the baseline, and the reason it is dumped from
production rather than from a database built by `alembic upgrade head`:

```
url_classifications_discovered_url_id_fkey
  production:    FOREIGN KEY (discovered_url_id) REFERENCES discovered_urls(id) ON DELETE CASCADE
  alembic head:  FOREIGN KEY (discovered_url_id) REFERENCES discovered_urls(id)
```

`ON DELETE CASCADE` appears in neither migration `6437528439cc` (which created
the table) nor `db/models.py`, and nothing in the repo mentions it — someone
`ALTER`ed it on production directly. A pristine `alembic upgrade head` database
differs from production by that **one line and nothing else**, which is also
the check that the round-trip is otherwise faithful.

Production is what the code actually runs against, so production is the
reference. Worth an Alembic revision to close the gap, or a decision that the
cascade is unwanted — but not something to fix silently inside a dump.

Separately, the **Python test database is not production's schema**: it lacks
that cascade and carries a blank `COMMENT ON SCHEMA public`, both artifacts of
pytest rebuilding it from `Base.metadata`. Same class of drift as fix #7. Don't
use it as the gate's reference.

## Two upstream ceilings worked around

**Sub-second request delays.** `RequestSchedulerInterface::setDelay()` is
typed `int`, and `SystemClock::sleepUntil()` truncates to whole seconds via
`getTimestamp()`. Five of six shops pace below 1s (vaga 0.2, ibiblioteka
0.1, almalittera 0.3, humanitas/patogupirkti 0.5), so stock roach forces a
choice between hammering the shop at 0s and running ~5× slower at 1s.
`Scheduling\SubSecondRequestScheduler` + `SubSecondClock` keep the
microseconds and are bound over roach's defaults in the DI container.

**roach-php and Laravel cannot share a composer project.** roach-php 3.x
pins Guzzle `^7.8`; Laravel 13 ships Guzzle 8. Since only the crawler needs
roach — the dashboard consumes this package for models, config and URL
helpers — `roach-php/core` sits in `require-dev` and PSR-4 keeps
`Scheduling\*` from ever loading in the dashboard. Installing roach in a
Laravel app means downgrading Laravel or splitting the package.

**`parse_url()` corrupts UTF-8 paths.** It substitutes `_` for some
non-ASCII bytes: `/asmeninis-tobulėjimas` → `/asmeninis-tobul\xc4_jimas`.
Since `normalized_url` backs a unique constraint, that corruption would
surface as duplicate products, not as an error. `UrlUtils::split()` uses an
RFC 3986 regex instead. `UrlUtilsDiacriticsTest` fails if anyone swaps it
back, and also fails if a future PHP release fixes `parse_url` — at which
point the workaround can go.

## Crawler (`crawler/`)

Discovers and scans any of the six shops: live fetch → parse → upsert →
price row → URL link, with each run recorded in `scrape_runs`.

```bash
make discover STRATEGY=sitemap           # 21,613 URLs, one fetch
make discover STRATEGY=categories PAGES=3
make crawl MAX=5 ARGS=--dry-run          # fetch + parse, write nothing
make crawl URLS=https://vaga.lt/trys-vasaros
make crawl MAX=50                        # from the pending queue
make crawl MAX=0 ARGS=--mode=full        # re-scrape everything, uncapped
make crawl-diff                          # scan: both stacks, diff the rows
make discover-diff STRATEGY=sitemap      # discover: both stacks, diff the rows
make mutation-diff                       # every write endpoint, both stacks
```

`--max-urls=0` means uncapped, which is what the dashboard passes; the CLI
default stays at 20 so an interactive `make crawl` cannot start a 30k-URL
crawl by accident. `--mode` mirrors the Python scan's delta/full split:
delta skips URLs already confirmed as products, full re-scrapes them.

`DATABASE_URL` decides where rows land and defaults to the **live**
database, which is why `--dry-run` exists and why `crawl-diff` is hard-wired
to the test database.

### The checks that make it trustworthy

Both stacks run the same phase against the test database and everything they
wrote is diffed — `shop_books`, `shop_book_attributes`,
`shop_book_authors`, `discovered_urls`, `prices` count.

| Check | Result |
|---|---|
| `make crawl-diff` (vaga) | identical |
| `make crawl-diff SHOP=pegasas` | identical (via the GraphQL rewrite) |
| `make crawl-diff SHOP=patogupirkti` | identical |
| `make crawl-diff SHOP=almalittera` | identical on books AND on merchandise |
| `make discover-diff STRATEGY=sitemap` | identical, 21,613 URLs |
| `make discover-diff STRATEGY=categories` | identical aggregates |

Two exclusions, both measured rather than assumed:

- **`price` value** moves between the two passes because the shop is live,
  so prices are compared by row count.
- **A both-empty result is reported as INCONCLUSIVE, not as a pass.** The
  tool used to print "identical" when *both* stacks had failed. It did that
  for humanitas, where Python reads the FlareSolverr endpoint straight from
  the shop TOML with no env override, so the compose hostname never resolves
  from the host and every fetch dies. A comparison that passes when both
  sides are broken is worse than no comparison.
- **There is no cross-shop URL fallback.** It used to fall back to vaga URLs
  when a shop had none, which meant vaga product pages parsed by the
  almalittera parser, reported as a real divergence.
- **Categories discovery can't be compared URL-for-URL.** The paginated
  listing reorders between requests: two *identical* PHP runs minutes apart
  differed by 6 URLs. Page 2 of one run simply holds different products than
  page 2 of the next, so that comparison comes down to aggregates plus a
  reported overlap. Sitemap is a single fetch and is compared exactly.

### What the upsert has to get right

Ported from `upsert_shop_book()`; every branch is covered by
`tests/ShopBookRepositoryTest.php`:

- **SKU before URL.** A renamed slug updates the existing row instead of
  creating a duplicate.
- **Stale-SKU split identity.** When a SKU matches a row whose URL another
  row now owns, the SKU is detached rather than writing a URL that violates
  `uq_shop_book_shop_url`. Happens when a shop fixes a wrong slug and
  recycles the old one.
- **Conditional fields.** A thin category scrape supplying no author must
  not erase one captured from the product page.
- **ISBN drift guard.** A linked book whose ISBN moves to one its canonical
  doesn't own gets unlinked, because match step 1's
  `WHERE book_id IS NULL` never re-evaluates an existing link.
- **url_type promotion ladder.** `unknown → product_partial → product`,
  and a partial rescrape never demotes a complete row.
- **Prices are append-only, written on every scrape with a price** — no
  change detection. "We looked and it was still 12.34" is a data point.

### Model defaults don't reach raw SQL

`HasSqlAlchemyDefaults` fixes Eloquent writes, but `DiscoveredUrlRepository`
issues a raw `INSERT … ON CONFLICT` (see below for why), which bypasses the
model entirely. Every NOT NULL column without a server default has to be
spelled out in that statement — `fail_count` was missed first time round and
every one of 21,613 sitemap URLs failed to persist.

### Model-level defaults

Several NOT NULL columns have no *server* default; the Python models
declare them Python-side (`default="unmatched"`, `default=datetime.utcnow`).
Eloquent can't see those, so `Models\Concerns\HasSqlAlchemyDefaults`
mirrors them per model. Without it, any write path that forgets a column
inserts NULL and trips the constraint.

## Shop parsers

All six are ported and compared field-for-field against golden dumped from
the Python parsers over the shared fixtures.

| Shop | Source | Notable |
|---|---|---|
| vaga | OpenCart HTML | JSON-LD + `propery-*` span pairs (the typo is theirs) |
| pegasas | Magento GraphQL + LupaSearch JSON | product pages are a React shell, so the scan URL is rewritten to a single-SKU GraphQL query |
| patogupirkti | Magento 1 HTML | inline `product_tracking_data` per card; two product templates |
| humanitas | CMSMS HTML via FlareSolverr | `Formatas:` overloads binding and dimensions |
| almalittera | Shopify JSON + HTML | sells merchandise alongside books |
| ibiblioteka | LIBIS API | emits CANONICAL books, not shop listings — no prices |

`ParserRegistry` dispatches by shop, and a test asserts it covers exactly
the shops Python has parser modules for — drift means a shop exists on one
side only.

### FlareSolverr shops run serially, by construction

humanitas has a Cloudflare Managed Challenge on every URL. `FlareSolverr`
drives the sidecar; `SerialScanner` fetches one URL at a time and is
deliberately NOT routed through roach.

The session is what forces it: FlareSolverr reuses one browser session so
the clearance cookie sticks, and two concurrent `request.get` calls on that
session race for the same browser — the second response silently returns the
FIRST request's body. That is the 2026-05-22 humanitas regression, where one
product's metadata was written to another product's row. Serial execution
makes it impossible structurally instead of relying on someone remembering
to set concurrency to 1.

## Fault tolerance

A long crawl needs three things or it gets reaped: a heartbeat, stall
detection, and a way back after a failure.

### The watchdog is a forked process, not a timer

The Python version runs the heartbeat on Twisted's worker pool specifically
so a hung `psycopg2` call cannot freeze the reactor — that froze runs
194/195. roach is synchronous with no event loop, so an in-process timer
would be *worse* than Python's: any blocking call stops the heartbeat, the
dashboard reaper sees a stale `last_heartbeat`, and a run that is merely slow
gets failed.

`Watchdog` forks instead. The child keeps ticking whatever the parent is
doing, which is strictly stronger than a thread — and
`WatchdogTest::test_the_heartbeat_ticks_while_the_parent_is_blocked` proves
it by blocking the parent outright.

Parent → child signalling is the **mtime of a marker file**. Crude on
purpose: no shared memory, no sockets, and it survives a parent stuck inside
a blocking syscall — which is exactly the condition being detected.

On stall the child fails the run *before* signalling the parent, so a parent
that dies badly cannot leave the row zombie-running. It sends SIGTERM, not
SIGKILL, so the current database write completes; a half-written item reads
as a data-quality problem later.

### Two brakes on restarting, in this order

- **Zero-progress circuit breaker** — two consecutive restarts whose
  `urls_processed` snapshot didn't move means the bug is structural. Fires
  after 2 attempts.
- **Depth cap** — the runaway-loop backstop, default 10.

The breaker has to fire *first*, and `ResumePolicyTest` pins that: with a
cap of 10, a stuck chain still stops after two useless attempts. Without it,
patogupirkti runs 363→365 burned the whole budget on a bug that could never
succeed.

### Restarts stay on one row

`RunLifecycle::adopt()` reopens the existing run rather than creating a new
one. That is not cosmetic — the depth cap and the breaker both count events
on that row, so a fresh row per attempt would make the runaway loop
invisible to the very brakes meant to stop it.

Adoption also inherits the queue: items the dead process left `processing`
are unowned and go back to `pending`, and failures with transient reasons
(`run_aborted`, `stuck_in_processing`, `subdivision_5xx`) are retried —
capped at 3 attempts, so a URL the shop persistently 5xxes retires instead
of being reset on every stall and re-stalling forever.

```bash
make reconcile        # fail runs left `running` by a killed process
```

Call `reconcile` on boot: any row still `running` belongs to a process the
restart killed. Those get flagged resumable, because an orphan had a real
crawl doing real work.

### The DSN bug this surfaced

The watchdog and failsafe open their own connections — necessarily, since
they run when the shared one may be broken, and in a forked child. My first
version re-resolved the DSN from the environment, which meant a watchdog
supervising a test-database run **connected to production**. `Database` now
remembers the DSN `boot()` used and that value is authoritative.

## Validator + match

`Services\ValidateService` is the port of `services/validate.py` — 20 issue
types across nine check groups. The SQL is carried over verbatim; only the
control flow and the Python post-filters are rewritten.
`Services\MatchService` covers match step 1 (ISBN linkage), which the Python
auto-trigger runs inline after every successful scan or discover.

```bash
make validate SHOP=vaga         # run the validator for real
make test                       # includes ValidateServiceCharacterisationTest,
                                # which replays 34 findings across all 20 types
```

### Verified on real catalogue data

An empty database proves nothing here: every suppression rule was tuned
against shapes that actually occur. So the comparison runs over copies of real
shops — and separately over a synthetic shop built from nothing
(`bin/synthesize-validate-cases`) that fires all 20 issue types plus their
suppression cases. Only the synthetic half is freezable: a copied shop moves
with the catalogue, so its counts would drift and a golden over it would fail
for reasons that are not regressions.

| Shop | Books | Findings | Result |
|---|---|---|---|
| vaga | 19,408 | 13,339 | identical |
| patogupirkti | 50,604 | 62,523 | identical |
| pegasas | 17,247 | 13,961 | identical |
| synthetic | 15 | 14 | identical |

**All 20 issue types covered**, and the auto-heal deactivation counts match
too (6,160 on vaga, 101 on patogupirkti, 3,461 on pegasas). The synthetic
set deliberately includes suppression cases — a puzzle and a DVD that carry
real ISBNs, and a plain EAN — so it proves the noise filters agree, not just
the detections.

Note the validator MUTATES data: the `non_product` check deactivates books
whose every URL is non_product. `validate_diff.py` snapshots and restores
`is_active` between passes, or the second validator would see a catalogue
the first already healed.

### Guards carried over

- `ISSUE_KEYS` is asserted equal to the Python frozenset, parsed from the
  Python source at test time. Drift is silent and destructive: `resolveGone`
  closes anything the run didn't re-emit, so a differently-spelled key
  resolves the real backlog and opens a bogus one.
- `is_active = true` and `in_stock = true` must each appear exactly once in
  the service — inside `liveBooks()`. A check writing its own predicate is
  what let seven checks drift ungated.
- A fully-delisted shop full of problem-shaped rows must produce **zero**
  findings, with an active control row proving the fixture really is
  problematic. That's the guard a grep cannot provide.

## Dashboard (`dashboard/`)

A Laravel app on **:8002**, running beside the Python dashboard on :8001
against the same database.

The UI is **not** ported and does not need to be: the Python dashboard is a
React SPA (JSX compiled in-browser) talking to a JSON API, so this app
serves the *same* frontend — `dashboard/public/static` is a symlink into
`book_scraper/dashboard/static`, not a copy — and only reproduces the API
underneath. One frontend source, two backends, no sync step.

```bash
make dashboard      # serve on :8002
make api-diff       # compare all 88 endpoint+filter combinations against :8001
```

`api-diff` fetches both sides simultaneously (several fields are
clock-relative, e.g. `startedH` and "4w ago") and diffs field by field. Its
exit code is the number of endpoints that differ, so it works as a gate.

**All 27 GET endpoints are ported** — every page renders: Overview, Runs
(list, detail, live, URLs, books), Shops, Shop Books, URLs, Books (list,
detail, price series, CSV export), Issues (inbox, grouped, trend, detail),
Schedules (list, detail) and Prices. **88/88 compared endpoints identical**,
including 404 bodies.

**All 23 mutations are ported too** — run create / stop / pause / resume /
rerun / continue / retry, failure acknowledgement, cron create / patch /
delete / toggle, issue lifecycle / snooze / bulk-acknowledge /
bulk-unacknowledge / bulk-rescrape, manual book creation, unlink-canonical,
and the four pre-SPA form endpoints outside `/api` (rate-settings,
scrape/filtered, scrape/url/{id}, scrape/unknown-urls). `make mutation-diff`
reports **101/101 checks identical**.

### Comparing writes without a restore step

A write endpoint can't be compared by calling it twice — the first call
changes what the second one sees. Rather than snapshot and restore between
passes, `mutation_diff.py` gives each stack **its own database**, cloned
from the test DB with `CREATE DATABASE … TEMPLATE`, starts both dashboards
itself against those clones, and sends every case to both in the same order.
Then it compares two things:

* the response of each case — status code and body, and
* the **final state of every table a write can touch**, so a mutation that
  returns the right JSON while writing the wrong row still fails.

Timestamp columns are compared within a window (both stacks stamp `now()`
from their own process); everything else exactly. Because the tool clones
and starts the servers itself, there is nothing to set up and no way to
point it at the live database.

The one case it cannot compare: the **success** path of the four endpoints
that spawn a crawl (`POST /runs`, `/rerun`, `/continue`, `/retry` on a
terminal run). Python's spawn `docker exec`s into the scraper container with
a hardcoded **production** DSN, so firing it from a test harness would start
a production crawl. Every refusal path *is* compared (404 / 400 / 409 /
422 — 15 cases), as is `/retry` on a live run, which resets rows and emits
its event without spawning. The success paths were verified by hand against
the test database: correct response, correct row writes, correct event
payload, and a detached crawl that logged and completed.

The PHP spawn passes its database explicitly (`--database=<dsn>` built from
the dashboard's own connection) rather than inheriting one, so a dashboard
pointed at the test database can only ever start a test-database crawl.

### What the comparison had to learn

Three fixes to the harness itself, each because it was reporting a pass it
had not earned:

- **Error responses were unverifiable.** `urlopen` raises on any non-2xx, so
  a stack returning 500 where the other returns 404 looked like a tooling
  failure. The status is now folded into the compared value.
- **Clock-relative fields need a tolerance.** `*_age_s` and `startedH` are
  measured from "now"; two processes cannot agree exactly. Compared within
  2s, and only those fields.
- **A both-empty result is INCONCLUSIVE, not a pass.** See the crawl-diff
  notes — the same lesson applies here.

Two PHP-side quirks the comparison caught, both in the CSV export: Python's
`csv.writer` emits `\r\n` where `fputcsv` emits `\n`, and Python renders a
whole float as `40.0` where PHP gives `40`. Neither is visible in a
three-row JSON sample; both show up across 6,300 CSV rows.

### Ground rules specific to the dashboard

- **Read-only.** `SESSION_DRIVER`/`CACHE_STORE` are `file`, not `database`.
  Laravel's default session driver tried to create a `sessions` table *in
  the production catalogue* on the first request; Alembic owns that schema
  and this app must never write to it.
- **Qualify column names.** `shop_id` and `url` exist on several tables and
  the URL queries join them; an unqualified reference is an ambiguous-column
  error at runtime, not a compile-time one.
- **Register static route segments before `{id}`.** `/books/stats`,
  `/issues/groups` and `/issues/trend` otherwise match as an id.
- **Generated metadata, not hand-copied.** `IssueMetadata` (40 severities +
  40 descriptions) and `Pegasas\CategoryNames` (1,170 entries) are produced
  from the Python source by `tools/dump_issue_metadata.py` and
  `tools/dump_pegasas_categories.py`. A hand-edited copy drifts the moment
  someone adds an issue type, and the symptom is an undescribed "warning".

### Pre-existing bugs found while porting

**Unstable sorts corrupted pagination — fixed in both stacks.** Six list
queries ordered by a non-unique column with no tiebreaker, so which rows
landed on a page was arbitrary among ties. Measured, not inferred:

| Query | Evidence |
|---|---|
| `shop-books?sort_by=price` | 65 books share `price = 0.00` |
| `books` (orders by `created_at`) | 339 books share one `created_at`; **13 books appeared on both page 1 and page 2** |
| `books/export` | Python's own CSV contained **227 duplicate rows** out of ~6,300, and omitted others |

Row *totals* always agreed (14,588 / 19,665 / 34,801 across the filters), so
the filters were correct — only row placement drifted. Both stacks now append
`id` as a final sort key, in the same direction as the primary sort, on all
six: canonical books, shop_books, discovered URLs, a run's added and updated
books, and a discover run's URLs. `api_diff.py`'s `ENVELOPE_ONLY` set is
consequently empty — every paginated endpoint is compared row for row, and
page 1 ∩ page 2 is now 0 of 50 on production data in both stacks.

**`primary_isbn` is arbitrary.** Python selects one ISBN with `LIMIT 1` and
no `ORDER BY`, and 138,033 books have more than one. PHP matches the
unordered query on purpose: imposing an order would show a different
"primary" ISBN than the Python dashboard does for the same book.

**Author lists included non-authors.** `book_authors` holds translators,
narrators and illustrators too. Python filters `role = 'author'`; my first
version did not, so `authors[0]` — the CSV export's `author` column — was
sometimes a translator. 753 of 6,300 export rows were wrong before the
filter went in.

## The five discovery strategies

```bash
make discover STRATEGY=sitemap                       # 21,613 URLs, one fetch
make discover STRATEGY=categories PAGES=3
make discover SHOP=pegasas STRATEGY=graphql PAGES=1
make discover SHOP=pegasas STRATEGY=lupasearch PAGES=1
make discover SHOP=ibiblioteka STRATEGY=ibiblioteka_api ARGS=--max-bands=2
```

The last three are JSON APIs, two of them POST-only. The queue stores URLs
and nothing else — no method, no body, no headers — so every request input
is encoded into a synthetic URL and the body is rebuilt from it at dispatch
time. That is what makes a resumed run reissue the *same* request the
original sent, and it is also what makes the port exactly checkable:
`DiscoveryUrlsTest` asserts the URLs and bodies byte for byte against
`tools/dump_discovery_golden.py` output (11 cases, 60 assertions), including
the legacy annual-band form still accepted for URLs queued before the switch
to monthly bands.

roach needs no changes to POST: it hands its request options straight to
Guzzle, which understands `body` and `headers`.

Live parity, both stacks against the test database:

| Strategy | Result |
|---|---|
| `sitemap` (vaga) | identical — 21,613 URLs |
| `graphql` (pegasas) | identical — 50 books, 50 URLs, 292 attributes, 50 prices |
| `lupasearch` (pegasas) | identical — 42 books, 42 URLs, 167 attributes, 42 prices |
| `categories` | aggregates only — the live listing reorders between runs |
| `ibiblioteka_api` | shape only — see below |

**ibiblioteka's search API has no stable order.** It sorts by `MATCH` on an
empty query, so paging it by `pageStartIndex` overlaps and drops records
differently on every call. Two consecutive runs of the *same* stack returned
900 and 800 URLs with 700 shared. Nothing there is comparable row-for-row,
and neither is the count — `crawl_diff` reports the overlap and compares the
shape of what was written. This is upstream behaviour that affects the
Python stack identically, not something the port introduced.

Because a 1990-2027 window is one request per calendar *month* — 444 seeds —
`crawl_diff` narrows the year range in the shop TOML to a single year for the
duration of the comparison and restores it in a `finally`. Python reads that
range from the file with no CLI override, so there is no other way to put
both stacks on the same footing. The crawler itself takes `--max-bands` for
dev runs; there is deliberately no default cap, because a production run has
to cover every month.

### Adaptive subdivision

When a GraphQL page returns 5xx, the same range is refetched as N smaller
pages instead of being dropped — Magento's full-page cache misses on deep
pages return transient 503s at `pageSize=50`, and the same items at
`pageSize=10` usually come back fine. Page 3 of size 50 covers items
100..149, so it becomes pages 11..15 of size 10; the sub-pages carry `_sub=1`
so a failure on one of them cannot recurse. Pagination continues either way,
or a single bad page would end the crawl. Each subdivision writes a
`subdivided` row to `scrape_run_events`, which is what the run's Timeline
card renders — without it the run just goes quiet while the spider works
around a struggling backend.

### Post-phase and cron chaining

`PostPhase` runs after every successful scan or discover, mirroring the two
Python extensions:

1. If a cron job fired the run and chains to another, spawn the chained job.
2. Otherwise link new books by ISBN (match step 1 — one `UPDATE`) and fire a
   validate run. Skipped when the chain already targets match or validate,
   which would otherwise produce two validate runs for one scrape.

`POST_PHASE_AUTO_TRIGGER=0` disables it, legacy `POST_SCAN_AUTO_TRIGGER`
included. A failure instead records `chain_skipped` on the run, so a gap in a
chain is visible on the timeline rather than inferred from a missing run.
`cron_jobs.last_run_at` is stamped by `RunLifecycle::finish()` for the
data-producing phases only — Python's validate and match services don't
stamp it, so neither does this.

## The validation layer

Between parsing and storage, upstream runs a layer that both **rewrites** the
item and records what it noticed. Skipping it does not merely lose the issue
log — it stores data the reference implementation refuses or corrects:

| Rewrite | Without it |
|---|---|
| description HTML → Markdown | every scraped book stores raw HTML in a column the dashboard renders as Markdown |
| invalid ISBN → null | a failed-checksum ISBN is stored, and links the book to the wrong canonical record |
| year out of range → unswapped with pages, or cleared | a page count is stored as a publication year |
| `title`/`author`/`publisher` trimmed | `'Alma littera '` and `'Alma littera'` become two publishers |
| price → Decimal string; unparseable → item dropped | a junk price reaches the price history |

`make validator-diff` feeds identical items to both layers and compares the
rewritten item, the drop decision, and the issues — **46/46 cases identical**,
one per check plus the combinations where checks interact. No database, no
network, so it is a hard gate rather than a sampling exercise.

The 28 in-crawl issue types are recorded too, buffered through the run and
written in one batch at close, as upstream does. That needed one thing the
validator phase never did: resolving a URL to its `shop_book_id` or
`discovered_url_id`. Without the FK the issue lands in the url-keyed partial
index instead of the entity-keyed one, so the same problem on the same book
opens a second row and never resolves.

### Description conversion

`markdownify(html, heading_style="ATX")` is part of the contract, so
`BookScraper\Markdown` is held to its real output over 31 cases (fixtures, live
pages, hand-built tag shapes) — **30/31**, with one deliberate divergence.
`league/html-to-markdown` was measured first and rejected at 13/25: different
bullet characters, entity handling, bracket escaping, and `div`/`table`/`u`
passed through as raw HTML.

Two rules took measurement rather than reading:

- **U+00A0 is whitespace to Python's `str.strip()` and not to PHP's `trim()`.**
  That single difference accounted for every remaining mismatch: a `&nbsp;`
  before a closing tag left a stray space at the end of a block, and one inside
  `<strong>` moved the emphasis markers to the wrong side of it.
- **A `<br>` at the end of a paragraph shields a preceding U+00A0 from the edge
  trim.** `<p>a. </p>` → `a.`, but `<p>a. <br></p>` → `a. ` (those are
  U+00A0). Shops emit `…&nbsp;<br></p>` constantly, so this decides the stored
  text of a large share of descriptions.

The deliberate divergence: markdownify drops everything after a `<br/>` that
follows a `<br>` in the same paragraph — `<p>One<br>Two<br/>Three</p>` becomes
`"One  \nTwo"`, while `<p>One<br>Two<br>Three</p>` and `<p>A<br/>B</p>` both
convert fully. It is an html.parser artifact, and reproducing silent content
loss is not worth fidelity.

## Runs get reaped from outside the crawl

A crawl that dies without unwinding leaves its row `running` forever: the runs
list shows it live, and the shop+phase preflight refuses to start a
replacement. Nothing inside the crawl can fix that — the process that would
have finished the row is the one that died.

Upstream runs the sweep on an asyncio timer inside the dashboard process. PHP
has no equivalent event loop, and putting it on the read path was rejected on
purpose: this dashboard's GETs are read-only, and a sweep triggered by whoever
happens to load the runs page makes a write depend on browsing. So it is a
command — `make reap`, or `make reap ARGS=--watch` under a supervisor.

**Something has to run it.** Without that, nothing fails a zombie.

`make reaper-diff` plants the same five run shapes in two clones — a `running`
run gone silent, a `stopping` run whose close callback never fired, a `paused`
run that must NOT be reaped, a live run with a hung worker, a terminal run with
orphaned rows — and diffs six tables afterwards. Identical, with the count
measured as a delta so a database full of already-failed runs cannot make it
pass by accident.

The fail transition itself is one function (`RunFinisher`), because upstream
learned that the hard way: the body was hand-rolled in three places, they
drifted, and the copies only handled `running` runs — so a run failing out of
`stopping` left stranded `processing` rows and recorded no issue at all.

## Pre-existing bugs found in the shops' own paths

Measured, not inferred. The two ibiblioteka ones are now **fixed in both
stacks**; the rest are still reproduced on purpose, because fixing them changes
the reference implementation this port is measured against.

**ibiblioteka's scan could not work at all.** The detail endpoint
content-negotiates: with a browser `Accept` it serves the SPA shell (30,995
bytes of xhtml), with `application/json` the record (19,593 bytes). Measured on
record 2097094. Python's download handler injects an HTML-preferring `Accept`
on every request and its scan spider never overrode it, so every fetch returned
200 with a shell the parser found no title in — a run that reported `completed`
having scraped nothing, and the reason ibiblioteka has no production rows.
Both stacks now expose `rewriteScanUrl` / `rewrite_scan_url` on the ibiblioteka
parser, returning the URL unchanged with `Accept: application/json`.

`make canonical-diff` still fetches each record once and hands the same bytes to
both writers. That was originally the only way to compare a path one stack could
not execute; it stays because one fetch for two writers is the cleaner
comparison anyway.

**ibiblioteka extracted no authors, ever.** The API returns
`authorViews[].titleLt` and `persons[].titleLt`; both parsers read `.value` and
`.name`, which no longer exist, so author extraction returned `[]` for every
record. Same class of breakage as the endpoint move noted in that module's
docstring. Both now read `titleLt` first and fall back to the old keys, which is
what the checked-in fixtures still carry. Measured on the three
`make canonical-diff` records: 0 authors before, 5 after, on both sides.

**`sku_duplicate` looked for a state the schema forbids — deleted from both
stacks.** Both sides of the pair are scoped to one shop by the mandatory
filter, and `uq_shop_books_shop_sku` is unique on `(shop_id, sku)`, so the
check could never fire: zero recorded in production, ever, against 7,156
`isbn_duplicate` and 6,272 `title_author_duplicate`. A cross-shop SKU
collision would be meaningless anyway — SKUs are shop-local.

It read as alive because the *test* database lacked that index: it is built
from `Base.metadata`, and the model never declared what migration
`f6a2b3c4d5e7` created. So an integration test inserted the pair, the check
fired, and the dead code looked covered. The index is now declared on the
model, which is the fix for the drift as well as for the check.

**markdownify truncated descriptions at a mixed line break — fixed upstream.**
It dropped everything after a `<br/>` that followed a `<br>` in the same
paragraph: `<p>One<br>Two<br/>Three</p>` converted to `"One  \nTwo"`, while the
all-`<br>` and single-`<br/>` forms converted in full. An html.parser artifact,
not an intention. This port never reproduced it — silent content loss is not
worth fidelity — and it was the one entry `MarkdownTest` skipped. Upstream now
normalises `<br/>` to `<br>` before converting, so nothing is skipped: all 31
golden cases are asserted.

**`year_pages_swap` fired on a year supplied as a string — fixed in both
stacks.** The issue was decided by `year_before != year_after`, and the
normalisation turns `"2024"` into `2024`, so a string year read as a swap.
Latent rather than active — all 14 production occurrences carry a genuine page
count (20, 50, 320, 784…) — but a shop changing its parser to yield strings
would have flooded the inbox. Both sides now compare numerically;
`make validator-diff`'s "year as string" case went from `year_pages_swap` to
no issues on both, and the genuine swap case still fires.

## Two bugs the JSON strategies surfaced

Both were invisible on vaga, whose parser never produces the values involved.

**Booleans were being written as `1` and `''`.** `shop_book_attributes.value`
is text and the Python writer stores `str(value)`, so a boolean lands as
`'True'`/`'False'`. PHP's cast gives `'1'`/`''`, which reads back as absent —
`is_new`, the flag pegasas discovery exists to surface, would have been
unusable for every new book. Floats needed the same care: PHP's default
float-to-string precision truncates, so the value goes through
`json_encode` (shortest round-tripping form, like `repr`) with `.0` restored
on whole numbers.

**Trailing whitespace wasn't stripped.** Python's validation pipeline strips
`title`, `author` and `publisher` before writing, and pegasas ships
`'Alma littera '` from GraphQL. Without the strip the same publisher lands as
two distinct strings.

**A sitemap index parsed to nothing.** patogupirkti's sitemap is an index
pointing at two child sitemaps. The PHP parser handled that shape — but only
when handed a fetcher for the children, and the spider called it with one
argument, so the run reported success having discovered 0 URLs where Python
found 61,234. Now identical. The fetch is deliberately blocking, as upstream's
is: discovery runs weekly, two children cost a couple of seconds, and threading
them through the scheduler would put a shop-specific hook in the generic spider.

## Operator overrides

`shop_settings` rows are the top tier of the rate-limit chain — a DB row beats
the shop TOML, which beats the built-in fallback, resolved per key. It is how a
shop that starts rate-limiting mid-crawl gets slowed down with one INSERT and no
redeploy, and reading only the TOML (as this port first did) quietly removed
that lever. `Config::applyShopSettings()` layers them on once, after the
database is up, so every later reader — including the ones inside SerialScanner
and the roach container — sees the effective value.

The dashboard's `POST /shops/{shop}/rate-settings` form is the UI for it, and is
one of four pre-SPA endpoints that live outside `/api` and answer with HTML or a
303 redirect. All four are ported and compared.

## Not done yet

- The **full match phase** as a standalone command. Step 1 (ISBN linkage)
  runs from `bin/validate --match-first`; steps 2–3 exist in `MatchService`
  and are verified by `make match-diff`, but nothing drives them from the
  CLI, so a cron chain targeting `match` runs step 1 and says so.
- `full_crawl` discovery.
- The **success** path of the crawl-spawning dashboard endpoints is verified by
  hand rather than by the differential harness — see above for why, and what is
  covered instead.
- **Structured logging.** `event_log.py`'s JSONL per-response log and the
  `key=value` lines Alloy parses into Loki have no PHP equivalent, so the
  Grafana panels would be blank for a PHP-run crawl.
- **No Docker packaging.** The PHP stack runs from the host only; the compose
  file still builds the Python scraper and dashboard.
- Ops scripts: `generate_crontab.py`, `cron_health_check.py`, the container
  entrypoints, and the one-off backfills. They read the same database, so the
  Python copies keep working — but they are not ported.
