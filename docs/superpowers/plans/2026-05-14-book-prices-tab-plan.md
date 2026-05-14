# Book Prices Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `HFBookPricesStub` placeholder with a real Prices tab showing a 30-day multi-line price chart (one line per shop) plus KPI cards, backed by a new `GET /api/books/{id}/prices` endpoint.

**Architecture:** New `get_book_price_history(session, book_id)` query in `queries.py` joins `ShopBook → Price`, aggregates to daily max per shop for the last 30 days. New `/api/books/{id}/prices` route calls it. `HFBookPrices` + inline `MultiLineChart` SVG component replace the stub in `hf-book.jsx` and fetch lazily when the Prices tab is clicked.

**Tech Stack:** Python/SQLAlchemy/FastAPI for backend; React 18 Babel CDN + inline SVG for frontend. No new libraries. No DB migrations.

**Spec:** `docs/superpowers/specs/2026-05-14-book-prices-tab-design.md`

---

## File Structure

| File | Change |
|---|---|
| `book_scraper/dashboard/queries.py` | Add `get_book_price_history` after existing `get_price_history` (line ~1910) |
| `book_scraper/dashboard/routes/api.py` | Add `GET /api/books/{book_id}/prices` after `api_book_detail` (line ~1860) |
| `tests/integration/test_books_api.py` | Append 4 new integration tests |
| `book_scraper/dashboard/static/hifi/hf-book.jsx` | Replace `HFBookPricesStub` with `MultiLineChart` + `HFBookPrices`; update dispatcher |

---

## Task 1: `get_book_price_history` query

**Files:**
- Modify: `book_scraper/dashboard/queries.py` (after line ~1910, after `get_price_history`)
- Test: `tests/integration/test_books_api.py` (append)

- [ ] **Step 1: Append failing integration tests**

Open `tests/integration/test_books_api.py` and append at the end:

```python
# ----- Price history (Task 1/2) --------------------------------------------


def test_book_prices_empty_for_book_without_shops(client, db_session):
    from book_scraper.db.models import Book

    book = Book(data_source="shop_inferred", title="PriceTest NoShop A", year=2020)
    db_session.add(book)
    db_session.commit()

    resp = client.get(f"/api/books/{book.id}/prices")
    assert resp.status_code == 200
    assert resp.json()["series"] == []


def test_book_prices_returns_series_for_linked_shop_books(client, db_session):
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from sqlalchemy import select

    from book_scraper.db.models import Book, Price, Shop, ShopBook

    shop = db_session.execute(
        select(Shop).where(Shop.name == "vaga")
    ).scalar_one_or_none()
    if shop is None:
        shop = Shop(name="vaga", base_url="https://vaga.lt")
        db_session.add(shop)
        db_session.flush()

    book = Book(data_source="shop_inferred", title="PriceTest WithShop B", year=2020)
    db_session.add(book)
    db_session.flush()

    sb = ShopBook(
        shop_id=shop.id, url="https://vaga.lt/ptb",
        title="PriceTest WithShop B", price=Decimal("19.90"),
        in_stock=True, book_id=book.id,
    )
    db_session.add(sb)
    db_session.flush()

    db_session.add(Price(
        shop_book_id=sb.id, price=Decimal("19.90"),
        scraped_at=datetime.now(UTC) - timedelta(days=1),
    ))
    db_session.add(Price(
        shop_book_id=sb.id, price=Decimal("18.50"),
        scraped_at=datetime.now(UTC) - timedelta(days=2),
    ))
    db_session.commit()

    resp = client.get(f"/api/books/{book.id}/prices")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"]) == 1
    assert data["series"][0]["shop"] == "vaga"
    assert len(data["series"][0]["series"]) == 2  # two distinct days


def test_book_prices_404_for_unknown_book(client):
    resp = client.get("/api/books/999999999/prices")
    assert resp.status_code == 404


def test_book_prices_excludes_data_older_than_30_days(client, db_session):
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from sqlalchemy import select

    from book_scraper.db.models import Book, Price, Shop, ShopBook

    shop = db_session.execute(
        select(Shop).where(Shop.name == "vaga")
    ).scalar_one_or_none()
    if shop is None:
        shop = Shop(name="vaga", base_url="https://vaga.lt")
        db_session.add(shop)
        db_session.flush()

    book = Book(data_source="shop_inferred", title="PriceTest OldData C", year=2020)
    db_session.add(book)
    db_session.flush()

    sb = ShopBook(
        shop_id=shop.id, url="https://vaga.lt/ptc",
        title="PriceTest OldData C", price=Decimal("15.00"),
        in_stock=True, book_id=book.id,
    )
    db_session.add(sb)
    db_session.flush()

    db_session.add(Price(
        shop_book_id=sb.id, price=Decimal("15.00"),
        scraped_at=datetime.now(UTC) - timedelta(days=5),   # recent
    ))
    db_session.add(Price(
        shop_book_id=sb.id, price=Decimal("12.00"),
        scraped_at=datetime.now(UTC) - timedelta(days=45),  # old, excluded
    ))
    db_session.commit()

    resp = client.get(f"/api/books/{book.id}/prices")
    assert resp.status_code == 200
    series = resp.json()["series"][0]["series"]
    prices = [p["price"] for p in series]
    assert 12.0 not in prices
    assert 15.0 in prices
```

- [ ] **Step 2: Run tests to confirm they fail**

```
uv run pytest tests/integration/test_books_api.py::test_book_prices_empty_for_book_without_shops tests/integration/test_books_api.py::test_book_prices_returns_series_for_linked_shop_books tests/integration/test_books_api.py::test_book_prices_404_for_unknown_book tests/integration/test_books_api.py::test_book_prices_excludes_data_older_than_30_days -v 2>&1 | tail -10
```

Expected: 4 failures — endpoint doesn't exist yet (404 or connection error).

- [ ] **Step 3: Add `get_book_price_history` to `queries.py`**

Open `book_scraper/dashboard/queries.py`. Find `def get_price_history` (around line 1903). Add the new function **immediately after** `get_price_history` ends (after the closing `return` of that function, before `def get_price_changes`):

```python
def get_book_price_history(
    session: Session, book_id: int, days: int = 30
) -> list[dict[str, Any]]:
    """Return 30-day daily price series for every shop linked to book_id.

    Returns [{"shop": str, "series": [{"date": "YYYY-MM-DD", "price": float}]}].
    Series sorted ascending by date. Days with no scrape are omitted (sparse is fine).
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from book_scraper.db.models import Price, Shop, ShopBook

    cutoff = datetime.now(UTC) - timedelta(days=days)

    rows = session.execute(
        select(
            Shop.name.label("shop"),
            func.date_trunc("day", Price.scraped_at).label("day"),
            func.max(Price.price).label("price"),
        )
        .join(ShopBook, Price.shop_book_id == ShopBook.id)
        .join(Shop, ShopBook.shop_id == Shop.id)
        .where(ShopBook.book_id == book_id)
        .where(Price.scraped_at >= cutoff)
        .group_by(Shop.name, func.date_trunc("day", Price.scraped_at))
        .order_by(Shop.name, func.date_trunc("day", Price.scraped_at))
    ).all()

    series: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        shop = row.shop
        if shop not in series:
            series[shop] = []
        series[shop].append({
            "date": row.day.strftime("%Y-%m-%d"),
            "price": float(row.price),
        })

    return [{"shop": shop, "series": pts} for shop, pts in series.items()]
```

- [ ] **Step 4: Add route to `api.py`**

Open `book_scraper/dashboard/routes/api.py`. Find `def api_book_detail` (around line 1851). Add the new route **immediately after** `api_book_detail` ends (after its `return detail` line, before `@router.get("/shops")`):

```python
@router.get("/books/{book_id}/prices")
def api_book_prices(
    book_id: int, session: Session = Depends(get_db)
) -> dict[str, Any]:
    from book_scraper.dashboard.queries import book_detail, get_book_price_history

    if book_detail(session, book_id) is None:
        raise HTTPException(status_code=404, detail="Book not found")
    series = get_book_price_history(session, book_id)
    return {"book_id": book_id, "series": series}
```

- [ ] **Step 5: Run the 4 tests**

```
uv run pytest tests/integration/test_books_api.py::test_book_prices_empty_for_book_without_shops tests/integration/test_books_api.py::test_book_prices_returns_series_for_linked_shop_books tests/integration/test_books_api.py::test_book_prices_404_for_unknown_book tests/integration/test_books_api.py::test_book_prices_excludes_data_older_than_30_days -v 2>&1 | tail -10
```

Expected: 4 passed.

- [ ] **Step 6: Run full books API suite to check no regressions**

```
uv run pytest tests/integration/test_books_api.py -q 2>&1 | tail -5
```

Expected: all pass.

- [ ] **Step 7: Ruff check on changed files**

```
uv run ruff check book_scraper/dashboard/queries.py book_scraper/dashboard/routes/api.py 2>&1 | tail -5
```

Expected: clean (or only pre-existing errors not in the new code).

- [ ] **Step 8: Commit**

```bash
git add book_scraper/dashboard/queries.py book_scraper/dashboard/routes/api.py tests/integration/test_books_api.py
git commit -m "feat(api): GET /api/books/{id}/prices — 30-day daily price series per shop"
```

---

## Task 2: `MultiLineChart` + `HFBookPrices` frontend components

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-book.jsx`

No Python test framework for JSX — verification is rebuild + manual check.

- [ ] **Step 1: Read `hf-book.jsx` to find `HFBookPricesStub`**

Locate the `HFBookPricesStub` function (around line 256) and the dispatcher line `{tab === 'prices' && <HFBookPricesStub />}` (around line 488).

- [ ] **Step 2: Replace `HFBookPricesStub` with `MultiLineChart` + `HFBookPrices`**

Delete the entire `HFBookPricesStub` function. In its place, insert these two functions:

```jsx
function MultiLineChart({ series, h, shopColors }) {
  if (!series || !series.length) return null;

  const allDates = [...new Set(series.flatMap(s => s.series.map(p => p.date)))].sort();
  if (!allDates.length) return null;

  const allPrices = series.flatMap(s => s.series.map(p => p.price));
  const minP = Math.min(...allPrices);
  const maxP = Math.max(...allPrices);
  const priceRange = maxP - minP || 1;

  const W = 100;
  const PAD_L = 8, PAD_R = 4, PAD_T = 8, PAD_B = 20;
  const chartW = W - PAD_L - PAD_R;
  const chartH = h - PAD_T - PAD_B;

  const xOf = date => PAD_L + (allDates.indexOf(date) / Math.max(allDates.length - 1, 1)) * chartW;
  const yOf = price => PAD_T + (1 - (price - minP) / priceRange) * chartH;

  return (
    <svg viewBox={`0 0 ${W} ${h}`}
         style={{ width: '100%', height: h, overflow: 'visible' }}
         preserveAspectRatio="none">
      {/* Gridlines + Y-axis labels */}
      {[0, 0.25, 0.5, 0.75, 1].map(t => {
        const y = PAD_T + t * chartH;
        const price = maxP - t * priceRange;
        return (
          <g key={t}>
            <line x1={PAD_L} y1={y} x2={W - PAD_R} y2={y}
                  stroke="var(--hf-border-faint)" strokeWidth="0.3"/>
            <text x={PAD_L - 1} y={y + 1} textAnchor="end"
                  style={{ fontSize: '2.5px', fill: 'var(--hf-ink4)', fontFamily: 'var(--hf-mono)' }}>
              {price.toFixed(2)}
            </text>
          </g>
        );
      })}

      {/* One line per shop */}
      {series.map((s, i) => {
        const raw = shopColors[i % shopColors.length];
        const color = raw === 'var(--hf-accent)' ? 'var(--hf-accent)' : raw;
        const pts = s.series.filter(p => allDates.includes(p.date));
        if (pts.length < 2) return null;
        const d = pts.map((p, j) =>
          `${j === 0 ? 'M' : 'L'}${xOf(p.date).toFixed(2)},${yOf(p.price).toFixed(2)}`
        ).join(' ');
        return (
          <path key={s.shop} d={d} fill="none"
                stroke={color} strokeWidth="0.8"
                strokeLinecap="round" strokeLinejoin="round" opacity="0.9"/>
        );
      })}

      {/* X-axis: first + last date */}
      {allDates.length > 1 && <>
        <text x={PAD_L} y={h - 2} textAnchor="start"
              style={{ fontSize: '2.5px', fill: 'var(--hf-ink4)', fontFamily: 'var(--hf-mono)' }}>
          {allDates[0]}
        </text>
        <text x={W - PAD_R} y={h - 2} textAnchor="end"
              style={{ fontSize: '2.5px', fill: 'var(--hf-ink4)', fontFamily: 'var(--hf-mono)' }}>
          {allDates[allDates.length - 1]}
        </text>
      </>}
    </svg>
  );
}

function HFBookPrices({ book }) {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch(`/api/books/${book.id}/prices`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [book.id]);

  if (loading) {
    return (
      <HFCard title="Price history" sub="Last 30 days">
        <div style={{ padding: 20 }}><HFSkeleton h={200} /></div>
      </HFCard>
    );
  }

  const series = data?.series || [];
  const allPrices = series.flatMap(s => s.series.map(p => p.price));

  if (!series.length || !allPrices.length) {
    return (
      <HFCard title="Price history" sub="Last 30 days">
        <div style={{ padding: 32 }}>
          <HFEmptyState
            title="No price history yet"
            sub="Prices will appear here once scraping has run for this book."
          />
        </div>
      </HFCard>
    );
  }

  const fmt = new Intl.NumberFormat('lt-LT', { style: 'currency', currency: 'EUR' });
  const currentPrices = (book.shops || [])
    .map(s => Number(s.price))
    .filter(p => Number.isFinite(p) && p > 0);
  const lowestNow = currentPrices.length ? Math.min(...currentPrices) : null;
  const lowestShop = lowestNow != null
    ? (book.shops || []).find(s => Math.abs(Number(s.price) - lowestNow) < 0.001)?.shop
    : null;
  const allTime = Math.min(...allPrices);
  const avg30d = allPrices.reduce((a, b) => a + b, 0) / allPrices.length;

  return (
    <>
      <HFKpiStrip items={[
        {
          label: 'Lowest now',
          value: lowestNow != null ? fmt.format(lowestNow) : '—',
          delta: lowestShop
            ? <span style={{ color: 'var(--hf-ok-ink)' }}>{lowestShop}</span>
            : null,
          tone: 'ok',
        },
        {
          label: '30d average',
          value: fmt.format(avg30d),
          delta: <span style={{ color: 'var(--hf-ink3)' }}>
            {series.length} shop{series.length !== 1 ? 's' : ''}
          </span>,
        },
        {
          label: 'All-time low',
          value: fmt.format(allTime),
          delta: <span style={{ color: 'var(--hf-ink3)' }}>in window</span>,
        },
      ]} />

      <HFCard
        title="30-day price comparison"
        sub="one line per shop · daily max price"
        style={{ marginBottom: 'var(--hf-gap)' }}
      >
        <div style={{ padding: 'var(--hf-card-p)' }}>
          <MultiLineChart series={series} h={240} shopColors={SHOP_COLORS} />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 12 }}>
            {series.map((s, i) => {
              const raw = SHOP_COLORS[i % SHOP_COLORS.length];
              const color = raw === 'var(--hf-accent)' ? 'var(--hf-accent)' : raw;
              return (
                <span key={s.shop} style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  fontSize: 12, color: 'var(--hf-ink2)',
                }}>
                  <span style={{
                    width: 12, height: 3, borderRadius: 2,
                    background: color,
                    display: 'inline-block', flexShrink: 0,
                  }} />
                  {s.shop}
                </span>
              );
            })}
          </div>
        </div>
      </HFCard>
    </>
  );
}
```

- [ ] **Step 3: Update the tab dispatcher**

Find and replace:
```jsx
{tab === 'prices'    && <HFBookPricesStub />}
```
with:
```jsx
{tab === 'prices'    && <HFBookPrices book={book} />}
```

- [ ] **Step 4: Rebuild dashboard**

```bash
HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy="" ALL_PROXY="" all_proxy="" docker compose build dashboard && docker compose up -d dashboard
```

- [ ] **Step 5: Verify in container**

```bash
docker exec book-scraper-dashboard-1 grep -c 'MultiLineChart\|HFBookPrices' /app/book_scraper/dashboard/static/hifi/hf-book.jsx
```

Expected: 4+ (both functions defined + both used).

Confirm `HFBookPricesStub` is gone:
```bash
docker exec book-scraper-dashboard-1 grep -c 'HFBookPricesStub' /app/book_scraper/dashboard/static/hifi/hf-book.jsx
```

Expected: 0.

- [ ] **Step 6: Manual browser verification**

Open `http://localhost:8000/books` → pick a book that has shops (check `/api/books?has_shops=true&per_page=1` to find one) → click the Prices tab.

Check:
- If the book has price history: chart renders with one colored line per shop, gridlines, date labels, KPI strip shows lowest/average/all-time.
- If no price history: empty state "No price history yet".
- Loading skeleton appears briefly before data loads.
- No JS console errors.

- [ ] **Step 7: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-book.jsx
git commit -m "feat(dashboard): Prices tab — MultiLineChart + 30d KPIs"
```

---

## Task 3: Final smoke

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest tests/ -q --tb=no 2>&1 | tail -5
```

Expected: all pass (810+ passing).

- [ ] **Step 2: Check no ruff errors in changed files**

```bash
uv run ruff check book_scraper/dashboard/queries.py book_scraper/dashboard/routes/api.py 2>&1 | grep -v "^$" | tail -10
```

Expected: clean (no errors in the new functions).

- [ ] **Step 3: Verify API endpoint directly**

```bash
# Get a book id that has shops
BOOK_ID=$(curl -s 'http://localhost:8000/api/books?has_shops=true&per_page=1' | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['books'][0]['id'] if d['books'] else 'none')")
echo "Book ID: $BOOK_ID"
curl -s "http://localhost:8000/api/books/$BOOK_ID/prices" | python3 -c "import json,sys; d=json.load(sys.stdin); print('shops in price series:', len(d.get('series', []))); [print(' ', s['shop'], len(s['series']), 'days') for s in d.get('series', [])]"
```

Expected: shows shop names and number of days with price data.

---

## Notes for the implementer

- **`SHOP_COLORS`** is already defined at the top of `hf-book.jsx` (added in the book tabs work). Do NOT redefine it.
- **`HFKpiStrip`** is available globally from `hf-ui.jsx` — no import needed.
- **`HFSkeleton`** is available globally from `hf-ui.jsx` — no import needed.
- **`HFEmptyState`** is available globally — no import needed.
- **Docker BuildKit cache gotcha:** if `MultiLineChart` doesn't appear after rebuild, confirm with `docker exec book-scraper-dashboard-1 grep -c 'MultiLineChart' /app/book_scraper/dashboard/static/hifi/hf-book.jsx`. If 0, rebuild with `--no-cache`: `docker compose build --no-cache dashboard && docker compose up -d dashboard`.
- **Sparse series:** the chart draws each shop's line only between consecutive days that have data. Days with no scrape produce a gap. This is intentional — no interpolation.
- **Single data point per shop:** if only one day has data for a shop, the line has 0 length (skipped by `if pts.length < 2`). Only two or more days produce a visible line.
- **`func.date_trunc`** is PostgreSQL-specific. The test DB is real PostgreSQL on port 5433 — this works fine there.
