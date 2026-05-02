// Hi-fi Shop Books list + detail

function HFChangesPanel({ changes, fmtDate }) {
  const TRUNC = 120;
  const [expanded, setExpanded] = React.useState({});
  const toggle = (key) => setExpanded(prev => ({ ...prev, [key]: !prev[key] }));

  const TruncValue = ({ value, expKey, dimmed }) => {
    if (!value) return <span style={{color:'var(--hf-ink4)'}}>—</span>;
    const str = String(value);
    const isLong = str.length > TRUNC;
    const isExp = expanded[expKey];
    return (
      <span style={{display:'flex', flexDirection:'column', gap:3}}>
        <span style={{fontFamily:'var(--hf-mono)', fontSize:11, lineHeight:1.55, color: dimmed ? 'var(--hf-ink3)' : 'var(--hf-ink)', wordBreak:'break-word', whiteSpace:'pre-wrap'}}>
          {isExp ? str : str.slice(0, TRUNC)}{!isExp && isLong ? '…' : ''}
        </span>
        {isLong && (
          <button onClick={(e)=>{e.stopPropagation(); toggle(expKey);}}
            style={{background:'none', border:'none', cursor:'pointer', color:'var(--hf-accent-ink)', fontSize:11, fontFamily:'var(--hf-mono)', padding:0, textAlign:'left', fontWeight:500}}>
            {isExp ? 'collapse ↑' : `show all (${str.length} chars) ↓`}
          </button>
        )}
      </span>
    );
  };

  if (changes.length === 0) {
    return (
      <HFCard title="Field change history" sub="no changes recorded">
        <HFEmptyState title="No changes recorded" sub="Changes are tracked whenever a field value differs from the previous scrape." onClear={null}/>
      </HFCard>
    );
  }

  return (
    <HFCard title="Field change history" sub={`${changes.length} recorded changes`}>
      {changes.map((c, i) => (
        <div key={i} style={{padding:`14px var(--hf-card-p)`, borderBottom: i < changes.length-1 ? `1px solid ${'var(--hf-border-faint)'}` : 'none'}}>
          <div style={{display:'flex', alignItems:'center', gap:10, marginBottom:10}}>
            <span style={{fontSize:11, fontFamily:'var(--hf-mono)', fontWeight:600, background:'var(--hf-subtle)', padding:'2px 8px', borderRadius:4, color:'var(--hf-ink2)'}}>
              {c.field}
            </span>
            <span style={{fontSize:12, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)'}}>{fmtDate(c.changed_at)}</span>
          </div>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:10}}>
            <div style={{background:'rgba(239,68,68,0.05)', border:`1px solid rgba(239,68,68,0.15)`, borderRadius:6, padding:'8px 10px'}}>
              <div style={{fontSize:10, color:'var(--hf-err-ink)', fontWeight:600, textTransform:'uppercase', letterSpacing:0.5, marginBottom:5}}>Was</div>
              <TruncValue value={c.old_value} expKey={`${i}-old`} dimmed/>
            </div>
            <div style={{background:'rgba(34,197,94,0.05)', border:`1px solid rgba(34,197,94,0.15)`, borderRadius:6, padding:'8px 10px'}}>
              <div style={{fontSize:10, color:'var(--hf-ok-ink)', fontWeight:600, textTransform:'uppercase', letterSpacing:0.5, marginBottom:5}}>Now</div>
              <TruncValue value={c.new_value} expKey={`${i}-new`}/>
            </div>
          </div>
        </div>
      ))}
    </HFCard>
  );
}

// Price chart with hover tooltip showing exact date + price
function HFPriceChart({ priceHistory, h = 160 }) {
  const [tooltip, setTooltip] = React.useState(null); // { x, y, label }
  const prices = priceHistory.map(p => p.price || 0).filter(v => v > 0);
  if (prices.length === 0) {
    return <div style={{height:h, display:'flex', alignItems:'center', justifyContent:'center', color:'var(--hf-ink4)', fontSize:13}}>No price history yet</div>;
  }
  const W = 900, H = h;
  const max = Math.max(...prices), min = Math.min(...prices);
  const range = max - min || 1;
  const denom = prices.length === 1 ? 1 : prices.length - 1;
  const pts = prices.map((v, i) => ({
    x: (i / denom) * W,
    y: H - ((v - min) / range) * (H - 14) - 7,
    price: v,
    date: priceHistory[i]?.scraped_at,
  }));

  const handleMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = (e.clientX - rect.left) / rect.width;
    const idx = Math.round(relX * (pts.length - 1));
    const pt = pts[Math.min(Math.max(0, idx), pts.length - 1)];
    if (!pt) return;
    const label = `€${pt.price.toFixed(2)}${pt.date ? ' · ' + new Date(pt.date).toLocaleDateString('lt-LT', {month:'short', day:'numeric'}) : ''}`;
    setTooltip({ x: e.clientX - rect.left, y: e.clientY - rect.top, label });
  };

  return (
    <div style={{position:'relative', cursor:'crosshair'}}
         onMouseMove={handleMove}
         onMouseLeave={() => setTooltip(null)}>
      <HFAreaChart data={prices} h={h} label="€ price"/>
      {tooltip && (
        <div style={{
          position:'absolute', top: Math.max(0, tooltip.y - 30), left: Math.min(tooltip.x + 8, 200),
          background:'var(--hf-surface)', border:`1px solid ${'var(--hf-border)'}`,
          borderRadius:5, padding:'3px 8px', fontSize:12, fontFamily:'var(--hf-mono)',
          color:'var(--hf-ink)', pointerEvents:'none', whiteSpace:'nowrap',
          boxShadow:'var(--hf-shadow-sm)', zIndex:10,
        }}>
          {tooltip.label}
        </div>
      )}
    </div>
  );
}

function HFShopBooks({ nav, goto }) {
  const HF = getHF();
  const statusTone = { active:'ok', out:'warn', delisted:'neutral' };

  // Filter state — backend handles filtering and pagination.
  const _sp = new URLSearchParams(window.location.search);
  const [q, setQ]                 = React.useState(_sp.get('q') || '');
  const [shop, setShop]           = React.useState(_sp.get('shop') || 'all');
  const [active, setActive]       = React.useState(_sp.get('active') || 'all');
  const [missing, setMissing]     = React.useState(_sp.get('missing') || 'any');
  const [bookType, setBookType]   = React.useState(_sp.get('type') || 'all');
  const [category, setCategory]   = React.useState(_sp.get('category') || '');
  const [urlUnreachable, setUrlUnreachable] = React.useState(_sp.get('unreachable') === '1');
  const [page, setPage]           = React.useState(Math.max(1, parseInt(_sp.get('page') || '1', 10) || 1));
  const PER_PAGE = 30;

  // Mirror filter state into URL bar
  React.useEffect(() => {
    const sp = new URLSearchParams();
    if (q.trim()) sp.set('q', q.trim());
    if (shop !== 'all') sp.set('shop', shop);
    if (active !== 'all') sp.set('active', active);
    if (missing !== 'any') sp.set('missing', missing);
    if (bookType !== 'all') sp.set('type', bookType);
    if (category.trim()) sp.set('category', category.trim());
    if (urlUnreachable) sp.set('unreachable', '1');
    if (page > 1) sp.set('page', String(page));
    const qs = sp.toString();
    window.history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : ''));
  }, [q, shop, active, missing, bookType, category, urlUnreachable, page]);

  React.useEffect(() => { setPage(1); }, [q, shop, active, missing, bookType, category, urlUnreachable]);

  const [data, setData] = React.useState({
    books: [], total: 0, page: 1, per_page: PER_PAGE, pages: 1,
    kpis: { total: 0, active: 0, missing_isbn: 0, missing_price: 0, unreachable: 0 },
  });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({ page: String(page), per_page: String(PER_PAGE) });
    if (q.trim()) params.set('search', q.trim());
    if (shop !== 'all') params.set('shop', shop);
    if (active !== 'all') params.set('active', active);
    if (missing !== 'any') params.set('missing_field', missing);
    if (bookType !== 'all') params.set('type_filter', bookType);
    if (category.trim()) params.set('category', category.trim());
    if (urlUnreachable) params.set('url_unreachable', 'true');
    fetch(`/api/shop-books?${params.toString()}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [q, shop, active, missing, bookType, category, urlUnreachable, page]);

  const rows = data.books;
  const activeCount =
    (q.trim()?1:0) + (shop!=='all'?1:0) + (active!=='all'?1:0) +
    (missing!=='any'?1:0) + (bookType!=='all'?1:0) + (category.trim()?1:0) + (urlUnreachable?1:0);

  const clearAll = () => { setQ(''); setShop('all'); setActive('all'); setMissing('any'); setBookType('all'); setCategory(''); setUrlUnreachable(false); };

  return (
    <HFShell {...nav} activePage="shop-books"
      title="Shop Books" subtitle="Every scraped listing from every shop."
      breadcrumb={<><span>BookScraper</span><span style={{color:'var(--hf-ink5)'}}>/</span><span style={{color:'var(--hf-ink)', fontWeight:500}}>Shop Books</span></>}
      actions={<>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.download}</span> Export</HFButton>
        <HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openAddBook()}><span style={{display:'flex'}}>{HF_ICONS.plus}</span> Add book</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Total books',   value: data.kpis.total.toLocaleString(), delta:<span style={{color:'var(--hf-ink3)'}}>total</span>,
          onClick: clearAll },
        { label:'Active',        value: data.kpis.active.toLocaleString(), delta:<span style={{color:'var(--hf-ink3)'}}>{data.kpis.total > 0 ? Math.round(data.kpis.active/data.kpis.total*100) : 0}%</span>,
          onClick: () => { clearAll(); setActive('true'); } },
        { label:'Unreachable URL', value: (data.kpis.unreachable||0).toLocaleString(), delta:<span style={{color:'var(--hf-err-ink)'}}>URL dead</span>, tone: (data.kpis.unreachable||0) > 0 ? 'err' : undefined,
          onClick: () => { clearAll(); setUrlUnreachable(true); } },
        { label:'Missing ISBN',  value: data.kpis.missing_isbn.toLocaleString(), delta:<span style={{color:'var(--hf-warn-ink)'}}>{data.kpis.total > 0 ? Math.round(data.kpis.missing_isbn/data.kpis.total*100) : 0}%</span>, tone:'warn',
          onClick: () => { clearAll(); setMissing('isbn'); } },
      ]}/>

      <HFCard style={{marginBottom:'var(--hf-gap)', overflow:"visible"}} padding={12}>
        <HFFilterBar right={<>
          <span style={{fontSize:12, color: activeCount? 'var(--hf-accent-ink)' : 'var(--hf-ink4)', fontFamily:'var(--hf-mono)', fontVariantNumeric:'tabular-nums', fontWeight: activeCount? 500 : 400}}>
            {rows.length.toLocaleString()} of {(data.total || 0).toLocaleString()}
          </span>
          {activeCount > 0 && <HFButton size="sm" variant="subtle" onClick={clearAll}>Clear ({activeCount})</HFButton>}
        </>}>
          <HFSearch placeholder="Title, author, ISBN…" width={260} value={q} onChange={setQ}/>
          <HFSearch placeholder="Category…" width={160} value={category} onChange={setCategory}/>
          <HFFilter label="Shop"    value={shop}     options={['all','vaga','knygos']}               onChange={setShop}/>
          <HFFilter label="Active"  value={active}   options={['all','true','false']}                onChange={setActive}/>
          <HFFilter label="Type"    value={bookType} options={['all','book','non_book','audio','ebook']} onChange={setBookType}/>
          <HFFilter label="Missing" value={missing}  options={['any','author','isbn','year','publisher','format','price']} onChange={setMissing} allLabel="any"/>
        </HFFilterBar>
      </HFCard>

      <HFCard>
        {rows.length === 0 ? (
          <div style={{padding:'60px 20px', textAlign:'center', color:'var(--hf-ink3)'}}>
            <div style={{fontSize:28, marginBottom:8, color:'var(--hf-ink5)', display:'flex', justifyContent:'center'}}>{HF_ICONS.search}</div>
            <div style={{fontSize:14, color:'var(--hf-ink)', fontWeight:500, marginBottom:4}}>
              {loading ? 'Loading…' : (data.kpis.total || 0) === 0 ? 'No books yet' : 'No books match these filters'}
            </div>
            {!loading && activeCount > 0 && (
              <HFButton size="sm" onClick={clearAll}>Reset filters</HFButton>
            )}
          </div>
        ) : (
        <HFTable
          onRowClick={(r) => goto('shop-book-detail', { id: r.id })}
          columns={[
            { key:'id', label:'ID', w:'0.5fr', mono:true, sortable:true, sortVal:r=>r.id, cell: v => <span style={{color:'var(--hf-accent-ink)', fontWeight:500}}>#{v}</span> },
            { key:'title', label:'Title', w:'2.4fr', sortable:true, cell: (v,r) => (
              <span style={{display:'flex', flexDirection:'column', gap:2, minWidth:0}}>
                <span style={{color:'var(--hf-ink)', fontWeight:500, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{v}</span>
                <span style={{color:'var(--hf-ink3)', fontSize:12, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{r.author}</span>
              </span>
            )},
            { key:'shop', label:'Shop', w:'0.7fr', sortable:true, cell: v => <span style={{color:'var(--hf-ink)'}}>{v}</span> },
            { key:'isbn', label:'ISBN', w:'1.1fr', mono:true, sortable:true, cell: v => v ? <span style={{color:'var(--hf-ink2)'}}>{v}</span> : <HFPill tone="warn">missing</HFPill> },
            { key:'price', label:'Price', w:'0.7fr', mono:true, align:'right', sortable:true, sortVal:r=>parseFloat((r.price||'').replace(/[^\d.]/g,''))||0, cell: v => <span style={{color: v==='—'? 'var(--hf-ink4)' : 'var(--hf-ink)', fontWeight:500}}>{v}</span> },
            { key:'status', label:'Status', w:'0.8fr', sortable:true, cell: v => <HFPill tone={statusTone[v]}>{v}</HFPill> },
            { key:'updated', label:'Updated', w:'0.8fr', muted:true, mono:true, sortable:true },
            { key:'_', label:'', w:'28px', align:'right', cell: () => <span style={{color:'var(--hf-ink4)', display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
          ]}
          rows={rows}
        />
        )}
      </HFCard>

      {(data.total || 0) > 0 && (
        <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:14, fontSize:13, color:'var(--hf-ink3)'}}>
          <span>
            Showing {((data.page - 1) * data.per_page + 1).toLocaleString()}–
            {Math.min(data.page * data.per_page, data.total).toLocaleString()} of {data.total.toLocaleString()} match{data.total === 1 ? '' : 'es'}
          </span>
          {data.pages > 1 && (
            <div style={{display:'flex', gap:6, alignItems:'center'}}>
              <HFButton size="sm" variant="ghost"
                aria-label="Previous page"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={data.page <= 1}>
                <span aria-hidden="true" style={{display:'flex', transform:'rotate(180deg)'}}>{HF_ICONS.chevron}</span>
                Prev
              </HFButton>
              {(() => {
                const buttons = [];
                const total = data.pages, cur = data.page;
                const push = (n) => buttons.push(
                  <HFButton key={n} size="sm" variant={n === cur ? 'accent' : 'default'}
                    onClick={() => setPage(n)}>{n}</HFButton>
                );
                const ell = (k) => buttons.push(
                  <span key={k} style={{padding:'6px 4px', color:'var(--hf-ink4)'}}>…</span>
                );
                if (total <= 7) {
                  for (let i = 1; i <= total; i++) push(i);
                } else {
                  push(1);
                  if (cur > 4) ell('l');
                  const lo = Math.max(2, cur - 1);
                  const hi = Math.min(total - 1, cur + 1);
                  for (let i = lo; i <= hi; i++) push(i);
                  if (cur < total - 3) ell('r');
                  push(total);
                }
                return buttons;
              })()}
              <HFButton size="sm" variant="ghost"
                aria-label="Next page"
                onClick={() => setPage(p => Math.min(data.pages, p + 1))}
                disabled={data.page >= data.pages}>
                Next
                <span aria-hidden="true" style={{display:'flex'}}>{HF_ICONS.chevron}</span>
              </HFButton>
            </div>
          )}
        </div>
      )}
    </HFShell>
  );
}

// ───────────────────────────── Detail ─────────────────────────────

function HFShopBookDetail({ nav, goto, params }) {
  const HF = getHF();
  const bookId = params?.id;
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [tab, setTab] = React.useState('overview');
  const [rescraping, setRescraping] = React.useState(false);

  React.useEffect(() => {
    if (!bookId) return;
    fetch(`/api/shop-books/${bookId}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [bookId]);

  if (loading || !data) {
    return (
      <HFShell {...nav} activePage="shop-books" title="Book detail" subtitle="Loading…"
        breadcrumb={<><HFBreadcrumbLink page="shop-books" goto={goto}>Shop Books</HFBreadcrumbLink><span>/</span><span>#{bookId}</span></>}>
        <div style={{padding:40, color:'var(--hf-ink3)'}}>Loading…</div>
      </HFShell>
    );
  }

  const id = data.id;
  const priceHistory = data.price_history || [];
  const changes = data.changes || [];
  const issuesList = data.issues_list || [];
  const runs = data.runs || [];
  const priceChanges = changes.filter(c => c.field === 'price');

  const priceNums = priceHistory.map(p => p.price || 0).filter(v => v > 0);
  const priceMin = priceNums.length ? Math.min(...priceNums) : null;
  const priceMax = priceNums.length ? Math.max(...priceNums) : null;

  const rescrape = async () => {
    if (rescraping || !data.url) return;
    setRescraping(true);
    try {
      const resp = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop: data.shop, phase: 'scan', mode: 'full', urls: data.url }),
      });
      if (resp.ok) goto('runs');
    } finally { setRescraping(false); }
  };

  const statusTone = { completed:'neutral', failed:'err', running:'ok', queued:'warn', stopping:'warn' };
  const sevTone = { critical:'err', warning:'warn', info:'neutral' };

  const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString('lt-LT', { year:'numeric', month:'short', day:'numeric' }) : '—';
  const fmtDateShort = (iso) => iso ? new Date(iso).toLocaleDateString('lt-LT', { month:'short', day:'numeric' }) : '';

  return (
    <HFShell {...nav} activePage="shop-books"
      title={<span style={{display:'flex', alignItems:'baseline', gap:12}}>
        <span>{data.title || 'Book detail'}</span>
        <HFPill tone={data.is_active ? 'ok' : 'neutral'}>{data.status || 'unknown'}</HFPill>
      </span>}
      subtitle={<span style={{fontSize:13}}>by {data.author || '—'} · <span style={{fontFamily:'var(--hf-mono)', color:'var(--hf-ink3)'}}>#{id}</span> · shop <span style={{color:'var(--hf-ink2)', fontWeight:500}}>{data.shop}</span></span>}
      breadcrumb={<>
        <HFBreadcrumbLink page="shop-books" goto={goto}>Shop Books</HFBreadcrumbLink>
        <span style={{color:'var(--hf-ink5)'}}>/</span>
        <span style={{color:'var(--hf-ink)', fontWeight:500, fontFamily:'var(--hf-mono)'}}>#{id}</span>
      </>}
      actions={<>
        {data.url && <HFButton onClick={() => window.open(data.url, '_blank')}><span style={{display:'flex'}}>{HF_ICONS.external}</span> Open on {data.shop}.lt</HFButton>}
        <HFButton variant="primary" onClick={rescrape} disabled={rescraping || !data.url}>
          <span style={{display:'flex'}}>{HF_ICONS.refresh}</span> {rescraping ? 'Queuing…' : 'Re-scrape'}
        </HFButton>
      </>}
    >
      {data.url_status === 'unreachable' && (
        <div style={{margin:`0 0 var(--hf-gap)`, padding:'12px 16px', background:'rgba(239,68,68,0.07)', border:'1px solid rgba(239,68,68,0.25)', borderRadius:8}}>
          <div style={{display:'flex', alignItems:'center', gap:10}}>
            <span style={{color:'var(--hf-err)', display:'flex'}}>{HF_ICONS.bang}</span>
            <div style={{flex:1}}>
              <span style={{color:'var(--hf-err-ink)', fontWeight:600, fontSize:13}}>URL is unreachable</span>
              <span style={{color:'var(--hf-ink2)', fontSize:13}}> — failed {data.url_fail_count} time{data.url_fail_count !== 1 ? 's' : ''} in a row. The listing has been marked inactive. It will be retried automatically after 7 days.</span>
            </div>
            <HFButton size="sm" onClick={rescrape} disabled={rescraping || !data.url}>
              {rescraping ? 'Queuing…' : 'Retry now'}
            </HFButton>
          </div>
        </div>
      )}
      <HFKpiStrip items={[
        { label:'Current price', value: data.price || '—', delta:<span style={{color:'var(--hf-ink3)'}}>in shop</span> },
        { label:'Price records', value: String(priceHistory.length), delta:<span style={{color:'var(--hf-ink3)'}}>{priceChanges.length} changes</span> },
        { label:'Issues',        value: String(data.issues || 0), delta:<span style={{color: (data.issues||0) > 0 ? 'var(--hf-warn-ink)' : 'var(--hf-ok-ink)'}}>{(data.issues||0) > 0 ? 'needs attention' : 'all clean'}</span>, tone: (data.issues||0) > 0 ? 'warn' : 'ok',
          ...(data.issues > 0 ? { onClick: () => setTab('issues') } : {}) },
        { label:'Status',  value: data.status || '—', tone: data.is_active ? 'ok' : 'neutral',
          delta:<span style={{color:'var(--hf-ink3)'}}>{data.is_active ? 'active listing' : `last seen ${data.updated || '—'}`}</span> },
        { label:'Last seen', value: data.updated || '—', delta:<span style={{color:'var(--hf-ink3)'}}>in catalog</span> },
      ]}/>

      <HFCard style={{marginBottom:'var(--hf-gap)'}}>
        <div style={{padding:`0 var(--hf-card-p)`}}>
          <HFTabs active={tab} onChange={setTab} tabs={[
            { id:'overview', label:'Overview' },
            { id:'prices',   label:'Prices',   count: priceHistory.length || undefined },
            { id:'changes',  label:'Changes',  count: changes.length || undefined },
            { id:'issues',   label:'Issues',   count: data.issues || undefined },
            { id:'urls',     label:'URLs',     count: data.url_count || undefined },
            { id:'runs',     label:'Runs',     count: data.run_count || undefined },
            { id:'raw',      label:'Raw data' },
          ]}/>
        </div>
      </HFCard>

      {/* ── Overview ── */}
      {tab === 'overview' && <>
      <div style={{display:'grid', gridTemplateColumns:'1.6fr 1fr', gap:'var(--hf-gap)', marginBottom:'var(--hf-gap)'}}>
        {(() => {
          const isFlat = priceNums.length > 0 && priceMin === priceMax;
          return (
            <HFCard title="Price history"
                    sub={isFlat ? `Stable at €${priceMin?.toFixed(2)} · ${priceHistory.length} records` : `${priceHistory.length} data points`}>
              <div style={{padding:`var(--hf-card-p)`}}>
                {priceHistory.length === 0 ? (
                  <div style={{height:140, display:'flex', alignItems:'center', justifyContent:'center', color:'var(--hf-ink4)', fontSize:13}}>No price history yet</div>
                ) : isFlat ? (
                  <div style={{height:140, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', gap:6}}>
                    <div style={{fontSize:28, fontWeight:700, fontFamily:'var(--hf-mono)', color:'var(--hf-ink)', fontVariantNumeric:'tabular-nums'}}>€{priceMin?.toFixed(2)}</div>
                    <div style={{fontSize:12, color:'var(--hf-ink3)', fontFamily:'var(--hf-mono)'}}>
                      unchanged since {fmtDateShort(priceHistory[0]?.scraped_at)}
                    </div>
                    <div style={{width:'100%', height:2, background:'var(--hf-ok)', borderRadius:1, opacity:0.5, marginTop:4}}/>
                  </div>
                ) : (<>
                  <div style={{display:'flex', justifyContent:'space-between', fontSize:11, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)', marginBottom:4}}>
                    <span>€{priceMin?.toFixed(2)} min</span>
                    <span>€{priceMax?.toFixed(2)} max</span>
                  </div>
                  <HFPriceChart priceHistory={priceHistory} h={140}/>
                  <div style={{display:'flex', justifyContent:'space-between', fontSize:11, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)', marginTop:6}}>
                    <span>{fmtDateShort(priceHistory[0]?.scraped_at)}</span>
                    <span>now</span>
                  </div>
                </>)}
              </div>
            </HFCard>
          );
        })()}

        <HFCard title="Metadata" sub="extracted fields">
          <div style={{padding:`2px 0 6px`}}>
            {[
              ['ISBN',        data.isbn || '—',        data.isbn],
              ['Author',      data.author || '—',      data.author],
              ['Publisher',   data.publisher || '—',   data.publisher],
              ['Year',        data.year ? String(data.year) : '—', data.year],
              ['Format',      data.format || '—',      data.format],
              ['In stock',    data.in_stock ? 'yes' : 'no',  data.in_stock !== null],
              ['First seen',  fmtDate(data.first_seen_at),   true],
              ['Last seen',   fmtDate(data.last_seen_at),    true],
            ].map(([k, v, ok], i, arr) => (
              <div key={k} style={{
                display:'grid', gridTemplateColumns:'110px 1fr 14px',
                padding:`7px var(--hf-card-p)`, alignItems:'center',
                borderBottom: i < arr.length-1 ? `1px solid ${'var(--hf-border-faint)'}` : 'none',
                fontSize:13,
              }}>
                <span style={{color:'var(--hf-ink3)', fontFamily:'var(--hf-mono)', fontSize:12}}>{k}</span>
                <span style={{color: v==='—'? 'var(--hf-ink4)' : 'var(--hf-ink)', fontWeight: v==='—'? 400 : 500}}>{v}</span>
                <span style={{color: ok? 'var(--hf-ok)' : 'var(--hf-warn)', display:'flex', justifyContent:'flex-end'}}>
                  {ok ? HF_ICONS.check : HF_ICONS.bang}
                </span>
              </div>
            ))}
          </div>
        </HFCard>
      </div>

      {/* Categories + URL row */}
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:'var(--hf-gap)', marginBottom:'var(--hf-gap)'}}>
        <HFCard title="Categories" sub={`${(data.categories||[]).filter(c=>c.trim()).length} assigned`}>
          {(data.categories||[]).filter(c => c.trim()).length === 0 ? (
            <div style={{padding:`10px var(--hf-card-p)`, color:'var(--hf-ink4)', fontSize:13}}>No categories</div>
          ) : (
            <div style={{padding:`10px var(--hf-card-p)`, display:'flex', flexWrap:'wrap', gap:6}}>
              {data.categories.filter(c => c.trim()).map((c, i) => (
                <HFPill key={i} tone="neutral" style={{fontSize:12}}>{c.trim()}</HFPill>
              ))}
            </div>
          )}
        </HFCard>
        <HFCard title="Source URL" sub="URL for this book">
          {data.url ? (
            <div style={{padding:`10px var(--hf-card-p)`, display:'flex', alignItems:'center', gap:10, fontSize:13}}>
              <span style={{fontFamily:'var(--hf-mono)', fontSize:11, color:'var(--hf-ink2)', flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{data.url}</span>
              <HFPill tone="accent">primary</HFPill>
            </div>
          ) : <div style={{padding:`10px var(--hf-card-p)`, color:'var(--hf-ink4)', fontSize:13}}>No URL available</div>}
        </HFCard>
      </div>

      {/* Description */}
      {data.description && (
        <HFCard title="Description" sub="from shop listing">
          <div style={{padding:`12px var(--hf-card-p)`, fontSize:13, color:'var(--hf-ink2)', lineHeight:1.65, whiteSpace:'pre-wrap', wordBreak:'break-word', maxHeight:220, overflow:'auto'}}>
            {data.description}
          </div>
        </HFCard>
      )}
      </>}

      {/* ── Prices ── */}
      {tab === 'prices' && (<>
        <HFKpiStrip items={[
          { label:'Current',       value: data.price || '—' },
          { label:'All-time low',  value: priceMin != null ? `€${priceMin.toFixed(2)}` : '—', delta:<span style={{color:'var(--hf-ink3)'}}>min recorded</span> },
          { label:'All-time high', value: priceMax != null ? `€${priceMax.toFixed(2)}` : '—', delta:<span style={{color:'var(--hf-ink3)'}}>max recorded</span> },
          { label:'Records',       value: String(priceHistory.length), delta:<span style={{color:'var(--hf-ink3)'}}>{priceChanges.length} price changes</span> },
        ]}/>
        {(() => {
          const isFlat = priceNums.length > 0 && priceMin === priceMax;
          return (
            <HFCard title="Price trajectory"
                    sub={isFlat ? `Stable at €${priceMin?.toFixed(2)} · ${priceHistory.length} records` : `${priceHistory.length} data points`}
                    style={{marginBottom:'var(--hf-gap)'}}>
              <div style={{padding:'var(--hf-card-p)'}}>
                {priceHistory.length === 0 ? (
                  <div style={{height:180, display:'flex', alignItems:'center', justifyContent:'center', color:'var(--hf-ink4)', fontSize:13}}>No price data</div>
                ) : isFlat ? (
                  <div style={{height:180, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', gap:8}}>
                    <div style={{fontSize:36, fontWeight:700, fontFamily:'var(--hf-mono)', color:'var(--hf-ink)', fontVariantNumeric:'tabular-nums'}}>€{priceMin?.toFixed(2)}</div>
                    <div style={{fontSize:13, color:'var(--hf-ink3)'}}>Price unchanged across all {priceHistory.length} scrapes</div>
                    <div style={{fontSize:12, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)'}}>
                      {fmtDateShort(priceHistory[0]?.scraped_at)} → {fmtDateShort(priceHistory[priceHistory.length-1]?.scraped_at)}
                    </div>
                  </div>
                ) : (<>
                  <div style={{display:'flex', justifyContent:'space-between', fontSize:11, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)', marginBottom:4}}>
                    <span>€{priceMin?.toFixed(2)}</span><span>€{priceMax?.toFixed(2)}</span>
                  </div>
                  <HFPriceChart priceHistory={priceHistory} h={180}/>
                  <div style={{display:'flex', justifyContent:'space-between', fontSize:11, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)', marginTop:6}}>
                    <span>{fmtDateShort(priceHistory[0]?.scraped_at)}</span>
                    <span>now</span>
                  </div>
                </>)}
              </div>
            </HFCard>
          );
        })()}
        <HFCard title="All price records" sub={`last ${priceHistory.length} scrapes`}>
          {priceHistory.length === 0
            ? <HFEmptyState title="No prices yet" sub="Run a scrape to collect prices." onClear={null}/>
            : <HFTable
                columns={[
                  { key:'scraped_at', label:'When', w:'1.2fr', mono:true, muted:true, cell: v => fmtDate(v) },
                  { key:'price', label:'Price', w:'0.7fr', mono:true, align:'right', cell: v => <span style={{fontWeight:500}}>{v != null ? `€${v.toFixed(2)}` : '—'}</span> },
                  { key:'in_stock', label:'Stock', w:'0.7fr', align:'right', cell: v => v ? <HFPill tone="ok">in stock</HFPill> : <HFPill tone="neutral">out</HFPill> },
                ]}
                rows={[...priceHistory].reverse()}
              />}
        </HFCard>
      </>)}

      {/* ── Changes ── */}
      {tab === 'changes' && <HFChangesPanel changes={changes} fmtDate={fmtDate}/>}

      {/* ── Issues ── */}
      {tab === 'issues' && (
        <HFCard title="Validation issues" sub={`${issuesList.length} recorded`}>
          {issuesList.length === 0
            ? <HFEmptyState title="No issues" sub="All fields passed validation." onClear={null}/>
            : <HFTable
                columns={[
                  { key:'issue', label:'Issue', w:'1.2fr', mono:true, sortable:true },
                  { key:'field', label:'Field', w:'0.7fr', mono:true, sortable:true, cell: v => <span style={{color:'var(--hf-ink3)'}}>{v || '—'}</span> },
                  { key:'raw_value', label:'Value', w:'1fr', cell: v => <span style={{fontFamily:'var(--hf-mono)', fontSize:12, color:'var(--hf-ink2)'}}>{v ?? '—'}</span> },
                  { key:'severity', label:'Sev.', w:'0.6fr', sortable:true, cell: v => <HFPill tone={sevTone[v]||'neutral'}>{v}</HFPill> },
                  { key:'lifecycle_state', label:'State', w:'0.8fr', sortable:true, cell: v => <HFPill tone={v==='already_seen'?'muted':'warn'}>{v?.replace('_',' ')}</HFPill> },
                ]}
                rows={issuesList}
              />}
        </HFCard>
      )}

      {/* ── URLs ── */}
      {tab === 'urls' && (
        <HFCard title="Source URLs" sub="discovered URLs linked to this book">
          {data.url ? (
            <div style={{padding:`10px var(--hf-card-p)`, display:'flex', alignItems:'center', gap:10, fontSize:13}}>
              <span style={{fontFamily:'var(--hf-mono)', color:'var(--hf-ink2)', flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{data.url}</span>
              <HFPill tone="accent">primary</HFPill>
            </div>
          ) : <HFEmptyState title="No URLs" sub="No URLs linked to this book." onClear={null}/>}
        </HFCard>
      )}

      {/* ── Runs ── */}
      {tab === 'runs' && (
        <HFCard title="Recent runs" sub="runs where this book was scraped">
          {runs.length === 0
            ? <HFEmptyState title="No runs" sub="This book has not been scraped yet." onClear={null}/>
            : <HFTable
                onRowClick={r => goto('run-detail', { id: r.id })}
                columns={[
                  { key:'id', label:'Run', w:'0.5fr', mono:true, sortable:true, sortVal:r=>r.id, cell:v => <span style={{color:'var(--hf-accent-ink)', fontWeight:500}}>#{v}</span> },
                  { key:'phase_type', label:'Phase', w:'1fr', sortable:true, sortVal:r=>r.phase_type+':'+r.phase_mode, cell:(v,r) => (
                    <span style={{display:'flex', flexDirection:'column', gap:3}}>
                      <span style={{fontFamily:'var(--hf-mono)', fontSize:12, color:'var(--hf-ink)', fontWeight:500, textTransform:'capitalize'}}>{v || r.phase}</span>
                      {r.phase_mode && <HFPill tone={v==='scan'?'accent':'neutral'} style={{width:'fit-content', height:16, fontSize:11, padding:'0 5px'}}>{r.phase_mode.replace('_',' ')}</HFPill>}
                    </span>
                  )},
                  { key:'started', label:'Started', w:'0.9fr', mono:true, muted:true, sortable:true },
                  { key:'elapsed', label:'Duration', w:'0.8fr', mono:true, muted:true, align:'right', sortable:true },
                  { key:'items_added', label:'Added', w:'0.5fr', mono:true, align:'right', sortable:true, sortVal:r=>r.items_added, cell:v => v ? <span style={{color:'var(--hf-ok-ink)', fontWeight:500}}>{v}</span> : <span style={{color:'var(--hf-ink4)'}}>—</span> },
                  { key:'items_updated', label:'Updated', w:'0.6fr', mono:true, align:'right', sortable:true, sortVal:r=>r.items_updated, cell:v => v ? <span style={{fontVariantNumeric:'tabular-nums'}}>{v}</span> : <span style={{color:'var(--hf-ink4)'}}>—</span> },
                  { key:'status', label:'Status', w:'0.8fr', sortable:true, cell:v => <HFPill tone={statusTone[v]||'neutral'}>{v}</HFPill> },
                  { key:'_', label:'', w:'28px', align:'right', cell:() => <span style={{color:'var(--hf-ink4)', display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
                ]}
                rows={runs}
              />}
        </HFCard>
      )}

      {/* ── Raw ── */}
      {tab === 'raw' && (
        <HFCard title="Raw extracted data" sub={`API response for book #${id}`}>
          <div style={{padding:14, background:'#0F1419', color:'#D9E0E6', fontFamily:'var(--hf-mono)', fontSize:12, lineHeight:1.65, borderTop:`1px solid ${'var(--hf-border-faint)'}`, borderRadius:`0 0 var(--hf-r3) var(--hf-r3)`, whiteSpace:'pre', overflow:'auto'}}>
            {JSON.stringify(data, null, 2)}
          </div>
        </HFCard>
      )}
    </HFShell>
  );
}

Object.assign(window, { HFShopBooks, HFShopBookDetail });
