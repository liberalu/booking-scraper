// Hi-fi Schedule detail + tab content panels (Parser config, Runs, Prices)

// ═══════════════════════ Shared tab panels ═══════════════════════

// Parser config panel — field selectors, test output, extraction stats
function HFParserConfigPanel({ shop = 'vaga', scope = 'shop', goto }) {
  const HF = getHF();

  const fields = [
    { k:'title',       sel:'h1.product-title',                    type:'text',    success:99.8, last:'matched',  required:true  },
    { k:'author',      sel:'.product-meta .author a',             type:'text',    success:97.2, last:'matched',  required:true  },
    { k:'price',       sel:'.price-now .value',                   type:'decimal', success:95.1, last:'matched',  required:true  },
    { k:'old_price',   sel:'.price-was .value',                   type:'decimal', success:62.4, last:'null',     required:false },
    { k:'isbn',        sel:'.product-specs [data-field="isbn"]',  type:'text',    success:81.4, last:'matched',  required:true  },
    { k:'publisher',   sel:'.product-specs [data-field="pub"]',   type:'text',    success:72.0, last:'matched',  required:false },
    { k:'pages',       sel:'.product-specs [data-field="pages"]', type:'integer', success:58.0, last:'null',     required:false },
    { k:'year',        sel:'.product-specs [data-field="year"]',  type:'integer', success:68.2, last:'matched',  required:false },
    { k:'description', sel:'.product-description',                type:'html',    success:94.8, last:'matched',  required:false },
    { k:'cover_url',   sel:'img.product-cover[src]',              type:'url',     success:99.1, last:'matched',  required:false },
  ];

  const version = { current:'product.v3', prev:'product.v2', deployed:'Apr 12, 2025' };

  return (
    <div>
      {/* Parser header / version */}
      <HFCard style={{marginBottom:HF.gap}} padding={14}>
        <div style={{display:'flex', alignItems:'center', gap:14}}>
          <div style={{flex:1}}>
            <div style={{fontSize:10.5, color:HF.ink4, textTransform:'uppercase', letterSpacing:0.5, fontWeight:600, marginBottom:4}}>Active parser</div>
            <div style={{display:'flex', alignItems:'center', gap:10}}>
              <span style={{fontFamily:HF.mono, fontSize:15, color:HF.ink, fontWeight:500}}>{version.current}</span>
              <HFPill tone="ok">deployed</HFPill>
              <span style={{fontSize:11.5, color:HF.ink3, fontFamily:HF.mono}}>{version.deployed}</span>
            </div>
          </div>
          <div style={{display:'flex', gap:6}}>
            <HFButton size="sm">View history</HFButton>
            <HFButton size="sm">Test on URL…</HFButton>
            <HFButton size="sm" variant="primary" onClick={() => goto && goto('parser', { shop })}>Edit parser</HFButton>
          </div>
        </div>
      </HFCard>

      {/* Field selectors */}
      <HFCard title="Field selectors" sub={`${fields.length} fields · ${fields.filter(f=>f.required).length} required`} style={{marginBottom:HF.gap}}>
        <HFTable
          columns={[
            { key:'k', label:'Field', w:'0.9fr', mono:true, cell:(v,r) => (
              <span style={{display:'inline-flex', alignItems:'center', gap:6}}>
                <span style={{color:HF.ink, fontWeight:500}}>{v}</span>
                {r.required && <span style={{fontSize:10, color:HF.errInk, fontWeight:600}}>*</span>}
              </span>
            )},
            { key:'type', label:'Type', w:'0.6fr', mono:true, muted:true },
            { key:'sel', label:'Selector', w:'2.2fr', mono:true, cell:v => <span style={{color:HF.ink2, fontSize:11.5, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{v}</span> },
            { key:'success', label:'Success', w:'0.9fr', align:'right', sortable:true, sortVal:r=>r.success, cell:v => {
              const tone = v >= 90 ? 'ok' : v >= 70 ? 'warn' : 'err';
              const ink = tone==='ok'? HF.okInk : tone==='warn'? HF.warnInk : HF.errInk;
              return (
                <span style={{display:'flex', alignItems:'center', gap:8, justifyContent:'flex-end'}}>
                  <span style={{width:40, height:4, background:HF.subtle, borderRadius:2, overflow:'hidden'}}>
                    <span style={{display:'block', width:`${v}%`, height:'100%', background: tone==='ok'? HF.ok : tone==='warn'? HF.warn : HF.err}}/>
                  </span>
                  <span style={{fontFamily:HF.mono, color:ink, fontWeight:500, fontSize:11.5, fontVariantNumeric:'tabular-nums', minWidth:40, textAlign:'right'}}>{v}%</span>
                </span>
              );
            }},
            { key:'last', label:'Last run', w:'0.7fr', cell:v => v==='matched' ? <HFPill tone="ok">{v}</HFPill> : <HFPill tone="warn">{v}</HFPill> },
            { key:'_', label:'', w:'40px', align:'right', cell:() => <HFButton size="sm" variant="subtle">Edit</HFButton> },
          ]}
          rows={fields}
        />
      </HFCard>

      {/* Test harness preview */}
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:HF.gap}}>
        <HFCard title="Last test" sub="ran against /knygos/sapiens-yuval-noah-harari · 2h ago"
                action={<HFPill tone="ok">9/10 fields ok</HFPill>}>
          <div style={{padding:14, fontFamily:HF.mono, fontSize:11.5, lineHeight:1.7, color:HF.ink2, background:HF.subtle, borderTop:`1px solid ${HF.borderFaint}`}}>
            <div><span style={{color:HF.ink4}}>title</span>   <span style={{color:HF.okInk}}>→</span> "Sapiens: A Brief History of Humankind"</div>
            <div><span style={{color:HF.ink4}}>author</span>  <span style={{color:HF.okInk}}>→</span> "Yuval Noah Harari"</div>
            <div><span style={{color:HF.ink4}}>price</span>   <span style={{color:HF.okInk}}>→</span> 19.90</div>
            <div><span style={{color:HF.ink4}}>isbn</span>    <span style={{color:HF.okInk}}>→</span> "9789955134572"</div>
            <div><span style={{color:HF.ink4}}>year</span>    <span style={{color:HF.okInk}}>→</span> 2019</div>
            <div><span style={{color:HF.ink4}}>pages</span>   <span style={{color:HF.warnInk}}>→</span> <span style={{color:HF.warnInk}}>null</span>  <span style={{color:HF.ink4}}>// selector matched 0 nodes</span></div>
            <div><span style={{color:HF.ink4}}>publisher</span> <span style={{color:HF.okInk}}>→</span> "Kitos knygos"</div>
          </div>
        </HFCard>

        <HFCard title="Recent extraction failures" sub="fields that returned null · 24h">
          <div style={{padding:'4px 0'}}>
            {[
              { f:'pages',       n:412, pct:42.0, tone:'err'  },
              { f:'old_price',   n:289, pct:37.6, tone:'warn' },
              { f:'publisher',   n:156, pct:28.0, tone:'warn' },
              { f:'isbn',        n:89,  pct:18.6, tone:'warn' },
              { f:'year',        n:62,  pct:31.8, tone:'warn' },
            ].map((r, i, arr) => (
              <div key={r.f} style={{padding:`10px ${HF.cardP}px`, borderBottom: i<arr.length-1?`1px solid ${HF.borderFaint}`:'none', display:'grid', gridTemplateColumns:'1fr 80px 80px', alignItems:'center', fontSize:12.5}}>
                <span style={{fontFamily:HF.mono, color:HF.ink}}>{r.f}</span>
                <span style={{fontFamily:HF.mono, color:HF.ink2, textAlign:'right', fontVariantNumeric:'tabular-nums'}}>{r.n} miss</span>
                <span style={{fontFamily:HF.mono, color: r.tone==='err'? HF.errInk : HF.warnInk, textAlign:'right', fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{r.pct.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </HFCard>
      </div>
    </div>
  );
}

// Runs panel for shop/book — lightweight runs table scoped to entity
function HFRunsPanel({ goto, scope = 'shop', entity = 'vaga' }) {
  const HF = getHF();

  const rows = [
    { id:4820, phase:'scan',     started:'12m ago',  dur:'14m 12s', items:1204, errors:2,  status:'completed' },
    { id:4815, phase:'discover', started:'2h ago',   dur:'42m',     items:48,   errors:0,  status:'completed' },
    { id:4810, phase:'scan',     started:'4h ago',   dur:'16m 8s',  items:1198, errors:1,  status:'completed' },
    { id:4805, phase:'prices',   started:'6h ago',   dur:'22m',     items:890,  errors:0,  status:'completed' },
    { id:4800, phase:'scan',     started:'9h ago',   dur:'15m 40s', items:1210, errors:0,  status:'completed' },
    { id:4792, phase:'scan',     started:'12h ago',  dur:'—',       items:0,    errors:12, status:'failed' },
    { id:4785, phase:'scan',     started:'1d ago',   dur:'14m 52s', items:1188, errors:0,  status:'completed' },
    { id:4780, phase:'discover', started:'1d 4h',    dur:'38m',     items:62,   errors:0,  status:'completed' },
  ];

  const statusTone = { completed:'neutral', failed:'err', running:'ok', queued:'warn' };

  return (
    <HFCard>
      <HFTable
        onRowClick={r => goto && goto('run-detail', { id:r.id })}
        columns={[
          { key:'id', label:'Run', w:'0.5fr', mono:true, sortable:true, sortVal:r=>r.id, cell:v => <span style={{color:HF.accentInk, fontWeight:500}}>#{v}</span> },
          { key:'phase', label:'Phase', w:'0.8fr', mono:true, sortable:true },
          { key:'started', label:'Started', w:'0.9fr', mono:true, muted:true, sortable:true },
          { key:'dur', label:'Duration', w:'0.8fr', mono:true, muted:true, align:'right', sortable:true },
          { key:'items', label:'Items', w:'0.6fr', mono:true, align:'right', sortable:true, sortVal:r=>r.items, cell:v => <span style={{color:HF.ink, fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v.toLocaleString()}</span> },
          { key:'errors', label:'Errors', w:'0.5fr', mono:true, align:'right', sortable:true, sortVal:r=>r.errors, cell:v => v ? <span style={{color:HF.errInk, fontWeight:500}}>{v}</span> : <span style={{color:HF.ink4}}>—</span> },
          { key:'status', label:'Status', w:'0.8fr', sortable:true, cell:v => <HFPill tone={statusTone[v]}>{v}</HFPill> },
          { key:'_', label:'', w:'28px', align:'right', cell:() => <span style={{color:HF.ink4, display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
        ]}
        rows={rows}
      />
    </HFCard>
  );
}

// Prices panel — for shop book detail (full price history)
function HFPricesPanel() {
  const HF = getHF();

  const history = [19.9, 19.9, 18.5, 18.5, 18.5, 19.5, 19.5, 21.0, 19.9, 19.9, 19.9, 19.9, 18.9, 19.9, 19.9, 19.9, 18.5, 19.9, 19.9, 19.9, 19.9, 18.9, 19.9, 19.9, 19.9, 19.9, 19.9, 19.9, 19.9, 19.9];

  const changes = [
    { ts:'Apr 18 12:04', old:'€21.00', neo:'€19.90', pct:-5.2,  run:4820, reason:'price drop' },
    { ts:'Apr 12 09:18', old:'€19.90', neo:'€21.00', pct:+5.5,  run:4770, reason:'back to list' },
    { ts:'Apr 2  14:40', old:'€18.50', neo:'€19.90', pct:+7.6,  run:4621, reason:'promo ended' },
    { ts:'Mar 22 10:12', old:'€19.90', neo:'€18.50', pct:-7.0,  run:4482, reason:'spring sale' },
    { ts:'Mar 10 08:00', old:'€21.00', neo:'€19.90', pct:-5.2,  run:4301, reason:'price drop' },
    { ts:'Feb 18 11:22', old:'—',      neo:'€21.00', pct:null,  run:4012, reason:'initial scrape' },
  ];

  return (
    <div>
      <HFKpiStrip items={[
        { label:'Current',      value:'€19.90', delta:<span style={{color:HF.errInk}}>▼ €1.10 · 12m ago</span>, tone:'err' },
        { label:'30d avg',      value:'€19.92', delta:<span style={{color:HF.ink3}}>σ €0.84</span> },
        { label:'All-time low', value:'€18.50', delta:<span style={{color:HF.ink3}}>Mar 22</span> },
        { label:'All-time high',value:'€21.00', delta:<span style={{color:HF.ink3}}>Apr 2</span> },
        { label:'Changes',      value:'12',     delta:<span style={{color:HF.ink3}}>of 127 scrapes</span> },
      ]}/>

      <HFCard title="Price trajectory" sub="30 data points · last 30 days" style={{marginBottom:HF.gap}}
              action={<HFPill tone="err">▼ 5.2% vs 30d avg</HFPill>}>
        <div style={{padding:HF.cardP}}>
          <HFAreaChart data={history} h={200}/>
          <div style={{display:'flex', justifyContent:'space-between', fontSize:11, color:HF.ink4, fontFamily:HF.mono, marginTop:10, fontVariantNumeric:'tabular-nums'}}>
            <span>Mar 20</span><span>Mar 27</span><span>Apr 3</span><span>Apr 10</span><span>Apr 17</span>
          </div>
        </div>
      </HFCard>

      <HFCard title="All price changes" sub={`${changes.length} recorded movements`}>
        <HFTable
          columns={[
            { key:'ts', label:'When', w:'1.1fr', mono:true, sortable:true, cell:v => <span style={{color:HF.ink2}}>{v}</span> },
            { key:'old', label:'Was', w:'0.7fr', mono:true, align:'right', muted:true, sortable:true, sortVal:r=>parseFloat((r.old||'').replace(/[^\d.]/g,''))||0 },
            { key:'neo', label:'Now', w:'0.7fr', mono:true, align:'right', sortable:true, sortVal:r=>parseFloat((r.neo||'').replace(/[^\d.]/g,''))||0, cell:v => <span style={{color:HF.ink, fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v}</span> },
            { key:'pct', label:'Δ %', w:'0.6fr', mono:true, align:'right', sortable:true, sortVal:r=>r.pct||0, cell:v => v == null ? <span style={{color:HF.ink4}}>—</span> : <span style={{color: v<0?HF.errInk:v>0?HF.okInk:HF.ink3, fontWeight:600, fontVariantNumeric:'tabular-nums'}}>{v>0?'+':''}{v.toFixed(1)}%</span> },
            { key:'reason', label:'Reason', w:'1.2fr', cell:v => <span style={{color:HF.ink2, fontSize:12}}>{v}</span> },
            { key:'run', label:'Run', w:'0.5fr', mono:true, align:'right', cell:v => <span style={{color:HF.accentInk, fontWeight:500}}>#{v}</span> },
          ]}
          rows={changes}
        />
      </HFCard>
    </div>
  );
}

// ═══════════════════════ Schedule detail page ═══════════════════════

function HFScheduleDetail({ nav, goto, params }) {
  const HF = getHF();
  const name = params?.name || 'vaga.scan.hourly';
  const cron = params?.cron || '0 * * * *';
  const shop = params?.shop || 'vaga';
  const enabled = params?.enabled !== false;
  const lastStatus = params?.lastStatus || 'ok';
  const [tab, setTab] = React.useState('runs');
  const [enabledState, setEnabledState] = React.useState(enabled);

  // Humanize cron
  const cronHuman = cron === '0 * * * *' ? 'every hour · on the hour'
                  : cron === '0 3 * * *' ? 'daily at 03:00'
                  : cron === '0 5 * * *' ? 'daily at 05:00'
                  : cron === '30 5 * * *' ? 'daily at 05:30'
                  : cron === '0 4 * * *' ? 'daily at 04:00'
                  : cron === '0 2 * * *' ? 'daily at 02:00'
                  : cron === '0 0 * * 0' ? 'weekly on Sunday 00:00'
                  : cron === '0 1 * * *' ? 'daily at 01:00' : 'custom schedule';

  // Next 5 scheduled runs (synthetic)
  const upcoming = [
    { when:'in 48m',  at:'14:00', date:'today' },
    { when:'in 1h 48m', at:'15:00', date:'today' },
    { when:'in 2h 48m', at:'16:00', date:'today' },
    { when:'in 3h 48m', at:'17:00', date:'today' },
    { when:'in 4h 48m', at:'18:00', date:'today' },
  ];

  // Last 24 runs — green/red cells for history heatmap
  const last24 = [
    'ok','ok','ok','ok','ok','fail','ok','ok','ok','ok','ok','ok',
    'ok','ok','ok','ok','ok','ok','ok','fail','ok','ok','ok','ok',
  ];

  // Recent run history
  const runs = [
    { id:4820, started:'12m ago',  dur:'14m 12s', items:1204, errors:2,  status:'completed' },
    { id:4815, started:'1h 12m',   dur:'14m 48s', items:1198, errors:0,  status:'completed' },
    { id:4810, started:'2h 12m',   dur:'13m 20s', items:1200, errors:0,  status:'completed' },
    { id:4805, started:'3h 12m',   dur:'—',       items:0,    errors:12, status:'failed' },
    { id:4800, started:'4h 12m',   dur:'15m 02s', items:1210, errors:0,  status:'completed' },
    { id:4792, started:'5h 12m',   dur:'14m 18s', items:1205, errors:0,  status:'completed' },
    { id:4785, started:'6h 12m',   dur:'14m 52s', items:1188, errors:0,  status:'completed' },
    { id:4780, started:'7h 12m',   dur:'14m 10s', items:1201, errors:0,  status:'completed' },
  ];
  const statusTone = { completed:'neutral', failed:'err', running:'ok', queued:'warn' };

  const logs = [
    { t:'14:12:04', lvl:'INFO',  msg:`schedule fired: ${name}` },
    { t:'14:12:04', lvl:'INFO',  msg:'queuing run on worker-02 · concurrency 4/4' },
    { t:'14:12:05', lvl:'INFO',  msg:'fetching seed URLs (47 sitemaps)' },
    { t:'14:12:08', lvl:'INFO',  msg:'1,204 URLs enqueued for scrape phase' },
    { t:'14:14:22', lvl:'WARN',  msg:'429 rate-limit from vaga.lt (host) · backing off 8s' },
    { t:'14:26:16', lvl:'INFO',  msg:'run 4820 completed · items=1204 · errors=2 · dur=14m 12s' },
  ];

  return (
    <HFShell {...nav} activePage="cron"
      title={<span style={{display:'flex', alignItems:'center', gap:12, minWidth:0}}>
        <HFDot tone={enabledState ? (lastStatus==='fail'?'err':'ok') : 'neutral'} size={10}/>
        <span style={{fontFamily:HF.mono, fontSize:18, color:HF.ink, fontWeight:500}}>{name}</span>
        {enabledState
          ? <HFPill tone={lastStatus==='fail'?'err':'ok'}>{lastStatus==='fail'?'failing':'active'}</HFPill>
          : <HFPill tone="neutral">disabled</HFPill>}
      </span>}
      subtitle={<span style={{fontFamily:HF.mono, fontSize:12.5, color:HF.ink3}}>{cron} · {cronHuman} · shop={shop}</span>}
      breadcrumb={<>
        <a href="#" onClick={e=>{e.preventDefault(); goto('cron');}} style={{color:HF.ink3, textDecoration:'none'}}>Schedules</a>
        <span style={{color:HF.ink5}}>/</span>
        <span style={{color:HF.ink, fontWeight:500, fontFamily:HF.mono}}>{name}</span>
      </>}
      actions={<>
        <HFButton onClick={()=>setEnabledState(!enabledState)}>
          <span style={{display:'flex'}}>{enabledState ? HF_ICONS.stop : HF_ICONS.play}</span>
          {enabledState ? 'Disable' : 'Enable'}
        </HFButton>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.settings}</span> Edit</HFButton>
        <HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openNewRun()}><span style={{display:'flex'}}>{HF_ICONS.play}</span> Run now</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Next run',     value:enabledState ? '48m' : '—', tone: enabledState ? 'accent' : undefined, delta:<span style={{color:HF.ink3}}>{enabledState ? 'today 14:00' : 'disabled'}</span> },
        { label:'Last 24h',     value:'24 runs', delta:<span style={{color:HF.okInk}}>22 ok · 2 failed</span> },
        { label:'Success rate', value:'94.7%',   delta:<span style={{color:HF.okInk}}>30d</span>, tone:'ok' },
        { label:'Avg duration', value:'14m 18s', delta:<span style={{color:HF.ink3}}>p95 16m 42s</span> },
        { label:'Last run',     value:'12m ago', delta:<span style={{color: lastStatus==='fail'? HF.errInk : HF.okInk}}>{lastStatus==='fail' ? 'failed' : 'ok'}</span>, tone: lastStatus==='fail'? 'err' : 'ok' },
      ]}/>

      {/* Schedule card + upcoming runs */}
      <div style={{display:'grid', gridTemplateColumns:'1.4fr 1fr', gap:HF.gap, marginBottom:HF.gap}}>
        <HFCard title="Schedule" sub="when this job fires"
                action={<HFButton size="sm">Edit cron</HFButton>}>
          <div style={{padding:HF.cardP, display:'grid', gridTemplateColumns:'1fr 1fr', gap:14}}>
            {[
              ['Cron expression', cron, true],
              ['Humanized',       cronHuman],
              ['Timezone',        'Europe/Vilnius'],
              ['Concurrency',     '4 workers'],
              ['Retry policy',    'exp × 3 (max 3)'],
              ['Timeout',         '30 minutes'],
              ['Priority',        'normal'],
              ['Owner',           'data-eng'],
            ].map(([k,v,mono]) => (
              <div key={k}>
                <div style={{fontSize:10.5, color:HF.ink4, textTransform:'uppercase', letterSpacing:0.5, fontWeight:600}}>{k}</div>
                <div style={{marginTop:3, fontSize:13, color:HF.ink, fontFamily: mono? HF.mono : HF.sans, fontWeight:500}}>{v}</div>
              </div>
            ))}
          </div>
          <div style={{padding:`12px ${HF.cardP}px`, borderTop:`1px solid ${HF.borderFaint}`, background:HF.subtle}}>
            <div style={{fontSize:10.5, color:HF.ink4, textTransform:'uppercase', letterSpacing:0.5, fontWeight:600, marginBottom:8}}>Last 24h history</div>
            <div style={{display:'flex', gap:3}}>
              {last24.map((s, i) => (
                <div key={i} title={`${24-i}h ago: ${s}`} style={{
                  flex:1, height:22, borderRadius:2,
                  background: s==='fail' ? HF.err : HF.ok,
                  opacity: s==='fail' ? 1 : 0.85,
                }}/>
              ))}
            </div>
            <div style={{display:'flex', justifyContent:'space-between', fontSize:11, color:HF.ink4, fontFamily:HF.mono, marginTop:6, fontVariantNumeric:'tabular-nums'}}>
              <span>24h ago</span><span>12h</span><span>now</span>
            </div>
          </div>
        </HFCard>

        <HFCard title="Upcoming runs" sub={enabledState ? 'next 5 scheduled' : 'job is disabled'}>
          {!enabledState ? (
            <div style={{padding:'28px 16px', textAlign:'center'}}>
              <div style={{color:HF.ink4, marginBottom:6, display:'flex', justifyContent:'center'}}>{HF_ICONS.stop}</div>
              <div style={{fontSize:12.5, color:HF.ink3}}>No upcoming runs — job is disabled.</div>
            </div>
          ) : (
            <div style={{padding:'4px 0'}}>
              {upcoming.map((r, i, arr) => (
                <div key={i} style={{padding:`11px ${HF.cardP}px`, borderBottom: i<arr.length-1? `1px solid ${HF.borderFaint}` : 'none', display:'flex', alignItems:'center', gap:12, fontSize:12.5}}>
                  <span style={{color: i===0? HF.accentInk : HF.ink3, fontFamily:HF.mono, fontWeight: i===0? 600 : 400, minWidth:80, fontVariantNumeric:'tabular-nums'}}>{r.when}</span>
                  <span style={{color:HF.ink2, fontFamily:HF.mono}}>{r.at}</span>
                  <span style={{color:HF.ink4, fontFamily:HF.mono, fontSize:11.5}}>{r.date}</span>
                  {i===0 && <HFPill tone="accent" style={{marginLeft:'auto'}}>next</HFPill>}
                </div>
              ))}
            </div>
          )}
        </HFCard>
      </div>

      {/* Tabs: runs / logs */}
      <HFCard style={{marginBottom:HF.gap}}>
        <div style={{padding:`0 ${HF.cardP}px`}}>
          <HFTabs active={tab} onChange={setTab} tabs={[
            { id:'runs', label:'Run history', count:runs.length },
            { id:'logs', label:'Latest logs' },
          ]}/>
        </div>
      </HFCard>

      {tab === 'runs' && (
        <HFCard>
          <HFTable
            onRowClick={r => goto('run-detail', { id:r.id })}
            columns={[
              { key:'id', label:'Run', w:'0.5fr', mono:true, sortable:true, sortVal:r=>r.id, cell:v => <span style={{color:HF.accentInk, fontWeight:500}}>#{v}</span> },
              { key:'started', label:'Started', w:'0.9fr', mono:true, muted:true, sortable:true },
              { key:'dur', label:'Duration', w:'0.8fr', mono:true, muted:true, align:'right', sortable:true },
              { key:'items', label:'Items', w:'0.6fr', mono:true, align:'right', sortable:true, sortVal:r=>r.items, cell:v => <span style={{color:HF.ink, fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v.toLocaleString()}</span> },
              { key:'errors', label:'Errors', w:'0.5fr', mono:true, align:'right', sortable:true, sortVal:r=>r.errors, cell:v => v ? <span style={{color:HF.errInk, fontWeight:500}}>{v}</span> : <span style={{color:HF.ink4}}>—</span> },
              { key:'status', label:'Status', w:'0.8fr', sortable:true, cell:v => <HFPill tone={statusTone[v]}>{v}</HFPill> },
              { key:'_', label:'', w:'28px', align:'right', cell:() => <span style={{color:HF.ink4, display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
            ]}
            rows={runs}
          />
        </HFCard>
      )}

      {tab === 'logs' && (
        <HFCard title="Latest logs" sub="from run #4820 · 12m ago"
                action={<HFButton size="sm"><span style={{display:'flex'}}>{HF_ICONS.download}</span> Download log</HFButton>}>
          <div style={{padding:14, background:'#0F1419', color:'#D9E0E6', fontFamily:HF.mono, fontSize:11.5, lineHeight:1.7, borderTop:`1px solid ${HF.borderFaint}`, borderRadius:`0 0 ${HF.cardR}px ${HF.cardR}px`}}>
            {logs.map((l, i) => {
              const lvlColor = l.lvl === 'WARN' ? '#F5B041' : l.lvl === 'ERROR' ? '#E74C3C' : '#58B3E0';
              return (
                <div key={i}>
                  <span style={{color:'#6B7680'}}>{l.t}</span>
                  {' '}
                  <span style={{color:lvlColor, fontWeight:600}}>{l.lvl.padEnd(5)}</span>
                  {' '}
                  <span>{l.msg}</span>
                </div>
              );
            })}
          </div>
        </HFCard>
      )}
    </HFShell>
  );
}

Object.assign(window, { HFScheduleDetail, HFParserConfigPanel, HFRunsPanel, HFPricesPanel });
