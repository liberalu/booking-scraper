# Data Quality Rules — Design

**Status:** Draft — not yet planned or implemented
**Date:** 2026-05-18

## Context

After a session of triaging real validator issues across pegasas, patogupirkti, vaga, and humanitas, a recurring pattern emerged: most "broken" entries are not bugs in the data itself but limits of our current validation and matching logic. This document proposes 13 new rules — each with a clear failure mode, current behaviour, proposed implementation, and acceptance signal.

Rules are ordered by impact-to-effort: rules 1–4 unlock the biggest reductions in noise / unmatched volume; rules 5–9 catch genuine data drift that's currently invisible; rules 10–13 are cleanup and parity items.

The rules build on fixes already shipped in this session:
- `zero_price` suppression when `in_stock=False`
- `url_aliases` trailing-slash normalisation
- `non_product_active` auto-heal (deactivate `shop_books` whose URLs are all `non_product`)
- `slug_title_mismatch` punctuation-aware tokenisation
- ISBN-13 `978-9789…` corruption signature rejected
- pegasas EAN-vs-ISBN reconciliation when publisher prefix matches
- ISBN normalised to ISBN-13 (pegasas)
- iBiblioteka multipart parts emit `_part_urls` for follow-up ingestion
- Bulk re-scrape from issue-group view (scan-with-urls path)

---

## Rule 1 — Multi-shop ISBN consensus synthesis

**Problem.** ~10k shop_books on pegasas (and similar counts elsewhere) carry valid ISBNs but stay `unmatched` because no canonical record exists for that ISBN. The current `match` phase's step 3 (synthesis) creates a canonical `shop_inferred` book only when the synthesis pass runs — but the match spider currently times out before reaching step 3 (see follow-up #1). Even when it runs, it creates a record per shop, leading to duplicates.

**Failure mode evidence.** Pegasas has 9 open `unmatched_has_isbn` issues; 5 are real (valid ISBN, no canonical), of which several have the same ISBN already present at patogupirkti with `match_status='matched'` to a `shop_inferred` canonical — but patogupirkti's record isn't visible to pegasas's matcher because they synthesised separately.

**Proposed rule.** When ≥2 shops report the same normalised ISBN and the same title-similarity (Jaro-Winkler ≥ 0.85 between cleaned titles), auto-create a single `shop_inferred` canonical book + `book_isbns` row. Subsequent shop_books with that ISBN match into the same canonical record.

**Implementation.**
- New service method `MatchService.synthesise_by_isbn_consensus(shop_id)`.
- SQL: find ISBNs present in `shop_books` for ≥2 distinct `shop_id`s that don't yet have a `book_isbns` row.
- For each such ISBN, pick the shop_book with the most populated metadata (year, publisher, author) as the synthesis source.
- Insert into `books` (data_source='shop_inferred', source_run_id=run_id) + `book_isbns`.
- Match step 1 re-links all matching shop_books in one UPDATE.

**Acceptance.** A targeted backfill run reduces `unmatched_has_isbn` by ≥80% across all shops. After deployment, the issue should never grow back beyond single digits per shop, with the remainder being shop-exclusive titles awaiting iBiblioteka ingestion.

---

## Rule 2 — Title+author fuzzy match for cross-edition linking

**Problem.** Different editions of the same book have different ISBNs (e.g. Rikiki skalbia 2000 → 9789986028383, Rikiki skalbia 2006 → also 9789986028383 — but other titles have a 2-year reprint with a new ISBN). Current matching is ISBN-exact, so editions are treated as unrelated rows. Browsing the canonical books table is fragmented; the dashboard shows "2 books" when really it's one work with 2 editions.

**Failure mode evidence.** "Pirmoji moterų seklių agentūra" → 2 canonical entries (book#3674 2005 ed., book#144106 2006 ed.). "Ana Karenina" → 18 canonical entries. Users see duplicates; matchers can't link a shop_book to "the work" only "an edition".

**Proposed rule.** Introduce `works` (or `book_id` → `parent_book_id` self-reference on `books`). Cluster editions by normalised title (lowercase, diacritic-stripped, alphanumeric tokens) + primary author's `canonical_author_id`. Fuzzy threshold: title token-set Jaccard ≥ 0.85 AND author exact match.

**Schema (option A — self-reference):**
```sql
ALTER TABLE books ADD COLUMN work_book_id INTEGER REFERENCES books(id);
CREATE INDEX ix_books_work ON books(work_book_id);
```
The "work canonical" is the lowest book_id in the cluster (or earliest year). All other editions point to it.

**Implementation phases.**
- Phase A: offline clustering job over existing `books` produces `(child_book_id, parent_book_id)` pairs. Manual review of borderline cases (similarity 0.85–0.92) before commit.
- Phase B: pipeline upsert checks for a work-match before creating a new canonical, links to existing parent.
- Phase C: dashboard collapses "editions of the same work" into a single card with edition list.

**Acceptance.** Canonical books table shrinks from ~227k to ~180k (rough 20% dedup). Dashboard `books?q=...` returns one row per work, with editions in a sub-list. Shop-book detail shows "Other editions of this work" sidebar.

---

## Rule 3 — Full ISBN group-ID registry validation

**Problem.** We currently reject the specific `9789789…` and `9799789…` corruption signatures, but other malformed ISBN-13s pass our checksum-only validation. The ISBN International Agency publishes the full list of valid group identifiers (e.g. `978-0`, `978-1`, …, `978-9952`, `978-9989`, etc.) — anything outside this set is structurally invalid even if the check digit is correct.

**Failure mode evidence.** During the session, `9789785430042` was initially flagged as corruption by an over-broad rule (it's actually a valid `978-5-...` Russian-group ISBN). The correct fix is full group-ID lookup.

**Proposed rule.** Load the ISBN agency's group-identifier ranges into a small lookup table or hardcoded set. `is_valid_isbn` performs three checks: (a) format regex, (b) check digit, (c) group prefix matches a registered range.

**Data source.** [International ISBN Agency — Range Message](https://www.isbn-international.org/range_file_generation). XML/JSON of all `978-X…` and `979-X…` ranges. ~6.7k entries, tiny. Ship as a static Python module `book_scraper/isbn_groups.py`, refresh annually.

**Implementation.**
- `book_scraper/isbn_groups.py`: `is_in_registered_group(digits: str) -> bool` — scans the digits[3:] prefix tree to find a registered group/publisher range.
- `is_valid_isbn` adds the group-registry check after checksum.
- Existing `_coerce_isbn` paths still work; this is a stricter gate.

**Acceptance.** Sample the 9k+ resolved `invalid_isbn` issues — recompute with new rule. The new rule should reject all known corruption patterns (`9789789…`, malformed publisher prefixes) without false-positiving any sample of valid international ISBNs (run against the OpenLibrary ISBN dump for ground truth).

---

## Rule 4 — `books` schema: `multipart` + `parent_book_id`

**Problem.** Multi-volume works exist in iBiblioteka as a parent + children (e.g. Ana Karenina, parts T.1 + T.2). The runtime fix in this session enqueues parts as separate scan items, so each volume becomes its own canonical row — but the relationship to the parent work is lost. Dashboard shows "Ana Karenina T.1" and "Ana Karenina T.2" as unrelated rows.

**Proposed rule.** Persist multipart relationships explicitly so the dashboard can present "Volume X of Y" relations and so matchers can use parent-level metadata when the part record is sparse.

**Schema.**
```sql
ALTER TABLE books ADD COLUMN multipart BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE books ADD COLUMN parent_book_id INTEGER REFERENCES books(id);
ALTER TABLE books ADD COLUMN part_index INTEGER; -- 1, 2, … (preserves T.1 / T.2 ordering)
CREATE INDEX ix_books_parent ON books(parent_book_id);
```

**Pipeline change.**
- `parse_product_page` (ibiblioteka) already detects `multipart=True`. Add `multipart=True` + `parts_codes=[...]` to the BookItem.
- BookItem pipeline: when ingesting the parent, set `multipart=True`. When ingesting a part (libis_code in `parts_codes` of an existing parent), set `parent_book_id` + `part_index` (derived from the parent's `parts[]` order).

**Acceptance.** Sample query: `SELECT title, COUNT(*) FROM books WHERE parent_book_id IS NOT NULL GROUP BY title HAVING COUNT(*) > 1` should show ~250 multi-volume works after backfill. Dashboard book page shows a "Volumes" sidebar for parents.

---

## Rule 5 — Cross-shop ISBN drift detection

**Problem.** Two shops may report different ISBNs for what is clearly the same book (typo on one side, or a reprint with a new ISBN). Today this leads to two unrelated canonical records (with Rule 1 active) or one unmatched + one matched (today). No alert is raised, and the discrepancy goes unnoticed.

**Failure mode evidence.** "Pirmoji moterų seklių agentūra" — pegasas had corruption-generated `9789789955084`; the real ISBN is `9789955087793`. Without cross-shop comparison, our system wouldn't have caught it — the user did manually.

**Proposed rule.** New validator issue `cross_shop_isbn_mismatch`: triggered when two shops both have a shop_book whose `(normalised_title, primary_author)` is identical but the ISBN differs. Severity: warning.

**SQL (sketch).**
```sql
SELECT a.id AS sb_a, b.id AS sb_b, a.isbn, b.isbn, a.title
FROM shop_books a JOIN shop_books b
  ON normalise(a.title) = normalise(b.title)
 AND a.shop_id <> b.shop_id
 AND a.isbn IS NOT NULL AND b.isbn IS NOT NULL
 AND a.isbn <> b.isbn
WHERE EXISTS (SELECT 1 FROM shop_book_authors saa
               JOIN shop_book_authors sba ON sba.shop_book_id = b.id
               WHERE saa.shop_book_id = a.id AND saa.position = sba.position);
```

**Implementation.** Add to `ValidateService.check_data_correctness`. Both sides get a `cross_shop_isbn_mismatch` issue with `raw_value` = "vs shop_book #N with isbn X". Severity `warning` so it can be reviewed without blocking matching.

**Acceptance.** First run flags ≤200 cases per shop pair (sampling shows mostly different editions or one-side typos). All should be investigable in <30 min each, with a dedicated "compare" view on the dashboard.

---

## Rule 6 — Configurable language-scope per shop

**Problem.** pegasas's LT-only scope is hardcoded in the parser via `_LANG_LITHUANIAN`. Adding a shop with a different scope (humanitas keeps LT + DE + EN academic; future shops may be LT + RU) requires editing the parser. The "out-of-scope" detection (English books leaking through, getting marked non_product) lives in scan logic, not config.

**Proposed rule.** Move language scope to per-shop TOML:
```toml
[scope]
languages = ["lt"]            # ISO 639-1 codes. Empty = no filter.
language_attribute = "Leidinio kalba"  # field name in the source data
language_values = ["Lietuvių", "Lithuanian", "lt"]  # values that count as a match
```

**Parser change.** Each shop parser reads its scope and applies the filter generically. The `_LANG_LITHUANIAN` constant moves into config.

**Out-of-scope handling.** Books out of scope are marked `non_product` (already current behaviour for pegasas English books). The validator's `non_product_active` auto-heal then deactivates the shop_book.

**Acceptance.** Adding a new bookshop with a different scope is a config-only change (no parser edit). pegasas behaviour unchanged. Humanitas explicitly opts in to multiple languages.

---

## Rule 7 — Stale-shop_book auto-resolve

**Problem.** When a `shop_book` is deactivated (`is_active=false`), its open validation issues stay in `new` state. They're effectively dead — the underlying entity is gone — but they pollute counts and waste reviewer attention.

**Failure mode evidence.** During this session's `non_product_active` auto-heal, we deactivated 1,945 pegasas shop_books, but issues attached to those books (other than `non_product_active` itself) didn't auto-close. The 9 `unmatched_has_isbn` we tracked included 4 whose shop_books are now inactive.

**Proposed rule.** New step in `ValidateService.run()`: after all checks complete, resolve any open `validation_issues` whose `shop_book_id` points to an `is_active=false` row. Mark with reason `shop_book_inactive` (stored in a new column or in `lifecycle_state` notes).

**SQL.**
```sql
UPDATE validation_issues vi
SET lifecycle_state = 'resolved', resolved_at = NOW()
FROM shop_books sb
WHERE vi.shop_book_id = sb.id
  AND vi.lifecycle_state IN ('new', 'acknowledged', 'snoozed')
  AND sb.is_active = false;
```

**Acceptance.** Issue counts drop visibly after the next validate run on each shop. Dashboard's "stale issues" gauge approaches zero.

---

## Rule 8 — Severity tier for `unmatched_has_isbn`

**Problem.** `unmatched_has_isbn` is currently a single class. But there are two very different root causes:
- (a) Canonical record exists in `book_isbns` for this ISBN, but the match-phase failed to link → this is a **real bug** (matcher broken, run aborted, or schema drift).
- (b) Canonical record doesn't exist yet (waiting on iBiblioteka or `shop_inferred` synthesis) → **info only**, no action needed today.

Treating them the same makes the issue list noisy and trains reviewers to ignore real bugs.

**Proposed rule.** Split into two issues:
- `unmatched_canon_exists` (severity `critical`) — `EXISTS (SELECT 1 FROM book_isbns WHERE isbn = sb.isbn)` AND `sb.book_id IS NULL`. This means our matcher should have linked it but didn't — investigate matcher state or rerun match.
- `unmatched_no_canon` (severity `info`) — `sb.isbn IS NOT NULL AND NOT EXISTS (...)`. Awaiting Rule 1 (consensus synthesis) or iBiblioteka ingestion.

**Implementation.** Update `check_match_readiness` in `ValidateService`. Update `ISSUE_SEVERITY` map in `queries.py`.

**Acceptance.** `unmatched_canon_exists` should be 0 on a healthy system; spikes signal matcher regressions. `unmatched_no_canon` becomes a tracked-but-low-priority backlog.

---

## Rule 9 — Diacritic-loss slug pattern detector

**Problem.** Some shop slug generators drop Lithuanian diacritic characters entirely instead of transliterating them, producing fragmented slugs like `kale-du-pu-ga` from "Kalėdų pūga". These slugs trigger our slug-title-mismatch validator correctly, but they're a shop-side bug class that deserves its own issue type for trending and shop-reporting.

**Failure mode evidence.** pegasas `issue#359984` — slug `kale-du-pu-ga-2196148`, title `Kalėdų pūga`. After our tokeniser fix, it's the only remaining `slug_title_mismatch` on pegasas, all others auto-resolved.

**Proposed rule.** New validator pattern `slug_diacritic_loss`: slug consists entirely of short alphabetic runs (1–3 chars) separated by hyphens, where the title has 1+ Lithuanian diacritics. Severity `info`, useful for tracking shop-side bugs and reporting to the shop.

**Detection.**
```python
import re
SHORT_RUN = re.compile(r'^[a-z]{1,3}(-[a-z]{1,3}){2,}-?\d*$')
def slug_looks_diacritic_lossy(slug: str, title: str) -> bool:
    return (
        bool(SHORT_RUN.match(slug.strip('-')))
        and any(c in title for c in 'ąčęėįšųūž')
    )
```

**Acceptance.** First scan flags ~1–10 per shop. Aggregate report identifies which shops have the bug and can be sent to them.

---

## Rule 10 — EAN-vs-ISBN reconciliation as shared utility

**Problem.** The EAN-vs-ISBN smart-pick logic (prefer strictly-valid EAN over recovered ISBN when publisher prefix matches) lives inline in `pegasas/parsers.py`. Other shops with both fields (humanitas via `<div class="book-info">`, patogupirkti) would benefit but would currently need a copy-paste.

**Proposed rule.** Lift `_strict()` + the precedence logic into `book_scraper/isbn.py` as `pick_isbn(raw_isbn: str | None, raw_ean: str | None) -> str | None`. Returns the best ISBN-13, applying:
1. Strictly-valid ISBN field → use it.
2. Recoverable ISBN field + EAN with matching publisher prefix → use EAN.
3. Recoverable ISBN field (no EAN match) → recover from ISBN-10 core.
4. Strictly-valid EAN, no ISBN → use EAN.
5. Last-resort recovery from EAN field.

**Implementation.**
```python
# book_scraper/isbn.py
def pick_isbn(raw_isbn: str | None, raw_ean: str | None) -> str | None:
    isbn_strict = _strict(raw_isbn)
    ean_strict = _strict(raw_ean)
    isbn_recovered = _recover_from_isbn10(raw_isbn)
    if isbn_strict: return isbn_strict
    if ean_strict and isbn_recovered and isbn_recovered[:9] == ean_strict[:9]:
        return ean_strict
    if isbn_recovered: return isbn_recovered
    return ean_strict or _recover_from_isbn10(raw_ean)
```

Each shop parser calls `pick_isbn(raw_isbn, raw_ean)` instead of bespoke logic.

**Acceptance.** pegasas behaviour unchanged. humanitas and patogupirkti pick up the smart logic and recover ~10–100 typo'd ISBNs each (estimate from sampling).

---

## Rule 11 — ISBN normalisation to ISBN-13 for all shops

**Problem.** During this session, pegasas got a one-off migration (4,475 ISBN-10 → ISBN-13). Vaga, humanitas, and patogupirkti likely still store some ISBN-10 values. Mixed formats break the cross-shop ISBN lookups Rule 1 and Rule 5 depend on, and bloat the index.

**Proposed rule.** Pipeline-side: every shop parser returns ISBN as ISBN-13 (calling `to_isbn13`). Migration: one-off `UPDATE shop_books SET isbn = to_isbn13(isbn)` per shop.

**Implementation.**
- Update humanitas, vaga, patogupirkti parsers to call `to_isbn13()` before storing.
- Migration script (similar to the pegasas one): per shop, convert all valid ISBN-10s; NULL anything that's neither a valid ISBN-10 nor ISBN-13.

**Acceptance.** `SELECT LENGTH(isbn), COUNT(*) FROM shop_books WHERE isbn IS NOT NULL GROUP BY 1` shows only `13` and `NULL`. Cross-shop ISBN joins work consistently.

---

## Rule 12 — `book_isbns` upsert by either form

**Problem.** When iBiblioteka returns both ISBN-10 and ISBN-13 for a book, we store both as separate `book_isbns` rows. Good. But if a shop stores only the ISBN-10 form and we only have the ISBN-13 in canonical (or vice versa), the matcher's ISBN-exact-match misses. With Rule 11 applied this is less of a problem going forward, but historical data has the mismatch.

**Proposed rule.** Match step 1 SQL compares against both forms by normalising both sides to ISBN-13 at match time:
```sql
UPDATE shop_books sb
   SET book_id = bi.book_id, match_status = 'matched', match_method = 'isbn'
  FROM book_isbns bi
 WHERE sb.book_id IS NULL
   AND sb.isbn IS NOT NULL
   AND to_isbn13(sb.isbn) = to_isbn13(bi.isbn);
```

This requires a `to_isbn13` SQL function. Implement as a Postgres `IMMUTABLE` function so it can be indexed and used in JOIN predicates.

**Implementation.**
- New Alembic migration creates `CREATE OR REPLACE FUNCTION to_isbn13(text) RETURNS text` in PL/pgSQL (the same logic as the Python `to_isbn13`).
- Match step 1 SQL upgraded to use it.

**Acceptance.** Targeted re-run of match step 1 links any historical ISBN-10/13 mismatches (estimate ~500 across all shops). Subsequent matches are format-agnostic.

---

## Rule 13 — Issue resolution audit log

**Problem.** We currently store `lifecycle_state` + `resolved_at` on `validation_issues`, but no reason. Issues auto-resolved by `resolve_gone_issues`, by Rule 7 (shop_book inactive), by a re-scan producing clean data, or by a manual click all look identical. This blocks any tuning of validator rules — we can't tell which rules are noisy (mostly auto-resolved) vs effective (mostly manually-actioned).

**Proposed rule.** Track resolution reason as a string column. Reasons:
- `auto_clean_run` — `resolve_gone_issues` closed it because a fresh run didn't re-raise.
- `shop_book_inactive` — Rule 7.
- `manual_dashboard` — operator clicked resolve.
- `acknowledged_to_resolved` — promoted from acknowledged after N clean runs (future rule).
- `bulk_rescrape` — closed by the bulk-rescrape flow.

**Schema.**
```sql
ALTER TABLE validation_issues ADD COLUMN resolved_reason TEXT;
```

**Dashboard.** Show resolution distribution per issue type on the issue-detail page or as a metric on the issues overview. Helps identify rules that fire-and-resolve constantly (consider tightening them).

**Acceptance.** After 4 weeks of data, each issue type has a resolution-reason distribution; rules with >90% `auto_clean_run` are candidates for tightening or downgrading severity.

---

## Rule 14 — Title + author exact match (no-ISBN fallback)

**Problem.** Match step 1 only links `shop_books` whose ISBN exists in `book_isbns`. shop_books with `isbn IS NULL` (or whose ISBN doesn't appear in any canonical record) stay permanently `unmatched`, even when the *same title + same author* exists in `books`. Patogupirkti and humanitas have a meaningful tail of older / niche titles with no ISBN at all (publisher never registered one, or ISBN scrubbed from the source page).

**Failure mode evidence.** Sample query against the current DB:
```sql
SELECT COUNT(*) FROM shop_books sb
WHERE sb.isbn IS NULL AND sb.match_status = 'unmatched'
  AND EXISTS (
    SELECT 1 FROM books b
    JOIN book_authors ba ON ba.book_id = b.id AND ba.role = 'author'
    WHERE normalise(b.title) = normalise(sb.title)
    -- author equivalence check
  );
```
A spot-check shows ~3-8% of unmatched no-ISBN shop_books have a clear title+author hit in canonical. That's hundreds to low thousands of recoverable matches per shop.

**Proposed rule.** New match step (between current step 1 and step 2): `_step1b_title_author_match`. Conditions:
- `sb.isbn IS NULL` (no ISBN to match)
- `sb.book_id IS NULL` (not already matched)
- Normalised title (lowercase + diacritic-stripped + alphanumeric tokens) matches **exactly** with a single canonical row's normalised title.
- Primary author (`shop_book_authors.position=0, role='author'`) name matches a `book_authors` entry for that canonical (via `canonical_author_id` OR normalised name).
- Year, if both present, must agree (else skip — different edition).

The match is recorded with `match_method = 'title_author_exact'`, distinct from `'isbn'`, so it can be filtered/audited separately and downgraded in confidence rankings.

**Implementation sketch.**
```sql
UPDATE shop_books sb
   SET book_id = b.id,
       match_status = 'matched',
       match_method = 'title_author_exact'
  FROM books b
  JOIN book_authors ba ON ba.book_id = b.id AND ba.role = 'author' AND ba.position = 0
  JOIN shop_book_authors sba ON sba.shop_book_id = sb.id AND sba.position = 0
  JOIN shop_authors sa ON sa.id = sba.author_id
 WHERE sb.shop_id = :shop_id
   AND sb.isbn IS NULL
   AND sb.book_id IS NULL
   AND normalise_title(sb.title) = normalise_title(b.title)
   AND (sa.canonical_author_id = ba.author_id
        OR normalise(sa.name) = normalise((
            SELECT name FROM authors WHERE id = ba.author_id
        )))
   AND (sb.year IS NULL OR b.year IS NULL OR sb.year = b.year)
   -- Refuse if multiple canonical books match — only proceed when exactly one.
   AND (SELECT COUNT(*) FROM books b2
        WHERE normalise_title(b2.title) = normalise_title(b.title)) = 1;
```

Requires a Postgres `normalise_title()` function (lowercase, NFD-strip-diacritics, alphanumeric-only). Indexable as a functional index on `books(normalise_title(title))`.

**Risk.** False positives when two unrelated books share title + author (rare but real: "Selected poems" by various authors with the same surname; "Atsiminimai" memoirs by different people). Mitigations:
- Year-agreement gate.
- Refuse when >1 canonical title-match exists (sketch's final `COUNT` filter).
- Mark as `match_method='title_author_exact'` so reviewers can sample.

**Acceptance.** First run links ~200-1,500 new matches per shop. Manual spot-check of 30 random matches per shop shows ≥95% correct.

---

## Rule 15 — LIBIS code direct match

**Problem.** Some shop product pages reference the iBiblioteka catalogue entry directly — humanitas occasionally links "Daugiau informacijos: ibiblioteka.lt/metis/publication/C1B…" in book descriptions. We currently ignore that signal. If captured, it's the *most authoritative* match possible — exact LIBIS code identity.

**Proposed rule.** Per-shop parser: when scraping a product page, scan the description / external links / "see also" sections for `metis/publication/C[A-Z0-9]+` patterns. If found, store the libis_code on the shop_book row (new column `shop_books.libis_hint`). Match step adds a pre-step-1: link shop_book to canonical where `shop_book.libis_hint = books.libis_code`.

**Schema.**
```sql
ALTER TABLE shop_books ADD COLUMN libis_hint TEXT;
CREATE INDEX ix_shop_books_libis_hint ON shop_books(libis_hint) WHERE libis_hint IS NOT NULL;
```

**Parser change.** humanitas/patogupirkti/vaga parsers add a regex scan over the description HTML. ~10 LOC per parser.

**Match step (step 0, runs before step 1):**
```sql
UPDATE shop_books sb
   SET book_id = b.id,
       match_status = 'matched',
       match_method = 'libis_code'
  FROM books b
 WHERE sb.shop_id = :shop_id
   AND sb.book_id IS NULL
   AND sb.libis_hint IS NOT NULL
   AND b.libis_code = sb.libis_hint;
```

**Coverage estimate.** Probably 0-2% of shop_books, depending on the shop. humanitas likely the highest (academic books frequently cross-reference LIBIS). Low effort, perfect precision when it fires.

**Acceptance.** A targeted parser run on humanitas surfaces at least a few dozen `libis_hint` values; step 0 matches them all with `match_method='libis_code'`.

---

## Match strategy chain (cross-rule reference)

For clarity, here is the full intended matcher pipeline once Rules 11, 12, 14, 15 are implemented. Each step only runs against shop_books still unmatched after prior steps. Each step uses a strictly more permissive predicate than the previous.

| Order | Step | Predicate | Method tag | Risk | Coverage gain |
|---|---|---|---|---|---|
| 0 | LIBIS hint | `sb.libis_hint = b.libis_code` | `libis_code` | Zero — exact identity | Low (0-2%) |
| 1 | ISBN exact (current) | `sb.isbn = bi.isbn` | `isbn` | Zero (with Rule 3 active) | High |
| 1b | ISBN-10/13 equivalence (Rule 12) | `to_isbn13(sb.isbn) = to_isbn13(bi.isbn)` | `isbn` | Zero — math-equivalent forms | Small (~500 backfill) |
| 1c | Synthesis (Rule 1) | ≥2 shops agree on ISBN, no canonical exists → create canonical + link | `isbn_synth` | Low — consensus is strong signal | Very high (~10k) |
| 1d | iBiblioteka enrichment (passive) | Pipeline upsert of new iBiblioteka record merges into existing shop_inferred canonical via ISBN | (data_source flips) | Zero | Ongoing |
| 2 | Title+author exact (Rule 14) | `sb.isbn IS NULL` + normalised title+author exact, year agreement, single canonical | `title_author_exact` | Low — strict gates | Medium (~1k) |
| 3 | Work-level fuzzy (Rule 2) | Cross-edition linking via `work_book_id` clustering | `work_fuzzy` | Medium — fuzzy similarity | Architectural, defer |

Each step also writes the `match_method` so the dashboard can colour-code or filter by method (e.g. show ISBN matches as solid links, title+author as dashed). Rolling out the chain in this order means each later step has a smaller, cleaner working set to operate on.

**Match-strategy expansion task list (use when rolling out the chain):**
1. Add `normalise_title()` and `to_isbn13()` Postgres functions (migration).
2. Add `match_method` literal `'title_author_exact'`, `'libis_code'`, `'isbn_synth'`, `'work_fuzzy'` to enum/check constraint.
3. Add `shop_books.libis_hint` column + index (Rule 15).
4. Implement `MatchService._step0_libis_hint`, `_step1b_isbn_equivalence`, `_step1c_synthesise`, `_step2_title_author_exact`.
5. Audit dashboard `/shop-books/{id}` to display `match_method` for transparency.
6. Spot-check 30 random matches per new method per shop after each rollout.

---

## Rollout order

Rules marked ✅ are shipped. Remaining sequence ordered by current priority (updated 2026-05-22):

- ✅ **Rule 9** (diacritic-loss detector) — shipped 2026-05-20; `slug_diacritic_loss` validator live.
- ✅ **Rule 7** (stale auto-resolve) — shipped; `resolve_gone_issues` runs after every validate pass.

**Next up (priority order from follow-ups doc):**

1. **Rule 11** (normalise ISBN to ISBN-13 across all shops) — prerequisite for Rules 1, 5, 12. Vaga/humanitas/patogupirkti all store mixed ISBN-10/13 without normalisation.
2. **Rule 12** (format-agnostic match SQL + `to_isbn13()` Postgres function) — closes remaining ISBN-10/13 cross-form match gaps. Adds step 1b in the match chain. Depends on Rule 11.
3. **Rule 15** (LIBIS code direct match) — adds step 0 in the match chain; cheapest, highest precision when applicable. Independent of 11/12.
4. **Rule 1** (multi-shop ISBN consensus synthesis) — depends on 11/12; resolves ~10k acknowledged `unmatched_has_isbn` cases. Also unblocks removing the `MATCH_SYNTHESIS_ENABLED=0` flag. Adds step 1c.
5. **Rule 14** (title+author exact fallback) — adds step 2; depends on Rule 1 so the no-ISBN candidate pool is realistic.
6. **Rule 8** (severity split) — depends on 1 to make sense; lets the issues page surface real matcher bugs.
7. **Rule 3** (full ISBN group registry) — independent, hardens validation against future corruption patterns.
8. **Rule 10** (shared EAN-vs-ISBN utility) — quick refactor; enables cleaner humanitas/patogupirkti parsers.
9. **Rule 6** (config-driven language scope) — quick refactor, blocks adding new shops.
10. **Rule 4** (multipart parent/child) — schema change + backfill; enables better dashboard.
11. **Rule 2** (work-level fuzzy match) — biggest design change; adds step 3; defer until 1+4+14 prove stable.
12. **Rule 5** (cross-shop drift) — depends on 1+2 for sane scope.
13. **Rule 13** (resolution audit log) — schema change + dashboard update; do alongside Rule 4 or 8 to amortise migration cost.

## Out of scope

- Cross-language deduplication (Russian editions of LT books, English translations).
- ISBN-A / ISBN-extended forms.
- Author-deduplication beyond the existing `canonical_author_id` linkage.
- LIBIS-API-level changes (we treat iBiblioteka responses as authoritative for the records they expose).
