# Follow-ups

Deferred work, newest first. **Mark done by deleting the section and
committing** — a list that only grows stops being read.

Last reviewed 2026-08-31 after the Laravel architecture and PHPStan-max sweep.
Resolved sections are deleted rather than retained as history. The remaining
items were checked against the running application and production-shaped local
database.

---

## Work with no open question

### The CLI entry points are scripts, not Artisan commands *(2026-08-27)*

Crawler launches now enter through `php artisan crawler:run`, including the
scheduler, watchdog restarts, cron chains, Make targets, and operator docs.
The command delegates to the characterised `bin/crawl` engine while its
procedural body is migrated incrementally. The smaller `validate`, `match`,
`canonical`, and `parse` scripts still need dedicated commands. `bin/migrate`
should remain independent because it targets databases Laravel is not
configured to use.

## Data and operations

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
  `.claude/` and `.github/` are excluded there. A new large
  top-level directory ships into the image unless it is added to that file.
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
