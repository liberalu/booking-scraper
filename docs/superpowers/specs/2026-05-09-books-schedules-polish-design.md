# Books + Schedules Polish — Design Spec

**Status:** Implemented
## Goal

Close the small but visible gaps in the existing Books and Schedules surfaces of the hifi dashboard, and adopt the newer canonical Book detail page. This is "Phase 1" of a larger Books/Schedules track; bigger items (book merge/unlink, manual book creation, schedule chain visualization) are deferred to their own specs.

## Scope

- Adopt the new `HFBook` (`hf-book.jsx`) on the production `/books/:id` route; delete the old `HFBookDetail` from `hf-books.jsx`.
- Apply UX-review fixes to `HFBook` (cover CLS, locale-correct prices, accessible URL link, line-length cap, language in meta, relative `last_seen_at`, ISBN copy-on-click, raw-enum fallback).
- Add server-side smart search to `GET /api/books`: ISBN-shaped input → exact match across `book_isbns`; otherwise title-substring + author-substring.
- Wire `DELETE /api/cron/{id}` from `HFScheduleDetail`. Backend strictly blocks (HTTP 409) when other schedules reference the target via `chain_to_id`; UI surfaces the dependent list with click-through to unlink them.
- Validate cron expressions on `POST /api/cron` and `PATCH /api/cron/{id}` using `croniter` (parse-only, 5-field).
- Verify the existing "Run history" tab on `HFScheduleDetail` works correctly; polish if rough.

## Non-Goals

- Book merge / unlink shop_book (Phase 4).
- Manual book creation (`data_source = manual`) (Phase 3).
- Chain visualization on the schedules list (Phase 2).
- Cron reachability checks or minimum-interval guards.
- Any change to `HFBooks` (the list page) beyond replacing client-side title-filter with the new server-side `?search=` parameter.
- Any redesign of the dialogs (`HFNewScheduleDialog`, `HFEditScheduleDialog`); only verifying the cron-422 error pathway surfaces correctly.

---

## Backend changes

### `book_scraper/dashboard/queries.py`

Extend `list_books(...)` with a `search: str | None = None` parameter. Inside:

```python
ISBN_RE = re.compile(r"^(?:\d{9}[\dX]|\d{13})$")

def list_books(session, *, search=None, ...):
    ...
    if search:
        normalized = search.strip().replace("-", "").replace(" ", "").upper()
        if ISBN_RE.fullmatch(normalized):
            query = query.join(BookIsbn).filter(BookIsbn.isbn == normalized)
        else:
            like = f"%{search.strip()}%"
            query = query.outerjoin(Book.authors).filter(
                or_(Book.title.ilike(like), Author.name.ilike(like))
            ).distinct()
    ...
```

Detection rule: strip dashes and spaces, uppercase, then match `^(\d{9}[\dX]|\d{13})$`. Anything else falls through to substring search on title and author name.

### `book_scraper/dashboard/routes/api.py`

**`GET /books`** — accept and forward a `search: str | None = None` query parameter to `list_books`.

**`POST /cron`, `PATCH /cron/{job_id}`** — validate the cron expression on `_CronJobBody.cron_expression` and `_CronJobPatch.cron_expression` (when present) using `croniter`. Validation lives in a small helper:

```python
from croniter import croniter

def _validate_cron(expression: str) -> None:
    parts = expression.strip().split()
    if len(parts) != 5 or not croniter.is_valid(expression):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid cron expression: {expression!r} (expected 5 fields)",
        )
```

The explicit length check enforces 5-field strictly — `croniter.is_valid` is permissive about 6/7-field inputs by default, which we don't want here. Both endpoints call `_validate_cron(body.cron_expression)` before any DB write.

**`DELETE /cron/{job_id}`** — new dependent check, before calling `delete_cron_job`:

```python
dependents = session.execute(
    select(CronJob.id, CronJob.shop_id, CronJob.phase, CronJob.strategy)
    .where(CronJob.chain_to_job_id == job_id)
).all()
if dependents:
    raise HTTPException(
        status_code=409,
        detail={
            "message": "Cannot delete: other schedules chain to this one.",
            "dependents": [
                {"id": d.id, "name": _format_job_name(session, d)}
                for d in dependents
            ],
        },
    )
```

`_format_job_name` matches the existing `f"{shop.name}.{phase}.{strategy or 'default'}"` convention used elsewhere.

### `pyproject.toml`

Add `croniter` to runtime deps if not already present.

---

## Frontend changes

### `book_scraper/dashboard/static/hifi/index.html`

- Add `<script type="text/babel" src="/static/hifi/hf-book.jsx"></script>` before the `hf-books.jsx` line (so `HFBook` is registered globally before the route map references it).
- Update the route map: `'book-detail': () => <HFBook nav={nav} goto={goto} params={params} />` (was `<HFBookDetail .../>`).

### `book_scraper/dashboard/static/hifi/hf-books.jsx`

- Delete the entire `HFBookDetail` function. Keep `HFBooks` (list) and the local `DataSourceBadge` definition (still used by `HFBooks` rows).
- In `HFBooks`:
  - Remove the client-side `q ? data.books.filter(...) : data.books` step.
  - Add `search` to the `URLSearchParams` sent to `/api/books`. Debounce `q` changes by 150ms before triggering the fetch (matches the existing search-debounce convention from `useHFFilters`).

### `book_scraper/dashboard/static/hifi/hf-book.jsx`

Apply the review fixes from the earlier review pass. Specifically:

| Fix | Change |
|---|---|
| Cover CLS | Set `aspectRatio: '2/3'` on the `<img>`; remove `height: 'auto'`. Add `loading="lazy"`. |
| Locale-correct prices | Replace `€${Number(s.price).toFixed(2)}` with `Intl.NumberFormat('lt-LT', {style:'currency', currency:'EUR'}).format(s.price)`. Helper hoisted to top of file. |
| Accessible URL column | Replace `<a>↗</a>` with `<a aria-label={\`Open at ${shop} (new tab)\`} title="Open in new tab" ...>` and widen the visible target (icon + text "Visit" or padded chip ≥ 32×32px). |
| Description line length | Wrap description block in `style={{ maxWidth: '70ch' }}`. |
| Language in meta | Add `book.language` (when present) to the meta-line array between `format` and `pages`. |
| Relative `last_seen_at` | Format with a small `formatRelative(iso)` helper inside `<time dateTime={iso}>{relative}</time>`. Reuse pattern from `hf-runs.jsx` if a similar helper exists; otherwise add one in this file. |
| ISBN copy-on-click | Convert ISBN chips from `<span>` to `<button>` with `onClick={() => navigator.clipboard.writeText(isbn).then(() => toast('Copied'))}`. Reuse existing toast mechanism if present; otherwise use a small inline toast. |
| `DataSourceBadge` fallback | Map unmapped values to `{ label: 'Unknown', tone: 'neutral' }` instead of leaking `value`. |

The component's data fetch and overall structure are unchanged.

### `book_scraper/dashboard/static/hifi/hf-more-details.jsx`

In `HFScheduleDetail`:

- Add a "Delete" button (danger variant) to the page-head actions, alongside the existing edit/toggle controls.
- Click opens a confirmation modal: "Delete schedule `<name>`? This cannot be undone."
- On confirm: `await fetch(\`/api/cron/${jobId}\`, { method: 'DELETE' })`.
- Response handling:
  - `200` → `goto('cron')`, toast `Schedule deleted`.
  - `409` → modal stays open, replaces confirmation copy with: "Cannot delete — these schedules chain to this one:" followed by a list of `{ id, name }` rendered as buttons that call `goto('schedule-detail', { id })`. The "Delete" button on the modal becomes disabled until dismissed.
  - Other → modal shows `Error: <detail>` with a Retry button.

### `book_scraper/dashboard/static/hifi/hf-overlays.jsx`

No new component. Verify (and adjust if needed) that the existing `error` state in `HFNewScheduleDialog` and `HFEditScheduleDialog` correctly surfaces a 422 `detail` string from the cron-validation pathway. The current code reads `d.detail || \`Error ${resp.status}\`` which already handles the FastAPI shape, so this should be a no-op verification.

---

## Data flow — delete-with-dependents

```
HFScheduleDetail "Delete" click
  → confirm modal (initial state)
    → DELETE /api/cron/{id}
      ├── 200 → goto('cron'); toast "Schedule deleted"
      ├── 409 → modal switches to "blocked" state, lists dependents,
      │         each with click-through to that schedule's detail
      │         (operator unlinks them one by one, then retries the delete)
      └── 5xx / network → modal shows error with Retry button
```

Once the operator has unlinked every dependent (via `HFEditScheduleDialog` on each dependent's detail page) the original schedule's delete will succeed.

## Error handling

- Backend: cron parse failure → 422 with `detail` string. Chain-dependents present → 409 with `detail = {message, dependents}`. Missing job → 404 (existing). Missing chain target → 404 (existing).
- Frontend: every error path renders inline. Transient/general errors via toast; the delete-conflict path is in-modal so the dependent list stays visible and actionable. No silent failures.

## Testing

### Unit (no DB)
- `_validate_cron`: valid 5-field expressions pass; malformed strings raise 422; 6-field expressions are rejected by the explicit length check; whitespace variations (extra spaces, leading/trailing) are normalized.
- `list_books` ISBN detection: `"9786094661099"`, `"978-609-466-1099"`, `"097522980X"` all match the ISBN branch; `"Tolkien"`, `"123"` (too short), `"abc12345678"` go to the substring branch.

### Integration (real PostgreSQL on port 5433)
- `POST /api/cron` with `cron_expression="not a cron"` → 422; no row created.
- `PATCH /api/cron/{id}` with `cron_expression="not a cron"` → 422; existing row unchanged.
- `DELETE /api/cron/{id}` with no dependents → 200, row gone.
- `DELETE /api/cron/{id}` with one dependent → 409, body lists dependent, both rows still exist.
- After unlinking the dependent (`PATCH ... clear_chain=true`), `DELETE` succeeds.
- `GET /api/books?search=<known-isbn>` → 1 result, the matching book.
- `GET /api/books?search=<known-isbn-with-dashes>` → 1 result, same book.
- `GET /api/books?search=tolkien` → results contain books whose title or author name match.
- `GET /api/books?search=` (empty) → behaves identically to no parameter.

### Smoke after deploy
- `uv run pytest tests/integration/test_dashboard_routes.py -v` — extended with the new contract cases above.
- Manual click-through: visit `/books/<id>` (verify new HFBook), search by ISBN on `/books`, attempt to delete a schedule with dependents (verify the 409 list renders and links work), unlink + retry delete.

## Out of scope (deferred phases)

- **Phase 2** — Chain visualization on the schedules list (S2): grouping/badging/tree rendering of `chain_to_id` relationships in `HFCron`.
- **Phase 3** — Manual book creation (B4): form, endpoint, ISBN-collision rules, audit.
- **Phase 4** — Book merge / unlink shop_book (B3): data-model and operator-workflow design for combining canonical books and detaching mis-linked shop_books.
