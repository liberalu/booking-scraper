# Python fixes, and a plan for removing Python

Rendered version (tables, phase gates): https://claude.ai/code/artifact/3d17d76a-1051-4c75-8708-859b69a74d2c

Found by running the PHP port and the Python stack against identical input and
diffing the results. Every item below was measured, not inferred.

**Recommendation: land part one now; hold off on part two.** The port's value so
far has been as an audit. Removal is feasible, but two phases carry the real
cost and they are not the obvious ones — schema ownership (phase 1) and freezing
the verification evidence (phase 6).

## Part one — the fix ledger

Ordered by what to land first: a whole shop's data, then correctness under
concurrency, then what users see, then noise.

| # | Defect | Where | Fix | Evidence |
|---|---|---|---|---|
| 1 | ✅ **Fixed** — vaga listings recorded no prices | `spiders/vaga/parsers.py` | done (`4e274bc`) | live listing 100 products / 0 prices → 100 of 100 |
| 2 | ibiblioteka's scan phase cannot work: the browser `Accept` gets the SPA shell | `spiders/ibiblioteka/parsers.py`, `download_handler.py:47` | add `rewrite_scan_url` returning `Accept: application/json` (the pegasas mechanism; `download_handler.py:459` already forwards it) | record 2097094: 30,995 B xhtml vs 19,593 B JSON. Why the shop has no production rows. |
| 3 | ibiblioteka extracts no authors, ever — API fields renamed | `spiders/ibiblioteka/parsers.py:129,147` | `.value` → `titleLt`, `.name` → `titleLt` | record 115594 has `persons[0].titleLt` + role code 070; extraction returns `[]` |
| 4 | Two processes can hold the same exclusive scan lock | `db/repo.py:834` | `abs(hash(phase))` → `zlib.crc32` (what the PHP crawler already uses) | keys 975101118 vs 136925746 for one phase |
| 5 | Pagination shows duplicates and hides rows | `queries.py:2904`, `:2254`, `:1379` | append an id tiebreaker — the `_id_tie` idiom already exists at `queries.py:1639` | 339 books share one `created_at`; 13 books on both page 1 and 2; CSV export duplicates 227 of ~6,300 |
| 6 | `year_pages_swap` fires on a year given as a string | `pipelines.py` | compare numerically, not by identity | latent: all 14 production occurrences carry a real page count |
| 7 | `sku_duplicate` looks for a state the schema forbids | `services/validate.py:468` | delete it, plus its `ISSUE_KEYS` / `ISSUE_DESCRIPTIONS` entries | 0 recorded ever, vs 7,156 `isbn_duplicate` |
| 8 | Descriptions truncate at a mixed line break (markdownify) | `pipelines.py` | normalise `<br/>` → `<br>` before conversion | `<p>One<br>Two<br/>Three</p>` loses "Three" |

**Every fix moves the reference implementation.** The PHP port is measured
against Python's behaviour, so each lands in lockstep: regenerate the goldens
(`make golden`, `make discovery-golden`, `make markdown-golden`) and re-run the
nine differentials. Items 6 and 7 require *removing* the deliberate
bug-reproduction from the PHP side. That lockstep is the standing cost of two
stacks.

## Part two — removing Python

Eight phases, each with the check that must pass before the next starts.

1. **Move schema ownership to PHP** — 3–4 days, the blocker. Alembic owns 118
   revisions; PHP owns nothing by design. Don't re-express the history: take
   `pg_dump --schema-only` as baseline migration 0001 for a PHP migrator in
   `php/` (shared by crawler and dashboard, never in the Laravel app). Keep
   `alembic/` as read-only history.
   *Gate:* fresh DB from the PHP baseline, `pg_dump --schema-only` both, diff to
   zero — that is what catches enums, partial unique indexes, check constraints.
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

Total: ~3 weeks focused work plus 2 weeks shadow.

## What removal gives up

- **The differential method.** Afterwards the PHP suite asserts PHP against its
  own frozen past — a regression net, not a correctness proof.
- **Python's suite** — 504 unit and 416 integration tests.
- **The audit capability.** Eight defects in one session came from having two
  implementations to disagree with each other. One cannot disagree with itself.

A smaller first step, if wanted: run the PHP crawler for a single shop in
parallel, keeping Python for schema, scheduling and observability. Real
operational signal, no cutover, and the differentials keep working.
