// Hi-fi Books list — canonical catalog (one row per ISBN, aggregated from
// shop-books + ISBN DB enrichment). Distinct from Shop Books (raw per-shop rows).

function HFBooks({ nav, goto }) {
  const HF = getHF();

  // Canonical rows. Each book has: shops_count (how many shops list it),
  // price_min / price_max (range across shops), enriched (ISBN-DB metadata applied).
  const rows = [
    { id:1841, title:'Sapiens: A Brief History of Humankind', author:'Yuval Noah Harari',  isbn:'9789955134572', shops:5, priceMin:18.50, priceMax:21.00, enriched:true,  conflicts:0, updated:'12m ago' },
    { id:1842, title:'Atomic Habits',                         author:'James Clear',        isbn:'9781847941831', shops:4, priceMin:13.40, priceMax:18.90, enriched:true,  conflicts:0, updated:'12m ago' },
    { id:1843, title:'Klara ir Saulė',                        author:'Kazuo Ishiguro',     isbn:'9786094661808', shops:3, priceMin:16.90, priceMax:18.50, enriched:true,  conflicts:1, updated:'1h ago' },
    { id:1844, title:'Thinking, Fast and Slow',               author:'Daniel Kahneman',    isbn:'9780141033570', shops:4, priceMin:19.50, priceMax:24.00, enriched:true,  conflicts:0, updated:'1h ago' },
    { id:1845, title:'Lietuvos istorija jaunimui',            author:'Edvardas Gudavičius',isbn:null,            shops:2, priceMin:11.20, priceMax:14.50, enriched:false, conflicts:0, updated:'18m ago' },
    { id:1846, title:'Mažasis princas',                       author:'Antoine de Saint-Exupéry', isbn:'9786094661105', shops:5, priceMin:8.90,  priceMax:12.99, enriched:true,  conflicts:2, updated:'12m ago' },
    { id:1847, title:'1984',                                  author:'George Orwell',      isbn:'9780451524935', shops:5, priceMin:11.50, priceMax:15.99, enriched:true,  conflicts:0, updated:'12m ago' },
    { id:1848, title:'The Lean Startup',                      author:'Eric Ries',          isbn:'9780307887894', shops:3, priceMin:15.80, priceMax:19.50, enriched:true,  conflicts:0, updated:'1h ago' },
    { id:1849, title:'Dune',                                  author:'Frank Herbert',      isbn:'9780441013593', shops:4, priceMin:12.20, priceMax:16.40, enriched:true,  conflicts:0, updated:'12m ago' },
    { id:1850, title:'Hobitas',                               author:'J.R.R. Tolkien',     isbn:'9786094660914', shops:3, priceMin:14.99, priceMax:17.50, enriched:true,  conflicts:0, updated:'18m ago' },
    { id:1851, title:'Kafka on the Shore',                    author:'Haruki Murakami',    isbn:'9781400079278', shops:2, priceMin:13.40, priceMax:16.90, enriched:true,  conflicts:0, updated:'18m ago' },
    { id:1852, title:'Anykščių šilelis',                      author:'Antanas Baranauskas',isbn:'9786094660921', shops:3, priceMin:6.50,  priceMax:9.40,  enriched:false, conflicts:0, updated:'4h ago' },
    { id:1853, title:'Rugiuose prie bedugnes',                author:'J.D. Salinger',      isbn:'9780316769174', shops:2, priceMin:11.20, priceMax:13.40, enriched:true,  conflicts:0, updated:'1d ago' },
    { id:1854, title:'Educated',                              author:'Tara Westover',      isbn:'9780399590504', shops:3, priceMin:12.90, priceMax:15.50, enriched:true,  conflicts:0, updated:'18m ago' },
    { id:1855, title:'Project Hail Mary',                     author:'Andy Weir',          isbn:'9780593135204', shops:0, priceMin:0,     priceMax:0,     enriched:true,  conflicts:0, updated:'just added' },
    { id:1856, title:'Tyrimo metodologija',                   author:'Vytautas Pranckūnas',isbn:null,            shops:0, priceMin:0,     priceMax:0,     enriched:false, conflicts:0, updated:'2d ago' },
  ];

  const filters = useHFFilters(rows, {
    search: { fields: r => `${r.id} ${r.title} ${r.author} ${r.isbn||''}` },
    filters: [
      { id:'shops',     default:'any', options:['any','1 shop only','2-3 shops','4+ shops'],
        match:(r,v) => v==='1 shop only'? r.shops===1 : v==='2-3 shops'? r.shops>=2 && r.shops<=3 : r.shops>=4 },
      { id:'enriched',  default:'any', options:['any','enriched','not enriched'],
        match:(r,v) => v==='enriched' ? r.enriched : !r.enriched },
      { id:'isbn',      default:'any', options:['any','has ISBN','missing ISBN'],
        match:(r,v) => v==='has ISBN' ? !!r.isbn : !r.isbn },
      { id:'conflicts', default:'any', options:['any','clean','has conflicts'],
        match:(r,v) => v==='clean' ? r.conflicts===0 : r.conflicts>0 },
      { id:'linked',    default:'any', options:['any','linked','not linked'],
        match:(r,v) => v==='linked' ? r.shops > 0 : r.shops === 0 },
    ],
  });

  return (
    <HFShell {...nav} activePage="books"
      title="Books" subtitle="Canonical catalog · 6,133 unique titles aggregated from 5 shops + ISBN DB. ↓ Each book maps to N Shop Books."
      breadcrumb={<><span>BookScraper</span><span style={{color:HF.ink5}}>/</span><span style={{color:HF.ink, fontWeight:500}}>Books</span></>}
      actions={<>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.download}</span> Export</HFButton>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.refresh}</span> Re-aggregate</HFButton>
        <HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openAddBook()}><span style={{display:'flex'}}>{HF_ICONS.plus}</span> Add book</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Total titles',     value:'6,133', delta:<span style={{color:HF.okInk}}>▲ 38 today</span> },
        { label:'Enriched (ISBN-DB)', value:'5,210', delta:<span style={{color:HF.ink3}}>85.0%</span> },
        { label:'Multi-shop',       value:'4,287', delta:<span style={{color:HF.ink3}}>69.9% in 2+ shops</span> },
        { label:'Missing ISBN',     value:'923',  delta:<span style={{color:HF.warnInk}}>15.0%</span>, tone:'warn' },
        { label:'Conflicts',        value:'47',    delta:<span style={{color:HF.errInk}}>needs review</span>, tone:'err' },
      ]}/>

      <HFCard style={{marginBottom:HF.gap, overflow:'visible'}} padding={12}>
        <HFFilterBar right={<>
          <span style={{fontSize:11.5, color: filters.activeCount? HF.accentInk : HF.ink4, fontFamily:HF.mono, fontVariantNumeric:'tabular-nums', fontWeight: filters.activeCount? 500 : 400}}>
            {filters.filtered.length} of {rows.length}
          </span>
          {filters.activeCount > 0 && <HFButton size="sm" variant="subtle" onClick={filters.clearAll}>Clear ({filters.activeCount})</HFButton>}
        </>}>
          <HFSearch placeholder="Search title, author, ISBN…" width={320} value={filters.q} onChange={filters.setQ}/>
          <HFFilter label="Shops"     value={filters.vals.shops}     options={['any','1 shop only','2-3 shops','4+ shops']}    onChange={v=>filters.setVal('shops',v)}     allLabel="any"/>
          <HFFilter label="Enriched"  value={filters.vals.enriched}  options={['any','enriched','not enriched']}                onChange={v=>filters.setVal('enriched',v)}  allLabel="any"/>
          <HFFilter label="ISBN"      value={filters.vals.isbn}      options={['any','has ISBN','missing ISBN']}                onChange={v=>filters.setVal('isbn',v)}      allLabel="any"/>
          <HFFilter label="Conflicts" value={filters.vals.conflicts} options={['any','clean','has conflicts']}                  onChange={v=>filters.setVal('conflicts',v)} allLabel="any"/>
          <HFFilter label="Linked"    value={filters.vals.linked}    options={['any','linked','not linked']}                    onChange={v=>filters.setVal('linked',v)}    allLabel="any"/>
        </HFFilterBar>
      </HFCard>

      <HFCard>
        {filters.filtered.length === 0 ? (
          <HFEmptyState title="No books match these filters" sub="Try clearing filters, or adjusting the search." onClear={filters.clearAll}/>
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
              <span style={{display:'inline-flex', alignItems:'baseline', gap:6, fontVariantNumeric:'tabular-nums'}}>
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
          rows={filters.filtered}
        />
        )}
      </HFCard>

      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:14, fontSize:12.5, color:HF.ink3}}>
        <span>Showing 1–14 of 6,133</span>
        <div style={{display:'flex', gap:6}}>
          <HFButton size="sm" variant="ghost">‹ Prev</HFButton>
          <HFButton size="sm" variant="accent">1</HFButton>
          <HFButton size="sm">2</HFButton>
          <HFButton size="sm">3</HFButton>
          <span style={{padding:'6px 4px', color:HF.ink4}}>…</span>
          <HFButton size="sm">438</HFButton>
          <HFButton size="sm">Next ›</HFButton>
        </div>
      </div>
    </HFShell>
  );
}

Object.assign(window, { HFBooks });
