// Hi-fi URLs list + Shops list + Shop detail

function HFUrls({ nav, goto }) {
  const HF = getHF();

  const rows = [
    { u:'/knygos/sapiens-yuval-noah-harari', shop:'vaga',   status:'ok',    code:200, last:'12m ago', next:'in 48m',  book:'Sapiens' },
    { u:'/knygos/atomic-habits',             shop:'vaga',   status:'ok',    code:200, last:'12m ago', next:'in 48m',  book:'Atomic Habits' },
    { u:'/category/history',                 shop:'vaga',   status:'ok',    code:200, last:'1h ago',  next:'in 11h',  book:'—' },
    { u:'/popular/sapiens',                  shop:'vaga',   status:'error', code:404, last:'3d ago',  next:'paused',  book:'Sapiens (alias)' },
    { u:'/knygos/thinking-fast-and-slow',    shop:'knygos', status:'ok',    code:200, last:'1h ago',  next:'in 11h',  book:'Thinking, Fast…' },
    { u:'/knygos/clean-code',                shop:'vaga',   status:'warn',  code:301, last:'4h ago',  next:'in 20h',  book:'Clean Code' },
    { u:'/authors/ries-eric',                shop:'knygos', status:'ok',    code:200, last:'1h ago',  next:'in 11h',  book:'—' },
    { u:'/knygos/zero-to-one',               shop:'knygos', status:'ok',    code:200, last:'1h ago',  next:'in 11h',  book:'Zero to One' },
    { u:'/promos/summer-2024',               shop:'vaga',   status:'error', code:410, last:'2d ago',  next:'paused',  book:'—' },
    { u:'/knygos/dune',                      shop:'vaga',   status:'ok',    code:200, last:'12m ago', next:'in 48m',  book:'Dune' },
  ];

  const sTone = { ok:'ok', warn:'warn', error:'err' };

  // Derive kind per row
  rows.forEach(r => {
    if (!r.kind) {
      r.kind = r.u.startsWith('/knygos/') ? 'product'
             : r.u.startsWith('/category/') ? 'category'
             : r.u.startsWith('/authors/') ? 'author'
             : r.u.startsWith('/popular/') ? 'alias'
             : r.u.startsWith('/promos/') ? 'promo' : 'other';
    }
  });

  const filters = useHFFilters(rows, {
    search: { fields: r => `${r.u} ${r.shop} ${r.book} ${r.code}` },
    filters: [
      { id:'shop',   default:'all', match:(r,v) => r.shop === v },
      { id:'status', default:'all', match:(r,v) => r.status === v },
      { id:'code',   default:'any',
        match:(r,v) => v==='2xx' ? r.code < 300 : v==='3xx' ? r.code>=300 && r.code<400 : v==='4xx' ? r.code>=400 && r.code<500 : r.code>=500 },
      { id:'kind',   default:'any', match:(r,v) => r.kind === v },
    ],
  });

  return (
    <HFShell {...nav} activePage="urls"
      title="URLs" subtitle="Every URL the scraper visits — seeds, category pages, and product pages."
      breadcrumb={<><span>BookScraper</span><span style={{color:HF.ink5}}>/</span><span style={{color:HF.ink, fontWeight:500}}>URLs</span></>}
      actions={<>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.download}</span> Export</HFButton>
        <HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openAddURL()}><span style={{display:'flex'}}>{HF_ICONS.plus}</span> Add URL</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Total URLs',   value:'24,182', delta:<span style={{color:HF.ink3}}>all shops</span> },
        { label:'Healthy',      value:'23,491', delta:<span style={{color:HF.okInk}}>97.1%</span>, tone:'ok' },
        { label:'Warnings',     value:'441',    delta:<span style={{color:HF.warnInk}}>3xx / slow</span>, tone:'warn' },
        { label:'Broken',       value:'250',    delta:<span style={{color:HF.errInk}}>4xx / 5xx</span>, tone:'err' },
        { label:'Paused',       value:'87',     delta:<span style={{color:HF.ink3}}>manually</span> },
      ]}/>

      <HFCard style={{marginBottom:HF.gap}} padding={12}>
        <HFFilterBar right={<>
          <span style={{fontSize:11.5, color: filters.activeCount? HF.accentInk : HF.ink4, fontFamily:HF.mono, fontVariantNumeric:'tabular-nums', fontWeight: filters.activeCount? 500 : 400}}>
            {filters.filtered.length} of {rows.length}
          </span>
          {filters.activeCount > 0 && <HFButton size="sm" variant="subtle" onClick={filters.clearAll}>Clear ({filters.activeCount})</HFButton>}
          <HFButton size="sm"><span style={{display:'flex'}}>{HF_ICONS.refresh}</span> Recheck all</HFButton>
        </>}>
          <HFSearch placeholder="Search URL, book, shop…" width={300} value={filters.q} onChange={filters.setQ}/>
          <HFFilter label="Shop"   value={filters.vals.shop}   options={['all','vaga','knygos']}            onChange={v=>filters.setVal('shop',v)}/>
          <HFFilter label="Status" value={filters.vals.status} options={['all','ok','warn','error']}         onChange={v=>filters.setVal('status',v)}/>
          <HFFilter label="Code"   value={filters.vals.code}   options={['any','2xx','3xx','4xx','5xx']}     onChange={v=>filters.setVal('code',v)} allLabel="any"/>
          <HFFilter label="Kind"   value={filters.vals.kind}   options={['any','product','category','author','alias','promo']} onChange={v=>filters.setVal('kind',v)} allLabel="any"/>
        </HFFilterBar>
      </HFCard>

      <HFCard>
        {filters.filtered.length === 0 ? (
          <HFEmptyState title="No URLs match these filters" sub="Try clearing filters, or adjusting the search." onClear={filters.clearAll}/>
        ) : (
        <HFTable
          onRowClick={(r) => goto('url-detail', { u: r.u, shop: r.shop, status: r.status, code: r.code })}
          columns={[
            { key:'u', label:'URL', w:'2.5fr', sortable:true, cell:(v,r) => (
              <span style={{display:'flex', alignItems:'center', gap:8, minWidth:0}}>
                <span style={{color:HF.ink3, fontFamily:HF.mono, fontSize:11.5, whiteSpace:'nowrap'}}>{r.shop}.lt</span>
                <span style={{fontFamily:HF.mono, color: r.status==='error'? HF.ink4 : HF.ink2, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', textDecoration: r.status==='error'? 'line-through' : 'none'}}>{v}</span>
              </span>
            )},
            { key:'status', label:'Status', w:'0.8fr', sortable:true, cell:v => <span style={{display:'inline-flex', alignItems:'center', gap:7}}><HFDot tone={sTone[v]}/> <span>{v}</span></span>},
            { key:'code', label:'Code', w:'0.5fr', mono:true, align:'right', sortable:true, sortVal:r=>r.code, cell:v => <span style={{color: v>=400? HF.errInk : v>=300? HF.warnInk : HF.ink2, fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v}</span>},
            { key:'book', label:'Resolves to', w:'1.2fr', muted:true, sortable:true, cell:v => v==='—' ? <span style={{color:HF.ink4}}>—</span> : <span style={{color:HF.ink2}}>{v}</span>},
            { key:'last', label:'Last check', w:'0.9fr', mono:true, muted:true, sortable:true },
            { key:'next', label:'Next', w:'0.9fr', mono:true, muted:true, sortable:true },
            { key:'_', label:'', w:'28px', align:'right', cell: () => <span style={{color:HF.ink4, display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.dots}</span> },
          ]}
          rows={filters.filtered}
        />
        )}
      </HFCard>
    </HFShell>
  );
}

// ─────────────────────────────── Shops list ───────────────────────────────

function HFShops({ nav, goto }) {
  const HF = getHF();

  const shops = [
    { name:'vaga',   tone:'ok',   status:'healthy',  books:15420, active:13892, issues:38,  last:'12m ago', success:98.4, host:'vaga.lt' },
    { name:'knygos', tone:'err',  status:'failing',  books:3012,  active:2309,  issues:229, last:'1h ago',  success:72.1, host:'knygos.lt' },
  ];

  return (
    <HFShell {...nav} activePage="shops"
      title="Shops" subtitle="Each shop is a scrape target with its own parser, schedule, and rate policy."
      breadcrumb={<><span>BookScraper</span><span style={{color:HF.ink5}}>/</span><span style={{color:HF.ink, fontWeight:500}}>Shops</span></>}
      actions={<HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openAddShop()}><span style={{display:'flex'}}>{HF_ICONS.plus}</span> Add shop</HFButton>}
    >
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:HF.gap}}>
        {shops.map(s => (
          <HFCard key={s.name}
            title={<span style={{display:'flex', alignItems:'center', gap:8}}>
              <HFDot tone={s.tone} pulse={s.tone==='err'} size={8}/>
              <span style={{fontSize:15, fontWeight:600}}>{s.host}</span>
              <HFPill tone={s.tone==='ok'?'ok':'err'}>{s.status}</HFPill>
            </span>}
            sub={`${s.books.toLocaleString()} books · last run ${s.last} · ${s.success}% success (7d)`}
            action={<HFButton size="sm" onClick={()=>goto('shop-detail',{name:s.name})}>Open <span style={{display:'flex'}}>{HF_ICONS.arrow}</span></HFButton>}
          >
            <div style={{padding:`${HF.cardP}px`, display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:14}}>
              {[['Books', s.books], ['Active', s.active], ['Issues', s.issues], ['Success', s.success+'%']].map(([l,v]) => (
                <div key={l}>
                  <div style={{fontSize:10.5, color:HF.ink4, textTransform:'uppercase', letterSpacing:0.5, fontWeight:600}}>{l}</div>
                  <div style={{fontFamily:HF.mono, fontSize:18, fontWeight:600, color:HF.ink, marginTop:4, fontVariantNumeric:'tabular-nums', letterSpacing:-0.3}}>
                    {typeof v === 'number' ? v.toLocaleString() : v}
                  </div>
                </div>
              ))}
            </div>
            <div style={{borderTop:`1px solid ${HF.borderFaint}`, padding:`10px ${HF.cardP}px`, display:'flex', gap:8, alignItems:'center', fontSize:11.5, color:HF.ink3, fontFamily:HF.mono}}>
              <span>concurrency=4</span>
              <span style={{color:HF.ink5}}>·</span>
              <span>rate=1/s</span>
              <span style={{color:HF.ink5}}>·</span>
              <span>retry=exp×3</span>
              <span style={{marginLeft:'auto'}}>
                <a href="#" style={hfLink(HF)}>Settings {HF_ICONS.arrow}</a>
              </span>
            </div>
          </HFCard>
        ))}
      </div>
    </HFShell>
  );
}

// ─────────────────────────────── Shop detail ───────────────────────────────

function HFShopDetail({ nav, goto, params }) {
  const HF = getHF();
  const name = params?.name || 'vaga';
  const [tab, setTab] = React.useState('overview');

  const spark = [220, 250, 280, 310, 290, 330, 360, 340, 380, 410, 390, 420, 450, 430];

  return (
    <HFShell {...nav} activePage="shops"
      title={<span style={{display:'flex', alignItems:'center', gap:12}}>
        <HFDot tone="ok" size={10}/>
        <span>{name}.lt</span>
        <HFPill tone="ok">healthy</HFPill>
      </span>}
      subtitle="Scheduled every hour · concurrency 4 · rate 1/s · retry exp×3"
      breadcrumb={<>
        <a href="#" onClick={(e)=>{e.preventDefault(); goto('shops');}} style={{color:HF.ink3, textDecoration:'none'}}>Shops</a>
        <span style={{color:HF.ink5}}>/</span>
        <span style={{color:HF.ink, fontWeight:500}}>{name}</span>
      </>}
      actions={<>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.settings}</span> Settings</HFButton>
        <HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openNewRun()}><span style={{display:'flex'}}>{HF_ICONS.play}</span> Run now</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Books',    value:'15,420', delta:<span style={{color:HF.okInk}}>▲ 94 today</span> },
        { label:'Active',   value:'13,892', delta:<span style={{color:HF.ink3}}>90.1%</span> },
        { label:'URLs',     value:'21,170', delta:<span style={{color:HF.ink3}}>seed+product</span> },
        { label:'Success',  value:'98.4%',  delta:<span style={{color:HF.okInk}}>7d avg</span>, tone:'ok' },
        { label:'Issues',   value:'38',     delta:<span style={{color:HF.warnInk}}>mostly validation</span>, tone:'warn' },
      ]}/>

      <HFCard style={{marginBottom:HF.gap}}>
        <div style={{padding:`0 ${HF.cardP}px`}}>
          <HFTabs active={tab} onChange={setTab} tabs={[
            { id:'overview', label:'Overview' },
            { id:'runs',     label:'Runs', count:184 },
            { id:'urls',     label:'URLs', count:21170 },
            { id:'books',    label:'Books', count:15420 },
            { id:'parser',   label:'Parser config' },
          ]}/>
        </div>
      </HFCard>

      {tab === 'overview' && (
      <div style={{display:'grid', gridTemplateColumns:'1.5fr 1fr', gap:HF.gap}}>
        <HFCard title="Catalog growth" sub="books added per day · last 14 days">
          <div style={{padding:`${HF.cardP}px`}}>
            <HFAreaChart data={spark} h={160}/>
          </div>
        </HFCard>
        <HFCard title="Parser health" sub="field extraction success · 7d">
          <div style={{padding:`6px 0`}}>
            {[
              ['title',     99.8,'ok'],
              ['author',    97.2,'ok'],
              ['price',     95.1,'ok'],
              ['isbn',      81.4,'warn'],
              ['publisher', 72.0,'warn'],
              ['pages',     58.0,'err'],
            ].map(([k,v,t], i, arr) => (
              <div key={k} style={{padding:`10px ${HF.cardP}px`, borderBottom: i<arr.length-1 ? `1px solid ${HF.borderFaint}` : 'none'}}>
                <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:6}}>
                  <span style={{fontFamily:HF.mono, fontSize:12.5, color:HF.ink}}>{k}</span>
                  <span style={{fontFamily:HF.mono, fontSize:12, color: t==='ok'?HF.okInk:t==='warn'?HF.warnInk:HF.errInk, fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v}%</span>
                </div>
                <div style={{height:5, background:HF.subtle, borderRadius:3, overflow:'hidden'}}>
                  <div style={{width:`${v}%`, height:'100%', background: t==='ok'?HF.ok:t==='warn'?HF.warn:HF.err, borderRadius:3}}/>
                </div>
              </div>
            ))}
          </div>
        </HFCard>
      </div>
      )}

      {tab === 'runs'   && <HFRunsPanel goto={goto} scope="shop" entity={name}/>}
      {tab === 'parser' && <HFParserConfigPanel shop={name} scope="shop" goto={goto}/>}

      {tab === 'urls' && (
        <HFCard title="URLs for this shop" sub="sample · open the full URLs list to filter further">
          <HFTable
            onRowClick={r => goto('url-detail', { u:r.u, shop:name, status:r.s, code:r.code })}
            columns={[
              { key:'u', label:'URL', w:'2.5fr', mono:true, sortable:true, cell:(v,r) => <span style={{color: r.s==='error'? HF.ink4 : HF.ink2, textDecoration: r.s==='error'?'line-through':'none'}}>{v}</span> },
              { key:'kind', label:'Kind', w:'0.7fr', mono:true, muted:true, sortable:true },
              { key:'s', label:'Status', w:'0.7fr', sortable:true, cell:v => <HFPill tone={v==='ok'?'ok':v==='warn'?'warn':'err'}>{v}</HFPill> },
              { key:'code', label:'HTTP', w:'0.5fr', mono:true, align:'right', sortable:true, sortVal:r=>r.code, cell:v => <span style={{color: v>=400?HF.errInk:v>=300?HF.warnInk:HF.ink2, fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v}</span> },
              { key:'last', label:'Last check', w:'0.8fr', mono:true, muted:true, sortable:true },
            ]}
            rows={[
              { u:'/knygos/sapiens-yuval-noah-harari', kind:'product',  s:'ok',    code:200, last:'12m ago' },
              { u:'/knygos/atomic-habits',             kind:'product',  s:'ok',    code:200, last:'12m ago' },
              { u:'/category/fiction',                  kind:'category', s:'ok',    code:200, last:'18m ago' },
              { u:'/category/non-fiction',              kind:'category', s:'ok',    code:200, last:'18m ago' },
              { u:'/authors/yuval-noah-harari',         kind:'author',   s:'ok',    code:200, last:'22m ago' },
              { u:'/popular/sapiens',                   kind:'alias',    s:'error', code:404, last:'12m ago' },
              { u:'/knygos/clean-code',                 kind:'product',  s:'warn',  code:301, last:'1h ago'  },
              { u:'/promos/spring-sale',                kind:'promo',    s:'ok',    code:200, last:'2h ago'  },
            ]}
          />
        </HFCard>
      )}

      {tab === 'books' && (
        <HFCard title="Books from this shop" sub="sample · open Shop Books for full list">
          <HFTable
            onRowClick={r => goto('shop-book-detail', { id:r.id })}
            columns={[
              { key:'id', label:'ID', w:'0.5fr', mono:true, sortable:true, sortVal:r=>r.id, cell:v => <span style={{color:HF.accentInk, fontWeight:500}}>#{v}</span> },
              { key:'title', label:'Title', w:'2.2fr', sortable:true, cell:(v,r) => (
                <span style={{display:'flex', flexDirection:'column', gap:2}}>
                  <span style={{color:HF.ink, fontWeight:500, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{v}</span>
                  <span style={{color:HF.ink3, fontSize:11.5}}>{r.author}</span>
                </span>
              )},
              { key:'isbn', label:'ISBN', w:'1.1fr', mono:true, muted:true, sortable:true, cell:v => v ? <span>{v}</span> : <HFPill tone="warn">missing</HFPill> },
              { key:'price', label:'Price', w:'0.7fr', mono:true, align:'right', sortable:true, sortVal:r=>parseFloat((r.price||'').replace(/[^\d.]/g,''))||0, cell:v => <span style={{color:HF.ink, fontWeight:500}}>{v}</span> },
              { key:'updated', label:'Updated', w:'0.8fr', mono:true, muted:true, sortable:true },
            ]}
            rows={[
              { id:10234, title:'Sapiens: A Brief History of Humankind', author:'Yuval Noah Harari',  isbn:'9789955134572', price:'€19.90', updated:'12m ago' },
              { id:10233, title:'Atomic Habits',                         author:'James Clear',         isbn:'9781847941831', price:'€16.50', updated:'12m ago' },
              { id:10231, title:'Lietuvos istorija, t. II',              author:'Edvardas Gudavičius', isbn:null,            price:'€28.00', updated:'18m ago' },
              { id:10229, title:'Dune',                                  author:'Frank Herbert',       isbn:'9780441013593', price:'€14.20', updated:'12m ago' },
              { id:10228, title:'Clean Code',                            author:'Robert C. Martin',    isbn:'9780132350884', price:'€32.90', updated:'4h ago'  },
              { id:10225, title:'Kafka on the Shore',                    author:'Haruki Murakami',     isbn:'9781400079278', price:'€15.40', updated:'18m ago' },
            ]}
          />
        </HFCard>
      )}
    </HFShell>
  );
}

Object.assign(window, { HFUrls, HFShops, HFShopDetail });
