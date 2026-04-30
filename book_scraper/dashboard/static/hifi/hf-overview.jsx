// Hi-fi Overview — light mode, Retool/Metabase-feel

function HFOverview({ nav, goto }) {
  const HF = getHF();
  const { collapsed, setCollapsed } = nav;

  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [refreshing, setRefreshing] = React.useState(false);

  // Shared loader — used for the initial mount fetch and the manual
  // Refresh button. `manual=true` toggles the toast feedback so the
  // first paint stays silent.
  const loadOverview = React.useCallback((manual = false) => {
    setRefreshing(true);
    fetch('/api/overview')
      .then(r => r.ok ? r.json() : r.text().then(t => { throw new Error(t || r.statusText); }))
      .then(d => {
        setData(d);
        setLoading(false);
        if (manual && window.HF_APP && window.HF_APP.toast) {
          window.HF_APP.toast({ tone: 'ok', message: 'Overview refreshed' });
        }
      })
      .catch(e => {
        setLoading(false);
        if (window.HF_APP && window.HF_APP.toast) {
          window.HF_APP.toast({
            tone: 'err',
            message: 'Refresh failed',
            detail: String(e.message || e),
          });
        }
      })
      .finally(() => setRefreshing(false));
  }, []);

  React.useEffect(() => { loadOverview(false); }, [loadOverview]);

  if (loading || !data) {
    return (
      <HFShell collapsed={collapsed} setCollapsed={setCollapsed} activePage="overview"
        title="Overview"
        subtitle="Health, catalog coverage, and recent scrape activity across all shops."
        breadcrumb={<span>Overview</span>}
        setPage={nav.setPage}>
        <HFKpiStripSkeleton count={5}/>
        <div style={{ display: 'grid', gridTemplateColumns: '1.55fr 1fr', gap: 'var(--hf-gap)', marginBottom: 'var(--hf-gap)' }}>
          <HFCard title="Scrape activity" sub="loading…">
            <div style={{padding: 'var(--hf-card-p)'}}>
              <HFSkeleton w={140} h={26} style={{ marginBottom: 14 }}/>
              <HFSkeleton w="100%" h={100}/>
            </div>
          </HFCard>
          <HFCard title="Metadata completeness" sub="loading…">
            <div style={{padding: 'var(--hf-card-p)'}}>
              {[0,1,2,3].map(i => (
                <div key={i} style={{ padding: '8px 0', borderBottom: i < 3 ? `1px solid ${'var(--hf-border-faint)'}` : 'none' }}>
                  <div style={{ display:'flex', justifyContent:'space-between', marginBottom: 6 }}>
                    <HFSkeleton w={70} h={12}/>
                    <HFSkeleton w={32} h={12}/>
                  </div>
                  <HFSkeleton w="100%" h={6} br={3}/>
                </div>
              ))}
            </div>
          </HFCard>
        </div>
        <HFCard title="Recent runs" sub="loading…" style={{ marginBottom: 'var(--hf-gap)' }}>
          <HFTableSkeleton rows={5} columns={[
            { w: '0.6fr', skelW: 40, mono: true },
            { w: '0.8fr', skelW: 60 },
            { w: '0.8fr', skelW: 60 },
            { w: '1fr',   skelW: 80 },
            { w: '1.6fr', skelW: 200 },
            { w: '0.7fr', skelW: 50, align: 'right' },
            { w: '0.6fr', skelW: 60, align: 'right' },
            { w: '40px',  skelW: 12, align: 'right' },
          ]}/>
        </HFCard>
      </HFShell>
    );
  }

  const buildPath = window.HF_BUILD_PATH || (() => '#');
  const stats = data.stats;
  const kpis = [
    { label: 'Shop books',      value: stats.total_shop_books.toLocaleString(),  delta: <span style={{color:'var(--hf-ink3)'}}>total</span>,
      href: buildPath('shop-books'), onClick: () => goto('shop-books') },
    { label: 'Active listings', value: stats.active_shop_books.toLocaleString(), delta: <span style={{color:'var(--hf-ink3)'}}>{stats.total_shop_books > 0 ? Math.round(stats.active_shop_books/stats.total_shop_books*100) : 0}% of total</span>,
      href: buildPath('shop-books'), onClick: () => goto('shop-books') },
    { label: 'With ISBN',       value: stats.with_isbn.toLocaleString(),          delta: <span style={{color:'var(--hf-ink3)'}}>{stats.total_shop_books > 0 ? Math.round(stats.with_isbn/stats.total_shop_books*100) : 0}% coverage</span>,
      href: buildPath('shop-books'), onClick: () => goto('shop-books') },
    { label: 'Price records',   value: stats.total_prices.toLocaleString(),       delta: <span style={{color:'var(--hf-ink3)'}}>total</span>, tone:'ok',
      href: buildPath('prices'), onClick: () => goto('prices') },
    { label: 'Open issues',     value: stats.open_issues.toLocaleString(),        delta: <span style={{color:'var(--hf-ink3)'}}>open</span>, tone: stats.open_issues > 0 ? 'warn' : 'ok',
      href: buildPath('issues'), onClick: () => goto('issues') },
  ];
  const spark = data.activity || [];
  const completeness = data.completeness.map(c => [c.field.charAt(0).toUpperCase() + c.field.slice(1), c.pct]);
  const statusTone = { running: 'ok', completed: 'neutral', failed: 'err' };
  const runs = data.recent_runs;
  const clusters = data.issue_clusters.map(c => ({ type: c.issue_type, n: c.count, tone: c.count > 100 ? 'err' : 'warn' }));
  const shopCards = data.shops;

  return (
    <HFShell
      collapsed={collapsed} setCollapsed={setCollapsed} setPage={nav.setPage}
      activePage="overview"
      title="Overview"
      subtitle="Health, catalog coverage, and recent scrape activity across all shops."
      breadcrumb={<>
        <span style={{ color: 'var(--hf-ink3)' }}>BookScraper</span>
        <span style={{ color: 'var(--hf-ink5)' }}>/</span>
        <span style={{ color: 'var(--hf-ink)', fontWeight: 500 }}>Overview</span>
      </>}
      actions={<>
        <HFButton disabled={refreshing} onClick={() => loadOverview(true)}>
          <span style={{display:'flex'}}>{HF_ICONS.refresh}</span>
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </HFButton>
        <HFButton>Last 7 days <span style={{display:'flex', opacity:.7}}>{HF_ICONS.chevronD}</span></HFButton>
      </>}
    >
      {/* KPI strip */}
      <HFKpiStrip items={kpis}/>

      {/* Activity + Completeness */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.55fr 1fr', gap: 'var(--hf-gap)', marginBottom: 'var(--hf-gap)' }}>
        <HFCard title="Scrape activity" sub={`items scraped per day · last ${spark.length || 14} days`}
                action={<a href={buildPath('runs')} className="hf-link" style={hfLink(HF)} onClick={(e)=>{if(e.metaKey||e.ctrlKey||e.shiftKey)return;e.preventDefault();goto('runs');}}>View runs {HF_ICONS.arrow}</a>}>
          <div style={{ padding: `14px var(--hf-card-p) var(--hf-card-p)` }}>
            {(() => {
              const last7 = spark.slice(-7);
              const prev7 = spark.slice(-14, -7);
              const sumLast = last7.reduce((s, n) => s + n, 0);
              const sumPrev = prev7.reduce((s, n) => s + n, 0);
              const pct = sumPrev > 0 ? Math.round(((sumLast - sumPrev) / sumPrev) * 100) : null;
              const pctTone = pct == null ? 'neutral' : pct >= 0 ? 'ok' : 'err';
              const pctText = pct == null ? '—' : `${pct >= 0 ? '+' : ''}${pct}% vs prev`;
              const days = spark.length;
              const today = new Date();
              const fmt = (d) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
              const labelAt = (offsetFromNewest) => {
                const d = new Date(today);
                d.setDate(d.getDate() - offsetFromNewest);
                return fmt(d);
              };
              const labels = days >= 4
                ? [labelAt(days - 1), labelAt(Math.floor((days - 1) * 2 / 3)), labelAt(Math.floor((days - 1) / 3)), labelAt(0)]
                : [];
              return (
                <>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
                    <span style={{ fontFamily: 'var(--hf-mono)', fontSize: 26, fontWeight: 600, letterSpacing: -0.5, color: 'var(--hf-ink)', fontVariantNumeric:'tabular-nums' }}>{sumLast.toLocaleString()}</span>
                    <span style={{ fontSize: 13, color: 'var(--hf-ink3)' }}>items this week</span>
                    {pct != null && <span style={{ marginLeft: 'auto' }}><HFPill tone={pctTone}>{pctText}</HFPill></span>}
                  </div>
                  <HFSparkBars data={spark} h={100} label="Items scraped per day"/>
                  {labels.length > 0 && (
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--hf-ink4)', fontFamily: 'var(--hf-mono)', marginTop: 8, fontVariantNumeric:'tabular-nums' }}>
                      {labels.map((l, i) => <span key={i}>{l}</span>)}
                    </div>
                  )}
                </>
              );
            })()}
          </div>
        </HFCard>

        <HFCard title="Metadata completeness" sub="field coverage · active listings"
                action={<a href={buildPath('shop-books')} style={hfLink(HF)} onClick={(e)=>{if(e.metaKey||e.ctrlKey||e.shiftKey)return;e.preventDefault();goto('shop-books');}}>View books {HF_ICONS.arrow}</a>}>
          <div style={{ padding: `10px var(--hf-card-p) 14px` }}>
            {completeness.map(([field, p], i) => (
              <div key={field} style={{ padding: '8px 0', borderBottom: i < completeness.length - 1 ? `1px solid ${'var(--hf-border-faint)'}` : 'none' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <span style={{ fontSize: 13, color: 'var(--hf-ink)', fontWeight: 500 }}>{field}</span>
                  <span style={{ fontFamily: 'var(--hf-mono)', fontSize: 12, color: p >= 80 ? 'var(--hf-ok-ink)' : p >= 60 ? 'var(--hf-ink2)' : 'var(--hf-warn-ink)', fontVariantNumeric:'tabular-nums', fontWeight:500 }}>{p}%</span>
                </div>
                <div style={{ height: 6, background: 'var(--hf-subtle)', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{
                    width: `${p}%`, height: '100%',
                    background: p >= 80 ? 'var(--hf-ok)' : p >= 60 ? 'var(--hf-accent)' : 'var(--hf-warn)',
                    borderRadius: 3,
                  }}/>
                </div>
              </div>
            ))}
          </div>
        </HFCard>
      </div>

      {/* Recent runs */}
      <HFCard title="Recent runs" sub="live + last 24 hours"
              action={<a href={buildPath('runs')} style={hfLink(HF)} onClick={(e)=>{if(e.metaKey||e.ctrlKey||e.shiftKey)return;e.preventDefault();goto('runs');}}>All runs {HF_ICONS.arrow}</a>}
              style={{ marginBottom: 'var(--hf-gap)' }}>
        <HFTable
          onRowClick={(r) => goto('run-detail', { id: r.id })}
          columns={[
            { key:'id', label:'Run', w:'0.6fr', mono:true, cell: v => <span style={{color: 'var(--hf-ink)', fontWeight:500}}>#{v}</span> },
            { key:'shop', label:'Shop', w:'0.8fr', cell: v => <span style={{color: 'var(--hf-ink)'}}>{v}</span> },
            { key:'phase', label:'Phase', w:'0.8fr', mono:true, muted:true },
            { key:'status', label:'Status', w:'1fr', cell: v => <span style={{display:'inline-flex', alignItems:'center', gap:7}}><HFDot tone={statusTone[v]} pulse={v==='running'}/> <span style={{color: v==='failed'? 'var(--hf-err-ink)' : 'var(--hf-ink)', fontWeight: v==='running'? 500 : 400}}>{v}</span></span> },
            { key:'progress', label:'Progress', w:'1.6fr', cell: (v, r) => (
              <span style={{display:'flex', alignItems:'center', gap:10, width:'100%'}}>
                <span style={{flex:1, maxWidth: 200, height: 6, background: 'var(--hf-subtle)', borderRadius: 3, overflow:'hidden'}}>
                  <span style={{display:'block', width:`${v}%`, height:'100%', background: r.status==='failed'? 'var(--hf-err)' : r.status==='running'? 'var(--hf-accent)' : 'var(--hf-ink4)', borderRadius:3}}/>
                </span>
                <span style={{fontFamily:'var(--hf-mono)', fontSize:12, color:'var(--hf-ink3)', minWidth:32, fontVariantNumeric:'tabular-nums'}}>{v}%</span>
              </span>
            )},
            { key:'items', label:'Items', w:'0.7fr', mono:true, align:'right', cell: v => v.toLocaleString() },
            { key:'elapsed', label:'Elapsed', w:'0.6fr', mono:true, muted:true, align:'right' },
            { key:'chev', label:'', w:'40px', align:'right', cell: () => <span style={{color: 'var(--hf-ink4)', display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
          ]}
          rows={runs}
        />
      </HFCard>

      {/* Issue clusters + By shop */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: 'var(--hf-gap)' }}>
        <HFCard title="Needs attention" sub="open validation clusters · click to triage"
                action={<a href={buildPath('issues')} style={hfLink(HF)} onClick={(e)=>{if(e.metaKey||e.ctrlKey||e.shiftKey)return;e.preventDefault();goto('issues');}}>All issues {HF_ICONS.arrow}</a>}>
          <div style={{ padding: `var(--hf-card-p)`, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {clusters.map(c => (
              <a key={c.type} href={buildPath('issues')} className="hf-row"
                 onClick={(e) => { if(e.metaKey||e.ctrlKey||e.shiftKey)return; e.preventDefault(); goto('issues', { type: c.type }); }}
                 aria-label={`${c.type}: ${c.n} issues`}
                 style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '10px 12px',
                borderRadius: 6,
                background: 'var(--hf-bg)',
                border: `1px solid ${'var(--hf-border)'}`,
                textDecoration: 'none', color: 'var(--hf-ink)',
              }}>
                <HFDot tone={c.tone}/>
                <span style={{ fontFamily: 'var(--hf-mono)', fontSize: 13, color: 'var(--hf-ink)', flex: 1 }}>{c.type}</span>
                <span style={{ fontFamily: 'var(--hf-mono)', fontSize: 14, color: 'var(--hf-ink)', fontWeight: 600, fontVariantNumeric:'tabular-nums' }}>{c.n}</span>
                <span style={{ color: 'var(--hf-ink4)', display: 'flex' }}>{HF_ICONS.arrow}</span>
              </a>
            ))}
          </div>
        </HFCard>

        <HFCard title="By shop" sub="health + key counts">
          <div style={{ padding: `2px var(--hf-card-p) 4px` }}>
            {shopCards.map((s, i) => {
              const sTone = s.last_run_status === 'completed' ? 'ok' : s.last_run_status === 'failed' ? 'err' : 'neutral';
              const sStatus = s.last_run_status === 'completed' ? 'healthy' : s.last_run_status === 'failed' ? 'failing' : s.last_run_status || 'unknown';
              return (
              <a key={s.name} href={buildPath('shop-detail', { name: s.name })}
                 onClick={(e) => { if(e.metaKey||e.ctrlKey||e.shiftKey)return; e.preventDefault(); goto('shop-detail', { name: s.name }); }}
                 style={{
                display: 'block', textDecoration: 'none', color: 'var(--hf-ink)',
                padding: '14px 0',
                borderBottom: i < shopCards.length - 1 ? `1px solid ${'var(--hf-border-faint)'}` : 'none',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                  <HFDot tone={sTone} pulse={sTone==='err'}/>
                  <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--hf-ink)' }}>{s.name}.lt</span>
                  <HFPill tone={sTone==='ok'?'ok':'err'}>{sStatus}</HFPill>
                  <span style={{ flex: 1 }}/>
                  <span style={{ fontSize: 12, color: 'var(--hf-ink3)', fontFamily: 'var(--hf-mono)', fontVariantNumeric:'tabular-nums' }}>last run {s.last_run_ago}</span>
                  <span style={{ color: 'var(--hf-ink4)', display: 'flex' }}>{HF_ICONS.external}</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                  {[['Books', s.books], ['Active', s.active], ['Issues', s.issues]].map(([l, v], j) => (
                    <div key={l} style={{ paddingLeft: j === 0 ? 0 : 12, borderLeft: j === 0 ? 'none' : `1px solid ${'var(--hf-border-faint)'}` }}>
                      <div style={{ fontSize: 11, color: 'var(--hf-ink4)', textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600 }}>{l}</div>
                      <div style={{ fontFamily: 'var(--hf-mono)', fontSize: 16, color: 'var(--hf-ink)', marginTop: 3, fontWeight: 600, fontVariantNumeric:'tabular-nums', letterSpacing:-0.3 }}>
                        {typeof v === 'number' ? v.toLocaleString() : v}
                      </div>
                    </div>
                  ))}
                </div>
              </a>
              );
            })}
          </div>
        </HFCard>
      </div>
    </HFShell>
  );
}

window.HFOverview = HFOverview;
