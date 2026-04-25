// Hi-fi Shop Books list + detail

function HFShopBooks({ nav, goto }) {
  const HF = getHF();

  const rows = [
    { id:10234, title:'Sapiens: A Brief History of Humankind', author:'Yuval Noah Harari',  shop:'vaga',   isbn:'9789955134572', price:'€19.90', status:'active',   issues:0, updated:'12m ago' },
    { id:10233, title:'Atomic Habits',                         author:'James Clear',         shop:'vaga',   isbn:'9781847941831', price:'€16.50', status:'active',   issues:0, updated:'12m ago' },
    { id:10232, title:'Thinking, Fast and Slow',               author:'Daniel Kahneman',     shop:'knygos', isbn:'9780141033570', price:'€21.00', status:'active',   issues:0, updated:'1h ago' },
    { id:10231, title:'Lietuvos istorija, t. II',              author:'Edvardas Gudavičius', shop:'vaga',   isbn:null,            price:'€28.00', status:'active',   issues:2, updated:'18m ago' },
    { id:10230, title:'The Lean Startup',                      author:'Eric Ries',           shop:'knygos', isbn:'9780307887894', price:'€17.80', status:'active',   issues:0, updated:'1h ago' },
    { id:10229, title:'Dune',                                  author:'Frank Herbert',       shop:'vaga',   isbn:'9780441013593', price:'€14.20', status:'active',   issues:0, updated:'12m ago' },
    { id:10228, title:'Clean Code',                            author:'Robert C. Martin',    shop:'vaga',   isbn:'9780132350884', price:'€32.90', status:'out',      issues:1, updated:'4h ago' },
    { id:10227, title:'Pragmatic Programmer, 2ed',             author:'Dave Thomas',         shop:'knygos', isbn:'9780135957059', price:'€29.50', status:'active',   issues:0, updated:'1h ago' },
    { id:10226, title:'Neimaru kam',                           author:'—',                   shop:'knygos', isbn:null,            price:'—',      status:'delisted', issues:3, updated:'2d ago' },
    { id:10225, title:'Kafka on the Shore',                    author:'Haruki Murakami',     shop:'vaga',   isbn:'9781400079278', price:'€15.40', status:'active',   issues:0, updated:'18m ago' },
    { id:10224, title:'Educated',                              author:'Tara Westover',       shop:'vaga',   isbn:'9780399590504', price:'€13.90', status:'active',   issues:0, updated:'18m ago' },
    { id:10223, title:'Zero to One',                           author:'Peter Thiel',         shop:'knygos', isbn:'9780804139298', price:'€18.50', status:'active',   issues:0, updated:'1h ago' },
  ];

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
        { label:'Total books',  value:'18,432', delta:<span style={{color:HF.okInk}}>▲ 124 today</span> },
        { label:'Active',       value:'16,201', delta:<span style={{color:HF.ink3}}>87.9%</span> },
        { label:'Missing ISBN', value:'3,543',  delta:<span style={{color:HF.warnInk}}>19.2%</span>, tone:'warn' },
        { label:'Missing price',value:'892',    delta:<span style={{color:HF.warnInk}}>4.8%</span>, tone:'warn' },
        { label:'Duplicates',   value:'47',     delta:<span style={{color:HF.errInk}}>needs merge</span>, tone:'err' },
      ]}/>

      <HFCard style={{marginBottom:HF.gap}} padding={12}>
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
  const id = params?.id || 10234;
  const [tab, setTab] = React.useState('overview');

  const priceHistory = [19.9, 19.9, 18.5, 18.5, 18.5, 19.5, 19.5, 21.0, 19.9, 19.9, 19.9, 19.9, 18.9, 19.9, 19.9, 19.9, 18.5, 19.9, 19.9, 19.9, 19.9, 18.9, 19.9, 19.9, 19.9, 19.9, 19.9, 19.9, 19.9, 19.9];

  return (
    <HFShell {...nav} activePage="shop-books"
      title={<span style={{display:'flex', alignItems:'baseline', gap:12}}>
        <span>Sapiens: A Brief History of Humankind</span>
        <HFPill tone="ok">active</HFPill>
      </span>}
      subtitle={<span style={{fontSize:13}}>by Yuval Noah Harari · <span style={{fontFamily:HF.mono, color:HF.ink3}}>#{id}</span> · shop <span style={{color:HF.ink2, fontWeight:500}}>vaga</span></span>}
      breadcrumb={<>
        <a href="#" onClick={(e)=>{e.preventDefault(); goto('shop-books');}} style={{color:HF.ink3, textDecoration:'none'}}>Shop Books</a>
        <span style={{color:HF.ink5}}>/</span>
        <span style={{color:HF.ink, fontWeight:500, fontFamily:HF.mono}}>#{id}</span>
      </>}
      actions={<>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.external}</span> Open on vaga.lt</HFButton>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.refresh}</span> Re-scrape</HFButton>
        <HFButton variant="primary">Edit</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Current price', value:'€19.90', delta:<span><span style={{color:HF.errInk}}>▼ €1.10</span><span style={{color:HF.ink3, marginLeft:4}}>vs 30d avg</span></span>, tone:'err' },
        { label:'All-time low',  value:'€18.50', delta:<span style={{color:HF.ink3}}>Mar 22</span> },
        { label:'All-time high', value:'€21.00', delta:<span style={{color:HF.ink3}}>Apr 2</span> },
        { label:'Data points',   value:'127',    delta:<span style={{color:HF.ink3}}>since Feb 18</span> },
        { label:'Issues',        value:'0',      delta:<span style={{color:HF.okInk}}>all clean</span>, tone:'ok' },
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
        <HFCard title="Source URLs" sub="all URLs that point to this book"
                action={<HFButton size="sm" onClick={() => window.HF_APP && window.HF_APP.openAddURL()}><span style={{display:'flex'}}>{HF_ICONS.plus}</span> Add URL</HFButton>}>
          <HFTable
            onRowClick={r => goto('url-detail', { u:r.u, shop:'vaga', status:r.s, code: r.s==='ok'?200:404 })}
            columns={[
              { key:'u', label:'URL', w:'2.4fr', mono:true, sortable:true, cell:(v,r) => (
                <span style={{color: r.s==='ok'? HF.ink2 : HF.ink4, textDecoration: r.s==='ok'? 'none' : 'line-through'}}>vaga.lt{v}</span>
              )},
              { key:'p', label:'Role', w:'0.6fr', sortable:true, cell:v => <HFPill tone={v==='primary'?'accent':'neutral'}>{v}</HFPill> },
              { key:'s', label:'Status', w:'0.6fr', sortable:true, cell:v => <HFPill tone={v==='ok'?'ok':'warn'}>{v}</HFPill> },
              { key:'last', label:'Last check', w:'0.8fr', mono:true, muted:true, sortable:true },
              { key:'hits', label:'Hits 30d', w:'0.6fr', mono:true, align:'right', muted:true, sortable:true, sortVal:r=>r.hits },
            ]}
            rows={[
              { u:'/knygos/sapiens-yuval-noah-harari',    p:'primary', s:'ok',   last:'12m ago', hits:720 },
              { u:'/autoriai/yuval-noah-harari/sapiens',  p:'alias',   s:'ok',   last:'12m ago', hits:318 },
              { u:'/popular/sapiens',                     p:'alias',   s:'warn', last:'3d ago',  hits:0 },
            ]}
          />
        </HFCard>
      )}
      {tab === 'raw' && (
        <HFCard title="Raw extracted data" sub={`JSON response · from run #4820 · 12m ago`}
                action={<HFButton size="sm"><span style={{display:'flex'}}>{HF_ICONS.download}</span> Export JSON</HFButton>}>
          <div style={{padding:14, background:'#0F1419', color:'#D9E0E6', fontFamily:HF.mono, fontSize:11.5, lineHeight:1.65, borderTop:`1px solid ${HF.borderFaint}`, borderRadius:`0 0 ${HF.cardR}px ${HF.cardR}px`, whiteSpace:'pre', overflow:'auto'}}>
{`{
  "id": ${id},
  "shop": "vaga",
  "url": "https://vaga.lt/knygos/sapiens-yuval-noah-harari",
  "scraped_at": "2025-04-19T14:12:04Z",
  "fields": {
    "title":       "Sapiens: A Brief History of Humankind",
    "author":      "Yuval Noah Harari",
    "price":       19.90,
    "old_price":   21.00,
    "currency":    "EUR",
    "isbn":        "9789955134572",
    "publisher":   "Kitos knygos",
    "year":        2019,
    "pages":       null,
    "language":    "EN",
    "binding":     "Paperback",
    "category":    ["History", "Non-fiction"],
    "description": "Sapiens tackles the biggest questions of history and of the modern world..."
  },
  "status":  "active",
  "issues":  [],
  "parser":  "product.v3"
}`}
          </div>
        </HFCard>
      )}

      {tab === 'overview' && <>
      <div style={{display:'grid', gridTemplateColumns:'1.6fr 1fr', gap:HF.gap, marginBottom:HF.gap}}>
        <HFCard title="Price history" sub="last 30 data points · vaga.lt"
                action={<HFPill tone="err">▼ 5.2% vs 30d avg</HFPill>}>
          <div style={{padding:`${HF.cardP}px`}}>
            <HFAreaChart data={priceHistory} h={180}/>
            <div style={{display:'flex', justifyContent:'space-between', fontSize:11, color:HF.ink4, fontFamily:HF.mono, marginTop:8, fontVariantNumeric:'tabular-nums'}}>
              <span>Mar 20</span><span>Mar 30</span><span>Apr 9</span><span>Apr 19</span>
            </div>
          </div>
        </HFCard>

        <HFCard title="Metadata" sub="extracted fields · 9 of 11 complete">
          <div style={{padding:`2px 0 6px`}}>
            {[
              ['ISBN',        '9789955134572', 'ok'],
              ['Author',      'Yuval Noah Harari', 'ok'],
              ['Publisher',   'Kitos knygos', 'ok'],
              ['Year',        '2019', 'ok'],
              ['Pages',       '464', 'ok'],
              ['Language',    'EN', 'ok'],
              ['Binding',     'Paperback', 'ok'],
              ['Weight',      '—', 'warn'],
              ['Dimensions',  '—', 'warn'],
              ['Category',    'History / Non-fiction', 'ok'],
              ['Description', '2,340 chars', 'ok'],
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
        <HFCard title="Source URLs" sub="3 URLs point to this book"
                action={<a href="#" style={hfLink(HF)}>Manage {HF_ICONS.arrow}</a>}>
          <div>
            {[
              { u:'/knygos/sapiens-yuval-noah-harari', p:'primary',   s:'ok',   r:'OK · 12m' },
              { u:'/autoriai/yuval-noah-harari/sapiens', p:'alias',  s:'ok',   r:'OK · 12m' },
              { u:'/popular/sapiens',                    p:'alias',  s:'warn', r:'404 · 3d' },
            ].map((r, i, arr) => (
              <div key={r.u} style={{
                padding:`10px ${HF.cardP}px`,
                borderBottom: i < arr.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
                display:'flex', alignItems:'center', gap:10,
                fontSize:12.5,
              }}>
                <span style={{fontFamily:HF.mono, color: r.s==='ok'? HF.ink2 : HF.ink4, flex:1, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', textDecoration: r.s==='ok'? 'none' : 'line-through'}}>{r.u}</span>
                <HFPill tone={r.p==='primary'?'accent':'neutral'}>{r.p}</HFPill>
                <HFPill tone={r.s==='ok'?'ok':'warn'}>{r.r}</HFPill>
              </div>
            ))}
          </div>
        </HFCard>

        <HFCard title="Recent runs" sub="last 5 scrapes"
                action={<a href="#" style={hfLink(HF)}>All runs {HF_ICONS.arrow}</a>}>
          <HFTable
            columns={[
              { key:'id', label:'Run', w:'0.7fr', mono:true, cell: v => <span style={{color:HF.accentInk, fontWeight:500}}>#{v}</span> },
              { key:'when', label:'When', w:'1fr', muted:true, mono:true },
              { key:'price', label:'Price', w:'0.8fr', mono:true, align:'right', cell: v => <span style={{color:HF.ink, fontWeight:500}}>{v}</span> },
              { key:'delta', label:'Δ', w:'0.6fr', mono:true, align:'right', cell: v => v ? <span style={{color: v.startsWith('-')? HF.errInk : HF.okInk, fontWeight:500}}>{v}</span> : <span style={{color:HF.ink4}}>—</span> },
              { key:'st', label:'Status', w:'0.7fr', cell: v => <HFPill tone={v==='ok'?'ok':'warn'}>{v}</HFPill> },
            ]}
            rows={[
              { id:4820, when:'12m ago',  price:'€19.90', delta:null,    st:'ok' },
              { id:4812, when:'1h ago',   price:'€19.90', delta:'0.00',  st:'ok' },
              { id:4801, when:'5h ago',   price:'€19.90', delta:'0.00',  st:'ok' },
              { id:4788, when:'12h ago',  price:'€19.90', delta:'-1.10', st:'ok' },
              { id:4770, when:'1d ago',   price:'€21.00', delta:'+1.10', st:'ok' },
            ]}
          />
        </HFCard>
      </div>
      </>}
    </HFShell>
  );
}

Object.assign(window, { HFShopBooks, HFShopBookDetail });
