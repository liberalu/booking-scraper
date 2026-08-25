# Python fixes, and a plan for removing Python

Rendered version (tables, phase gates): https://claude.ai/code/artifact/3d17d76a-1051-4c75-8708-859b69a74d2c

Found by running the PHP port and the Python stack against identical input and
diffing the results. Every item below was measured, not inferred.

**Part one is done; part two is still on hold.** All eight defects are fixed in
both stacks (commits `4e274bc`, `2c90beb`, `ac2caa9`, `d92e948`, `2340650`,
`8b66faf`, `8828651`). The port's value so far has been as an audit. Removal is
feasible, but two phases carry the real cost and they are not the obvious ones —
schema ownership (phase 1) and freezing the verification evidence (phase 6).

## Part one — the fix ledger

Ordered by what to land first: a whole shop's data, then correctness under
concurrency, then what users see, then noise.

| # | Defect | Where | Fix | Evidence |
|---|---|---|---|---|
| 1 | ✅ **Fixed** — vaga listings recorded no prices | `spiders/vaga/parsers.py` | done (`4e274bc`) | live listing 100 products / 0 prices → 100 of 100 |
| 2 | ✅ **Fixed** — ibiblioteka's scan phase could not work: the browser `Accept` got the SPA shell | `spiders/ibiblioteka/parsers.py` | `rewrite_scan_url` returns the URL unchanged with `Accept: application/json` | record 2097094: 30,995 B xhtml vs 19,593 B JSON. Why the shop has no production rows. |
| 3 | ✅ **Fixed** — ibiblioteka extracted no authors, ever: API fields renamed | `spiders/ibiblioteka/parsers.py` | read `titleLt` first, old keys as fallback (the fixtures predate the rename) | `make canonical-diff` on 3 live records: 0 authors → 5, both stacks |
| 4 | ✅ **Fixed** — two processes could hold the same exclusive scan lock | `db/repo.py` | `abs(hash(phase))` → `zlib.crc32` via `scan_lock_key()`, matching PHP's `crc32()` | keys 975101118 vs 136925746 for one phase; now byte-identical across processes and stacks |
| 5 | ✅ **Fixed** — pagination showed duplicates and hid rows | `queries.py` (six sites, not the three first counted) | append an id tiebreaker in the primary sort's direction | 339 books share one `created_at`; page 1 ∩ page 2 was 13 of 50, now 0 in both stacks; `api_diff.py`'s `ENVELOPE_ONLY` is now empty |
| 6 | ✅ **Fixed** — `year_pages_swap` fired on a year given as a string | `pipelines.py`, `php/src/Crawler/ItemValidator.php` | compare numerically, not by identity, on both sides | `make validator-diff`'s "year as string" case: `year_pages_swap` → no issues, both stacks |
| 7 | ✅ **Fixed** — `sku_duplicate` looked for a state the schema forbids | `services/validate.py`, `db/models.py` | deleted, with its registry entries; the missing partial unique index that made it look alive is now declared on the model | 0 recorded ever, vs 7,156 `isbn_duplicate`; `make validate-diff` still identical (13,339 issues) |
| 8 | ✅ **Fixed** — descriptions truncated at a mixed line break (markdownify) | `pipelines.py` | normalise `<br/>` → `<br>` in a shared `html_to_markdown()` the golden dumper also calls | `<p>One<br>Two<br/>Three</p>` lost "Three"; `MarkdownTest` now skips no cases |

**All eight landed, in lockstep.** The PHP port is measured against Python's
behaviour, so every fix moved both sides together: goldens regenerated
(`make golden`, `make markdown-golden`), and `api-diff` (88/88), `validate-diff`
(13,339 issues), `validator-diff` (46/46) and `canonical-diff` all identical
afterwards. Three of the eight required *removing* deliberate bug-reproduction
from the PHP side — the string-year comparison, the impossible SKU check, and
the markdownify truncation `MarkdownTest` used to skip. That lockstep is the
standing cost of two stacks, and it is the practical argument for eventually
keeping one.

Two things the fixes turned up that the ledger did not predict:

- **Pagination was six sites, not three.** The other three are the same defect
  reached from different endpoints (a run's added and updated books, and a
  discover run's URLs).
- **`sku_duplicate` looked alive because the test schema had drifted.** The
  model never declared the partial unique index migration `f6a2b3c4d5e7`
  created, and the test database is built from the model — so a test could
  insert a state production forbids and the dead check appeared covered. The
  index is now on the model. This is worth remembering for removal phase 1,
  whose gate is exactly a schema diff.

Still open, found while verifying: seeding the test database for the PHP
differentials (`make seed-test-db`) makes the next full Python `pytest` run
fail ~61 tests — the Python conftest assumes an empty database, and both stacks
share one. Pre-existing, and unrelated to any fix above.

## Part two — removing Python

Eight phases, each with the check that must pass before the next starts.

1. **Move schema ownership to PHP** — ~half a day, *measured 25 Aug*. Alembic owns 118
   revisions; PHP owns nothing by design. Don't re-express the history: take
   `pg_dump --schema-only` as baseline migration 0001 for a PHP migrator in
   `php/` (shared by crawler and dashboard, never in the Laravel app). Keep
   `alembic/` as read-only history.
   *Gate:* fresh DB from the PHP baseline, `pg_dump --schema-only` both, diff to
   zero — that is what catches enums, partial unique indexes, check constraints.

   **Verified.** The round-trip is faithful, so this phase is one migration that
   executes that SQL rather than a rewrite of 118 revisions. A 2,163-line schema
   dump restored into a fresh database produced all 25 tables, 12 enums, 5 unique
   indexes (partials included) and 3 check constraints; re-dumping differed only
   in `pg_dump`'s own session tokens plus one CHECK expression Postgres deparses
   in an equivalent form. The automated gate must normalise that re-render or it
   reports a permanent false positive. This was the estimate I was least sure of,
   and it is the cheapest phase rather than the most expensive — which leaves
   phase 6 as the only one that genuinely bites.
2. **Package the PHP stack** — 2 days. Compose targets for crawler and
   dashboard, PHP 8.4, via the existing Make wrappers.
   *Trap:* `php/dashboard/public/static` is a symlink into
   `book_scraper/dashboard/static` (636 KB, 16 JSX files). Deleting Python
   breaks the SPA; the tree must move into `php/` and become canonical.
   *Gate:* compose serves the dashboard and a scan completes in-container.
3. **Scheduling and supervision** — 2 days. Port `generate_crontab.py`;
   supervise `artisan runs:reap --watch`; port the entrypoints.
   *Gate:* a cron-fired run lands with the right `cron_job_id`, and a `kill -9`'d
   crawl is failed within 60s.
4. **Observability** — 1–2 days. Emit the same `key=value` lines and the JSONL
   per-response log; Loki/Alloy/Grafana are upstream images and don't change.
   *Gate:* existing Grafana dashboards populate from a PHP run.
5. **Close the feature gaps** — 2–3 days. `full_crawl`; a CLI for the full match
   phase (steps 2–3 exist and pass `make match-diff`, nothing drives them);
   decide on `cron_health_check.py` and the backfills.
   *Gate:* every phase in `cron_jobs` has a working PHP command.
6. **Freeze the evidence — before deleting anything** — 2–3 days, do not skip.
   16 of 17 comparison tools import `book_scraper`. Convert them while both
   stacks exist: save the PHP side as a characterisation golden and compare
   against that. You keep "did this change"; you permanently lose "does this
   match Python".
   *Gate:* the converted suite passes in a checkout with no Python installed.
7. **Shadow run** — 2 weeks calendar. Both stacks, non-overlapping schedules
   (needs fix 4 first). Compare run outcomes, rows written, issues by type,
   price rows.
   *Gate:* 14 consecutive days with no unexplained divergence.
8. **Cutover with a way back** — 1 day + a week's watch. Tag first, then remove
   `book_scraper/` (66 files), `tests/` (86), `scripts/` (6), `alembic/` (60,
   kept in history), the Python packaging and compose services. Rollback is a
   revert to the tag, cheap because the deletion never touches the database.
   *Gate:* a full week of scheduled PHP-only runs with no intervention.

Total: ~2.5 weeks focused work plus 2 weeks shadow.

## What removal gives up

- **The differential method.** Afterwards the PHP suite asserts PHP against its
  own frozen past — a regression net, not a correctness proof.
- **Python's suite** — 504 unit and 416 integration tests.
- **The audit capability.** Eight defects in one session came from having two
  implementations to disagree with each other. One cannot disagree with itself.

A smaller first step, if wanted: run the PHP crawler for a single shop in
parallel, keeping Python for schema, scheduling and observability. Real
operational signal, no cutover, and the differentials keep working.
