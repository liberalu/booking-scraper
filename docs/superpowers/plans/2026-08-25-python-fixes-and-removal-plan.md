# Python fixes, and a plan for removing Python

Rendered version (tables, phase gates): https://claude.ai/code/artifact/3d17d76a-1051-4c75-8708-859b69a74d2c

Found by running the PHP port and the Python stack against identical input and
diffing the results. Every item below was measured, not inferred.

**Part one is done.** All nine defects are fixed in both stacks (commits
`4e274bc`, `2c90beb`, `ac2caa9`, `d92e948`, `2340650`, `8b66faf`, `8828651`,
`1f5e364`), and the undeclared schema drift they surfaced is closed (`09bff38`).
Phase 1 of part two is landed too (`80ae730`), the test databases are no longer
shared (`50a6447`), and **phase 6 — freezing the evidence — is done**: every
comparison now has a golden a Python-free checkout can replay.

**There is no production.** `book-scraper-postgres-1` is a container on this
machine, every DSN in the repo resolves to `localhost` or the compose service
name, and the last scrape ran 31 days ago. Earlier drafts of this plan — and
the estimates in them — were written as though a live service were at stake. It
is not. Phase 7 stops being meaningful, phase 8 takes minutes, and phases 2–4
become optional polish.

Phase 6 was the one that genuinely bit, and it is now done — see the phase
entry below for what it cost and what it could not preserve. The remaining
argument against removal is unchanged in kind: removal retires the mechanism
that found all nine defects above.

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
| 9 | ✅ **Fixed** — `full_crawl` followed whitespace-padded hrefs as separate URLs, fetching those products twice | `spiders/discover.py` | `link.strip()` before resolving, which is what a browser does and what DomCrawler already did on the PHP side | vaga's homepage: 65 padded hrefs, 62 distinct from their clean twins; 629 links before, 565 after. 3 such rows in the catalogue. Pinned by `DiscoverEmitTest` on the surviving stack |

**All nine landed, in lockstep.** The PHP port is measured against Python's
behaviour, so every fix moved both sides together: goldens regenerated
(`make golden`, `make markdown-golden`), and `api-diff`, `validate-diff`
(13,339 issues), `validator-diff` (46/46) and `canonical-diff` all identical
afterwards. Three of the nine required *removing* deliberate bug-reproduction
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

Found while verifying, and since fixed: seeding the test database for the PHP
differentials made the next full Python `pytest` run fail ~61 tests, because
the Python conftest assumes an empty database and both stacks shared one. They
have separate databases now (`50a6447`).

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
5. **Close the feature gaps** — 2–3 days. `full_crawl` (✅ `1f5e364`); a CLI for
   the full match phase (steps 2–3 exist and pass `make match-diff`, nothing
   drives them).

   **`scripts/` decided — all four go, and none needs a port.** Measured
   against the catalogue rather than assumed:

   - `backfill_shop_book_attributes.py` — **delete.** It copies
     `shop_books.properties` into `shop_book_attributes`, and that column no
     longer exists (checked `information_schema`); its own docstring says it
     becomes a no-op after migration `a4bd6135313a`. Already true.
   - `backfill_html_entities.py` — **delete.** 1 row of 101,105 still carries an
     entity (in a description). The parsers decode at scrape time now, and one
     row is a re-scrape, not a script.
   - `backfill_authors.py` — **delete, but the gap is real.** 12,682 active
     books have no author: patogupirkti 7,156, humanitas 3,930, vaga 1,527,
     pegasas 69. This was never a one-off repair — it is a narrower
     `discover --strategy=categories`, which PHP already has, and the missing
     authors are already surfaced as `book_no_metadata` / `book_no_signals`.
     Use the discover pass; the script adds nothing PHP cannot do.
   - `cron_health_check.py` — **delete.** A heartbeat line for a
     `tail -f scraper.log` workflow that Loki, Grafana and the dashboard's runs
     page replaced. Its own docstring calls the dashboard "the rich source".

   *Gate:* every phase in `cron_jobs` has a working PHP command.
6. **Freeze the evidence — before deleting anything.** ✅ **Done.** Nine of the
   17 comparison tools import `book_scraper` (the "16 of 17" in an earlier draft
   was a grep that also matched the database name). Each comparison now writes a
   golden, and `--freeze` writes one **only when both stacks already agree**, so
   what is replayed is Python's behaviour captured rather than PHP's output
   blessed:

   | Comparison | Golden | Replayed by |
   |---|---|---|
   | `api-diff` (79 endpoints) | `api_shapes.json` | `ApiShapeCharacterisationTest` |
   | `mutation-diff` (100 cases) | `mutation_cases.json` | `MutationCharacterisationTest` |
   | `validate-diff` (34 findings, all 20 issue types) | `validate_findings.json` | `ValidateServiceCharacterisationTest` |
   | `match-diff` (linkage + author backfill) | `match_linkage.json` | `MatchServiceCharacterisationTest` |
   | `validator-diff` (46 cases) | `validator_cases.json` | `ItemValidatorCharacterisationTest` |
   | `reaper-diff` | `reaper_fixtures.json` + `reaper_expected.json` | `ReaperCharacterisationTest` |
   | `canonical-diff` | `canonical_expected.json` | `CanonicalBookCharacterisationTest` |
   | `validate-diff` helpers (1,823 cases) | `validate_predicates.json` | `ValidateHelpersDifferentialTest` |

   What this cost, and it is the whole lesson of the phase: **a golden can only
   describe data that comes back the same way every time.** Goldens taken over
   the seeded database kept failing for reasons that were not regressions — the
   seed is a copy of the live catalogue, and a reseed turned a field from `str`
   into `null`. So the API and write-route goldens are taken over a database
   built from nothing: `php/schema`'s baseline plus `SyntheticShop`, both code.
   The validator and matcher goldens are taken over the same synthetic shop,
   which had to grow from 8 issue types to all 20.

   The other half was litter. Six tools and tests left fixtures behind — 13,339
   findings, a sentinel run with a fixed id that survived reseeds, a re-matched
   catalogue, three marked books — and each one moved a golden somewhere else.
   Two tests carried unscoped assertions that read another fixture's rows.

   Two shared behaviours had to be made deterministic before they could be
   frozen at all, and both were arbitrary in *Python* too: the "already active"
   409 named whichever active run Postgres returned first, and the matcher's
   author backfill picked arbitrarily among candidate authors. Both stacks now
   order explicitly.

   *Gate:* met. `crawl_diff` is the one comparison that cannot be frozen — it
   needs live HTTP — but the layers under it are: the parser differentials, the
   item validator, `PersisterTest` (fixture → rows) and the discovery goldens.
   What is lost is "the live site still looks like the fixture", which is
   monitoring, not a regression test.
7. **Shadow run** — ~~2 weeks calendar~~ **redundant.** A shadow period exists
   to prove the new stack behaves on live traffic before cutover. There is no
   live service and no traffic. The meaningful version — run both stacks over
   the same shops and diff what they wrote — is what `crawl_diff`,
   `validate_diff` and `match_diff` already do, and they agree.
   *Gate:* the differentials pass on every shop with seeded data.
8. **Cutover with a way back** — minutes. No scheduled runs to watch, so the
   week-long observation does not apply either. Tag first, then remove
   `book_scraper/` (66 files), `tests/` (86), `scripts/` (6), `alembic/` (60,
   kept in history), the Python packaging and compose services. Rollback is a
   revert to the tag, cheap because the deletion never touches the database.
   *Gate:* one full discover + scan + validate cycle on PHP only.

Total: **~1 week of focused work, no calendar wait.** Phases 1 (done), 5 and 6
are the substance. Phases 2, 3 and 4 matter only if you want it running in
compose on a timer rather than invoked by hand.

## What removal gives up

- **The differential method.** Afterwards the PHP suite asserts PHP against its
  own frozen past — a regression net, not a correctness proof.
- **Python's suite** — 504 unit and 416 integration tests.
- **The audit capability.** Nine defects came from having two implementations to
  disagree with each other. One cannot disagree with itself.
- **Not** the test database's contents. Verified after phase 6: the whole PHP
  suite — library 2,113 tests, dashboard 4, crawler 51 — passes against an
  *empty* database carrying nothing but `php/schema`'s baseline. Every fixture
  is built from code, so `seed_test_db.py` needs no port; it exists to give the
  differentials realistic data, and the differentials are what is being retired.

A smaller first step, if wanted: run the PHP crawler for a single shop in
parallel, keeping Python for schema, scheduling and observability. Real
operational signal, no cutover, and the differentials keep working.
