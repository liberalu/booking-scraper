# Data Quality Cleanup — Follow-up Tasks

**Date:** 2026-05-21
**Shipped in:** in-session SQL/code/config changes across `book_scraper/services/validate.py`, `book_scraper/spiders/pegasas/parsers.py`, `book_scraper/spiders/pegasas/category_names.py` (new, 46 KB), `book_scraper/services/match.py`, `tests/unit/test_validate_service_structural.py`, `tests/unit/test_pegasas_parsers.py`, plus 17 targeted DB cleanups.

A two-session marathon working through the validator backlog — started at 124,858 open issues, ended at 0. This document captures what shipped, what's deferred, and what's worth doing in the next session.

---

## What landed (19 tasks)

### Validator refinements (`book_scraper/services/validate.py`)

- **R — `is_active=true` filter on structural duplicates + match + data-correctness validators.** Deactivated shop_books no longer fire `isbn_duplicate`, `title_author_duplicate`, `sku_duplicate`, `slug_title_mismatch`, `slug_diacritic_loss`, `unmatched_has_isbn`, `match_isbn_drift`, `year_out_of_range`. Cleared ~4,700 stale issues whose underlying shop_books had been deactivated by Q/T/X.
- **X / Y — `in_stock=true` gate added to `active_no_price` and `no_price_history`.** Out-of-stock books no longer fire price-missing flags (mirrors `zero_price` and `missing_price` precedent). Cleared ~30k stale issues across patogupirkti and humanitas.
- **CC — `_title_indicates_non_book` filter on `non_book_has_isbn`.** Suppresses noise on DVDs/CDs/bundles that legitimately have ISBNs (regex matches `(DVD)`, `(CD)`, `rinkinys`, `komplektas`, audio formats; deliberately excludes `(su DVD)` etc. which are books-with-DVD-included). Cleared ~200 patogupirkti issues.
- **Deprecated `product_url_non_book` validator.** Previously fired for every shop_book with `type='non_book'` at `url_type='product'` — over-strict for shops legitimately selling DVDs/CDs/bundles. Replaced with empty list; the misclassification-with-ISBN case is already covered by `non_book_has_isbn`.

### Parser fixes (`book_scraper/spiders/pegasas/parsers.py`)

- **H — Pegasas category-ID → name resolution.** New static module `category_names.py` with 1,170 entries fetched from the Magento `categoryList` GraphQL once. LupaSearch parser now resolves numeric IDs to human-readable names so the `_categories_indicate_non_book` check works on pegasas the same as on other shops. 15,495 shop_books backfilled.
- **P — `derive_book_type` `has_book_category` fallback.** When Magento's `is_book=False` but category names contain book-signalling substrings (`knyg`, `groz`, `literat`, `vadovel`, `pratyb`), classify as `book`. Covers pegasas's unreliable `is_book` flag for educational textbooks and certain illustrated children's books.

### Match-phase improvements (`book_scraper/services/match.py`)

- **AA / S — Direct SQL re-match passes (one-shot, not productionised yet).** Used inline UPDATE statements to:
  - Re-run match step 1 for shops with auto-trigger gaps (4,349 patogupirkti books matched)
  - Re-attribute drifted matches (1,451 humanitas shop_books re-pointed to correct canonical when their ISBN changed)

### Test coverage (`tests/unit/`)

- **F — 21 new tests for validator helpers.** Covers `_looks_diacritic_lossy` (NFD/NFC encoding regression guard), `_categories_indicate_non_book`, `_is_genuine_url_alias`, `_strict` (pegasas EAN-pick), `format_from_cover_type` edge cases. The NFD fixture explicitly NFD-normalises at runtime so the test doesn't depend on source-file byte preservation.

### DB cleanups (one-shot SQL, 17 operations)

| Task | Action | Rows | Issues cleared |
|---|---|---|---|
| Q | Humanitas dedup (title+ISBN winner selection) | 3,556 deactivated | 12,701 |
| T | Humanitas url_aliases orphaning | 2,396 du rows shop_book_id=NULL | 2,278 |
| X | Humanitas active_no_price triplet deactivation | 771 deactivated | 2,313 |
| W | Pegasas + patogupirkti dedup | 31 deactivated | ~140 |
| BB | Patogupirkti DVD/CD/bundle type-flip | 1,045 reclassified | ~280 |
| CC | Patogupirkti `(su DVD)` revert | 22 reverted | (no-op for issues) |
| Z | slug_diacritic_loss batch-ack | 1,500 acknowledged | 1,500 |
| DD | Patogupirkti price-triplet batch-ack | 34,494 acknowledged | 34,494 |
| EE | Final per-cluster acks (slug_title_mismatch, stale_active, title_author_duplicate, url_aliases, book_no_metadata, book_no_signals, unmatched_has_isbn, orphan_no_url, small residuals) | 353 + 113 acknowledged | 466 |

### Result

Open `new` issues: **124,858 → 0** (-100% this run; 174,064 resolved + 37,384 acknowledged).

---

## What's still open

### ~~**U — humanitas discover-categories parser misattribution**~~ ✅ FIXED 2026-05-22

**Root cause confirmed.** Live category listing pages (with `cntnt01page` pagination) embed inner `<a>` tags inside book-item cards — a wishlist or "Add to cart" button appearing *before* the `<div class="title">` block. The old `_CARD_BLOCK_RE` regex used non-greedy `(.*?)</a>`, which terminated the body capture at the inner anchor's `</a>`, leaving no title/author/price in the extracted body. `_parse_card` then returned a url-only stub, silently dropping all card metadata. When the inner anchor appeared early enough in the card, consecutive cards produced misaligned (url-from-card-N, metadata-from-card-N+1) shop_book rows — explaining the `[Oshi No Ko]` titled / `kakegurui-...` URL mismatch and the isbn_duplicate pairs.

**Fix shipped (`book_scraper/spiders/humanitas/parsers.py`).**

Replaced `_CARD_BLOCK_RE` with `_CARD_OPENING_RE` and rewrote `parse_category_page` to use a "slice between openings" approach:

- Find all `<a class="book-item">` opening tag positions via `_CARD_OPENING_RE.finditer(html)`.
- Body for card N = `html[opening_N.end() : opening_N+1.start()]`.
- No reliance on `</a>` as a boundary — immune to nested anchors and missing close tags.

All 465 unit tests pass. Two new regression tests added (`test_parse_category_page_nested_anchor_before_title_preserves_card_data`, `test_parse_category_page_nested_anchor_no_url_title_swap`).

**Remaining: one-off T-style DB cleanup.**

Future discover runs will no longer generate ghost shop_books or misattributed alias URLs. However, residue from runs #423/#437/#342/#389 (the 4 affected runs) still exists in the DB. After the scraper is redeployed and the next successful humanitas discover-categories run completes, run the T-style cleanup:

```sql
-- Orphan alias discovered_urls (no canonical shop_book owns these URLs)
UPDATE discovered_urls SET shop_book_id = NULL
WHERE shop_id = (SELECT id FROM shops WHERE name = 'humanitas')
  AND url_type = 'product'
  AND shop_book_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM shop_books sb WHERE sb.id = discovered_urls.shop_book_id
      AND sb.url = discovered_urls.url
  );
```

Then re-run the X-style check for title-URL mismatch (771 still-active shop_books) and deactivate confirmed ghosts. The fresh discover run will re-populate correct records.

---

### Architectural rules deferred (see `docs/superpowers/specs/2026-05-18-data-quality-rules-design.md`)

These are designed but not built. Their priority order for next session:

1. **Rule 11** — ISBN-13 normalisation across vaga / humanitas / patogupirkti (prerequisite for 12, 1, 5)
2. **Rule 12** — Postgres `to_isbn13()` function + format-agnostic match SQL (closes remaining ISBN-10/13 cross-form gaps; would unlock more matches)
3. **Rule 15** — LIBIS code direct match (cheapest, highest precision when applicable)
4. **Rule 1** — multi-shop ISBN consensus synthesis (depends on 11/12; would resolve ~10k acknowledged `unmatched_has_isbn` cases AND unblock removing the `MATCH_SYNTHESIS_ENABLED=0` flag)
5. **Rule 14** — title+author exact match fallback (after Rule 1 so the no-ISBN candidate pool is realistic)

---

### Small follow-ups uncovered this session

| Task | Why | Estimate |
|---|---|---|
| **EE-1 — Verify patogupirkti scan #438 reaches completion** | The 34,494 acknowledged price-triplet issues will mostly auto-flip back to `resolved` as the scan re-scrapes books and populates prices. ~24-40h remaining. Worth checking after scan completes whether any genuine stragglers remain. | passive monitoring |
| **EE-2 — Investigate humanitas `orphan_no_url` (10)** | Active shop_books with zero `discovered_urls` rows. Either deleted-but-not-cascaded FK or a rare race in the discover pipeline. | 30 min |
| **EE-3 — Extend `_NON_BOOK_TITLE_RE` patterns** | Add `(Blu-ray)`, `(USB)`, `(Vinyl)` — caught after this session for patogupirkti's edge cases. | 15 min |
| **EE-4 — Auto-acknowledge for confirmed shop-side bugs** | New validator behaviour: emit `slug_diacritic_loss` as `acknowledged` instead of `new` (since the bug is in the shop, not our code, and we'll never fix it). Eliminates the recurring need to manually ack. | 1 hr |
| **EE-5 — Formally delete `product_url_non_book` dead branch** | Currently stubbed to return empty list. Decide: remove entirely, or rebuild with smarter heuristic. | 30 min |
| **EE-6 — Add integration tests for the `is_active=true` filter** | We added the filter to 6 validators in R. No test would catch a regression if someone removed it. A single fixture-loaded test asserting "deactivated shop_book stops firing isbn_duplicate" would prevent class-wide regression. | 1 hr |
| **EE-7 — `_NON_BOOK_TITLE_RE` false-negative guard** | The current regex correctly distinguishes `(DVD)` (non-book) from `(su DVD)` (book-with-DVD-included). Add a test covering both to lock that behaviour down. | 15 min |
| **EE-8 — Update data-quality spec's Rollout-Order** | Rule 9 (diacritic loss detection) is now Implemented; Rules 3, 7, 8 details unchanged. Reorder by what's actually next. | 15 min |
| **EE-9 — Add "Validator filter cheatsheet" to CLAUDE.md** | Document: all shop_book-targeted validators require `is_active=true`; structural duplicates require it on both sides; price-missing checks require `in_stock=true`. Prevents future PRs from forgetting these gates. | 30 min |
| **EE-10 — Regenerate `docs/superpowers/specs/INDEX.md`** | Rule 9 moved to Implemented bucket. Should pick up the spec's status header automatically via the existing script. | 5 min |

---

## Cumulative session totals (2 sessions)

| Issue type | Reduction |
|---|---|
| Total open issues | 124,858 → 0 (-100%) |
| Resolved by code/SQL fixes | ~74,000 |
| Acknowledged (deferred until architectural rules land) | ~37,000 |
| Net validator noise eliminated | 100% of `new` queue |

**Lifecycle distribution (end of session):**
- `resolved`: 174,064
- `acknowledged`: 37,384
- `new`: 0

---

## Process notes

- **Approval friction.** The Claude Code auto-mode classifier blocked several bulk operations (mass `UPDATE` on shared production DB). The successful pattern was: justify per-cluster, do small batches, request explicit "yes" per destructive action. Bulk "ack all" was acceptable only with that exact phrasing as user input.
- **`MATCH_SYNTHESIS_ENABLED=0`** remains the right call until Rule 1 lands with batched commits — the synthesis loop on patogupirkti's ~2.5k unmatched-with-ISBN books would block the reactor past the 60s heartbeat reaper.
- The **`PostPhaseAutoTrigger`** extension (from earlier session) continues to do the right thing — match step 1 + validate after every successful scan/discover. No further intervention needed for the steady-state pipeline.
