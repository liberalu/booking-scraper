// Hi-fi Book page — logical book aggregating ShopBook entries across multiple shops.
// "Book" is the canonical entity (identified by ISBN); each shop has its own ShopBook
// row pointing at it. This page shows: which shop listings are matched, when they
// were matched, how they were matched, and prices side-by-side.

function HFBook({ nav, goto, params }) {
  const HF = getHF();
  const bookId = params?.id;

  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [notFound, setNotFound] = React.useState(false);
  const [tab, setTab] = React.useState('overview');
  const [history, setHistory] = React.useState(null);

  React.useEffect(() => {
    if (!bookId) { setLoading(false); return; }
    setLoading(true);
    setNotFound(false);
    setHistory(null);
    fetch(`/api/books/${bookId}`)
      .then(r => { if (r.status === 404) { setNotFound(true); setLoading(false); return null; } return r.json(); })
      .then(d => { if (d) { setData(d); setLoading(false); } });
    fetch(`/api/books/${bookId}/prices`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setHistory(d.series || []); })
      .catch(() => {});
  }, [bookId]);

  if (loading) return <div style={{padding:40, color: HF.ink3, fontFamily: HF.sans}}>Loading…</div>;
  if (notFound || !data) return <div style={{padding:40, color: HF.ink3, fontFamily: HF.sans}}>Book not found.</div>;

  const primaryIsbn = data.isbns?.find(i => i.isbn_type === 'isbn13')?.isbn || data.isbns?.[0]?.isbn || '—';

  const book = {
    title: data.title,
    title_full: data.title_full,
    isbn: primaryIsbn,
    publisher: data.publisher,
    year: data.year,
    pages: data.pages,
    language: data.language,
    binding: data.format,
    cover_url: data.cover_url,
    description: data.description,
    firstMatched: '—',
    author: data.authors?.find(a => a.role === 'author')?.name || '',
    contributors: (data.authors || []).map(a => ({
      role: a.role.charAt(0).toUpperCase() + a.role.slice(1).replace('_', ' '),
      name: a.name,
    })),
  };

  function fmtRelative(iso) {
    if (!iso) return '—';
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  }

  // Build a lookup of {shop -> price ~30 days ago} from real history.
  // The Δ 30d column subtracts current price from this baseline.
  const historyByShop = {};
  (history || []).forEach(h => { historyByShop[h.shop] = h.series || []; });
  function prevPriceFor(shopName) {
    const series = historyByShop[shopName];
    if (!series || series.length === 0) return null;
    const cutoff = Date.now() - 30 * 24 * 3600 * 1000;
    // Pick the point closest to 30 days ago (or the oldest available point)
    let best = null;
    for (const p of series) {
      const t = new Date(p.date).getTime();
      if (t > cutoff) break;
      best = p;
    }
    if (!best) best = series[0];
    const v = parseFloat(best.price);
    return isNaN(v) ? null : v;
  }

  // One row per shop that lists this book. Field names mirror what
  // `book_detail` returns: shop, shop_book_id, url, price, in_stock,
  // last_seen_at, title, author, year, isbn, publisher, format, match_method.
  const shops = (data.shops || []).map(s => ({
    shop: s.shop,
    shopBookId: s.shop_book_id,
    sbStatus: s.in_stock ? 'active' : 'out',
    url: s.url,
    price: s.price != null ? parseFloat(s.price) : null,
    prev: prevPriceFor(s.shop),
    currency: 'EUR',
    stock: s.in_stock ? 'in stock' : 'out of stock',
    lastSeen: fmtRelative(s.last_seen_at),
    matchedAt: '—',
    method: s.match_method || '—',
    confidence: null,
    by: 'auto',
    // Per-shop metadata fields (for Metadata matrix + Contributors)
    shopAuthor: s.author,
    shopTitle: s.title,
    shopIsbn: s.isbn,
    shopYear: s.year,
    shopPublisher: s.publisher,
    shopFormat: s.format,
  }));

  const prices = shops.map(s => s.price).filter(p => p != null && !isNaN(p));
  const hasPrices = prices.length > 0;
  const lowest = hasPrices ? Math.min(...prices) : null;
  const highest = hasPrices ? Math.max(...prices) : null;
  const spread = hasPrices && lowest != null && highest != null ? (highest - lowest).toFixed(2) : null;
  const spreadPct = hasPrices && lowest != null && highest != null && highest > 0 ? (((highest - lowest) / highest) * 100).toFixed(1) : null;
  const lowestShop = hasPrices ? shops.find(s => s.price === lowest)?.shop : null;
  const highestShop = hasPrices ? shops.find(s => s.price === highest)?.shop : null;
  const matched = shops.filter(s => s.sbStatus !== 'pending').length;
  const pending = shops.filter(s => s.sbStatus === 'pending').length;

  const methodTone = { isbn:'ok', 'title+author':'warn', manual:'accent', slug:'neutral' };
  const sbTone     = { active:'ok', out:'warn', pending:'neutral', delisted:'neutral' };

  return (
    <HFShell {...nav} activePage="shop-books"
      title={<span style={{display:'flex', alignItems:'baseline', gap:12, flexWrap:'wrap'}}>
        <span>{book.title}</span>
        <HFPill tone="accent">matched · {matched} shops</HFPill>
        {pending > 0 && <HFPill tone="warn">{pending} pending review</HFPill>}
      </span>}
      subtitle={<span style={{fontSize:13}}>
        by <span style={{color:HF.ink2, fontWeight:500}}>{book.author}</span>
        {' · '}<span style={{fontFamily:HF.mono, color:HF.ink3}}>ISBN {book.isbn}</span>
        {' · '}{book.publisher} · {book.year}
        {' · '}<span style={{color:HF.ink3}}>first matched {book.firstMatched}</span>
      </span>}
      breadcrumb={<>
        <a href="#" onClick={(e)=>{e.preventDefault(); goto('shop-books');}} style={{color:HF.ink3, textDecoration:'none'}}>Catalog</a>
        <span style={{color:HF.ink5}}>/</span>
        <a href="#" onClick={(e)=>{e.preventDefault(); goto('shop-books');}} style={{color:HF.ink3, textDecoration:'none'}}>Books</a>
        <span style={{color:HF.ink5}}>/</span>
        <span style={{color:HF.ink, fontWeight:500, fontFamily:HF.mono}}>{book.isbn}</span>
      </>}
      actions={<>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.refresh}</span> Re-scrape all</HFButton>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.plus}</span> Add shop listing</HFButton>
        <HFButton variant="primary">Edit book</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Shops matched', value:`${matched}`, delta:<span style={{color:HF.ink3}}>of {shops.length} listings</span> },
        { label:'Lowest price',  value: lowest != null ? `€${lowest.toFixed(2)}` : '—', delta: lowestShop ? <span style={{color:HF.okInk}}>{lowestShop}</span> : null, tone:'ok' },
        { label:'Highest price', value: highest != null ? `€${highest.toFixed(2)}` : '—', delta: highestShop ? <span style={{color:HF.ink3}}>{highestShop}</span> : null },
        { label:'Spread',        value: spread != null ? `€${spread}` : '—', delta: spreadPct != null ? <span style={{color:HF.warnInk}}>{spreadPct}% range</span> : null, tone: spreadPct != null ? 'warn' : undefined },
        { label:'Last matched',  value: shops[0]?.lastSeen ?? '—', delta: shops[0] ? <span style={{color:HF.ink3}}>{shops[0].shop}</span> : null },
      ]}/>

      <HFCard style={{marginBottom:HF.gap}}>
        <div style={{padding:`0 ${HF.cardP}px`}}>
          <HFTabs active={tab} onChange={setTab} tabs={[
            { id:'overview',  label:'Listings', count: shops.length },
            { id:'prices',    label:'Prices' },
            { id:'metadata',  label:'Metadata' },
          ]}/>
        </div>
      </HFCard>

      {tab === 'overview' && <HFBookListings HF={HF} shops={shops} goto={goto} methodTone={methodTone} sbTone={sbTone} lowest={lowest}/>}
      {tab === 'prices'   && <HFBookPrices   HF={HF} shops={shops} lowest={lowest} history={history}/>}
      {tab === 'metadata' && <HFBookMetadata HF={HF} book={book} shops={shops}/>}
    </HFShell>
  );
}

// ─────────────────────── Listings tab (single, unified) ───────────────────────
// One row per shop — combines price, stock, match method, confidence,
// matched-at, matched-by, last scrape, and per-row actions in one place.

function HFBookListings({ HF, shops, goto, methodTone, sbTone, lowest }) {
  return (
    <HFCard title="Listings across shops"
            sub={`${shops.length} shop books point to this canonical book — price, stock, match info, and last scrape`}
            action={<HFButton size="sm"><span style={{display:'flex'}}>{HF_ICONS.plus}</span> Add match manually</HFButton>}
            flush>
      <HFTable
        onRowClick={r => goto('shop-book-detail', { id:r.shopBookId })}
        columns={[
          { key:'shop', label:'Shop', w:'1.1fr', sortable:true, cell:(v,r) => (
            <span style={{display:'flex', alignItems:'center', gap:8, minWidth:0}}>
              <ShopMark name={v} HF={HF}/>
              <span style={{display:'flex', flexDirection:'column', minWidth:0}}>
                <span style={{color:HF.ink, fontWeight:500}}>{v}</span>
                <span style={{fontFamily:HF.mono, fontSize:11, color:HF.ink4, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>#{r.shopBookId}</span>
              </span>
            </span>
          )},
          { key:'sbStatus', label:'Listing', w:'0.6fr',
            cell:v => <HFPill tone={sbTone[v]}>{v}</HFPill> },
          { key:'price', label:'Price', w:'0.7fr', mono:true, align:'right', sortable:true,
            sortVal:r=>r.price ?? 999,
            cell:(v) => v == null
              ? <span style={{color:HF.ink4}}>—</span>
              : <span style={{display:'inline-flex', alignItems:'baseline', gap:6, justifyContent:'flex-end'}}>
                  <span style={{color: v===lowest? HF.okInk : HF.ink, fontWeight: v===lowest? 600 : 500}}>€{v.toFixed(2)}</span>
                  {v===lowest && <span style={{fontSize:10, color:HF.okInk, fontWeight:600, letterSpacing:0.4}}>BEST</span>}
                </span>
          },
          { key:'delta', label:'Δ 30d', w:'0.55fr', mono:true, align:'right',
            cell:(_,r) => {
              if (r.price == null || r.prev == null) return <span style={{color:HF.ink4}}>—</span>;
              const d = r.price - r.prev;
              if (Math.abs(d) < 0.01) return <span style={{color:HF.ink4}}>0.00</span>;
              return <span style={{color: d<0? HF.okInk : HF.errInk, fontWeight:500}}>{d<0?'▼':'▲'} €{Math.abs(d).toFixed(2)}</span>;
            }
          },
          { key:'stock', label:'Stock', w:'0.6fr',
            cell:v => <HFPill tone={v==='in stock'?'ok':'warn'}>{v==='in stock'?'on':'out'}</HFPill>
          },
          { key:'method', label:'Match', w:'0.9fr',
            cell:v => <HFPill tone={methodTone[v]}>{v}</HFPill>
          },
          { key:'matchedAt', label:'Matched', w:'1fr', muted:true, mono:true, sortable:true,
            cell:v => <span style={{color:HF.ink3, fontSize:11.5}}>{v}</span>
          },
          { key:'lastSeen', label:'Last scrape', w:'0.7fr', muted:true, mono:true, align:'right', sortable:true },
          { key:'_', label:'', w:'160px', align:'right',
            cell:() => <div style={{display:'flex', gap:4, justifyContent:'flex-end'}}>
              <button className="hf-btn" style={btnSm(HF)} onClick={(e)=>e.stopPropagation()}>Re-match</button>
              <button className="hf-btn" style={{...btnSm(HF), color:HF.errInk, borderColor:HF.errBorder}} onClick={(e)=>e.stopPropagation()}>Unlink</button>
            </div> },
        ]}
        rows={shops}
      />
    </HFCard>
  );
}

// ─────────────────────── Prices tab ───────────────────────

function HFBookPrices({ HF, shops, lowest, history }) {
  if (shops.length === 0 || shops.every(s => s.price == null)) {
    return <HFCard><div style={{padding:40, textAlign:'center', color:HF.ink4}}>No price data available.</div></HFCard>;
  }

  // Build per-shop series from real history when present; fall back to a flat
  // single-point line at the current price when the shop has no recorded history.
  const historyByShop = {};
  (history || []).forEach(h => { historyByShop[h.shop] = h.series || []; });

  const series = shops.filter(s => s.price != null).map(s => {
    const hist = historyByShop[s.shop] || [];
    const data = hist.length > 0
      ? hist.map(p => parseFloat(p.price)).filter(p => !isNaN(p))
      : [s.price];
    return { shop: s.shop, data, current: s.price, history: hist };
  });

  // All-time low across all shops' real history
  const allHistoryPrices = (history || []).flatMap(h => (h.series || []).map(p => ({ shop: h.shop, price: parseFloat(p.price), date: p.date })))
    .filter(p => !isNaN(p.price));
  const allTimeLow = allHistoryPrices.length > 0
    ? allHistoryPrices.reduce((min, p) => p.price < min.price ? p : min, allHistoryPrices[0])
    : null;

  // Average price across all current shop prices
  const currentPrices = shops.map(s => s.price).filter(p => p != null);
  const avgPrice = currentPrices.length > 0
    ? currentPrices.reduce((a, b) => a + b, 0) / currentPrices.length
    : null;

  return (
    <>
      <HFCard title="30-day price comparison" sub="every shop overlaid · click a shop to isolate"
              style={{marginBottom:HF.gap}}>
        <div style={{padding:HF.cardP}}>
          <MultiLineChart HF={HF} series={series} h={260}/>
          <div style={{display:'flex', flexWrap:'wrap', gap:14, marginTop:14, paddingTop:12, borderTop:`1px solid ${HF.borderFaint}`}}>
            {series.map((s, i) => (
              <div key={s.shop} style={{display:'flex', alignItems:'center', gap:6, fontSize:12}}>
                <span style={{width:10, height:10, borderRadius:2, background: shopColor(i, HF)}}/>
                <span style={{color:HF.ink, fontWeight:500}}>{s.shop}</span>
                <span style={{fontFamily:HF.mono, color: s.current===lowest? HF.okInk : HF.ink3, fontWeight: s.current===lowest? 600 : 400}}>
                  €{s.current.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </HFCard>

      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:HF.gap}}>
        <HFCard title="Cheapest right now" sub="best deal across matched shops">
          <div style={{padding:HF.cardP, display:'flex', flexDirection:'column', gap:6}}>
            <div style={{display:'flex', alignItems:'baseline', gap:8}}>
              <span style={{fontSize:28, fontWeight:700, color:HF.okInk, fontFamily:HF.mono}}>{lowest != null ? `€${lowest.toFixed(2)}` : '—'}</span>
              <span style={{color:HF.ink3, fontSize:13}}>{shops.find(s => s.price === lowest)?.shop ?? ''}</span>
            </div>
            <span style={{fontSize:12, color:HF.ink3}}>{lowest != null ? `€${(Math.max(...shops.map(s=>s.price||0))-lowest).toFixed(2)} cheaper than the most expensive listing.` : ''}</span>
          </div>
        </HFCard>
        <HFCard title="All-time low" sub="across all shops, since first match">
          <div style={{padding:HF.cardP, display:'flex', flexDirection:'column', gap:6}}>
            <div style={{display:'flex', alignItems:'baseline', gap:8}}>
              <span style={{fontSize:28, fontWeight:700, color:HF.ink, fontFamily:HF.mono}}>{allTimeLow ? `€${allTimeLow.price.toFixed(2)}` : '—'}</span>
              <span style={{color:HF.ink3, fontSize:13}}>{allTimeLow?.shop ?? ''}</span>
            </div>
            <span style={{fontSize:12, color:HF.ink3}}>{allTimeLow?.date ?? (history === null ? 'Loading…' : 'No history yet')}</span>
          </div>
        </HFCard>
        <HFCard title="Average price" sub="current price across all shops">
          <div style={{padding:HF.cardP, display:'flex', flexDirection:'column', gap:6}}>
            <div style={{display:'flex', alignItems:'baseline', gap:8}}>
              <span style={{fontSize:28, fontWeight:700, color:HF.ink, fontFamily:HF.mono}}>{avgPrice != null ? `€${avgPrice.toFixed(2)}` : '—'}</span>
            </div>
            <span style={{fontSize:12, color:HF.ink3}}>{currentPrices.length} shop{currentPrices.length===1?'':'s'} contributing</span>
          </div>
        </HFCard>
      </div>
    </>
  );
}

// ─────────────────────── Metadata tab ───────────────────────

function HFBookMetadata({ HF, book, shops }) {
  const order = shops.map(s => s.shop);
  return (
    <>
      <HFContributorsCard HF={HF} book={book} shops={shops} order={order}/>
      <HFMetadataMatrix HF={HF} book={book} shops={shops} order={order}/>
    </>
  );
}

function HFContributorsCard({ HF, book, shops, order }) {
  // Build per-role rows from canonical contributors. API only exposes a
  // single shop_author per shop (not per-role), so only the Author row has
  // per-shop cells; other roles show canonical-only.
  const contributors = (book.contributors || []).map(c => ({
    role: c.role,
    canonical: c.name,
    cells: order.reduce((acc, shopName) => {
      const shopObj = shops.find(s => s.shop === shopName);
      const shopAuthor = shopObj?.shopAuthor;
      acc[shopName] = (c.role === 'Author' && shopAuthor) ? shopAuthor : null;
      return acc;
    }, {}),
  }));

  if (!contributors.length) return null;

  return (
    <HFCard title="Contributors" sub="people credited on this book — author, translator, editor, cover artist, illustrator, producer, narrator"
            style={{marginBottom:HF.gap}} flush>
      <div style={{overflowX:'auto'}} className="hf-scroll">
        <div style={{minWidth: 200 + order.length*140}}>
          <div style={{
            display:'grid', gridTemplateColumns:`160px 200px repeat(${order.length}, 1fr)`,
            padding:`8px ${HF.cardP}px`, alignItems:'center',
            background:HF.subtle, borderBottom:`1px solid ${HF.border}`,
            fontSize:11, fontWeight:600, color:HF.ink3, textTransform:'uppercase', letterSpacing:0.5,
          }}>
            <span>Role</span><span>Canonical</span>
            {order.map(n => (
              <span key={n} style={{display:'flex', alignItems:'center', gap:6, textTransform:'none', letterSpacing:0, fontWeight:600, color:HF.ink2, fontSize:11.5}}>
                <ShopMark name={n} HF={HF}/><span style={{overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{n}</span>
              </span>
            ))}
          </div>
          {contributors.map((c, i) => (
            <div key={c.role} style={{
              display:'grid', gridTemplateColumns:`160px 200px repeat(${order.length}, 1fr)`,
              padding:`9px ${HF.cardP}px`, alignItems:'center',
              borderBottom: i < contributors.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
              fontSize:12,
            }}>
              <span style={{color:HF.ink, fontWeight:600, fontSize:12.5}}>{c.role}</span>
              <span style={{color: (typeof c.canonical === 'string' && c.canonical.startsWith('—')) ? HF.ink4 : HF.ink, fontWeight:500, paddingRight:12, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{c.canonical}</span>
              {order.map(n => {
                const v = c.cells[n];
                if (v == null) return <span key={n} style={{color:HF.ink4, fontSize:11.5, fontFamily:HF.mono}}>—</span>;
                if (typeof v === 'object' && v.conflict) {
                  return <span key={n} title={v.v} style={{display:'flex', alignItems:'center', gap:6, color:HF.warnInk, fontSize:11.5, minWidth:0}}>
                    <span style={{width:14, height:14, borderRadius:3, background:HF.warnSoft, border:`1px solid ${HF.warnBorder}`, display:'inline-flex', alignItems:'center', justifyContent:'center', fontSize:9, fontWeight:700}}>!</span>
                    <span style={{overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{v.v}</span>
                  </span>;
                }
                return <span key={n} style={{color: v===c.canonical? HF.ink2 : HF.warnInk, fontSize:11.5, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{v}</span>;
              })}
            </div>
          ))}
        </div>
      </div>
    </HFCard>
  );
}

function HFMetadataMatrix({ HF, book, shops, order }) {
  // Per-field per-shop matrix derived from real API data.
  // Each cell is:
  //   { v: '<value>' }              → shop reported this value (matches canonical → green check)
  //   { v: '<value>', conflict:true } → shop reported a different value (warning)
  //   { missing:true }              → shop did not provide this field
  const fields = [
    { field:'ISBN',       canonical: book.isbn,      perShop: s => s.shopIsbn },
    { field:'Title',      canonical: book.title,     perShop: s => s.shopTitle },
    { field:'Author',     canonical: book.author,    perShop: s => s.shopAuthor },
    { field:'Year',       canonical: book.year != null ? String(book.year) : null, perShop: s => s.shopYear != null ? String(s.shopYear) : null },
    { field:'Publisher',  canonical: book.publisher, perShop: s => s.shopPublisher },
    { field:'Format',     canonical: book.binding,   perShop: s => s.shopFormat },
    { field:'Language',   canonical: book.language,  perShop: () => null },
    { field:'Pages',      canonical: book.pages != null ? String(book.pages) : null, perShop: () => null },
  ];

  const matrix = fields.map(row => {
    const cells = {};
    let provided = 0, conflicts = 0, missing = 0;
    for (const s of shops) {
      const raw = row.perShop(s);
      if (raw == null || raw === '') {
        cells[s.shop] = { missing:true };
        missing++;
      } else {
        const v = String(raw);
        const matches = row.canonical != null && v === String(row.canonical);
        cells[s.shop] = matches ? { v } : { v, conflict:true };
        provided++;
        if (!matches) conflicts++;
      }
    }
    const total = shops.length;
    let source;
    if (total === 0) source = 'no shop data';
    else if (conflicts === 0 && missing === 0) source = 'consensus';
    else {
      const parts = [`${provided} of ${total}`];
      if (conflicts) parts.push(`${conflicts} conflict${conflicts>1?'s':''}`);
      if (missing) parts.push(`${missing} missing`);
      source = parts.join(' · ');
    }
    return {
      field: row.field,
      canonical: row.canonical != null && row.canonical !== '' ? String(row.canonical) : '—',
      source,
      cells,
    };
  });

  // Conflicts list — every shop × field where the shop value disagrees with canonical.

  return (
    <>
      <HFCard title="Canonical metadata · per shop"
              sub="each row is a field; each column is a shop. ✓ = shop value matches canonical, ⚠ = conflict, — = not provided"
              style={{marginBottom:HF.gap}} flush>
        <div style={{overflowX:'auto'}} className="hf-scroll">
          <div style={{minWidth: 200 + order.length*140}}>
            {/* Header row */}
            <div style={{
              display:'grid',
              gridTemplateColumns:`140px 200px repeat(${order.length}, 1fr)`,
              padding:`8px ${HF.cardP}px`, alignItems:'center',
              background:HF.subtle, borderBottom:`1px solid ${HF.border}`,
              fontSize:11, fontWeight:600, color:HF.ink3, textTransform:'uppercase', letterSpacing:0.5,
            }}>
              <span>Field</span>
              <span>Canonical</span>
              {order.map(name => (
                <span key={name} style={{display:'flex', alignItems:'center', gap:6, textTransform:'none', letterSpacing:0, fontWeight:600, color:HF.ink2, fontSize:11.5}}>
                  <ShopMark name={name} HF={HF}/>
                  <span style={{overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{name}</span>
                </span>
              ))}
            </div>
            {/* Rows */}
            {matrix.map((row, i) => (
              <div key={row.field} style={{
                display:'grid',
                gridTemplateColumns:`140px 200px repeat(${order.length}, 1fr)`,
                padding:`10px ${HF.cardP}px`, alignItems:'center',
                borderBottom: i < matrix.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
                fontSize:12,
              }}>
                <div style={{display:'flex', flexDirection:'column', gap:2}}>
                  <span style={{color:HF.ink, fontWeight:600, fontSize:12.5}}>{row.field}</span>
                  <span style={{color: row.source.includes('conflict')? HF.warnInk : HF.ink4, fontSize:10.5, fontFamily:HF.mono}}>{row.source}</span>
                </div>
                <span style={{color:HF.ink, fontWeight:500, fontSize:12.5, paddingRight:12, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{row.canonical}</span>
                {order.map(name => {
                  const c = row.cells[name] || { missing:true };
                  if (c.missing) {
                    return (
                      <span key={name} style={{display:'flex', alignItems:'center', gap:6, color:HF.ink4, fontSize:11.5, fontFamily:HF.mono}}>
                        <span style={{width:14, display:'inline-flex', justifyContent:'center'}}>—</span>
                        <span>not provided</span>
                      </span>
                    );
                  }
                  const matches = c.v === row.canonical;
                  if (c.conflict || !matches) {
                    return (
                      <span key={name} title={c.v} style={{display:'flex', alignItems:'center', gap:6, color:HF.warnInk, fontSize:11.5, minWidth:0}}>
                        <span style={{width:14, height:14, borderRadius:3, background:HF.warnSoft, border:`1px solid ${HF.warnBorder}`, display:'inline-flex', alignItems:'center', justifyContent:'center', fontSize:9, fontWeight:700}}>!</span>
                        <span style={{overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{c.v}</span>
                      </span>
                    );
                  }
                  return (
                    <span key={name} style={{display:'flex', alignItems:'center', gap:6, color:HF.okInk, fontSize:11.5}}>
                      <span style={{width:14, height:14, borderRadius:3, background:HF.okSoft, border:`1px solid ${HF.okBorder}`, display:'inline-flex', alignItems:'center', justifyContent:'center'}}>
                        <svg width="8" height="8" viewBox="0 0 8 8" fill="none"><path d="M1.5 4 L3.5 6 L6.5 2" stroke={HF.okInk} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
                      </span>
                      <span style={{color:HF.ink2, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>match</span>
                    </span>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </HFCard>

      <HFCard title="Conflicts to resolve" sub="fields where a shop disagrees with the canonical value" flush>
        <div style={{padding:`6px 0`}}>
          {matrix.flatMap(row =>
            order.filter(name => row.cells[name]?.conflict).map(name => ({ field: row.field, canonical: row.canonical, name, value: row.cells[name].v }))
          ).map((c, i, arr) => (
            <div key={`${c.field}-${c.name}`} style={{
              padding:`12px ${HF.cardP}px`,
              borderBottom: i < arr.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
              display:'grid', gridTemplateColumns:'1fr 1fr 1fr auto', gap:16, alignItems:'center', fontSize:12.5,
            }}>
              <div style={{display:'flex', alignItems:'center', gap:8}}>
                <ShopMark name={c.name} HF={HF}/>
                <span style={{color:HF.ink, fontWeight:600}}>{c.name}</span>
                <span style={{color:HF.ink3}}>disagrees on</span>
                <HFPill tone="warn">{c.field}</HFPill>
              </div>
              <div style={{display:'flex', flexDirection:'column', gap:2, fontSize:11.5}}>
                <span style={{color:HF.ink4, fontFamily:HF.mono, fontSize:10.5, textTransform:'uppercase', letterSpacing:0.4}}>canonical</span>
                <span style={{color:HF.ink2, fontWeight:500}}>{c.canonical}</span>
              </div>
              <div style={{display:'flex', flexDirection:'column', gap:2, fontSize:11.5}}>
                <span style={{color:HF.warnInk, fontFamily:HF.mono, fontSize:10.5, textTransform:'uppercase', letterSpacing:0.4}}>shop value</span>
                <span style={{color:HF.warnInk, fontWeight:600}}>{c.value}</span>
              </div>
              <div style={{display:'flex', gap:6}}>
                <button className="hf-btn" style={btnSm(HF)}>Use shop</button>
                <button className="hf-btn" style={btnSm(HF)}>Keep canonical</button>
              </div>
            </div>
          ))}
        </div>
      </HFCard>
    </>
  );
}

// ─────────────────────── Helper components ───────────────────────

const SHOP_COLORS = ['accent','#0e7490','#b45309','#7c3aed','#16a34a','#6b7280'];
function shopColor(i, HF) {
  const map = [HF.accent, '#0e7490', '#b45309', '#7c3aed', '#16a34a', '#6b7280'];
  return map[i % map.length];
}

function ShopMark({ name, HF }) {
  const i = (name.charCodeAt(0) + name.charCodeAt(name.length-1)) % 6;
  const c = shopColor(i, HF);
  return (
    <span style={{
      width:22, height:22, borderRadius:5,
      background:`${c}1A`, color:c,
      display:'flex', alignItems:'center', justifyContent:'center',
      fontSize:10, fontWeight:700, letterSpacing:-0.3,
      fontFamily:HF.sans, border:`1px solid ${c}33`,
      flexShrink:0,
    }}>{name.slice(0,2).toUpperCase()}</span>
  );
}

function ConfidenceBar({ v, HF }) {
  const c = v >= 0.95 ? HF.ok : v >= 0.85 ? HF.warn : HF.err;
  return (
    <span style={{display:'inline-flex', alignItems:'center', gap:6, justifyContent:'flex-end'}}>
      <span style={{width:48, height:5, background:HF.subtle, borderRadius:3, overflow:'hidden', display:'inline-block'}}>
        <span style={{display:'block', height:'100%', width:`${v*100}%`, background:c, borderRadius:3}}/>
      </span>
      <span style={{color: v>=0.95? HF.ink2 : HF.warnInk, fontWeight: v>=0.95? 500 : 600}}>{v.toFixed(2)}</span>
    </span>
  );
}

function PriceBars({ HF, shops, lowest }) {
  const max = Math.max(...shops.map(s => s.price || 0));
  return (
    <div style={{display:'flex', flexDirection:'column', gap:11}}>
      {shops.map(s => {
        const p = s.price;
        const w = p ? (p / max) * 100 : 0;
        const isMin = p === lowest;
        return (
          <div key={s.shop} style={{display:'grid', gridTemplateColumns:'90px 1fr 70px', alignItems:'center', gap:10, fontSize:12.5}}>
            <span style={{color:HF.ink, fontWeight:500, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{s.shop}</span>
            <div style={{height:18, background:HF.subtle, borderRadius:4, position:'relative', overflow:'hidden'}}>
              {p == null ? (
                <span style={{position:'absolute', inset:0, display:'flex', alignItems:'center', paddingLeft:8, fontSize:11, color:HF.ink4, fontFamily:HF.mono}}>no price</span>
              ) : (
                <div style={{
                  height:'100%', width:`${w}%`,
                  background: isMin ? `linear-gradient(90deg, ${HF.ok}, #15803d)` : `linear-gradient(90deg, ${HF.accent}, ${HF.accentHover})`,
                  borderRadius:4,
                }}/>
              )}
            </div>
            <span style={{fontFamily:HF.mono, color: p==null? HF.ink4 : isMin? HF.okInk : HF.ink, fontWeight: isMin?600:500, textAlign:'right'}}>
              {p == null ? '—' : `€${p.toFixed(2)}`}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function MatchTimeline({ HF, shops, methodTone }) {
  const sorted = [...shops].sort((a,b) => new Date(a.matchedAt) - new Date(b.matchedAt));
  return (
    <div style={{padding:`8px 0`}}>
      {sorted.map((s, i, a) => (
        <div key={s.shop} style={{
          display:'grid', gridTemplateColumns:'14px 1fr',
          padding:`10px ${HF.cardP}px 10px 0`, marginLeft:HF.cardP,
          gap:14, alignItems:'flex-start', position:'relative',
        }}>
          <div style={{display:'flex', flexDirection:'column', alignItems:'center', paddingTop:4}}>
            <span style={{
              width:8, height:8, borderRadius:'50%',
              background: s.sbStatus==='pending'? HF.warn : HF.accent,
              boxShadow: `0 0 0 3px ${s.sbStatus==='pending'? HF.warnSoft : HF.accentSoft}`,
            }}/>
            {i < a.length-1 && <span style={{flex:1, width:1, background:HF.borderFaint, marginTop:6, minHeight:18}}/>}
          </div>
          <div style={{display:'flex', flexDirection:'column', gap:3, paddingBottom: i<a.length-1? 4 : 0}}>
            <div style={{display:'flex', alignItems:'center', gap:8, fontSize:12.5, flexWrap:'wrap'}}>
              <ShopMark name={s.shop} HF={HF}/>
              <span style={{color:HF.ink, fontWeight:600}}>{s.shop}</span>
              <span style={{color:HF.ink3}}>matched via</span>
              <HFPill tone={methodTone[s.method]}>{s.method}</HFPill>
              <span style={{fontFamily:HF.mono, fontSize:11, color: s.confidence>=0.95? HF.ink3 : HF.warnInk}}>conf {s.confidence.toFixed(2)}</span>
            </div>
            <div style={{fontSize:11.5, color:HF.ink3, display:'flex', gap:10, flexWrap:'wrap'}}>
              <span style={{fontFamily:HF.mono}}>{s.matchedAt}</span>
              <span style={{color:HF.ink4}}>·</span>
              <span>{s.by}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function MatchStrategy({ HF, shops }) {
  const counts = shops.reduce((acc, s) => { acc[s.method] = (acc[s.method]||0)+1; return acc; }, {});
  const order = ['isbn','title+author','manual','slug'];
  const labels = {
    isbn:          ['ISBN exact',       'highest-confidence path · lookup by ISBN-13'],
    'title+author':['Title + author',   'fuzzy match when ISBN missing or invalid'],
    manual:        ['Manual link',      'matched by an operator from review queue'],
    slug:          ['URL slug',         'last-resort by canonical URL slug'],
  };
  const total = shops.length;
  return (
    <div style={{padding:`4px 0`}}>
      {order.filter(k => counts[k]).map((k, i, a) => {
        const n = counts[k];
        const pct = (n/total)*100;
        const tone = k==='isbn'? HF.ok : k==='title+author'? HF.warn : k==='manual'? HF.accent : HF.ink4;
        return (
          <div key={k} style={{
            padding:`10px ${HF.cardP}px`,
            borderBottom: i < a.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
            display:'flex', flexDirection:'column', gap:6,
          }}>
            <div style={{display:'flex', alignItems:'baseline', justifyContent:'space-between', gap:10}}>
              <span style={{color:HF.ink, fontWeight:600, fontSize:12.5}}>{labels[k][0]}</span>
              <span style={{fontFamily:HF.mono, fontSize:12, color:HF.ink2, fontWeight:500}}>{n} of {total}</span>
            </div>
            <div style={{height:4, background:HF.subtle, borderRadius:2, overflow:'hidden'}}>
              <div style={{height:'100%', width:`${pct}%`, background:tone, borderRadius:2}}/>
            </div>
            <span style={{fontSize:11.5, color:HF.ink3, lineHeight:1.5}}>{labels[k][1]}</span>
          </div>
        );
      })}
    </div>
  );
}

function MultiLineChart({ HF, series, h }) {
  const w = 720;
  const padL = 36, padR = 12, padT = 12, padB = 22;
  const all = series.flatMap(s => s.data);
  const min = Math.min(...all) - 0.5;
  const max = Math.max(...all) + 0.5;
  const n = series[0]?.data.length || 30;
  const xs = i => padL + (i/(n-1))*(w - padL - padR);
  const ys = v => padT + (1 - (v-min)/(max-min))*(h - padT - padB);

  const yTicks = 4;
  const ticks = Array.from({length:yTicks+1}, (_,i) => min + (i/yTicks)*(max-min));

  return (
    <svg viewBox={`0 0 ${w} ${h}`} style={{width:'100%', height:'auto', display:'block'}} preserveAspectRatio="none">
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={padL} x2={w-padR} y1={ys(t)} y2={ys(t)} stroke={HF.chartGrid} strokeWidth={1}/>
          <text x={padL-8} y={ys(t)+3} textAnchor="end" fontSize="10" fill={HF.ink4} fontFamily={HF.mono}>€{t.toFixed(0)}</text>
        </g>
      ))}
      {[0, Math.floor(n/3), Math.floor(2*n/3), n-1].map(i => (
        <text key={i} x={xs(i)} y={h-6} textAnchor="middle" fontSize="10" fill={HF.ink4} fontFamily={HF.mono}>D-{n-1-i}</text>
      ))}
      {series.map((s, idx) => {
        const c = shopColor(idx, HF);
        const path = s.data.map((v,i) => `${i===0?'M':'L'} ${xs(i)} ${ys(v)}`).join(' ');
        return (
          <g key={s.shop}>
            <path d={path} fill="none" stroke={c} strokeWidth={1.7} strokeLinejoin="round" strokeLinecap="round"/>
            <circle cx={xs(n-1)} cy={ys(s.data[n-1])} r={3} fill={c} stroke={HF.surface} strokeWidth={1.5}/>
          </g>
        );
      })}
    </svg>
  );
}

function btnSm(HF) {
  return {
    padding:'3px 8px', fontSize:11.5, height:24,
    background:HF.surface, border:`1px solid ${HF.borderStrong}`,
    color:HF.ink2, borderRadius:5, cursor:'pointer',
    fontFamily:HF.sans,
  };
}

// ─────────────────────── Conflicts tab ───────────────────────

function HFBookConflicts({ HF, book, shops }) {
  // Each shop's per-dimension agreement with canonical. Y/N/?/~ semantics:
  //   true  → matches canonical
  //   false → conflicts with canonical
  //   null  → not provided / unknown
  //   'fuzzy' → close but not exact (e.g., title diacritic / author abbreviation)
  const dims = ['isbn','title','author','year','binding','translator','cover'];
  const dimLabel = { isbn:'ISBN', title:'Title', author:'Author', year:'Year', binding:'Binding', translator:'Translator', cover:'Cover artist' };

  const rows = [
    { shop:'vaga',         method:'isbn',         confidence:1.00,
      dim:{ isbn:true,  title:true,    author:true,    year:true,  binding:true,  translator:true,  cover:true   } },
    { shop:'knygos.lt',    method:'isbn',         confidence:1.00,
      dim:{ isbn:true,  title:true,    author:true,    year:true,  binding:true,  translator:true,  cover:null   } },
    { shop:'patogu',       method:'title+author', confidence:0.94,
      dim:{ isbn:true,  title:'fuzzy', author:true,    year:true,  binding:'fuzzy', translator:true, cover:null  } },
    { shop:'krisostomus',  method:'manual',       confidence:1.00,
      dim:{ isbn:true,  title:true,    author:true,    year:true,  binding:false, translator:null,  cover:false  } },
    { shop:'humanitas',    method:'isbn',         confidence:1.00,
      dim:{ isbn:true,  title:true,    author:true,    year:false, binding:true,  translator:'fuzzy', cover:null } },
    { shop:'mintis',       method:'title+author', confidence:0.81,
      dim:{ isbn:null,  title:true,    author:'fuzzy', year:true,  binding:null,  translator:null,  cover:null   } },
  ];

  // Buckets: classify each shop by which combination of dims agreed/conflicted.
  const buckets = [
    {
      id:'isbn-but-not-binding',
      title:'Matched by ISBN — but binding disagrees',
      desc:'Same ISBN-13, but the shop reports a different physical edition (e.g. hardcover vs paperback).',
      tone:'warn', icon:'⚠',
      test: r => r.dim.isbn === true && r.dim.binding === false,
      action:'Likely a different edition reusing the ISBN. Decide: split into a new book, or accept as a variant.',
    },
    {
      id:'isbn-but-not-cover',
      title:'Matched by ISBN — but cover artist disagrees',
      desc:'ISBN matches, but credited cover artist differs from canonical.',
      tone:'warn', icon:'⚠',
      test: r => r.dim.isbn === true && r.dim.cover === false,
      action:'Cover may have been re-illustrated for a regional reprint. Verify with the shop page.',
    },
    {
      id:'isbn-but-not-year',
      title:'Matched by ISBN — but year disagrees',
      desc:'ISBN matches, but the shop reports a different publication year.',
      tone:'warn', icon:'⚠',
      test: r => r.dim.isbn === true && r.dim.year === false,
      action:'Often a re-print sharing the ISBN. Accept the canonical year, or escalate if it is a true different edition.',
    },
    {
      id:'fuzzy-title-author',
      title:'Matched by title + author — fuzzy on either',
      desc:'No ISBN was used; we matched on title and/or author with fuzzy similarity below 1.0.',
      tone:'accent', icon:'~',
      test: r => r.method === 'title+author' && (r.dim.title === 'fuzzy' || r.dim.author === 'fuzzy'),
      action:'Inspect the shop title — diacritics, translated subtitle, or initials (e.g. "Y. N. Harari") are common.',
    },
    {
      id:'manual-no-isbn-confirm',
      title:'Manual match — fields ambiguous',
      desc:'An operator linked this shop manually. Some fields the operator did not verify still differ from canonical.',
      tone:'accent', icon:'M',
      test: r => r.method === 'manual' && Object.values(r.dim).some(v => v === false),
      action:'Sanity-check the operator-confirmed fields against any conflicts flagged here.',
    },
    {
      id:'isbn-missing',
      title:'No ISBN provided by shop',
      desc:'Shop omits ISBN entirely; match relies on title+author similarity.',
      tone:'warn', icon:'?',
      test: r => r.dim.isbn == null,
      action:'Lower-confidence match. Consider routing to the review queue if confidence < 0.85.',
    },
  ];

  const tagged = buckets.map(b => ({ ...b, hits: rows.filter(b.test).map(r => r.shop) }));

  return (
    <>
      <HFKpiStrip items={[
        { label:'Conflict types',  value:String(tagged.filter(b => b.hits.length).length), delta:<span style={{color:HF.ink3}}>distinct buckets</span> },
        { label:'Shops affected',  value:String(new Set(tagged.flatMap(b => b.hits)).size), delta:<span style={{color:HF.warnInk}}>at least one issue</span>, tone:'warn' },
        { label:'ISBN-but-other',  value:String(tagged.filter(b => b.id.startsWith('isbn-but')).reduce((n,b)=>n+b.hits.length,0)), delta:<span style={{color:HF.errInk}}>could be wrong edition</span>, tone:'err' },
        { label:'Fuzzy / manual',  value:String(tagged.filter(b => b.id.includes('fuzzy') || b.id.startsWith('manual')).reduce((n,b)=>n+b.hits.length,0)), delta:<span style={{color:HF.ink3}}>review-worthy</span> },
        { label:'Below 0.85',      value:String(rows.filter(r=>r.confidence < 0.85).length), delta:<span style={{color:HF.warnInk}}>auto-flagged</span>, tone:'warn' },
      ]}/>

      <div style={{
        marginTop: HF.gap,
        padding: `12px ${HF.cardP}px`,
        background: HF.surface,
        border: `1px solid ${HF.border}`,
        borderLeft: `3px solid ${HF.accent}`,
        borderRadius: 6,
        fontSize: 12.5, color: HF.ink2, lineHeight: 1.55,
      }}>
        Field-by-field values are on the <b style={{color:HF.ink}}>Metadata</b> tab. This view groups shops by <i>which combination of dimensions disagrees</i> with the canonical book — so you can decide whether a mismatch is a re-print, a wrong edition, or a bad match.
      </div>

      <HFCard title="Conflict types" sub="grouped by which combination of dimensions disagrees" style={{marginTop:HF.gap}} flush>
        <div>
          {tagged.filter(b => b.hits.length > 0).map((b, i, arr) => (
            <div key={b.id} style={{
              padding:`14px ${HF.cardP}px`,
              borderBottom: i < arr.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
              display:'grid', gridTemplateColumns:'auto 1fr auto', gap:14, alignItems:'flex-start',
            }}>
              <span style={{
                width:30, height:30, borderRadius:7,
                background: b.tone==='warn'? HF.warnSoft : b.tone==='err'? HF.errSoft : HF.accentSoft,
                border:`1px solid ${b.tone==='warn'? HF.warnBorder : b.tone==='err'? HF.errBorder : HF.accentBorder}`,
                color: b.tone==='warn'? HF.warnInk : b.tone==='err'? HF.errInk : HF.accentInk,
                display:'flex', alignItems:'center', justifyContent:'center',
                fontSize:14, fontWeight:700, fontFamily:HF.mono,
              }}>{b.icon}</span>
              <div style={{display:'flex', flexDirection:'column', gap:6, minWidth:0}}>
                <div style={{display:'flex', alignItems:'center', gap:8, flexWrap:'wrap'}}>
                  <span style={{color:HF.ink, fontWeight:600, fontSize:13}}>{b.title}</span>
                  <HFPill tone={b.tone}>{b.hits.length} {b.hits.length===1?'shop':'shops'}</HFPill>
                </div>
                <span style={{fontSize:12, color:HF.ink3, lineHeight:1.5}}>{b.desc}</span>
                <div style={{display:'flex', flexWrap:'wrap', gap:6, marginTop:2}}>
                  {b.hits.map(s => (
                    <span key={s} style={{display:'inline-flex', alignItems:'center', gap:6, padding:'3px 7px 3px 4px', border:`1px solid ${HF.border}`, borderRadius:5, background:HF.surface, fontSize:11.5}}>
                      <ShopMark name={s} HF={HF}/>
                      <span style={{color:HF.ink, fontWeight:500}}>{s}</span>
                    </span>
                  ))}
                </div>
                <span style={{fontSize:11.5, color:HF.ink3, fontStyle:'italic', marginTop:2}}>→ {b.action}</span>
              </div>
              <div style={{display:'flex', flexDirection:'column', gap:5}}>
                <HFButton size="sm">Review</HFButton>
                <HFButton size="sm" variant="subtle">Dismiss</HFButton>
              </div>
            </div>
          ))}
        </div>
      </HFCard>
    </>
  );
}

function DimCell({ v, HF }) {
  if (v === true) {
    return <span style={{display:'flex', justifyContent:'center'}}>
      <span style={{width:18, height:18, borderRadius:4, background:HF.okSoft, border:`1px solid ${HF.okBorder}`, display:'inline-flex', alignItems:'center', justifyContent:'center'}}>
        <svg width="10" height="10" viewBox="0 0 8 8" fill="none"><path d="M1.5 4 L3.5 6 L6.5 2" stroke={HF.okInk} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
      </span>
    </span>;
  }
  if (v === false) {
    return <span style={{display:'flex', justifyContent:'center'}}>
      <span style={{width:18, height:18, borderRadius:4, background:HF.errSoft, border:`1px solid ${HF.errBorder}`, display:'inline-flex', alignItems:'center', justifyContent:'center', color:HF.errInk, fontSize:11, fontWeight:700}}>✗</span>
    </span>;
  }
  if (v === 'fuzzy') {
    return <span style={{display:'flex', justifyContent:'center'}}>
      <span style={{width:18, height:18, borderRadius:4, background:HF.warnSoft, border:`1px solid ${HF.warnBorder}`, display:'inline-flex', alignItems:'center', justifyContent:'center', color:HF.warnInk, fontSize:11, fontWeight:700, fontFamily:HF.mono}}>~</span>
    </span>;
  }
  return <span style={{display:'flex', justifyContent:'center'}}>
    <span style={{width:18, height:18, borderRadius:4, background:HF.subtle, border:`1px solid ${HF.borderFaint}`, display:'inline-flex', alignItems:'center', justifyContent:'center', color:HF.ink4, fontSize:11, fontFamily:HF.mono}}>—</span>
  </span>;
}

Object.assign(window, { HFBook });
