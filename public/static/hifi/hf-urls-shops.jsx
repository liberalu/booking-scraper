
function HFUrls({ nav, goto, params: initParams }) {
  const HF = getHF();
  const sTone = { ok:'ok', warn:'warn', error:'err' };

  const shopNames = useShopNames();
  const [q, setQ]               = React.useState(initParams?.q || '');
  const [shop, setShop]         = React.useState(initParams?.shop || 'all');
  const [urlType, setUrlType]   = React.useState('all');
  const [isBook, setIsBook]     = React.useState('any');
  const [failing, setFailing]   = React.useState(false);
  const [hasBook, setHasBook]   = React.useState(false);
  const [sortBy, setSortBy]     = React.useState('discovered');
  const [sortOrder, setSortOrder] = React.useState('desc');
  const [page, setPage]         = React.useState(1);
  const PER_PAGE = 30;

  React.useEffect(() => { setPage(1); }, [q, shop, urlType, isBook, failing, hasBook, sortBy, sortOrder]);

  const clearAll = () => { setQ(''); setShop('all'); setUrlType('all'); setIsBook('any'); setFailing(false); setHasBook(false); };

  const [data, setData] = React.useState({
    urls: [], total: 0, page: 1, per_page: PER_PAGE, pages: 1,
    stats: { total: 0, in_shop_books: 0, not_in_shop_books: 0, failed: 0 },
  });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({ page: String(page), per_page: String(PER_PAGE), sort_by: sortBy, sort_order: sortOrder });
    if (q.trim()) params.set('search', q.trim());
    if (shop !== 'all') params.set('shop', shop);
    if (urlType !== 'all') params.set('url_type', urlType);
    if (isBook !== 'any') params.set('is_book', isBook);
    if (failing) params.set('failing', 'true');
    if (hasBook) params.set('has_book', 'true');
    fetch(`/api/urls?${params.toString()}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [q, shop, urlType, isBook, failing, hasBook, sortBy, sortOrder, page]);

  const rows = data.urls;
  const urlStats = data.stats;
  const activeCount =
    (q.trim()?1:0) + (shop!=='all'?1:0) + (urlType!=='all'?1:0) + (isBook!=='any'?1:0) + (failing?1:0) + (hasBook?1:0);

  return (
    <HFShell {...nav} activePage="urls"
      title="URLs" subtitle="Every URL the scraper visits — seeds, category pages, and product pages."
      breadcrumb={<><span>BookScraper</span><span style={{color:'var(--hf-ink5)'}}>/</span><span style={{color:'var(--hf-ink)', fontWeight:500}}>URLs</span></>}
      actions={<>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.download}</span> Export</HFButton>
        <HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openAddURL()}><span style={{display:'flex'}}>{HF_ICONS.plus}</span> Add URL</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Total URLs',    value: urlStats.total.toLocaleString(),          delta:<span style={{color:'var(--hf-ink3)'}}>all shops</span>,                      onClick: clearAll },
        { label:'In catalog',   value: urlStats.in_shop_books.toLocaleString(),  delta:<span style={{color:'var(--hf-ok-ink)'}}>matched books</span>,    tone:'ok',  onClick: () => { clearAll(); setHasBook(true); setSortBy('book'); setSortOrder('asc'); } },
        { label:'Not in catalog',value: urlStats.not_in_shop_books.toLocaleString(), delta:<span style={{color:'var(--hf-warn-ink)'}}>unmatched</span>, tone:'warn', onClick: () => { clearAll(); setIsBook('not_book'); } },
        { label:'Failing',       value: urlStats.failed.toLocaleString(),         delta:<span style={{color:'var(--hf-err-ink)'}}>3+ fails</span>,       tone:'err',  onClick: () => { clearAll(); setFailing(true); } },
      ]}/>

      <HFCard style={{marginBottom:'var(--hf-gap)', overflow:"visible"}} padding={12}>
        <HFFilterBar right={<>
          <span style={{fontSize:12, color: activeCount? 'var(--hf-accent-ink)' : 'var(--hf-ink4)', fontFamily:'var(--hf-mono)', fontVariantNumeric:'tabular-nums', fontWeight: activeCount? 500 : 400}}>
            {rows.length.toLocaleString()} of {(data.total || 0).toLocaleString()}
          </span>
          {activeCount > 0 && <HFButton size="sm" variant="subtle" onClick={clearAll}>Clear ({activeCount})</HFButton>}
        </>}>
          <HFSearch placeholder="Search URL, book, shop…" width={300} value={q} onChange={setQ}/>
          <HFFilter label="Shop"    value={shop}    options={shopNames}            onChange={setShop}/>
          <HFFilter label="Type"    value={urlType} options={['all','product','non_product','unknown','unreachable']}    onChange={v => { setUrlType(v); setFailing(false); }}/>
          <HFFilter label="Is book" value={isBook}  options={['any','book','not_book']}                   onChange={setIsBook} allLabel="any"/>
          {failing  && <HFPill tone="err"  style={{cursor:'pointer'}} onClick={() => setFailing(false)}>Failing only ×</HFPill>}
          {hasBook  && <HFPill tone="ok"   style={{cursor:'pointer'}} onClick={() => setHasBook(false)}>Has book ×</HFPill>}
        </HFFilterBar>
      </HFCard>

      <HFCard>
        {rows.length === 0 ? (
          <div style={{padding:'60px 20px', textAlign:'center', color:'var(--hf-ink3)'}}>
            <div style={{fontSize:28, marginBottom:8, color:'var(--hf-ink5)', display:'flex', justifyContent:'center'}}>{HF_ICONS.search}</div>
            <div style={{fontSize:14, color:'var(--hf-ink)', fontWeight:500, marginBottom:4}}>
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
                  <span style={{color:'var(--hf-ink3)', fontFamily:'var(--hf-mono)', fontSize:12, whiteSpace:'nowrap'}}>{r.shop}.lt</span>
                  <span style={{fontFamily:'var(--hf-mono)', color: urlStatus==='error'? 'var(--hf-ink4)' : 'var(--hf-ink2)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', textDecoration: urlStatus==='error'? 'line-through' : 'none'}}>{v}</span>
                </span>
              );
            }},
            { key:'book_title', label:'Book', w:'1.2fr',
              sortable:true,
              sortVal: null,
              onHeaderClick: () => {
                if (sortBy === 'book') setSortOrder(o => o === 'asc' ? 'desc' : 'asc');
                else { setSortBy('book'); setSortOrder('asc'); setHasBook(true); }
              },
              cell:(v,r) => r.book_id
                ? <span onClick={e=>{e.stopPropagation(); goto('shop-book-detail',{id:r.book_id});}}
                    style={{color:'var(--hf-accent-ink)', fontWeight:500, fontSize:12, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', display:'block', cursor:'pointer'}}>
                    {v || `#${r.book_id}`}
                  </span>
                : <span style={{color:'var(--hf-ink4)', fontSize:12}}>—</span> },
            { key:'url_type', label:'Type', w:'0.85fr', sortable:true, cell:v => {
              if (v === 'product')     return <HFPill tone="accent">product</HFPill>;
              if (v === 'non_product') return <HFPill tone="neutral">non-product</HFPill>;
              if (v === 'unreachable') return <HFPill tone="err">unreachable</HFPill>;
              return <HFPill tone="warn">unscanned</HFPill>;
            }},
            { key:'fail_count', label:'Status', w:'0.65fr', sortable:true, cell:(v) => {
              const urlStatus = v >= 3 ? 'error' : 'ok';
              return <span style={{display:'inline-flex', alignItems:'center', gap:7}}><HFDot tone={sTone[urlStatus]}/> <span>{urlStatus}</span></span>;
            }},
            { key:'last_scraped_ago', label:'Last check', w:'0.85fr', mono:true, muted:true, sortable:true, cell:v => v || '—' },
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
                const push = (n) => buttons.push(<HFButton key={n} size="sm" variant={n === cur ? 'accent' : 'default'} onClick={() => setPage(n)}>{n}</HFButton>);
                const ell = (k) => buttons.push(<span key={k} style={{padding:'6px 4px', color:'var(--hf-ink4)'}}>…</span>);
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
      breadcrumb={<><span>BookScraper</span><span style={{color:'var(--hf-ink5)'}}>/</span><span style={{color:'var(--hf-ink)', fontWeight:500}}>Shops</span></>}
      actions={<HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openAddShop()}><span style={{display:'flex'}}>{HF_ICONS.plus}</span> Add shop</HFButton>}
    >
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:'var(--hf-gap)'}}>
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
            <div style={{padding:`var(--hf-card-p)`, display:'grid', gridTemplateColumns:'repeat(2, 1fr)', gap:14}}>
              {[['Books', s.books], ['Active', s.active]].map(([l,v]) => (
                <div key={l}>
                  <div style={{fontSize:11, color:'var(--hf-ink4)', textTransform:'uppercase', letterSpacing:0.5, fontWeight:600}}>{l}</div>
                  <div style={{fontFamily:'var(--hf-mono)', fontSize:18, fontWeight:600, color:'var(--hf-ink)', marginTop:4, fontVariantNumeric:'tabular-nums', letterSpacing:-0.3}}>
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
        breadcrumb={<><HFBreadcrumbLink page="shops" goto={goto}>Shops</HFBreadcrumbLink><span>/</span><span>{shopName}</span></>}>
        <div style={{padding:40, color:'var(--hf-ink3)'}}>Loading…</div>
      </HFShell>
    );
  }

  const name = data.name || shopName;
  const dTone = data.last_run_status === 'completed' ? 'ok' : data.last_run_status === 'failed' ? 'err' : 'neutral';
  const dStatus = data.last_run_status === 'completed' ? 'healthy' : data.last_run_status === 'failed' ? 'failing' : data.last_run_status || 'unknown';

  const [urlsData,  setUrlsData]  = React.useState({ urls: [] });
  const [booksData, setBooksData] = React.useState({ shop_books: [] });
  React.useEffect(() => {
    if (tab === 'urls')
      fetch(`/api/urls?shop=${encodeURIComponent(name)}&per_page=8&sort_by=discovered&sort_order=desc`)
        .then(r => r.json()).then(setUrlsData).catch(() => {});
  }, [tab, name]);
  React.useEffect(() => {
    if (tab === 'books')
      fetch(`/api/shop-books?shop=${encodeURIComponent(name)}&per_page=6`)
        .then(r => r.json()).then(setBooksData).catch(() => {});
  }, [tab, name]);

  return (
    <HFShell {...nav} activePage="shops"
      title={<span style={{display:'flex', alignItems:'center', gap:12}}>
        <HFDot tone={dTone} size={10}/>
        <span>{name}.lt</span>
        <HFPill tone={dTone}>{dStatus}</HFPill>
      </span>}
      subtitle={`${(data.books||0).toLocaleString()} books · last run ${data.last_run_ago || '—'}`}
      breadcrumb={<>
        <HFBreadcrumbLink page="shops" goto={goto}>Shops</HFBreadcrumbLink>
        <span style={{color:'var(--hf-ink5)'}}>/</span>
        <span style={{color:'var(--hf-ink)', fontWeight:500}}>{name}</span>
      </>}
      actions={<>
        <HFButton onClick={() => setSettingsOpen(true)}><span style={{display:'flex'}}>{HF_ICONS.settings}</span> Settings</HFButton>
        <HFButton onClick={async () => {
          const res = await fetch('/api/runs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ shop: name, phase: 'validate' }),
          });
          const d = await res.json();
          if (res.ok) window.alert(`Validate started for ${name}.`);
          else window.alert('Failed: ' + (d.detail || res.status));
        }}>Run validate</HFButton>
        <HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openNewRun()}><span style={{display:'flex'}}>{HF_ICONS.play}</span> Run now</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Books',    value: (data.books||0).toLocaleString(), delta:<span style={{color:'var(--hf-ink3)'}}>total</span> },
        { label:'Active',   value: (data.active||0).toLocaleString(), delta:<span style={{color:'var(--hf-ink3)'}}>{data.books > 0 ? Math.round((data.active||0)/data.books*100) : 0}%</span> },
        { label:'Last run', value: data.last_run_ago || '—', delta:<span style={{color:'var(--hf-ink3)'}}>{dStatus}</span>, tone: dTone },
      ]}/>

      <HFCard style={{marginBottom:'var(--hf-gap)'}}>
        <div style={{padding:`0 var(--hf-card-p)`}}>
          <HFTabs active={tab} onChange={setTab} tabs={[
            { id:'overview', label:'Overview' },
            { id:'runs',     label:'Runs' },
            { id:'urls',     label:'URLs',  count: data.discovered_urls || 0 },
            { id:'books',    label:'Books', count: data.books || 0 },
          ]}/>
        </div>
      </HFCard>

      {tab === 'overview' && (
      <div style={{display:'grid', gridTemplateColumns:'1.5fr 1fr', gap:'var(--hf-gap)'}}>
        <HFCard title="Shop summary" sub="current catalogue counts">
          <div style={{padding:`var(--hf-card-p)`, display:'grid', gridTemplateColumns:'repeat(2,1fr)', gap:20}}>
            {[
              ['Books (total)',    data.books           || 0],
              ['Active',          data.active          || 0],
              ['Discovered URLs', data.discovered_urls || 0],
              ['Price records',   data.prices          || 0],
            ].map(([l, v]) => (
              <div key={l}>
                <div style={{fontSize:11, color:'var(--hf-ink4)', textTransform:'uppercase', letterSpacing:0.5, fontWeight:600, marginBottom:4}}>{l}</div>
                <div style={{fontFamily:'var(--hf-mono)', fontSize:22, fontWeight:600, color:'var(--hf-ink)', fontVariantNumeric:'tabular-nums', letterSpacing:-0.5}}>
                  {v.toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        </HFCard>
        <HFCard title="Field coverage" sub="% of books with this field set">
          <div style={{padding:`6px 0`}}>
            {data.field_stats && data.field_stats.total > 0
              ? Object.entries(data.field_stats.fields).map(([k, f], i, arr) => {
                  const pct = data.field_stats.total > 0 ? (f.present / data.field_stats.total * 100) : 0;
                  const t = pct >= 95 ? 'ok' : pct >= 75 ? 'warn' : 'err';
                  return (
                    <div key={k} style={{padding:`10px var(--hf-card-p)`, borderBottom: i<arr.length-1 ? `1px solid ${'var(--hf-border-faint)'}` : 'none'}}>
                      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:6}}>
                        <span style={{fontFamily:'var(--hf-mono)', fontSize:13, color:'var(--hf-ink)'}}>{k}</span>
                        <span style={{fontFamily:'var(--hf-mono)', fontSize:12, color: t==='ok'?'var(--hf-ok-ink)':t==='warn'?'var(--hf-warn-ink)':'var(--hf-err-ink)', fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{pct.toFixed(1)}%</span>
                      </div>
                      <div style={{height:5, background:'var(--hf-subtle)', borderRadius:3, overflow:'hidden'}}>
                        <div style={{width:`${pct}%`, height:'100%', background: t==='ok'?'var(--hf-ok)':t==='warn'?'var(--hf-warn)':'var(--hf-err)', borderRadius:3}}/>
                      </div>
                    </div>
                  );
                })
              : <div style={{padding:`20px var(--hf-card-p)`, color:'var(--hf-ink4)', fontSize:13}}>No field data yet</div>
            }
          </div>
        </HFCard>
      </div>
      )}

      {tab === 'runs'   && <HFRunsPanel goto={goto} scope="shop" entity={name}/>}

      {tab === 'urls' && (
        <HFCard title="URLs for this shop" sub={`${(urlsData.total||0).toLocaleString()} total · most recent · `+ <span style={{cursor:'pointer',color:'var(--hf-accent-ink)'}} onClick={()=>goto('urls',{shop:name})}>view all →</span>}
          action={<HFButton size="sm" onClick={()=>goto('urls',{})}>View all URLs →</HFButton>}
        >
          <HFTable
            onRowClick={r => goto('url-detail', { id: r.id })}
            columns={[
              { key:'url', label:'URL', w:'2.5fr', mono:true, cell:(v,r) => <span style={{color: r.fail_count>=3? 'var(--hf-ink4)' : 'var(--hf-ink2)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', display:'block', textDecoration: r.fail_count>=3?'line-through':'none'}}>{v}</span> },
              { key:'url_type', label:'Type', w:'0.85fr', cell:v => {
                if (v === 'product')     return <HFPill tone="accent">product</HFPill>;
                if (v === 'non_product') return <HFPill tone="neutral">non-product</HFPill>;
                if (v === 'unreachable') return <HFPill tone="err">unreachable</HFPill>;
                return <HFPill tone="warn">unscanned</HFPill>;
              }},
              { key:'fail_count', label:'Status', w:'0.65fr', cell:v => {
                const s = v >= 3 ? 'error' : 'ok';
                return <span style={{display:'inline-flex', alignItems:'center', gap:7}}><HFDot tone={s==='error'?'err':'ok'}/> <span>{s}</span></span>;
              }},
              { key:'last_scraped_ago', label:'Last check', w:'0.85fr', mono:true, muted:true, cell:v => v || '—' },
            ]}
            rows={urlsData.urls || []}
          />
          {(urlsData.urls||[]).length === 0 && <div style={{padding:'20px', color:'var(--hf-ink4)', fontSize:13, textAlign:'center'}}>No URLs yet</div>}
        </HFCard>
      )}

      {tab === 'books' && (
        <HFCard title="Books from this shop" sub={`${(data.books||0).toLocaleString()} total`}
          action={<HFButton size="sm" onClick={()=>goto('shop-books',{})}>View all books →</HFButton>}
        >
          <HFTable
            onRowClick={r => goto('shop-book-detail', { id:r.id })}
            columns={[
              { key:'id', label:'ID', w:'0.5fr', mono:true, cell:v => <span style={{color:'var(--hf-accent-ink)', fontWeight:500}}>#{v}</span> },
              { key:'title', label:'Title', w:'2.2fr', cell:(v,r) => (
                <span style={{display:'flex', flexDirection:'column', gap:2}}>
                  <span style={{color:'var(--hf-ink)', fontWeight:500, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{v}</span>
                  <span style={{color:'var(--hf-ink3)', fontSize:12}}>{r.author}</span>
                </span>
              )},
              { key:'isbn', label:'ISBN', w:'1.1fr', mono:true, muted:true, cell:v => v ? <span>{v}</span> : <HFPill tone="warn">missing</HFPill> },
              { key:'price', label:'Price', w:'0.7fr', mono:true, align:'right', cell:v => <span style={{color:'var(--hf-ink)', fontWeight:500}}>{v}</span> },
              { key:'updated', label:'Updated', w:'0.8fr', mono:true, muted:true },
            ]}
            rows={booksData.books || []}
          />
          {(booksData.books||[]).length === 0 && <div style={{padding:'20px', color:'var(--hf-ink4)', fontSize:13, textAlign:'center'}}>No books yet</div>}
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
