// Hi-fi Overview — light mode, Retool/Metabase-feel

function HFOverview({ nav }) {
  const HF = getHF();
  const { collapsed, setCollapsed } = nav;

  const kpis = [
    { label: 'Shop books', value: '18,432', delta: <span><span style={{color:HF.okInk}}>▲ 124</span><span style={{color:HF.ink3, marginLeft:4}}>today</span></span>, href: '#' },
    { label: 'Active listings', value: '16,201', delta: <span style={{color:HF.ink3}}>87.9% of total</span>, href: '#' },
    { label: 'With ISBN', value: '14,889', delta: <span style={{color:HF.ink3}}>80.8% coverage</span>, href: '#' },
    { label: 'Price records', value: '412,550', delta: <span><span style={{color:HF.okInk}}>▲ 1,204</span><span style={{color:HF.ink3, marginLeft:4}}>· 24h</span></span>, tone:'ok', href: '#' },
    { label: 'Open issues', value: '267', delta: <span><span style={{color:HF.warnInk}}>▲ 12</span><span style={{color:HF.ink3, marginLeft:4}}>new · 24h</span></span>, tone:'warn', href: '#' },
  ];

  const spark = [420, 380, 510, 390, 680, 720, 640, 810, 520, 470, 560, 720, 910, 640];

  const completeness = [
    ['ISBN',        81],
    ['Author',      94],
    ['Publisher',   72],
    ['Year',        64],
    ['Pages',       58],
    ['Description', 49],
  ];

  const runs = [
    { id: 4821, shop: 'vaga',    phase: 'scan',     status: 'running',   prog: 72,  items: 1240, elapsed: '12m' },
    { id: 4820, shop: 'vaga',    phase: 'discover', status: 'completed', prog: 100, items: 820,  elapsed: '4m'  },
    { id: 4819, shop: 'knygos',  phase: 'prices',   status: 'running',   prog: 41,  items: 455,  elapsed: '2m'  },
    { id: 4815, shop: 'vaga',    phase: 'scan',     status: 'completed', prog: 100, items: 3102, elapsed: '42m' },
    { id: 4812, shop: 'knygos',  phase: 'discover', status: 'failed',    prog: 12,  items: 0,    elapsed: '1m'  },
    { id: 4810, shop: 'vaga',    phase: 'discover', status: 'completed', prog: 100, items: 612,  elapsed: '18m' },
  ];

  const clusters = [
    { type: 'missing_isbn',        n: 234, tone: 'warn' },
    { type: 'price_regression',    n: 48,  tone: 'err' },
    { type: 'title_too_short',     n: 19,  tone: 'warn' },
    { type: 'stale_listing',       n: 112, tone: 'neutral' },
    { type: 'duplicate_sku',       n: 6,   tone: 'err' },
    { type: 'invalid_year',        n: 3,   tone: 'neutral' },
  ];

  const statusTone = { running: 'ok', completed: 'neutral', failed: 'err' };

  return (
    <HFShell
      collapsed={collapsed} setCollapsed={setCollapsed}
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
                action={<a href="#" className="hf-link" style={hfLink(HF)}>View runs {HF_ICONS.arrow}</a>}>
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
                action={<a href="#" style={hfLink(HF)}>Filter {HF_ICONS.arrow}</a>}>
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
              action={<a href="#" style={hfLink(HF)}>All runs {HF_ICONS.arrow}</a>}
              style={{ marginBottom: HF.gap }}>
        <HFTable
          columns={[
            { key:'id', label:'Run', w:'0.6fr', mono:true, cell: v => <span style={{color: HF.ink, fontWeight:500}}>#{v}</span> },
            { key:'shop', label:'Shop', w:'0.8fr', cell: v => <span style={{color: HF.ink}}>{v}</span> },
            { key:'phase', label:'Phase', w:'0.8fr', mono:true, muted:true },
            { key:'status', label:'Status', w:'1fr', cell: v => <span style={{display:'inline-flex', alignItems:'center', gap:7}}><HFDot tone={statusTone[v]} pulse={v==='running'}/> <span style={{color: v==='failed'? HF.errInk : HF.ink, fontWeight: v==='running'? 500 : 400}}>{v}</span></span> },
            { key:'prog', label:'Progress', w:'1.6fr', cell: (v, r) => (
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
                action={<a href="#" style={hfLink(HF)}>All issues {HF_ICONS.arrow}</a>}>
          <div style={{ padding: `${HF.cardP}px`, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {clusters.map(c => (
              <a key={c.type} href="#" className="hf-row" style={{
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
            {[
              { name: 'vaga',   status: 'healthy', tone: 'ok',  books: 15420, active: 13892, issues: 38,  last: '12m' },
              { name: 'knygos', status: 'failing', tone: 'err', books: 3012,  active: 2309,  issues: 229, last: '1h'  },
            ].map((s, i) => (
              <a key={s.name} href="#" style={{
                display: 'block', textDecoration: 'none', color: HF.ink,
                padding: '14px 0',
                borderBottom: i === 0 ? `1px solid ${HF.borderFaint}` : 'none',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                  <HFDot tone={s.tone} pulse={s.tone==='err'}/>
                  <span style={{ fontSize: 14.5, fontWeight: 600, color: HF.ink }}>{s.name}.lt</span>
                  <HFPill tone={s.tone==='ok'?'ok':'err'}>{s.status}</HFPill>
                  <span style={{ flex: 1 }}/>
                  <span style={{ fontSize: 11.5, color: HF.ink3, fontFamily: HF.mono, fontVariantNumeric:'tabular-nums' }}>last run {s.last}</span>
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
            ))}
          </div>
        </HFCard>
      </div>
    </HFShell>
  );
}

window.HFOverview = HFOverview;
