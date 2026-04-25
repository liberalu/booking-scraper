// Hi-fi Overview — light mode, Retool/Metabase-feel

function HFOverview({ nav, goto }) {
  const HF = getHF();
  const { collapsed, setCollapsed } = nav;

  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch('/api/overview')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  if (loading || !data) {
    return (
      <HFShell collapsed={collapsed} setCollapsed={setCollapsed} activePage="overview"
        title="Overview" subtitle="Loading…" breadcrumb={<span>Overview</span>}
        setPage={nav.setPage}>
        <div style={{padding:40, color:HF.ink3, fontSize:13}}>Loading…</div>
      </HFShell>
    );
  }

  const stats = data.stats;
  const kpis = [
    { label: 'Shop books',      value: stats.total_shop_books.toLocaleString(),  delta: <span style={{color:HF.ink3}}>total</span> },
    { label: 'Active listings', value: stats.active_shop_books.toLocaleString(), delta: <span style={{color:HF.ink3}}>{stats.total_shop_books > 0 ? Math.round(stats.active_shop_books/stats.total_shop_books*100) : 0}% of total</span> },
    { label: 'With ISBN',       value: stats.with_isbn.toLocaleString(),          delta: <span style={{color:HF.ink3}}>{stats.total_shop_books > 0 ? Math.round(stats.with_isbn/stats.total_shop_books*100) : 0}% coverage</span> },
    { label: 'Price records',   value: stats.total_prices.toLocaleString(),       delta: <span style={{color:HF.ink3}}>total</span>, tone:'ok' },
    { label: 'Open issues',     value: stats.open_issues.toLocaleString(),        delta: <span style={{color:HF.ink3}}>open</span>, tone: stats.open_issues > 0 ? 'warn' : 'ok' },
  ];
  const spark = data.activity;
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
        <span style={{ color: HF.ink3 }}>BookScraper</span>
        <span style={{ color: HF.ink5 }}>/</span>
        <span style={{ color: HF.ink, fontWeight: 500 }}>Overview</span>
      </>}
      actions={<>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.refresh}</span> Refresh</HFButton>
        <HFButton>Last 7 days <span style={{display:'flex', opacity:.7}}>{HF_ICONS.chevronD}</span></HFButton>
      </>}
    >
      {/* KPI strip */}
      <HFKpiStrip items={kpis}/>

      {/* Activity + Completeness */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.55fr 1fr', gap: HF.gap, marginBottom: HF.gap }}>
        <HFCard title="Scrape activity" sub="items scraped per day · last 14 days"
                action={<a href="#" className="hf-link" style={hfLink(HF)} onClick={(e)=>{e.preventDefault();goto('runs');}}>View runs {HF_ICONS.arrow}</a>}>
          <div style={{ padding: `14px ${HF.cardP}px ${HF.cardP}px` }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
              <span style={{ fontFamily: HF.mono, fontSize: 26, fontWeight: 600, letterSpacing: -0.5, color: HF.ink, fontVariantNumeric:'tabular-nums' }}>9,170</span>
              <span style={{ fontSize: 12.5, color: HF.ink3 }}>items this week</span>
              <span style={{ marginLeft: 'auto' }}><HFPill tone="ok">▲ 14% vs prev</HFPill></span>
            </div>
            <HFSparkBars data={spark} h={100}/>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: HF.ink4, fontFamily: HF.mono, marginTop: 8, fontVariantNumeric:'tabular-nums' }}>
              <span>Apr 6</span><span>Apr 10</span><span>Apr 14</span><span>Apr 19</span>
            </div>
          </div>
        </HFCard>

        <HFCard title="Metadata completeness" sub="field coverage · active listings"
                action={<a href="#" style={hfLink(HF)} onClick={(e)=>{e.preventDefault();goto('shop-books');}}>View books {HF_ICONS.arrow}</a>}>
          <div style={{ padding: `10px ${HF.cardP}px 14px` }}>
            {completeness.map(([field, p], i) => (
              <div key={field} style={{ padding: '8px 0', borderBottom: i < completeness.length - 1 ? `1px solid ${HF.borderFaint}` : 'none' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <span style={{ fontSize: 13, color: HF.ink, fontWeight: 500 }}>{field}</span>
                  <span style={{ fontFamily: HF.mono, fontSize: 12, color: p >= 80 ? HF.okInk : p >= 60 ? HF.ink2 : HF.warnInk, fontVariantNumeric:'tabular-nums', fontWeight:500 }}>{p}%</span>
                </div>
                <div style={{ height: 6, background: HF.subtle, borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{
                    width: `${p}%`, height: '100%',
                    background: p >= 80 ? HF.ok : p >= 60 ? HF.accent : HF.warn,
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
              action={<a href="#" style={hfLink(HF)} onClick={(e)=>{e.preventDefault();goto('runs');}}>All runs {HF_ICONS.arrow}</a>}
              style={{ marginBottom: HF.gap }}>
        <HFTable
          onRowClick={(r) => goto('run-detail', { id: r.id })}
          columns={[
            { key:'id', label:'Run', w:'0.6fr', mono:true, cell: v => <span style={{color: HF.ink, fontWeight:500}}>#{v}</span> },
            { key:'shop', label:'Shop', w:'0.8fr', cell: v => <span style={{color: HF.ink}}>{v}</span> },
            { key:'phase', label:'Phase', w:'0.8fr', mono:true, muted:true },
            { key:'status', label:'Status', w:'1fr', cell: v => <span style={{display:'inline-flex', alignItems:'center', gap:7}}><HFDot tone={statusTone[v]} pulse={v==='running'}/> <span style={{color: v==='failed'? HF.errInk : HF.ink, fontWeight: v==='running'? 500 : 400}}>{v}</span></span> },
            { key:'progress', label:'Progress', w:'1.6fr', cell: (v, r) => (
              <span style={{display:'flex', alignItems:'center', gap:10, width:'100%'}}>
                <span style={{flex:1, maxWidth: 200, height: 6, background: HF.subtle, borderRadius: 3, overflow:'hidden'}}>
                  <span style={{display:'block', width:`${v}%`, height:'100%', background: r.status==='failed'? HF.err : r.status==='running'? HF.accent : HF.ink4, borderRadius:3}}/>
                </span>
                <span style={{fontFamily:HF.mono, fontSize:11.5, color:HF.ink3, minWidth:32, fontVariantNumeric:'tabular-nums'}}>{v}%</span>
              </span>
            )},
            { key:'items', label:'Items', w:'0.7fr', mono:true, align:'right', cell: v => v.toLocaleString() },
            { key:'elapsed', label:'Elapsed', w:'0.6fr', mono:true, muted:true, align:'right' },
            { key:'chev', label:'', w:'40px', align:'right', cell: () => <span style={{color: HF.ink4, display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
          ]}
          rows={runs}
        />
      </HFCard>

      {/* Issue clusters + By shop */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 1fr', gap: HF.gap }}>
        <HFCard title="Needs attention" sub="open validation clusters · click to triage"
                action={<a href="#" style={hfLink(HF)} onClick={(e)=>{e.preventDefault();goto('issues');}}>All issues {HF_ICONS.arrow}</a>}>
          <div style={{ padding: `${HF.cardP}px`, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {clusters.map(c => (
              <a key={c.type} href="#" className="hf-row"
                 onClick={(e) => { e.preventDefault(); goto('issues', { type: c.type }); }}
                 style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '10px 12px',
                borderRadius: 6,
                background: HF.bg,
                border: `1px solid ${HF.border}`,
                textDecoration: 'none', color: HF.ink,
              }}>
                <HFDot tone={c.tone}/>
                <span style={{ fontFamily: HF.mono, fontSize: 12.5, color: HF.ink, flex: 1 }}>{c.type}</span>
                <span style={{ fontFamily: HF.mono, fontSize: 14, color: HF.ink, fontWeight: 600, fontVariantNumeric:'tabular-nums' }}>{c.n}</span>
                <span style={{ color: HF.ink4, display: 'flex' }}>{HF_ICONS.arrow}</span>
              </a>
            ))}
          </div>
        </HFCard>

        <HFCard title="By shop" sub="health + key counts">
          <div style={{ padding: `2px ${HF.cardP}px 4px` }}>
            {shopCards.map((s, i) => {
              const sTone = s.last_run_status === 'completed' ? 'ok' : s.last_run_status === 'failed' ? 'err' : 'neutral';
              const sStatus = s.last_run_status === 'completed' ? 'healthy' : s.last_run_status === 'failed' ? 'failing' : s.last_run_status || 'unknown';
              return (
              <a key={s.name} href="#"
                 onClick={(e) => { e.preventDefault(); goto('shop-detail', { name: s.name }); }}
                 style={{
                display: 'block', textDecoration: 'none', color: HF.ink,
                padding: '14px 0',
                borderBottom: i < shopCards.length - 1 ? `1px solid ${HF.borderFaint}` : 'none',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                  <HFDot tone={sTone} pulse={sTone==='err'}/>
                  <span style={{ fontSize: 14.5, fontWeight: 600, color: HF.ink }}>{s.name}.lt</span>
                  <HFPill tone={sTone==='ok'?'ok':'err'}>{sStatus}</HFPill>
                  <span style={{ flex: 1 }}/>
                  <span style={{ fontSize: 11.5, color: HF.ink3, fontFamily: HF.mono, fontVariantNumeric:'tabular-nums' }}>last run {s.last_run_ago}</span>
                  <span style={{ color: HF.ink4, display: 'flex' }}>{HF_ICONS.external}</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                  {[['Books', s.books], ['Active', s.active], ['Issues', s.issues]].map(([l, v], j) => (
                    <div key={l} style={{ paddingLeft: j === 0 ? 0 : 12, borderLeft: j === 0 ? 'none' : `1px solid ${HF.borderFaint}` }}>
                      <div style={{ fontSize: 10.5, color: HF.ink4, textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 600 }}>{l}</div>
                      <div style={{ fontFamily: HF.mono, fontSize: 16, color: HF.ink, marginTop: 3, fontWeight: 600, fontVariantNumeric:'tabular-nums', letterSpacing:-0.3 }}>
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
