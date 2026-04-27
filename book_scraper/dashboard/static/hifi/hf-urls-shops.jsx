// Hi-fi URLs list + Shops list + Shop detail

function HFUrls({ nav, goto }) {
  const HF = getHF();
  const sTone = { ok:'ok', warn:'warn', error:'err' };

  // Filter state — backend handles filtering & pagination.
  const [q, setQ]               = React.useState('');
  const [shop, setShop]         = React.useState('all');
  const [urlType, setUrlType]   = React.useState('all');
  const [isBook, setIsBook]     = React.useState('any');
  const [page, setPage]         = React.useState(1);
  const PER_PAGE = 30;

  React.useEffect(() => { setPage(1); }, [q, shop, urlType, isBook]);

  const [data, setData] = React.useState({
    urls: [], total: 0, page: 1, per_page: PER_PAGE, pages: 1,
    stats: { total: 0, in_shop_books: 0, not_in_shop_books: 0, failed: 0 },
  });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({ page: String(page), per_page: String(PER_PAGE) });
    if (q.trim()) params.set('search', q.trim());
    if (shop !== 'all') params.set('shop', shop);
    if (urlType !== 'all') params.set('url_type', urlType);
    if (isBook !== 'any') params.set('is_book', isBook);
    fetch(`/api/urls?${params.toString()}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [q, shop, urlType, isBook, page]);

  const rows = data.urls;
  const urlStats = data.stats;
  const activeCount =
    (q.trim()?1:0) + (shop!=='all'?1:0) + (urlType!=='all'?1:0) + (isBook!=='any'?1:0);
  const clearAll = () => { setQ(''); setShop('all'); setUrlType('all'); setIsBook('any'); };

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
        { label:'Total URLs',  value: urlStats.total.toLocaleString(), delta:<span style={{color:HF.ink3}}>all shops</span> },
        { label:'In catalog',  value: urlStats.in_shop_books.toLocaleString(), delta:<span style={{color:HF.okInk}}>mapped</span>, tone:'ok' },
        { label:'Not scraped', value: urlStats.not_in_shop_books.toLocaleString(), delta:<span style={{color:HF.warnInk}}>pending</span>, tone:'warn' },
        { label:'Failing',     value: urlStats.failed.toLocaleString(), delta:<span style={{color:HF.errInk}}>3+ fails</span>, tone:'err' },
      ]}/>

      <HFCard style={{marginBottom:HF.gap, overflow:"visible"}} padding={12}>
        <HFFilterBar right={<>
          <span style={{fontSize:11.5, color: activeCount? HF.accentInk : HF.ink4, fontFamily:HF.mono, fontVariantNumeric:'tabular-nums', fontWeight: activeCount? 500 : 400}}>
            {rows.length.toLocaleString()} of {(data.total || 0).toLocaleString()}
          </span>
          {activeCount > 0 && <HFButton size="sm" variant="subtle" onClick={clearAll}>Clear ({activeCount})</HFButton>}
        </>}>
          <HFSearch placeholder="Search URL, book, shop…" width={300} value={q} onChange={setQ}/>
          <HFFilter label="Shop"    value={shop}    options={['all','vaga','knygos']}                                          onChange={setShop}/>
          <HFFilter label="Type"    value={urlType} options={['all','product','category','sitemap','unknown']}                onChange={setUrlType}/>
          <HFFilter label="Is book" value={isBook}  options={['any','book','not_book']}                                       onChange={setIsBook} allLabel="any"/>
        </HFFilterBar>
      </HFCard>

      <HFCard>
        {rows.length === 0 ? (
          <div style={{padding:'60px 20px', textAlign:'center', color:HF.ink3}}>
            <div style={{fontSize:28, marginBottom:8, color:HF.ink5, display:'flex', justifyContent:'center'}}>{HF_ICONS.search}</div>
            <div style={{fontSize:14, color:HF.ink, fontWeight:500, marginBottom:4}}>
              {loading ? 'Loading…' : (urlStats.total || 0) === 0 ? 'No URLs yet' : 'No URLs match these filters'}
            </div>
            {!loading && activeCount > 0 && <HFButton size="sm" onClick={clearAll}>Reset filters</HFButton>}
          </div>
        ) : (
        <HFTable
          onRowClick={(r) => goto('url-detail', { id: r.id })}
          columns={[
            { key:'url', label:'URL', w:'2.5fr', sortable:true, cell:(v,r) => {
              const urlStatus = r.fail_count >= 3 ? 'error' : 'ok';
              return (
                <span style={{display:'flex', alignItems:'center', gap:8, minWidth:0}}>
                  <span style={{color:HF.ink3, fontFamily:HF.mono, fontSize:11.5, whiteSpace:'nowrap'}}>{r.shop}.lt</span>
                  <span style={{fontFamily:HF.mono, color: urlStatus==='error'? HF.ink4 : HF.ink2, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', textDecoration: urlStatus==='error'? 'line-through' : 'none'}}>{v}</span>
                </span>
              );
            }},
            { key:'url_type', label:'Type', w:'0.7fr', mono:true, muted:true, sortable:true, cell:v => v || '—' },
            { key:'fail_count', label:'Status', w:'0.7fr', sortable:true, cell:(v,r) => {
              const urlStatus = r.fail_count >= 3 ? 'error' : 'ok';
              return <span style={{display:'inline-flex', alignItems:'center', gap:7}}><HFDot tone={sTone[urlStatus]}/> <span>{urlStatus}</span></span>;
            }},
            { key:'last_scraped_ago', label:'Last check', w:'0.9fr', mono:true, muted:true, sortable:true, cell:v => v || '—' },
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
              <HFButton size="sm" variant="ghost" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={data.page <= 1}>‹ Prev</HFButton>
              {(() => {
                const buttons = [];
                const total = data.pages, cur = data.page;
                const push = (n) => buttons.push(<HFButton key={n} size="sm" variant={n === cur ? 'accent' : 'default'} onClick={() => setPage(n)}>{n}</HFButton>);
                const ell = (k) => buttons.push(<span key={k} style={{padding:'6px 4px', color:HF.ink4}}>…</span>);
                if (total <= 7) { for (let i = 1; i <= total; i++) push(i); }
                else {
                  push(1);
                  if (cur > 4) ell('l');
                  const lo = Math.max(2, cur - 1), hi = Math.min(total - 1, cur + 1);
                  for (let i = lo; i <= hi; i++) push(i);
                  if (cur < total - 3) ell('r');
                  push(total);
                }
                return buttons;
              })()}
              <HFButton size="sm" variant="ghost" onClick={() => setPage(p => Math.min(data.pages, p + 1))} disabled={data.page >= data.pages}>Next ›</HFButton>
            </div>
          )}
        </div>
      )}
    </HFShell>
  );
}

// ─────────────────────────────── Shops list ───────────────────────────────

function HFShops({ nav, goto }) {
  const HF = getHF();
  const [data, setData] = React.useState({ shops: [] });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch('/api/shops')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const rows = data.shops;

  return (
    <HFShell {...nav} activePage="shops"
      title="Shops" subtitle="Each shop is a scrape target with its own parser, schedule, and rate policy."
      breadcrumb={<><span>BookScraper</span><span style={{color:HF.ink5}}>/</span><span style={{color:HF.ink, fontWeight:500}}>Shops</span></>}
      actions={<HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openAddShop()}><span style={{display:'flex'}}>{HF_ICONS.plus}</span> Add shop</HFButton>}
    >
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:HF.gap}}>
        {rows.map(s => {
          const sTone = s.last_run_status === 'completed' ? 'ok' : s.last_run_status === 'failed' ? 'err' : 'neutral';
          const sStatus = s.last_run_status === 'completed' ? 'healthy' : s.last_run_status === 'failed' ? 'failing' : s.last_run_status || 'unknown';
          return (
          <div key={s.name} onClick={() => goto('shop-detail', { name: s.name })} style={{ cursor: 'pointer' }}>
          <HFCard
            title={<span style={{display:'flex', alignItems:'center', gap:8}}>
              <HFDot tone={sTone} pulse={sTone==='err'} size={8}/>
              <span style={{fontSize:15, fontWeight:600}}>{s.name}.lt</span>
              <HFPill tone={sTone==='ok'?'ok':'err'}>{sStatus}</HFPill>
            </span>}
            sub={`${(s.books||0).toLocaleString()} books · last run ${s.last_run_ago || '—'}`}
            action={<HFButton size="sm" onClick={(e)=>{e.stopPropagation(); goto('shop-detail',{name:s.name});}}>Open <span style={{display:'flex'}}>{HF_ICONS.arrow}</span></HFButton>}
          >
            <div style={{padding:`${HF.cardP}px`, display:'grid', gridTemplateColumns:'repeat(2, 1fr)', gap:14}}>
              {[['Books', s.books], ['Active', s.active]].map(([l,v]) => (
                <div key={l}>
                  <div style={{fontSize:10.5, color:HF.ink4, textTransform:'uppercase', letterSpacing:0.5, fontWeight:600}}>{l}</div>
                  <div style={{fontFamily:HF.mono, fontSize:18, fontWeight:600, color:HF.ink, marginTop:4, fontVariantNumeric:'tabular-nums', letterSpacing:-0.3}}>
                    {typeof v === 'number' ? v.toLocaleString() : (v || '—')}
                  </div>
                </div>
              ))}
            </div>
          </HFCard>
          </div>
          );
        })}
      </div>
    </HFShell>
  );
}

// ─────────────────────────────── Shop detail ───────────────────────────────

function HFShopDetail({ nav, goto, params }) {
  const HF = getHF();
  const shopName = params?.name;
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [tab, setTab] = React.useState('overview');
  const [settingsOpen, setSettingsOpen] = React.useState(false);

  React.useEffect(() => {
    if (!shopName) return;
    fetch(`/api/shops/${shopName}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [shopName]);

  if (loading || !data) {
    return (
      <HFShell {...nav} activePage="shops" title="Shop detail" subtitle="Loading…"
        breadcrumb={<><a href="#" onClick={e=>{e.preventDefault();goto('shops');}}>Shops</a><span>/</span><span>{shopName}</span></>}>
        <div style={{padding:40, color:HF.ink3}}>Loading…</div>
      </HFShell>
    );
  }

  const name = data.name || shopName;
  const dTone = data.last_run_status === 'completed' ? 'ok' : data.last_run_status === 'failed' ? 'err' : 'neutral';
  const dStatus = data.last_run_status === 'completed' ? 'healthy' : data.last_run_status === 'failed' ? 'failing' : data.last_run_status || 'unknown';
  const spark = [220, 250, 280, 310, 290, 330, 360, 340, 380, 410, 390, 420, 450, 430];

  return (
    <HFShell {...nav} activePage="shops"
      title={<span style={{display:'flex', alignItems:'center', gap:12}}>
        <HFDot tone={dTone} size={10}/>
        <span>{name}.lt</span>
        <HFPill tone={dTone}>{dStatus}</HFPill>
      </span>}
      subtitle={`${(data.books||0).toLocaleString()} books · last run ${data.last_run_ago || '—'}`}
      breadcrumb={<>
        <a href="#" onClick={(e)=>{e.preventDefault(); goto('shops');}} style={{color:HF.ink3, textDecoration:'none'}}>Shops</a>
        <span style={{color:HF.ink5}}>/</span>
        <span style={{color:HF.ink, fontWeight:500}}>{name}</span>
      </>}
      actions={<>
        <HFButton onClick={() => setSettingsOpen(true)}><span style={{display:'flex'}}>{HF_ICONS.settings}</span> Settings</HFButton>
        <HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openNewRun()}><span style={{display:'flex'}}>{HF_ICONS.play}</span> Run now</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Books',    value: (data.books||0).toLocaleString(), delta:<span style={{color:HF.ink3}}>total</span> },
        { label:'Active',   value: (data.active||0).toLocaleString(), delta:<span style={{color:HF.ink3}}>{data.books > 0 ? Math.round((data.active||0)/data.books*100) : 0}%</span> },
        { label:'Last run', value: data.last_run_ago || '—', delta:<span style={{color:HF.ink3}}>{dStatus}</span>, tone: dTone },
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
            onRowClick={r => goto('url-detail', { id: r.id })}
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
      <HFRateSettingsDialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        shopName={name}
      />

    </HFShell>
  );
}

Object.assign(window, { HFUrls, HFShops, HFShopDetail });
