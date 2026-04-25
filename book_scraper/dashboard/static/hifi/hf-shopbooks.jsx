// Hi-fi Shop Books list + detail

function HFShopBooks({ nav, goto }) {
  const HF = getHF();

  const [data, setData] = React.useState({ books: [], total: 0, kpis: { total: 0, active: 0, missing_isbn: 0, missing_price: 0 } });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch('/api/shop-books?per_page=100')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const rows = data.books;

  const statusTone = { active:'ok', out:'warn', delisted:'neutral' };

  const filters = useHFFilters(rows, {
    search: { fields: r => `${r.id} ${r.title} ${r.author} ${r.isbn||''} ${r.shop}` },
    filters: [
      { id:'shop',   default:'all', options:['all','vaga','knygos'],
        match:(r,v) => r.shop === v },
      { id:'status', default:'all', options:['all','active','out','delisted'],
        match:(r,v) => r.status === v },
      { id:'isbn',   default:'any', options:['any','has ISBN','missing ISBN'],
        match:(r,v) => v==='has ISBN' ? !!r.isbn : !r.isbn },
      { id:'price',  default:'any', options:['any','has price','missing price'],
        match:(r,v) => v==='has price' ? r.price !== '—' : r.price === '—' },
      { id:'issues', default:'any', options:['any','clean','has issues'],
        match:(r,v) => v==='clean' ? r.issues === 0 : r.issues > 0 },
    ],
  });

  return (
    <HFShell {...nav} activePage="shop-books"
      title="Shop Books" subtitle="Every scraped listing from every shop. 18,432 total · 16,201 active."
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
          <span style={{fontSize:11.5, color: filters.activeCount? HF.accentInk : HF.ink4, fontFamily:HF.mono, fontVariantNumeric:'tabular-nums', fontWeight: filters.activeCount? 500 : 400}}>
            {filters.filtered.length} of {rows.length}
          </span>
          {filters.activeCount > 0 && <HFButton size="sm" variant="subtle" onClick={filters.clearAll}>Clear ({filters.activeCount})</HFButton>}
          <HFButton size="sm"><span style={{display:'flex'}}>{HF_ICONS.filter}</span> More filters</HFButton>
        </>}>
          <HFSearch placeholder="Search title, author, ISBN…" width={320} value={filters.q} onChange={filters.setQ}/>
          <HFFilter label="Shop"   value={filters.vals.shop}   options={['all','vaga','knygos']}                onChange={v=>filters.setVal('shop',v)}/>
          <HFFilter label="Status" value={filters.vals.status} options={['all','active','out','delisted']}       onChange={v=>filters.setVal('status',v)} allLabel="all"/>
          <HFFilter label="ISBN"   value={filters.vals.isbn}   options={['any','has ISBN','missing ISBN']}       onChange={v=>filters.setVal('isbn',v)}   allLabel="any"/>
          <HFFilter label="Price"  value={filters.vals.price}  options={['any','has price','missing price']}     onChange={v=>filters.setVal('price',v)}  allLabel="any"/>
          <HFFilter label="Issues" value={filters.vals.issues} options={['any','clean','has issues']}            onChange={v=>filters.setVal('issues',v)} allLabel="any"/>
        </HFFilterBar>
      </HFCard>

      <HFCard>
        {filters.filtered.length === 0 ? (
          <HFEmptyState title="No books match these filters" sub="Try clearing filters, or adjusting the search." onClear={filters.clearAll}/>
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
            { key:'issues', label:'Issues', w:'0.55fr', mono:true, align:'right', sortable:true, sortVal:r=>r.issues, cell: v => v ? <span style={{color:HF.warnInk, fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v}</span> : <span style={{color:HF.ink4}}>—</span> },
            { key:'updated', label:'Updated', w:'0.8fr', muted:true, mono:true, sortable:true },
            { key:'_', label:'', w:'28px', align:'right', cell: () => <span style={{color:HF.ink4, display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
          ]}
          rows={filters.filtered}
        />
        )}
      </HFCard>

      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:14, fontSize:12.5, color:HF.ink3}}>
        <span>Showing 1–12 of 18,432</span>
        <div style={{display:'flex', gap:6}}>
          <HFButton size="sm" variant="ghost">‹ Prev</HFButton>
          <HFButton size="sm" variant="accent">1</HFButton>
          <HFButton size="sm">2</HFButton>
          <HFButton size="sm">3</HFButton>
          <span style={{padding:'6px 4px', color:HF.ink4}}>…</span>
          <HFButton size="sm">1536</HFButton>
          <HFButton size="sm">Next ›</HFButton>
        </div>
      </div>
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
