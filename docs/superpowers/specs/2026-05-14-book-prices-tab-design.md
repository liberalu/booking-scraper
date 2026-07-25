# Book Prices Tab — Design Spec

**Status:** Implemented
## Goal

Replace the `HFBookPricesStub` placeholder in the Book detail page with a real Prices tab showing a 30-day multi-line price chart (one line per shop) plus three KPI cards.

## Scope

- New query: `get_book_price_history(session, book_id)` in `book_scraper/dashboard/queries.py`
- New route: `GET /api/books/{book_id}/prices` in `book_scraper/dashboard/routes/api.py`
- New frontend component: `HFBookPrices` + `MultiLineChart` in `book_scraper/dashboard/static/hifi/hf-book.jsx`
- Integration tests for the new endpoint
- No schema changes, no new models

## Non-Goals

- Time window toggle (30d/90d/all-time) — deferred
- Per-shop isolate/filter interactions on the chart
- Exporting price data
- Price alerts

---

## Backend

### Query: `get_book_price_history`

Add to `book_scraper/dashboard/queries.py`:

```python
def get_book_price_history(
    session: Session, book_id: int, days: int = 30
) -> list[dict[str, Any]]:
    """Return 30-day daily price series for every shop linked to book_id.

    One dict per shop: {"shop": str, "series": [{"date": "YYYY-MM-DD", "price": float}]}
    Series is sorted ascending by date. Days with no scrape are omitted (sparse).
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

    # Group into per-shop series
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

### Route: `GET /api/books/{book_id}/prices`

Add to `book_scraper/dashboard/routes/api.py` (near the other `/books` routes):

```python
@router.get("/books/{book_id}/prices")
def api_book_prices(
    book_id: int, session: Session = Depends(get_db)
) -> dict[str, Any]:
    from book_scraper.dashboard.queries import get_book_price_history, book_detail

    if book_detail(session, book_id) is None:
        raise HTTPException(status_code=404, detail="Book not found")
    series = get_book_price_history(session, book_id)
    return {"book_id": book_id, "series": series}
```

**Response shape:**
```json
{
  "book_id": 1,
  "series": [
    {
      "shop": "humanitas",
      "series": [
        {"date": "2026-04-15", "price": 19.9},
        {"date": "2026-04-16", "price": 19.9}
      ]
    }
  ]
}
```

---

## Frontend

### Component: `HFBookPrices`

Replace `HFBookPricesStub` in `hf-book.jsx` with this component:

```jsx
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
    return <HFCard title="Price history" sub="Last 30 days"><div style={{padding:20}}><HFSkeleton h={200}/></div></HFCard>;
  }

  const series = data?.series || [];
  const allPrices = series.flatMap(s => s.series.map(p => p.price));

  if (series.length === 0 || allPrices.length === 0) {
    return (
      <HFCard title="Price history" sub="Last 30 days">
        <div style={{padding:32}}>
          <HFEmptyState title="No price history yet" sub="Prices will appear here once scraping has run for this book."/>
        </div>
      </HFCard>
    );
  }

  const lowestNow = Math.min(...(book.shops || []).map(s => Number(s.price)).filter(p => p > 0));
  const lowestShop = (book.shops || []).find(s => Math.abs(Number(s.price) - lowestNow) < 0.001)?.shop;
  const allTime = Math.min(...allPrices);
  const avg30d = allPrices.reduce((a, b) => a + b, 0) / allPrices.length;

  const fmt = new Intl.NumberFormat('lt-LT', { style: 'currency', currency: 'EUR' });

  return (
    <>
      <HFKpiStrip items={[
        { label: 'Lowest now',   value: isFinite(lowestNow) ? fmt.format(lowestNow) : '—',
          delta: lowestShop ? <span style={{color:'var(--hf-ok-ink)'}}>{lowestShop}</span> : null,
          tone: 'ok' },
        { label: '30d average',  value: fmt.format(avg30d),
          delta: <span style={{color:'var(--hf-ink3)'}}>{series.length} shop{series.length!==1?'s':''}</span> },
        { label: 'All-time low', value: fmt.format(allTime),
          delta: <span style={{color:'var(--hf-ink3)'}}>in window</span> },
      ]} />

      <HFCard title="30-day price comparison" sub="one line per shop · daily max price"
              style={{marginBottom:'var(--hf-gap)'}}>
        <div style={{padding:'var(--hf-card-p)'}}>
          <MultiLineChart series={series} h={240} shopColors={SHOP_COLORS}/>
          <div style={{display:'flex', flexWrap:'wrap', gap:12, marginTop:12}}>
            {series.map((s, i) => (
              <span key={s.shop} style={{display:'inline-flex', alignItems:'center', gap:6, fontSize:12, color:'var(--hf-ink2)'}}>
                <span style={{width:12, height:3, borderRadius:2,
                  background: SHOP_COLORS[i % SHOP_COLORS.length] === 'var(--hf-accent)'
                    ? 'var(--hf-accent)' : SHOP_COLORS[i % SHOP_COLORS.length],
                  display:'inline-block', flexShrink:0}}/>
                {s.shop}
              </span>
            ))}
          </div>
        </div>
      </HFCard>
    </>
  );
}
```

### Component: `MultiLineChart`

New inline SVG chart component in `hf-book.jsx`:

```jsx
function MultiLineChart({ series, h = 240, shopColors }) {
  if (!series.length) return null;

  // Collect all dates across all series, sorted
  const allDates = [...new Set(series.flatMap(s => s.series.map(p => p.date)))].sort();
  if (!allDates.length) return null;

  const allPrices = series.flatMap(s => s.series.map(p => p.price));
  const minP = Math.min(...allPrices);
  const maxP = Math.max(...allPrices);
  const priceRange = maxP - minP || 1;

  const W = 100; // % width (viewBox units)
  const PAD_L = 8; const PAD_R = 4; const PAD_T = 8; const PAD_B = 20;
  const chartW = W - PAD_L - PAD_R;
  const chartH = h - PAD_T - PAD_B;

  const xOf = (date) => PAD_L + (allDates.indexOf(date) / Math.max(allDates.length - 1, 1)) * chartW;
  const yOf = (price) => PAD_T + (1 - (price - minP) / priceRange) * chartH;

  return (
    <svg viewBox={`0 0 ${W} ${h}`} style={{width:'100%', height:h, overflow:'visible'}}
         preserveAspectRatio="none">
      {/* Y-axis gridlines */}
      {[0, 0.25, 0.5, 0.75, 1].map(t => {
        const y = PAD_T + t * chartH;
        const price = maxP - t * priceRange;
        return (
          <g key={t}>
            <line x1={PAD_L} y1={y} x2={W - PAD_R} y2={y}
                  stroke="var(--hf-border-faint)" strokeWidth="0.3"/>
            <text x={PAD_L - 1} y={y + 1} textAnchor="end"
                  style={{fontSize:'2.5px', fill:'var(--hf-ink4)', fontFamily:'var(--hf-mono)'}}>
              {price.toFixed(2)}
            </text>
          </g>
        );
      })}

      {/* Lines */}
      {series.map((s, i) => {
        const color = shopColors[i % shopColors.length];
        const resolved = color === 'var(--hf-accent)' ? 'var(--hf-accent)' : color;
        const pts = s.series.filter(p => allDates.includes(p.date));
        if (pts.length < 2) return null;
        const d = pts.map((p, j) =>
          `${j === 0 ? 'M' : 'L'}${xOf(p.date).toFixed(2)},${yOf(p.price).toFixed(2)}`
        ).join(' ');
        return (
          <path key={s.shop} d={d} fill="none"
                stroke={resolved} strokeWidth="0.8" strokeLinecap="round" strokeLinejoin="round"
                opacity="0.9"/>
        );
      })}

      {/* X-axis: first + last date labels */}
      {allDates.length > 1 && <>
        <text x={PAD_L} y={h - 2} textAnchor="start"
              style={{fontSize:'2.5px', fill:'var(--hf-ink4)', fontFamily:'var(--hf-mono)'}}>
          {allDates[0]}
        </text>
        <text x={W - PAD_R} y={h - 2} textAnchor="end"
              style={{fontSize:'2.5px', fill:'var(--hf-ink4)', fontFamily:'var(--hf-mono)'}}>
          {allDates[allDates.length - 1]}
        </text>
      </>}
    </svg>
  );
}
```

### Wiring

In the tab dispatcher inside `HFBook`, change:
```jsx
{tab === 'prices' && <HFBookPricesStub />}
```
to:
```jsx
{tab === 'prices' && <HFBookPrices book={book} />}
```

Also update the tab dispatcher to pass `book` (it already has it in scope).

---

## Testing

### Integration tests (`tests/integration/test_books_api.py`)

```python
def test_book_prices_empty_for_book_without_shops(client, db_session):
    from book_scraper.db.models import Book
    book = Book(data_source="shop_inferred", title="PriceTest NoShop", year=2020)
    db_session.add(book); db_session.commit()
    resp = client.get(f"/api/books/{book.id}/prices")
    assert resp.status_code == 200
    assert resp.json()["series"] == []

def test_book_prices_returns_series_for_linked_shop_books(client, db_session):
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal
    from book_scraper.db.models import Book, Price, Shop, ShopBook
    from sqlalchemy import select
    shop = db_session.execute(select(Shop).where(Shop.name == "vaga")).scalar_one_or_none()
    if shop is None:
        shop = Shop(name="vaga", base_url="https://vaga.lt"); db_session.add(shop); db_session.flush()
    book = Book(data_source="shop_inferred", title="PriceTest WithShop", year=2020)
    db_session.add(book); db_session.flush()
    sb = ShopBook(shop_id=shop.id, url="https://vaga.lt/pt", title="PriceTest WithShop",
                  price=Decimal("19.90"), in_stock=True, book_id=book.id)
    db_session.add(sb); db_session.flush()
    db_session.add(Price(shop_book_id=sb.id, price=Decimal("19.90"),
                         scraped_at=datetime.now(UTC) - timedelta(days=1)))
    db_session.add(Price(shop_book_id=sb.id, price=Decimal("18.50"),
                         scraped_at=datetime.now(UTC) - timedelta(days=2)))
    db_session.commit()
    resp = client.get(f"/api/books/{book.id}/prices")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["series"]) == 1
    assert data["series"][0]["shop"] == "vaga"
    assert len(data["series"][0]["series"]) == 2

def test_book_prices_404_for_unknown_book(client):
    resp = client.get("/api/books/999999999/prices")
    assert resp.status_code == 404

def test_book_prices_excludes_data_older_than_30_days(client, db_session):
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal
    from book_scraper.db.models import Book, Price, Shop, ShopBook
    from sqlalchemy import select
    shop = db_session.execute(select(Shop).where(Shop.name == "vaga")).scalar_one_or_none()
    if shop is None:
        shop = Shop(name="vaga", base_url="https://vaga.lt"); db_session.add(shop); db_session.flush()
    book = Book(data_source="shop_inferred", title="PriceTest Old", year=2020)
    db_session.add(book); db_session.flush()
    sb = ShopBook(shop_id=shop.id, url="https://vaga.lt/old", title="PriceTest Old",
                  price=Decimal("15.00"), in_stock=True, book_id=book.id)
    db_session.add(sb); db_session.flush()
    # One recent, one old
    db_session.add(Price(shop_book_id=sb.id, price=Decimal("15.00"),
                         scraped_at=datetime.now(UTC) - timedelta(days=5)))
    db_session.add(Price(shop_book_id=sb.id, price=Decimal("12.00"),
                         scraped_at=datetime.now(UTC) - timedelta(days=45)))
    db_session.commit()
    resp = client.get(f"/api/books/{book.id}/prices")
    assert resp.status_code == 200
    series = resp.json()["series"][0]["series"]
    prices = [p["price"] for p in series]
    assert 12.0 not in prices
    assert 15.0 in prices
```

---

## Notes

- `MultiLineChart` uses `viewBox` with `preserveAspectRatio="none"` — SVG stretches to fill the card width. Font sizes are in SVG user units (~2.5px at ~100 unit wide viewBox).
- Y-axis shows price values at 5 gridlines. X-axis shows first + last date.
- Sparse series (days with no scrape) show as gaps / broken lines — this is correct.
- `SHOP_COLORS` is already defined in `hf-book.jsx` from the Listings tab work.
- `HFKpiStrip` is already available globally from `hf-ui.jsx`.
- `HFSkeleton` is used for loading state — already available globally.
