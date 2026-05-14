// Hi-fi Books list — canonical catalog (one row per ISBN, aggregated from
// shop-books + ISBN DB enrichment). Distinct from Shop Books (raw per-shop rows).

function HFBooks({ nav, goto }) {
  const HF = getHF();

  // Remote data state
  const [data, setData] = React.useState({ books: [], total: 0, pages: 1 });
  const [loading, setLoading] = React.useState(true);
  const [page, setPage] = React.useState(1);

  // Filter state (server-side filters)
  const [q, setQ] = React.useState('');
  const [enrichedFilter, setEnrichedFilter] = React.useState('any');
  const [linkedFilter, setLinkedFilter] = React.useState('any');
  const [conflictsFilter, setConflictsFilter] = React.useState('any');
  const [isbnFilter, setIsbnFilter] = React.useState('any');
  const [shopsFilter, setShopsFilter] = React.useState('any');

  React.useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams();
    params.set('per_page', '50');
    params.set('page', String(page));
    if (q) params.set('search', q);
    if (enrichedFilter === 'enriched')     params.set('data_source', 'ibiblioteka');
    if (enrichedFilter === 'not enriched') params.set('data_source', 'shop_inferred');
    if (linkedFilter === 'linked')         params.set('has_shops', 'true');
    if (linkedFilter === 'not linked')     params.set('has_shops', 'false');
    if (isbnFilter === 'has ISBN')         params.set('has_isbn', 'true');
    if (isbnFilter === 'missing ISBN')     params.set('has_isbn', 'false');
    fetch(`/api/books?${params}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [q, enrichedFilter, linkedFilter, isbnFilter, page]);

  // Map API rows to JSX shape
  const rows = (data.books || []).map(b => ({
    id:       b.id,
    title:    b.title,
    author:   (b.authors && b.authors[0]) || '',
    isbn:     b.primary_isbn || null,
    shops:    b.shop_count || 0,
    priceMin: null,
    priceMax: null,
    enriched: b.data_source !== 'shop_inferred',
    conflicts: 0,
    updated:  '—',
  }));

  // Client-side filters applied on top of server-filtered rows
  // (conflicts + shops range can't be pushed to API — apply locally)
  const filteredRows = rows.filter(r => {
    if (conflictsFilter === 'clean'         && r.conflicts !== 0) return false;
    if (conflictsFilter === 'has conflicts' && r.conflicts === 0) return false;
    if (shopsFilter === '1 shop only' && r.shops !== 1)                       return false;
    if (shopsFilter === '2-3 shops'   && !(r.shops >= 2 && r.shops <= 3))     return false;
    if (shopsFilter === '4+ shops'    && r.shops < 4)                         return false;
    return true;
  });

  return (
    <HFShell {...nav} activePage="books"
      title="Books" subtitle={`Canonical catalog · ${data.total.toLocaleString()} unique titles aggregated from 5 shops + ISBN DB. ↓ Each book maps to N Shop Books.`}
      breadcrumb={<><span>BookScraper</span><span style={{color:HF.ink5}}>/</span><span style={{color:HF.ink, fontWeight:500}}>Books</span></>}
      actions={<>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.download}</span> Export</HFButton>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.refresh}</span> Re-aggregate</HFButton>
        <HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openAddBook()}><span style={{display:'flex'}}>{HF_ICONS.plus}</span> Add book</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Total titles',     value:data.total.toLocaleString(), delta:<span style={{color:HF.okInk}}>▲ 38 today</span> },
        { label:'Enriched (ISBN-DB)', value:'5,210', delta:<span style={{color:HF.ink3}}>85.0%</span> },
        { label:'Multi-shop',       value:'4,287', delta:<span style={{color:HF.ink3}}>69.9% in 2+ shops</span> },
        { label:'Missing ISBN',     value:'923',  delta:<span style={{color:HF.warnInk}}>15.0%</span>, tone:'warn' },
        { label:'Conflicts',        value:'47',    delta:<span style={{color:HF.errInk}}>needs review</span>, tone:'err' },
      ]}/>

      <HFCard style={{marginBottom:HF.gap, overflow:'visible'}} padding={12}>
        {(() => {
          const activeCount = [
            q !== '',
            enrichedFilter !== 'any',
            linkedFilter !== 'any',
            conflictsFilter !== 'any',
            isbnFilter !== 'any',
            shopsFilter !== 'any',
          ].filter(Boolean).length;
          const clearAll = () => { setQ(''); setEnrichedFilter('any'); setLinkedFilter('any'); setConflictsFilter('any'); setIsbnFilter('any'); setShopsFilter('any'); setPage(1); };
          return (
            <HFFilterBar right={<>
              <span style={{fontSize:11.5, color: activeCount? HF.accentInk : HF.ink4, fontFamily:HF.mono, fontVariantNumeric:'tabular-nums', fontWeight: activeCount? 500 : 400}}>
                {loading ? '…' : `${filteredRows.length} of ${data.total.toLocaleString()}`}
              </span>
              {activeCount > 0 && <HFButton size="sm" variant="subtle" onClick={clearAll}>Clear ({activeCount})</HFButton>}
            </>}>
              <HFSearch placeholder="Search title, author, ISBN…" width={320} value={q} onChange={v => { setQ(v); setPage(1); }}/>
              <HFFilter label="Shops"     value={shopsFilter}     options={['any','1 shop only','2-3 shops','4+ shops']}    onChange={v=>{ setShopsFilter(v); setPage(1); }}     allLabel="any"/>
              <HFFilter label="Enriched"  value={enrichedFilter}  options={['any','enriched','not enriched']}                onChange={v=>{ setEnrichedFilter(v); setPage(1); }}  allLabel="any"/>
              <HFFilter label="ISBN"      value={isbnFilter}      options={['any','has ISBN','missing ISBN']}                onChange={v=>{ setIsbnFilter(v); setPage(1); }}      allLabel="any"/>
              <HFFilter label="Conflicts" value={conflictsFilter} options={['any','clean','has conflicts']}                  onChange={v=>{ setConflictsFilter(v); setPage(1); }} allLabel="any"/>
              <HFFilter label="Linked"    value={linkedFilter}    options={['any','linked','not linked']}                    onChange={v=>{ setLinkedFilter(v); setPage(1); }}    allLabel="any"/>
            </HFFilterBar>
          );
        })()}
      </HFCard>

      <HFCard>
        {loading ? (
          <HFEmptyState title="Loading…" sub="Fetching books from the catalog." />
        ) : filteredRows.length === 0 ? (
          <HFEmptyState title="No books match these filters" sub="Try clearing filters, or adjusting the search." onClear={() => { setQ(''); setEnrichedFilter('any'); setLinkedFilter('any'); setConflictsFilter('any'); setIsbnFilter('any'); setShopsFilter('any'); setPage(1); }}/>
        ) : (
        <HFTable
          onRowClick={(r) => goto('book', { id: r.id })}
          columns={[
            { key:'id', label:'ID', w:'0.5fr', mono:true, sortable:true, sortVal:r=>r.id, cell: v => <span style={{color:HF.accentInk, fontWeight:500}}>#{v}</span> },
            { key:'title', label:'Title', w:'2.4fr', sortable:true, cell: (v, r) => (
              <span style={{display:'flex', flexDirection:'column', gap:2, minWidth:0}}>
                <span style={{display:'flex', alignItems:'center', gap:8, minWidth:0}}>
                  <span style={{color:HF.ink, fontWeight:500, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{v}</span>
                  {r.enriched && <span title="Enriched from ISBN DB" style={{
                    fontFamily: HF.mono, fontSize: 9.5, fontWeight: 600, letterSpacing: 0.4,
                    color: HF.accentInk, background: HF.accentSoft,
                    border: `1px solid ${HF.accentBorder}`,
                    borderRadius: 3, padding: '0 5px', lineHeight: 1.5,
                    flexShrink: 0,
                  }}>ISBN-DB</span>}
                </span>
                <span style={{color:HF.ink3, fontSize:11.5, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{r.author}</span>
              </span>
            )},
            { key:'isbn', label:'ISBN', w:'1.1fr', mono:true, sortable:true, cell: v => v ? <span style={{color:HF.ink2}}>{v}</span> : <HFPill tone="warn">missing</HFPill> },
            { key:'shops', label:'Shops', w:'0.7fr', mono:true, align:'right', sortable:true, sortVal:r=>r.shops, cell: v => (
              <span style={{display:'inline-flex', alignItems:'center', gap:6, fontVariantNumeric:'tabular-nums'}}>
                <span style={{color: v >= 4 ? HF.okInk : v >= 2 ? HF.ink2 : HF.warnInk, fontWeight:500}}>{v}</span>
                <span style={{color:HF.ink4, fontSize:11}}>shops</span>
              </span>
            )},
            { key:'priceRange', label:'Price range', w:'1.2fr', mono:true, align:'right', sortable:true, sortVal:r=>r.priceMin, cell: (_, r) => (
              r.priceMin == null
                ? <span style={{color:HF.ink4}}>—</span>
                : <span style={{display:'inline-flex', alignItems:'baseline', gap:6, fontVariantNumeric:'tabular-nums'}}>
                    <span style={{color:HF.okInk, fontWeight:600}}>€{r.priceMin.toFixed(2)}</span>
                    <span style={{color:HF.ink4}}>—</span>
                    <span style={{color:HF.ink2}}>€{r.priceMax.toFixed(2)}</span>
                    {r.priceMax > r.priceMin && (
                      <span style={{color:HF.ink4, fontSize:11}}>({Math.round((r.priceMax/r.priceMin - 1) * 100)}%)</span>
                    )}
                  </span>
            )},
            { key:'conflicts', label:'Conflicts', w:'0.7fr', mono:true, align:'right', sortable:true, sortVal:r=>r.conflicts, cell: v => v ? <span style={{color:HF.errInk, fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v}</span> : <span style={{color:HF.ink4}}>—</span> },
            { key:'updated', label:'Updated', w:'0.8fr', muted:true, mono:true, sortable:true },
            { key:'_', label:'', w:'28px', align:'right', cell: () => <span style={{color:HF.ink4, display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
          ]}
          rows={filteredRows}
        />
        )}
      </HFCard>

      {(() => {
        const totalPages = data.pages || 1;
        const perPage = 50;
        const start = (page - 1) * perPage + 1;
        const end = Math.min(page * perPage, data.total);
        // Build visible page buttons: always show first, last, current ±1, with ellipsis gaps
        const pageNums = [];
        const addPage = n => { if (n >= 1 && n <= totalPages && !pageNums.includes(n)) pageNums.push(n); };
        addPage(1); addPage(page - 1); addPage(page); addPage(page + 1); addPage(totalPages);
        pageNums.sort((a,b) => a - b);
        const buttons = [];
        pageNums.forEach((n, i) => {
          if (i > 0 && n > pageNums[i-1] + 1) buttons.push('…');
          buttons.push(n);
        });
        return (
          <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:14, fontSize:12.5, color:HF.ink3}}>
            <span>{loading ? '…' : `Showing ${start}–${end} of ${data.total.toLocaleString()}`}</span>
            <div style={{display:'flex', gap:6}}>
              <HFButton size="sm" variant="ghost" onClick={() => setPage(p => Math.max(1, p-1))} disabled={page <= 1}>‹ Prev</HFButton>
              {buttons.map((b, i) => b === '…'
                ? <span key={`ellipsis-${i}`} style={{padding:'6px 4px', color:HF.ink4}}>…</span>
                : <HFButton key={b} size="sm" variant={b === page ? 'accent' : undefined} onClick={() => setPage(b)}>{b}</HFButton>
              )}
              <HFButton size="sm" onClick={() => setPage(p => Math.min(totalPages, p+1))} disabled={page >= totalPages}>Next ›</HFButton>
            </div>
          </div>
        );
      })()}
    </HFShell>
  );
}

Object.assign(window, { HFBooks });
