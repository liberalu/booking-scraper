# Follow-ups

Deferred work, newest first. **Mark done by deleting the section and
committing** — a list that only grows stops being read.

Last reviewed 2026-08-26, when the Python stack was removed. Every section below
was checked against the running system on that date rather than carried over on
faith: three earlier items turned out to be already done and were deleted.

Six sections were added on 2026-08-27, when the three composer projects became
one Laravel application at the repository root. They are marked *(2026-08-27)*
and come from reading the merged tree, not from that sweep.

---

## Needs a decision, not a patch

These are judgement calls about intended behaviour. Each has a short fix once
the call is made.

### Nothing authenticates the dashboard, and `POST /api/runs` starts crawls *(2026-08-27)*

Every route in `routes/api.php` is open: no auth, no throttle, and
`bootstrap/app.php` exempts the pre-SPA form posts from CSRF.
`RunSpawnController::store()` ends at `CrawlSpawner::spawn()`, which runs
`proc_open(['/bin/sh', '-c', …])`. The arguments are `escapeshellarg`-quoted and
the phase and shop are whitelisted, so it is not injectable — but anyone who can
reach the port can start a crawl against a live shop, and `docker-compose.yml`
publishes the dashboard as `"8001:8000"`, which binds every host interface.

The decision is whether that port is ever reachable from outside the machine. If
it is not, record that here and delete this section. If it is,
`->middleware('throttle:60,1')` on the group plus a shared-secret check on the
mutation routes is the fix — neither golden covers request headers, so it can be
added without touching frozen behaviour.

### A paused run can be resumed but never stopped

`RunMutationsController::stop()` accepts only a `running` run; a `paused` one
gets its own status back. So a run paused by mistake can only be un-paused,
never ended — which is how run 386 sat `paused` from 2026-05-08 to 2026-08-26
(finalised in `faa2f9f`).

Either let `stop` accept `paused`, or decide that resume-then-stop is the
intended path. Note `mutation_cases.json` freezes the stop route's behaviour;
adding a new accepted state does not change any frozen case, but changing what
`stop` returns for `paused` would.

### Nothing reaps a run paused far beyond any plausible intent

`Reaper::sweep()` considers only `running` and `stopping` — deliberately, since
a paused run is alive and its quiet heartbeat is expected. Combined with the
crawler's shop+phase preflight counting `paused` as active, one forgotten pause
blocks that shop+phase forever.

A time bound would fix it (paused with no heartbeat for N days → fail). Picking
N is the decision. A week is defensible; an hour is not.

### The crawler builds its whole work list in memory

A scan materialises every request before fetching anything. patogupirkti's
50,536 URLs exhausted the default 128M in Guzzle's `Uri` constructor, and
`bin/crawl` now raises the limit to 512M (`CRAWL_MEMORY_LIMIT` overrides it).

**That is a ceiling, not a fix** — steady-state RSS is 60M, so the peak is
purely construction. A shop twice patogupirkti's size needs the number raised
again. The real fix is streaming the queue. Marked in `bin/crawl` with a
`ponytail:` comment.

### Roach paths record no watchdog activity on a transport failure

`ActivityExtension` subscribes to `ResponseReceived` and `ItemScraped`, which is
what Python's StallDetector watched. A request that fails at transport level
(timeout, connection refused) produces neither, so it is silence as far as the
watchdog is concerned.

Fixed for `SerialScanner` in `5a9d234`, where concurrency is 1 by construction
and two consecutive 240s timeouts were 480s of silence on a healthy humanitas
run. Left alone on the roach paths, where concurrent requests cover for each
other. Roach exposes `RequestDropped` and `RequestSending` if you want them
consistent.

---

## Work with no open question

### The CLI entry points are scripts, not Artisan commands *(2026-08-27)*

`bin/` holds 1,291 lines of procedural PHP with its own argv parsing —
`crawl`, `validate`, `match`, `canonical`, `parse`, `migrate`, `fixture-db`,
`synthesize-validate-cases` — in a project where `runs:reap` and
`runs:schedule` are already Artisan commands. This is the one part of the
2026-08-27 layout change that was not done.

It is not only the scripts. `CrawlSpawner::spawn()`, `PostPhase::command()` and
`Watchdog` all invoke them by absolute path, and the operator instructions in
`CLAUDE.md` say `docker compose exec dashboard php bin/crawl`. `bin/crawl` is
652 of those lines and is the most load-bearing path in the system, so convert
it with the Crawler suite in front of you rather than as a sweep. `bin/migrate`
is the exception that should probably stay a script: it must run against a
database Laravel is not configured for, which is the whole point of its
`--database=DSN`.

### `LegacyFormsController` sits under `Api\` and serves no API *(2026-08-27)*

It answers `/scrape/*` and `/shops/{shop}/rate-settings` with HTML or a 303 —
the form posts that predate the SPA. When the JSON routes moved to
`routes/api.php` it correctly stayed behind in `routes/web.php`, but its class
is still `App\Http\Controllers\Api\LegacyFormsController`.

Move it to `App\Http\Controllers\`. `mutation_cases.json` freezes both routes'
responses, so re-run the Feature suite rather than assuming a namespace change
is inert.

### Query parameters are coerced by hand in every controller *(2026-08-27)*

There is no `FormRequest` in the project. Each list endpoint repeats the same
block: `(string) $request->query(…)`, a whitelist for sortable columns,
`max(1, min($perPage, 200))`. It is consistent and defensive, which is why it
has lasted, but it is one block written eleven times.

Related, and with a trap in it: there is no route model binding either. Every
`{run}` route does its own `ScrapeRun::find($id)` and returns a manual 404 whose
body is `{"detail": "Run not found"}`. Laravel's implicit binding produces a
different 404 body, and `mutation_cases.json` freezes that string — so adopting
binding means a `missing()` handler or an explicit resolver, not just a
type-hint.

### `IssuesController` and `BooksController` carry their own query layer *(2026-08-27)*

756 and 661 lines. Both build SQL inline, do their own pagination arithmetic,
and declare severity maps and sortable-column lists as controller constants.
`IssuesController` also merges two sources — `validation_issues` and
`scrape_failures` — with a hand-rolled pigeonhole argument about how many rows
to take from each before slicing.

The Laravel answer is a query object per list endpoint, not more controllers.
`api_shapes.json` freezes all 79 GET responses, which is what makes this worth
starting: the extraction is verifiable one endpoint at a time.

### There is no static analysis *(2026-08-27)*

`make lint` is `php -l`, which catches parse errors and nothing else. Items are
plain arrays, several public methods return `mixed`, and the array shapes that
flow from the parsers through `ItemValidator` into `Persister` are described in
docblocks that nothing verifies.

phpstan at level 5, with the Laravel extension, plus a step in `ci.yml`. Expect
a baseline file on the first run; the value is in what it refuses to let in
afterwards, not in emptying it.

### The PHP scan never populates `scrape_url_items.retry_count`

203 rows have `retry_count > 0` and every one was written by a Python run — the
highest is run 845, and no PHP run has ever written the column. Nothing in
`app/Crawler` touches it outside the model and the test fixture.

Forward the retry count from the HTTP layer into `mark_scrape_url_item_response`'s
PHP equivalent when a request is retried. Worth doing on the discover side too.

### Retries are invisible in the dashboard Timeline

`scrape_run_events` is the Timeline card's source of truth and there has never
been a single `request_retried` row. Retries happen silently, so transient
backend pressure being papered over by retries cannot be seen.

Write a `request_retried` event per retry and render it in the SPA's timeline
(`public/static/hifi/`) with a distinct icon — `⊟` is already
taken by `subdivided`, so pick another (`↻`).

### `heartbeat_timeout` should probably not auto-resume

38 runs closed `heartbeat_timeout` are marked resumable. A stall means the crawl
stopped fetching; a *heartbeat* timeout means the process stopped writing its
own heartbeat, which points at something wedged rather than slow. Auto-resuming
retries the wedge.

`STALL_AUTO_RESUME_MAX` bounds the damage, but the principle stands: gate
auto-resume off when `close_reason === 'heartbeat_timeout'` and leave the
Continue button for an operator. `ResumePolicy` is where the decision lives —
today it only mentions the reason in a comment.

---

## Data and operations

### 12,719 active books have no author

patogupirkti ~7,200, humanitas ~3,900, vaga ~1,500, pegasas ~69. Already
surfaced by the validator as `book_no_metadata` / `book_no_signals`, and part of
the 17,236 open issues.

A `discover --strategy=categories` pass per shop closes most of it — category
pages carry the author where product pages sometimes do not. There is no
separate backfill script and does not need to be one; that is what
`backfill_authors.py` was, and it was deleted as a narrower version of the same
crawl.

### 103 failed runs are still marked resumable

Some are from testing on 2026-08-26. The dashboard offers Continue on each, so
the list reads as actionable when most of it is not. Decide a retention policy
or clear the flag on anything older than a week.

### One bilingual pegasas book

After the 2026-05-04 cleanup of 31 explicitly non-LT pegasas books, one
`Lietuvių ir anglų k.` title remains. Keep or delete — operator's call.

### `POSTGRES_DB` on the test cluster only applies to a fresh volume

`docker-compose.yml` names the test database `book_scraper_php_test`, which is
how it gets created now that seeding is gone. An existing `pgdata_test` volume
keeps whatever it was initialised with — here, `book_scraper_test`. Recreate the
volume or create the database by hand if a fresh checkout disagrees.

---

## Cosmetic

- **`.dockerignore` is load-bearing since 2026-08-27.** The Dockerfile copies
  the whole repository (`COPY . .`) now that the application *is* the
  repository; it used to copy `config/` and `php/` only. `docs/`, `monitoring/`,
  `.planning/`, `.claude/` and `.github/` are excluded there. A new large
  top-level directory ships into the image unless it is added to that file.
- **CI pins `actions/checkout@v4`**, which GitHub forces onto Node 24 with a
  deprecation warning on every run. Bump to v5.
- **Alloy re-reads container log history on restart** and Loki 400s the entries
  older than its retention. The dropped lines are Loki's own from June, not
  ours.
- **`filename` is an unbounded Loki label** on the spawn-file streams — one new
  stream per crawl, forever. Not dropped because `stage.regex` extracts `role`
  and `shop` from it, and losing it costs an operator the ability to tell which
  spawn a line came from. Revisit if the index gets heavy.
- **`level` is absent on most PHP log lines.** The crawler writes for humans
  ("done — 2 url(s), books added 0") and no panel filters on level. Adding
  levels means reshaping output the Grafana panels grep for by phrasing.
- **One `.py` survives**: `docs/superpowers/scripts/build-spec-index.py`, a
  dependency-free stdlib docs-index generator unrelated to the scraper. Kept
  deliberately.
- **69 "port of `book_scraper/…`" comments** across 59 files. Provenance; the
  files they name are at the `python-final` tag.

---

## Constraints, not tasks

Listed because they look like omissions and are not.

- **The characterisation goldens cannot be regenerated.** The tools that wrote
  them were Python. A failing golden is a regression to explain, never a file to
  refresh.
- **`SyntheticShop` is frozen with them.** It is the input those goldens were
  recorded over, so adding rows invalidates shapes nothing can re-verify. A test
  needing different data plants it itself, in a transaction — see
  `ScheduleRunsTest`. Consequence: `/api/runs?status=running` is frozen as an
  empty list and cannot be filled.
- **`crawl_diff` is gone and cannot come back.** It needed live HTTP and both
  stacks. The layers under it are covered — parser differentials, the item
  validator, `PersisterTest`, the discovery goldens. What is lost is "the live
  site still looks like the fixture", which is monitoring, not regression
  testing.
