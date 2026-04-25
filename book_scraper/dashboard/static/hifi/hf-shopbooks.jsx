// Hi-fi Shop Books list + detail

function HFShopBooks({ nav, goto }) {
  const HF = getHF();
  const statusTone = { active:'ok', out:'warn', delisted:'neutral' };

  // Filter state — backend handles filtering and pagination.
  const [q, setQ]                 = React.useState('');
  const [shop, setShop]           = React.useState('all');
  const [active, setActive]       = React.useState('all');     // all | true | false
  const [missing, setMissing]     = React.useState('any');     // any | author | isbn | year | publisher | format
  const [bookType, setBookType]   = React.useState('all');     // all | book | non_book | audio | ebook
  const [hasIsbn, setHasIsbn]     = React.useState('any');     // any | yes
  const [page, setPage]           = React.useState(1);
  const PER_PAGE = 30;

  React.useEffect(() => { setPage(1); }, [q, shop, active, missing, bookType, hasIsbn]);

  const [data, setData] = React.useState({
    books: [], total: 0, page: 1, per_page: PER_PAGE, pages: 1,
    kpis: { total: 0, active: 0, missing_isbn: 0, missing_price: 0 },
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
    if (hasIsbn === 'yes') params.set('has_isbn', 'true');
    fetch(`/api/shop-books?${params.toString()}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [q, shop, active, missing, bookType, hasIsbn, page]);

  const rows = data.books;
  const activeCount =
    (q.trim()?1:0) + (shop!=='all'?1:0) + (active!=='all'?1:0) +
    (missing!=='any'?1:0) + (bookType!=='all'?1:0) + (hasIsbn!=='any'?1:0);

  const clearAll = () => { setQ(''); setShop('all'); setActive('all'); setMissing('any'); setBookType('all'); setHasIsbn('any'); };

  return (
    <HFShell {...nav} activePage="shop-books"
      title="Shop Books" subtitle="Every scraped listing from every shop."
      breadcrumb={<><span>BookScraper</span><span style={{color:HF.ink5}}>/</span><span style={{color:HF.ink, fontWeight:500}}>Shop Books</span></>}
      actions={<>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.download}</span> Export</HFButton>
        <HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openAddBook()}><span style={{display:'flex'}}>{HF_ICONS.plus}</span> Add book</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Total books',   value: data.kpis.total.toLocaleString(), delta:<span style={{color:HF.ink3}}>total</span> },
        { label:'Active',        value: data.kpis.active.toLocaleString(), delta:<span style={{color:HF.ink3}}>{data.kpis.total > 0 ? Math.round(data.kpis.active/data.kpis.total*100) : 0}%</span> },
        { label:'Missing ISBN',  value: data.kpis.missing_isbn.toLocaleString(), delta:<span style={{color:HF.warnInk}}>{data.kpis.total > 0 ? Math.round(data.kpis.missing_isbn/data.kpis.total*100) : 0}%</span>, tone:'warn' },
        { label:'Missing price', value: data.kpis.missing_price.toLocaleString(), delta:<span style={{color:HF.warnInk}}>{data.kpis.total > 0 ? Math.round(data.kpis.missing_price/data.kpis.total*100) : 0}%</span>, tone:'warn' },
      ]}/>

      <HFCard style={{marginBottom:HF.gap, overflow:"visible"}} padding={12}>
        <HFFilterBar right={<>
          <span style={{fontSize:11.5, color: activeCount? HF.accentInk : HF.ink4, fontFamily:HF.mono, fontVariantNumeric:'tabular-nums', fontWeight: activeCount? 500 : 400}}>
            {rows.length.toLocaleString()} of {(data.total || 0).toLocaleString()}
          </span>
          {activeCount > 0 && <HFButton size="sm" variant="subtle" onClick={clearAll}>Clear ({activeCount})</HFButton>}
        </>}>
          <HFSearch placeholder="Search title, author, ISBN…" width={300} value={q} onChange={setQ}/>
          <HFFilter label="Shop"     value={shop}     options={['all','vaga','knygos']}                                  onChange={setShop}/>
          <HFFilter label="Active"   value={active}   options={['all','true','false']}                                   onChange={setActive}/>
          <HFFilter label="Type"     value={bookType} options={['all','book','non_book','audio','ebook']}                onChange={setBookType}/>
          <HFFilter label="Missing"  value={missing}  options={['any','author','isbn','year','publisher','format']}      onChange={setMissing} allLabel="any"/>
          <HFFilter label="ISBN"     value={hasIsbn}  options={['any','yes']}                                            onChange={setHasIsbn} allLabel="any"/>
        </HFFilterBar>
      </HFCard>

      <HFCard>
        {rows.length === 0 ? (
          <div style={{padding:'60px 20px', textAlign:'center', color:HF.ink3}}>
            <div style={{fontSize:28, marginBottom:8, color:HF.ink5, display:'flex', justifyContent:'center'}}>{HF_ICONS.search}</div>
            <div style={{fontSize:14, color:HF.ink, fontWeight:500, marginBottom:4}}>
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
            { key:'id', label:'ID', w:'0.5fr', mono:true, sortable:true, sortVal:r=>r.id, cell: v => <span style={{color:HF.accentInk, fontWeight:500}}>#{v}</span> },
            { key:'title', label:'Title', w:'2.4fr', sortable:true, cell: (v,r) => (
              <span style={{display:'flex', flexDirection:'column', gap:2, minWidth:0}}>
                <span style={{color:HF.ink, fontWeight:500, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{v}</span>
                <span style={{color:HF.ink3, fontSize:11.5, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{r.author}</span>
              </span>
            )},
            { key:'shop', label:'Shop', w:'0.7fr', sortable:true, cell: v => <span style={{color:HF.ink}}>{v}</span> },
            { key:'isbn', label:'ISBN', w:'1.1fr', mono:true, sortable:true, cell: v => v ? <span style={{color:HF.ink2}}>{v}</span> : <HFPill tone="warn">missing</HFPill> },
            { key:'price', label:'Price', w:'0.7fr', mono:true, align:'right', sortable:true, sortVal:r=>parseFloat((r.price||'').replace(/[^\d.]/g,''))||0, cell: v => <span style={{color: v==='—'? HF.ink4 : HF.ink, fontWeight:500}}>{v}</span> },
            { key:'status', label:'Status', w:'0.8fr', sortable:true, cell: v => <HFPill tone={statusTone[v]}>{v}</HFPill> },
            { key:'updated', label:'Updated', w:'0.8fr', muted:true, mono:true, sortable:true },
            { key:'_', label:'', w:'28px', align:'right', cell: () => <span style={{color:HF.ink4, display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
          ]}
          rows={rows}
        />
        )}
      </HFCard>

      {(data.total || 0) > 0 && (
        <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:14, fontSize:12.5, color:HF.ink3}}>
          <span>
            Showing {((data.page - 1) * data.per_page + 1).toLocaleString()}–
            {Math.min(data.page * data.per_page, data.total).toLocaleString()} of {data.total.toLocaleString()} match{data.total === 1 ? '' : 'es'}
          </span>
          {data.pages > 1 && (
            <div style={{display:'flex', gap:6, alignItems:'center'}}>
              <HFButton size="sm" variant="ghost"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={data.page <= 1}>‹ Prev</HFButton>
              {(() => {
                const buttons = [];
                const total = data.pages, cur = data.page;
                const push = (n) => buttons.push(
                  <HFButton key={n} size="sm" variant={n === cur ? 'accent' : 'default'}
                    onClick={() => setPage(n)}>{n}</HFButton>
                );
                const ell = (k) => buttons.push(
                  <span key={k} style={{padding:'6px 4px', color:HF.ink4}}>…</span>
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
                onClick={() => setPage(p => Math.min(data.pages, p + 1))}
                disabled={data.page >= data.pages}>Next ›</HFButton>
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
        breadcrumb={<><a href="#" onClick={e=>{e.preventDefault();goto('shop-books');}}>Shop Books</a><span>/</span><span>#{bookId}</span></>}>
        <div style={{padding:40, color:HF.ink3}}>Loading…</div>
      </HFShell>
    );
  }

  const id = data.id;
  const priceHistory = data.price_history || [];

  return (
    <HFShell {...nav} activePage="shop-books"
      title={<span style={{display:'flex', alignItems:'baseline', gap:12}}>
        <span>{data.title || 'Book detail'}</span>
        <HFPill tone={data.is_active ? 'ok' : 'neutral'}>{data.status || 'unknown'}</HFPill>
      </span>}
      subtitle={<span style={{fontSize:13}}>by {data.author || '—'} · <span style={{fontFamily:HF.mono, color:HF.ink3}}>#{id}</span> · shop <span style={{color:HF.ink2, fontWeight:500}}>{data.shop}</span></span>}
      breadcrumb={<>
        <a href="#" onClick={(e)=>{e.preventDefault(); goto('shop-books');}} style={{color:HF.ink3, textDecoration:'none'}}>Shop Books</a>
        <span style={{color:HF.ink5}}>/</span>
        <span style={{color:HF.ink, fontWeight:500, fontFamily:HF.mono}}>#{id}</span>
      </>}
      actions={<>
        {data.url && <HFButton onClick={() => window.open(data.url, '_blank')}><span style={{display:'flex'}}>{HF_ICONS.external}</span> Open on {data.shop}.lt</HFButton>}
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.refresh}</span> Re-scrape</HFButton>
        <HFButton variant="primary">Edit</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Current price', value: data.price || '—', delta:<span style={{color:HF.ink3}}>current</span> },
        { label:'Issues',        value: String(data.issues || 0), delta:<span style={{color: (data.issues||0) > 0 ? HF.warnInk : HF.okInk}}>{(data.issues||0) > 0 ? 'needs attention' : 'all clean'}</span>, tone: (data.issues||0) > 0 ? 'warn' : 'ok' },
        { label:'Status',        value: data.status || '—', tone: data.is_active ? 'ok' : 'neutral', delta:<span style={{color:HF.ink3}}>listing</span> },
      ]}/>

      <HFCard style={{marginBottom:HF.gap}}>
        <div style={{padding:`0 ${HF.cardP}px`}}>
          <HFTabs active={tab} onChange={setTab} tabs={[
            { id:'overview', label:'Overview' },
            { id:'prices',   label:'Price history', count:127 },
            { id:'urls',     label:'URLs', count:3 },
            { id:'runs',     label:'Runs', count:24 },
            { id:'raw',      label:'Raw data' },
          ]}/>
        </div>
      </HFCard>

      {tab === 'prices' && <HFPricesPanel/>}
      {tab === 'runs'   && <HFRunsPanel goto={goto} scope="book" entity={id}/>}
      {tab === 'urls'   && (
        <HFCard title="Source URLs" sub="all URLs that point to this book">
          {data.url ? (
            <div style={{padding:`10px ${HF.cardP}px`, display:'flex', alignItems:'center', gap:10, fontSize:12.5}}>
              <span style={{fontFamily:HF.mono, color:HF.ink2, flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{data.url}</span>
              <HFPill tone="accent">primary</HFPill>
              <HFPill tone="ok">ok</HFPill>
            </div>
          ) : (
            <HFEmptyState title="No URLs" sub="No URLs available for this book."/>
          )}
        </HFCard>
      )}
      {tab === 'raw' && (
        <HFCard title="Raw extracted data" sub={`API response for book #${id}`}
                action={<HFButton size="sm"><span style={{display:'flex'}}>{HF_ICONS.download}</span> Export JSON</HFButton>}>
          <div style={{padding:14, background:'#0F1419', color:'#D9E0E6', fontFamily:HF.mono, fontSize:11.5, lineHeight:1.65, borderTop:`1px solid ${HF.borderFaint}`, borderRadius:`0 0 ${HF.cardR}px ${HF.cardR}px`, whiteSpace:'pre', overflow:'auto'}}>
            {JSON.stringify(data, null, 2)}
          </div>
        </HFCard>
      )}

      {tab === 'overview' && <>
      <div style={{display:'grid', gridTemplateColumns:'1.6fr 1fr', gap:HF.gap, marginBottom:HF.gap}}>
        <HFCard title="Price history" sub={`${priceHistory.length} data points`}>
          <div style={{padding:`${HF.cardP}px`}}>
            {priceHistory.length > 0 ? (
              <HFAreaChart data={priceHistory.map(p => typeof p === 'number' ? p : p.price || 0)} h={180}/>
            ) : (
              <div style={{height:180, display:'flex', alignItems:'center', justifyContent:'center', color:HF.ink4, fontSize:13}}>No price history yet</div>
            )}
          </div>
        </HFCard>

        <HFCard title="Metadata" sub="extracted fields">
          <div style={{padding:`2px 0 6px`}}>
            {[
              ['ISBN',        data.isbn || '—',        data.isbn ? 'ok' : 'warn'],
              ['Author',      data.author || '—',      data.author ? 'ok' : 'warn'],
              ['Publisher',   data.publisher || '—',   data.publisher ? 'ok' : 'warn'],
              ['Year',        data.year ? String(data.year) : '—', data.year ? 'ok' : 'warn'],
              ['Format',      data.format || '—',      data.format ? 'ok' : 'warn'],
              ['Status',      data.status || '—',      'ok'],
            ].map(([k, v, tone], i, arr) => (
              <div key={k} style={{
                display:'grid', gridTemplateColumns:'110px 1fr 14px',
                padding:`7px ${HF.cardP}px`, alignItems:'center',
                borderBottom: i < arr.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
                fontSize:12.5,
              }}>
                <span style={{color:HF.ink3, fontFamily:HF.mono, fontSize:11.5}}>{k}</span>
                <span style={{color: v==='—'? HF.ink4 : HF.ink, fontWeight: v==='—'? 400 : 500}}>{v}</span>
                <span style={{color: tone==='ok'? HF.ok : HF.warn, display:'flex', justifyContent:'flex-end'}}>
                  {tone==='ok' ? HF_ICONS.check : HF_ICONS.bang}
                </span>
              </div>
            ))}
          </div>
        </HFCard>
      </div>

      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:HF.gap}}>
        <HFCard title="Source URL" sub="URL for this book">
          <div>
            {data.url ? (
              <div style={{
                padding:`10px ${HF.cardP}px`,
                display:'flex', alignItems:'center', gap:10,
                fontSize:12.5,
              }}>
                <span style={{fontFamily:HF.mono, color:HF.ink2, flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{data.url}</span>
                <HFPill tone="accent">primary</HFPill>
                <HFPill tone="ok">ok</HFPill>
              </div>
            ) : (
              <div style={{padding:`10px ${HF.cardP}px`, color:HF.ink4, fontSize:12.5}}>No URL available</div>
            )}
          </div>
        </HFCard>

        <HFCard title="Recent price history" sub="from price records">
          {(priceHistory.length > 0) ? (
            <HFTable
              columns={[
                { key:'scraped_at', label:'When', w:'1fr', muted:true, mono:true, cell: v => v ? new Date(v).toLocaleDateString() : '—' },
                { key:'price', label:'Price', w:'0.8fr', mono:true, align:'right', cell: v => <span style={{color:HF.ink, fontWeight:500}}>{v != null ? `€${v.toFixed(2)}` : '—'}</span> },
                { key:'in_stock', label:'Stock', w:'0.6fr', align:'right', cell: v => v ? <HFPill tone="ok">in stock</HFPill> : <HFPill tone="neutral">out</HFPill> },
              ]}
              rows={priceHistory.slice(0, 5)}
            />
          ) : (
            <div style={{padding:`${HF.cardP}px`, color:HF.ink4, fontSize:12.5}}>No price history yet</div>
          )}
        </HFCard>
      </div>
      </>}
    </HFShell>
  );
}

Object.assign(window, { HFShopBooks, HFShopBookDetail });
