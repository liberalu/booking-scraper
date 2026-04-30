# Dashboard UI Sweep — Follow-up Tasks

**Date:** 2026-04-30
**Shipped in:** commits `f61f3cd` (UI sweep) + `5bdbb84` (books-by-run) + follow-on commits for live polling indicator + functional Refresh button

A multi-strand quality-and-accessibility pass across the hi-fi dashboard, plus the backend wiring for the run-detail Books tab. This document captures what shipped, what was reviewed, and what's still open.

---

## What landed

### `f61f3cd` — Dashboard UI sweep
14 files, +1610/-530.

**Run detail**
- Section tabs (General / History / Books) persisted to `?tab=`
- Timeline + Throughput moved into a 2-col row above the live cards
- Timeline restyled as a logger (full timestamp · LEVEL · message · summary), clipped to 10 with "Show all N events" toggle and 480px scroll on expand
- Removed redundant Parameters card (every field shown elsewhere in the page)
- Replaced `window.confirm`/`prompt` with `HFConfirmDialog` + `HFAckGroupDialog`
- Action handlers (stop/pause/resume/retry/ack/rerun/continue) toast on success and failure; persistent `actionError` banner removed
- Fix: `hfSweep` keyframe was referenced but never defined — "Now fetching" sweep bar now actually animates
- Fix: `canContinue` falls back to `urlData.breakdown.pending` when `data.pending_count` is stale
- Fix: Failures "Open issues" switches to History tab before scrolling

**Toasts (new infrastructure)**
- `HFToast` + `HFToastHost` in `hf-overlays.jsx`
- Module-level pub/sub bus, exposed via `window.HF_APP.toast({tone, message, detail, ttl})`
- Tone-coded left border, optional icon, dismiss `×`, auto-dismiss
- TTL by tone (errors 7s, warn 5.5s, info 4s)
- `aria-live="polite"`, bottom-right stack

**Skeleton loaders (new infrastructure)**
- `HFSkeleton`, `HFTableSkeleton`, `HFKpiStripSkeleton` primitives
- `@keyframes hfShimmer` in `hf-base`; respects `prefers-reduced-motion`
- Applied to: overview load, run-detail load, runs list load, History table load, Books table load

**Modal accessibility (`HFModal` base)**
- Focus trap (Tab/Shift+Tab cycles inside the panel)
- Initial focus on first interactive element after mount
- Return focus to trigger on close
- Body scroll lock with stack-counter for nested modals
- `role="dialog"` + `aria-modal="true"` + `aria-labelledby` (Context-wired via `HFModalHead`)
- `aria-label="Close dialog"` on the `×` button
- `HFAvatarMenu` got `role="menu"` + `[role="menuitem"]` items + arrow-key navigation + return-focus-to-trigger

**Cross-page sweep**
- New `HFBreadcrumbLink` primitive (real hrefs from `window.HF_BUILD_PATH`, cmd/ctrl/shift fall-through for new-tab opens)
- `‹ Prev` / `Next ›` glyph buttons replaced with chevron icon + text + `aria-label` across runs list, shopbooks, urls-shops, prices, cron
- `<a href="#">` SPA-link breadcrumbs replaced across `hf-shopbooks`, `hf-urls-shops`, `hf-details` (URL/issue), `hf-more-details` (schedule), `hf-parser`
- Run-detail in-table title/URL/Disc.URL links got real hrefs (middle-click opens in new tab)
- Pause + cycle SVG icons added; `⏸` `▶` glyphs removed from action buttons

**Earlier-in-branch consolidated changes**
- Focus rings via `.hf-focus` / `:focus-visible` using `--hf-accent` CSS var
- `prefers-reduced-motion` guard disables animations site-wide
- `HFKpiTile` accepts `href` prop with click-intercept; cmd/ctrl/middle-click falls through to native open-in-new-tab
- Charts (`HFAreaChart`/`HFBarChart`/`HFSparkBars`): `role="img"` + `aria-label` + `<title>`; defend against empty/single-point data
- Density token sizes snapped to integers (12/13/14 ladder); inline `fontSize: X.5` swept across all hi-fi files
- Token additions: `contentX`, `shadowSm`, `shadowLg`
- Overview Activity card numbers + date axis derived from `data.activity` instead of hardcoded

### `5bdbb84` — Books-by-run feature
8 files, +346/-47.

**Schema**
- Migration `f21086852374`: `shop_books.created_run_id` (nullable, indexed, FK to `scrape_runs`)
- `repo.upsert_shop_book` sets it on create only; never overwrites

**Queries**
- `get_run_item_counts` uses `created_run_id` (forward-only; pre-migration runs return 0 for `items_added`)
- New `get_run_books_added` (paginated by `ShopBook.title`)
- New `get_run_books_updated` (joins `shop_book_changes`, `string_agg` of changed fields per book)
- `get_run_failure_groups`: split unacked/acked counts via conditional aggregation; `HAVING` clause hides fully-acked buckets when `include_acked=False`; examples carry `error_detail` (capped 4000 chars)
- `get_run_discovered_urls`: filter by `source` matching `run.phase`

**API**
- New `GET /api/runs/{id}/books?type=added|updated&page&per_page`
- `/api/runs/{id}/live` accepts `include_acked`
- URL items return `response_bytes`

**Cleanup**
- Removed unused `cleanup_scrape_url_items` from `repo.py` (call site dropped earlier in this branch)
- Updated stale docstrings in `queries.py` and `services/scan.py`

**Tests**
- 6 integration tests covering immutability, item counts, API happy path with changed fields, validation, 404
- All pass; lint clean

### Follow-on commits
- **Live polling indicator** — small "LIVE" pill (pulsing dot + uppercase mono label) in the run-detail title, visible while polling is active (`running` / `stopping` / `paused`)
- **Functional Refresh button on Overview** — wired to refetch `/api/overview`; toasts "Overview refreshed" on success, error toast on failure; button disabled with "Refreshing…" label during in-flight fetch

---

## Verified

- 46/46 dashboard route tests pass
- 6/6 new `test_run_books.py` tests pass
- All static hi-fi assets serve 200
- `ruff check` clean across all changed files
- Pre-existing test failures (`test_change_diff.py`, `test_relative_time.py`, `test_shop_books_filter_sort.py`, `test_validation_lifecycle.py`) confirmed unrelated — they fail on bare `main` too (stale tests for helpers and server-rendered HTML that no longer exist post-SPA migration)

---

## P2 — Open follow-ups, ranked by ROI

### 1. Pre-existing test cleanup
Four test files fail on bare `main`: `test_change_diff.py`, `test_relative_time.py`, `test_shop_books_filter_sort.py`, `test_validation_lifecycle.py`. They reference helpers that were removed (`_change_diff`, `_relative_time`) or assert on server-rendered HTML for a SPA dashboard that no longer renders content server-side.

**Action:** Either delete or rewrite. Currently `pytest tests/` is unhelpful as a CI signal because of the noise (~30 failures, all pre-existing).

**Effort:** ~30 min.

### 2. CSS custom properties migration
The biggest architectural unlock left on the table. Currently:
- `getHF()` rebuilds the token object on every component render
- Theme/density swap forces a full React re-render via the `force()` reducer
- Hover/focus styles need `!important` because inline styles always win

Migration plan (incremental, surface by surface):
1. Phase 1: Set up the CSS-vars publisher + global stylesheet skeleton. Migrate `HFButton`, `HFCard`, `HFPill`, `HFDot`. ~1.5 hrs.
2. Phase 2: Migrate `HFShell`, `HFTable`, `HFKpiTile`, `HFFilter`, `HFTabs`. ~2 hrs.
3. Phase 3: Sweep page-level components (overview, runs, run-detail, etc.). ~2 hrs.
4. Phase 4: Drop `force()`, remove `!important` from `hf-base`. ~30 min.

**Pays for itself when:** dark mode, density swap polish, or any other theme variation becomes a real ask.

**Effort:** ~half day total.

### 3. Split `HFRunDetail` into focused subcomponents
File is ~1900 lines in one function. Proposed extraction:
- `HFRunActions` — topbar buttons + action handlers
- `HFRunInFlightCard`
- `HFRunFailuresCard`
- `HFRunHistoryCard`
- `HFRunBooksCard`
- `useRunData(runId)` hook owning data + live fetch effects

Each becomes ~150-300 lines, independently reviewable, and `confirmDialog` / `ackDialog` state can live where it belongs. Not urgent — current code works — but this is the file most likely to harbor small bugs as it grows.

**Effort:** ~half day.

### 4. URL state on remaining pages
Run-detail persists filter/sort/page/tab to the URL. The runs list, overview filters, shop books, and urls/shops pages don't. Sharing a filtered URL works inconsistently.

**Effort:** ~1 hour (each page is small; the pattern is established).

### 5. Tab content fade/crossfade
Subtle transition when switching the General/History/Books tabs in run detail. Currently the swap is instant; a 150ms crossfade would feel more polished.

**Effort:** ~30 min.

### 6. Modal/overlay content review
The a11y audit covered focus management for all dialogs in `hf-overlays.jsx`, but the dialog content itself wasn't reviewed (validation, error handling, helper text, autofocus targets, autocomplete attributes on inputs).

**Effort:** ~1 hour.

### 7. Pages not yet reviewed in depth
- `hf-parser.jsx` (422 lines, never reviewed)
- `hf-details.jsx` (URL detail, issue detail) — got breadcrumb fixes but no content review
- `hf-more-details.jsx` (schedule detail, shop-book detail) — same
- `hf-other.jsx` (prices, cron, issues) — same
- `hf-shopbooks.jsx` — same

Each likely has the same kinds of issues we already fixed elsewhere, but at lower density.

**Effort:** ~1-2 hours per page, depending on issues found.

### 8. Better default ordering on `get_run_books_updated`
Currently orders by `ShopBook.title` alphabetically. Operators usually want most-changed-first or most-recently-changed-first. Either change the default or add a `sort` query param + UI control.

**Effort:** ~30 min.

### 9. Debug logging on unknown discover phases
`_PHASE_TO_SOURCE` in `queries.py` silently skips the source filter when `run.phase` doesn't match a known mapping. A `logger.debug("unknown phase: %s", run.phase)` would help future debugging.

**Effort:** 5 min.

### 10. Migration drops constraints by `None` name
`alembic/versions/f21086852374_add_created_run_id_to_shop_books.py:downgrade()` uses `op.drop_constraint(None, ...)`. Works while there's only one matching FK, but fragile. Naming the constraint explicitly (`fk_shop_books_created_run_id`) is cleaner.

**Effort:** 5 min (apply on next migration touching this table).

---

## Bigger pieces

### Dark mode
Tokens are designed for it (ink ramp, semantic soft/border/ink trios). Pairs naturally with the CSS custom properties migration — once tokens are CSS vars, dark mode becomes ~20 var overrides on `[data-theme="dark"]`. Until then, requires duplicating the entire token set.

**Effort:** ~1-2 days, mostly design pass on every accent + ink + shadow variant.

### Match phase
Linking `shop_books` → canonical `books` is mentioned in `CLAUDE.md` as "not yet implemented." That's product work, not polish — the actual scrape pipeline is incomplete without it.

**Effort:** unknown; design spec needed first.

---

## Notes for future maintainers

- **Toast infrastructure** (`window.HF_APP.toast`) is global — use it everywhere instead of inline error banners. Standard pattern: success toast on `.then()`, error toast on `.catch()`. See `hf-runs.jsx` action handlers for examples.
- **`HF_BUILD_PATH`** is exposed on `window` and is the canonical way to construct in-app URLs. Use `HFBreadcrumbLink` for breadcrumbs; for in-table links use the same pattern (real `href` + click-intercept with cmd/ctrl/shift fall-through).
- **Modal a11y is now centralized** in `HFModal`. New dialogs that wrap `HFModal` + `HFModalHead` automatically get focus trap, return focus, body scroll lock, and `aria-labelledby`. Don't roll your own.
- **Skeleton loaders** are the default for any loading state >300ms. Use `HFSkeleton` / `HFTableSkeleton` / `HFKpiStripSkeleton` instead of `"Loading…"` text.
- **Charts** (`HFAreaChart` / `HFBarChart` / `HFSparkBars`) accept a `label` prop that drives `aria-label`. Always pass it — defaults are generic.
