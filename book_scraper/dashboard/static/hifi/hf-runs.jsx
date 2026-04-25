// Hi-fi Runs list + detail

function HFRuns({ nav, goto }) {
  const HF = getHF();
  const statusTone = { running:'ok', completed:'neutral', failed:'err', queued:'warn' };

  const allRows = [
    { id:4821, shop:'vaga',   phase:'scan',     type:'full',       status:'running',   prog:72,  items:1240, dur:'12m',   started:'2 min ago',  startedH:0.03, by:'cron:hourly' },
    { id:4820, shop:'vaga',   phase:'discover', type:'sitemap',    status:'completed', prog:100, items:820,  dur:'4m 18s', started:'18 min ago', startedH:0.3, by:'cron:hourly' },
    { id:4819, shop:'knygos', phase:'prices',   type:'discovered', status:'running',   prog:41,  items:455,  dur:'2m 02s', started:'2 min ago',  startedH:0.03,by:'manual · anna' },
    { id:4818, shop:'vaga',   phase:'scan',     type:'discovered', status:'queued',    prog:0,   items:0,    dur:'—',     started:'queued',     startedH:0,   by:'cron:hourly' },
    { id:4815, shop:'vaga',   phase:'scan',     type:'full',       status:'completed', prog:100, items:3102, dur:'42m',   started:'1h 12m ago', startedH:1.2, by:'cron:daily' },
    { id:4814, shop:'knygos', phase:'scan',     type:'discovered', status:'completed', prog:100, items:612,  dur:'18m',   started:'2h ago',     startedH:2,   by:'cron:daily' },
    { id:4812, shop:'knygos', phase:'discover', type:'sitemap',    status:'failed',    prog:12,  items:0,    dur:'1m',    started:'3h ago',     startedH:3,   by:'manual · tomas' },
    { id:4810, shop:'vaga',   phase:'discover', type:'sitemap',    status:'completed', prog:100, items:612,  dur:'18m',   started:'5h ago',     startedH:5,   by:'cron:daily' },
    { id:4808, shop:'vaga',   phase:'prices',   type:'full',       status:'completed', prog:100, items:14200,dur:'1h 02m', started:'7h ago',    startedH:7,   by:'cron:daily' },
    { id:4805, shop:'knygos', phase:'prices',   type:'discovered', status:'completed', prog:100, items:2890, dur:'22m',   started:'9h ago',     startedH:9,   by:'cron:daily' },
    { id:4803, shop:'vaga',   phase:'scan',     type:'full',       status:'failed',    prog:38,  items:420,  dur:'14m',   started:'12h ago',    startedH:12,  by:'cron:hourly' },
    { id:4800, shop:'knygos', phase:'discover', type:'sitemap',    status:'completed', prog:100, items:1012, dur:'22m',   started:'1d ago',     startedH:24,  by:'cron:daily' },
    { id:4795, shop:'vaga',   phase:'scan',     type:'discovered', status:'completed', prog:100, items:240,  dur:'6m',    started:'1d 4h ago',  startedH:28,  by:'manual · anna' },
    { id:4790, shop:'vaga',   phase:'prices',   type:'sitemap',    status:'completed', prog:100, items:8900, dur:'48m',   started:'1d 12h ago', startedH:36,  by:'cron:daily' },
    { id:4784, shop:'knygos', phase:'scan',     type:'full',       status:'failed',    prog:62,  items:180,  dur:'22m',   started:'2d ago',     startedH:48,  by:'cron:daily' },
    { id:4770, shop:'vaga',   phase:'discover', type:'discovered', status:'completed', prog:100, items:94,   dur:'3m',    started:'5d ago',     startedH:120, by:'manual · tomas' },
  ];

  const typeTone = { full: 'accent', sitemap: 'neutral', discovered: 'muted' };

  // Filter state
  const [q, setQ] = React.useState('');
  const [shop, setShop]     = React.useState('all');
  const [phase, setPhase]   = React.useState('all');
  const [type, setType]     = React.useState('all');
  const [status, setStatus] = React.useState('all');
  const [when, setWhen]     = React.useState('any');
  const [trigger, setTrigger] = React.useState('all');

  const whenBounds = { any: Infinity, '1h': 1, '24h': 24, '7d': 168, '30d': 720 };

  const filtered = React.useMemo(() => {
    const qq = q.trim().toLowerCase();
    return allRows.filter(r => {
      if (shop !== 'all' && r.shop !== shop) return false;
      if (phase !== 'all' && r.phase !== phase) return false;
      if (type !== 'all' && r.type !== type) return false;
      if (status !== 'all' && r.status !== status) return false;
      if (trigger !== 'all') {
        if (trigger === 'cron' && !r.by.startsWith('cron')) return false;
        if (trigger === 'manual' && !r.by.startsWith('manual')) return false;
      }
      if (when !== 'any' && r.startedH > whenBounds[when]) return false;
      if (qq) {
        const hay = `${r.id} ${r.shop} ${r.phase} ${r.type} ${r.status} ${r.by}`.toLowerCase();
        if (!hay.includes(qq)) return false;
      }
      return true;
    });
  }, [q, shop, phase, type, status, when, trigger]);

  const activeCount =
    (shop!=='all'?1:0) + (phase!=='all'?1:0) + (type!=='all'?1:0) +
    (status!=='all'?1:0) + (when!=='any'?1:0) + (trigger!=='all'?1:0) +
    (q.trim()?1:0);

  const clearAll = () => { setQ(''); setShop('all'); setPhase('all'); setType('all'); setStatus('all'); setWhen('any'); setTrigger('all'); };

  return (
    <HFShell {...nav} activePage="runs"
      title="Runs" subtitle="Every scrape execution — manual and scheduled. Click a row to open details."
      breadcrumb={<><span>BookScraper</span><span style={{color:HF.ink5}}>/</span><span style={{color:HF.ink, fontWeight:500}}>Runs</span></>}
      actions={<>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.download}</span> Export CSV</HFButton>
        <HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openNewRun()}><span style={{display:'flex'}}>{HF_ICONS.play}</span> New run</HFButton>
      </>}
    >
      {/* Summary strip */}
      <HFKpiStrip items={[
        { label:'Running now', value:'2', delta:<span style={{color:HF.okInk}}>● live</span> },
        { label:'Queued',      value:'1', delta:<span style={{color:HF.ink3}}>next in 4m</span> },
        { label:'Today',       value:'38', delta:<span style={{color:HF.ink3}}>34 completed · 2 failed</span> },
        { label:'Success rate (7d)', value:'94.2%', delta:<span style={{color:HF.okInk}}>▲ 1.4pp</span> },
        { label:'Avg duration', value:'18m', delta:<span style={{color:HF.ink3}}>p95 42m</span> },
      ]}/>

      {/* Filters */}
      <HFCard style={{ marginBottom: HF.gap }} padding={12}>
        <HFFilterBar right={<>
          <span style={{fontSize:11.5, color: activeCount? HF.accentInk : HF.ink4, fontFamily:HF.mono, fontVariantNumeric:'tabular-nums', fontWeight: activeCount? 500 : 400}}>
            {filtered.length} of {allRows.length}
          </span>
          {activeCount > 0 && (
            <HFButton size="sm" variant="subtle" onClick={clearAll}>Clear ({activeCount})</HFButton>
          )}
          <HFButton size="sm"><span style={{display:'flex'}}>{HF_ICONS.refresh}</span> Refresh</HFButton>
        </>}>
          <HFSearch placeholder="Search by ID, shop, user…" width={260} value={q} onChange={setQ}/>
          <HFFilter label="Shop"    value={shop}    onChange={setShop}    options={['all','vaga','knygos']}/>
          <HFFilter label="Phase"   value={phase}   onChange={setPhase}   options={['all','discover','scan','prices']}/>
          <HFFilter label="Type"    value={type}    onChange={setType}    options={['all','full','sitemap','discovered']}/>
          <HFFilter label="Status"  value={status}  onChange={setStatus}  options={['all','running','queued','completed','failed']}/>
          <HFFilter label="When"    value={when}    onChange={setWhen}    options={['any','1h','24h','7d','30d']}/>
          <HFFilter label="Trigger" value={trigger} onChange={setTrigger} options={['all','cron','manual']}/>
        </HFFilterBar>
      </HFCard>

      <HFCard>
        {filtered.length === 0 ? (
          <div style={{padding:'60px 20px', textAlign:'center', color:HF.ink3}}>
            <div style={{fontSize:28, marginBottom:8, color:HF.ink5, display:'flex', justifyContent:'center'}}>{HF_ICONS.search}</div>
            <div style={{fontSize:14, color:HF.ink, fontWeight:500, marginBottom:4}}>No runs match these filters</div>
            <div style={{fontSize:12.5, color:HF.ink3, marginBottom:14}}>Try clearing filters or adjusting the time range.</div>
            <HFButton size="sm" onClick={clearAll}>Clear filters</HFButton>
          </div>
        ) : (
        <HFTable
          onRowClick={(r) => goto('run-detail', { id: r.id })}
          columns={[
            { key:'id', label:'Run', w:'0.55fr', mono:true, sortable:true, sortVal:r=>r.id, cell: v => <span style={{color:HF.accentInk, fontWeight:500}}>#{v}</span> },
            { key:'shop', label:'Shop', w:'0.6fr', sortable:true, cell: v => <span style={{color:HF.ink, fontWeight:500}}>{v}</span> },
            { key:'phase', label:'Phase / Type', w:'1fr', sortable:true, sortVal:r=>r.phase+':'+r.type, cell: (v, r) => (
              <span style={{display:'flex', flexDirection:'column', gap:3, minWidth:0}}>
                <span style={{fontFamily:HF.mono, fontSize:12.5, color:HF.ink, fontWeight:500}}>{v}</span>
                <HFPill tone={typeTone[r.type]} style={{width:'fit-content', height:17, fontSize:10.5, padding:'0 6px', letterSpacing:0.2}}>{r.type}</HFPill>
              </span>
            )},
            { key:'status', label:'Status', w:'0.85fr', sortable:true, cell: (v, r) => (
              <span style={{display:'inline-flex', alignItems:'center', gap:7}}>
                <HFDot tone={statusTone[v]} pulse={v==='running'}/>
                <span style={{color: v==='failed'? HF.errInk : HF.ink, fontWeight: v==='running'? 500 : 400}}>{v}</span>
              </span>
            )},
            { key:'prog', label:'Progress', w:'1.3fr', sortable:true, sortVal:r=>r.prog, cell: (v, r) => (
              <span style={{display:'flex', alignItems:'center', gap:10, width:'100%'}}>
                <span style={{flex:1, maxWidth:160, height:5, background:HF.subtle, borderRadius:3, overflow:'hidden'}}>
                  <span style={{display:'block', width:`${v}%`, height:'100%', background: r.status==='failed'? HF.err : r.status==='running'? HF.accent : r.status==='queued'? HF.warn : HF.ink4, borderRadius:3}}/>
                </span>
                <span style={{fontFamily:HF.mono, fontSize:11.5, color:HF.ink3, minWidth:32, fontVariantNumeric:'tabular-nums'}}>{v}%</span>
              </span>
            )},
            { key:'items', label:'Items', w:'0.6fr', mono:true, align:'right', sortable:true, sortVal:r=>r.items, cell: v => v ? v.toLocaleString() : '—' },
            { key:'dur', label:'Duration', w:'0.65fr', mono:true, muted:true, align:'right', sortable:true, sortVal:r=>r.dur },
            { key:'started', label:'Started', w:'0.9fr', muted:true, sortable:true, sortVal:r=>r.startedH },
            { key:'by', label:'Trigger', w:'0.9fr', mono:true, muted:true, sortable:true },
            { key:'_', label:'', w:'28px', align:'right', cell: () => <span style={{color:HF.ink4, display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
          ]}
          rows={filtered}
        />
        )}
      </HFCard>

      {/* Pagination */}
      <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:14, fontSize:12.5, color:HF.ink3}}>
        <span>Showing 1–12 of 2,184</span>
        <div style={{display:'flex', gap:6}}>
          <HFButton size="sm" variant="ghost">‹ Prev</HFButton>
          <HFButton size="sm" variant="accent">1</HFButton>
          <HFButton size="sm">2</HFButton>
          <HFButton size="sm">3</HFButton>
          <span style={{padding:'6px 4px', color:HF.ink4}}>…</span>
          <HFButton size="sm">183</HFButton>
          <HFButton size="sm">Next ›</HFButton>
        </div>
      </div>
    </HFShell>
  );
}

// ───────────────────────────── Run Detail ─────────────────────────────

function HFRunDetail({ nav, goto, params }) {
  const HF = getHF();
  const id = params?.id || 4821;

  const timeline = [
    { t:'14:02:11', ev:'run.started',    msg:'Triggered by cron:hourly · shop=vaga', tone:'accent' },
    { t:'14:02:13', ev:'urls.loaded',    msg:'Loaded 1,720 URLs from seed queue',    tone:'neutral' },
    { t:'14:02:14', ev:'worker.spawned', msg:'4 workers started · concurrency=4',    tone:'neutral' },
    { t:'14:03:02', ev:'batch.completed',msg:'Batch 1/14 · 124 items · 49s',         tone:'ok' },
    { t:'14:04:41', ev:'batch.completed',msg:'Batch 2/14 · 128 items · 1m 39s',      tone:'ok' },
    { t:'14:06:18', ev:'rate_limit',     msg:'429 from vaga.lt · backoff 20s',       tone:'warn' },
    { t:'14:08:22', ev:'batch.completed',msg:'Batch 3/14 · 118 items · 2m 04s',      tone:'ok' },
    { t:'14:10:55', ev:'validation',     msg:'18 items failed validation (missing_isbn)', tone:'warn' },
    { t:'14:13:09', ev:'batch.completed',msg:'Batch 4/14 · 130 items · 2m 14s',      tone:'ok' },
    { t:'14:14:22', ev:'heartbeat',      msg:'alive · 532/1720 done · eta 9m',       tone:'neutral' },
  ];

  const throughputData = [22, 28, 34, 30, 18, 26, 32, 35, 33, 29, 31, 34, 36, 33, 30, 28];

  const phases = [
    { name:'init',     status:'ok',      dur:'2s',    items:0 },
    { name:'load',     status:'ok',      dur:'14s',   items:1720 },
    { name:'discover', status:'ok',      dur:'52s',   items:532 },
    { name:'scan',     status:'running', dur:'11m',   items:1240, prog:72 },
    { name:'validate', status:'pending', dur:'—',     items:0 },
    { name:'persist',  status:'pending', dur:'—',     items:0 },
  ];

  return (
    <HFShell {...nav} activePage="runs"
      title={<span style={{display:'flex', alignItems:'center', gap:12}}>
        <span style={{fontFamily:HF.mono, fontSize:24, fontWeight:600, color:HF.ink}}>Run #{id}</span>
        <HFPill tone="ok"><HFDot tone="ok" pulse size={6}/> running</HFPill>
      </span>}
      subtitle={<span style={{fontFamily:HF.mono, fontSize:12.5, color:HF.ink3}}>shop=vaga · phase=scan · started 2 min ago · triggered by cron:hourly</span>}
      breadcrumb={<>
        <a href="#" onClick={(e)=>{e.preventDefault(); goto('runs');}} style={{color:HF.ink3, textDecoration:'none'}}>Runs</a>
        <span style={{color:HF.ink5}}>/</span>
        <span style={{color:HF.ink, fontWeight:500, fontFamily:HF.mono}}>#{id}</span>
      </>}
      actions={<>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.download}</span> Logs</HFButton>
        <HFButton variant="danger"><span style={{display:'flex'}}>{HF_ICONS.stop}</span> Stop run</HFButton>
      </>}
    >
      {/* Live metrics strip */}
      <HFKpiStrip items={[
        { label:'Progress',       value:'72%', delta:<span style={{color:HF.ink3}}>1,240 of 1,720</span> },
        { label:'Throughput',     value:'28/min', delta:<span style={{color:HF.okInk}}>▲ 4 vs avg</span> },
        { label:'Elapsed',        value:'12m 04s', delta:<span style={{color:HF.ink3}}>eta 4m</span> },
        { label:'Workers',        value:'4 / 4',   delta:<span style={{color:HF.ink3}}>0 idle</span> },
        { label:'Errors',         value:'18', delta:<span style={{color:HF.warnInk}}>all validation</span>, tone:'warn' },
      ]}/>

      {/* Phase pipeline + Throughput */}
      <div style={{display:'grid', gridTemplateColumns:'1.55fr 1fr', gap:HF.gap, marginBottom:HF.gap}}>
        <HFCard title="Pipeline" sub="phase-by-phase">
          <div style={{padding:`14px ${HF.cardP}px ${HF.cardP}px`}}>
            <div style={{display:'flex', alignItems:'stretch', gap:8}}>
              {phases.map((p, i) => {
                const tone = p.status==='ok'?'ok':p.status==='running'?'accent':p.status==='fail'?'err':'neutral';
                const bg = p.status==='ok'? HF.okSoft : p.status==='running'? HF.accentSoft : HF.subtle;
                const bd = p.status==='ok'? HF.okBorder : p.status==='running'? HF.accentBorder : HF.border;
                const fg = p.status==='pending'? HF.ink4 : HF.ink;
                return (
                  <div key={p.name} style={{flex:1, minWidth:0}}>
                    <div style={{
                      background:bg, border:`1px solid ${bd}`, borderRadius:6,
                      padding:'10px 12px', position:'relative',
                    }}>
                      <div style={{display:'flex', alignItems:'center', gap:6, marginBottom:6}}>
                        <HFDot tone={tone} pulse={p.status==='running'} size={7}/>
                        <span style={{fontFamily:HF.mono, fontSize:12, color:fg, fontWeight:500}}>{p.name}</span>
                      </div>
                      <div style={{fontFamily:HF.mono, fontSize:11, color:HF.ink3, fontVariantNumeric:'tabular-nums'}}>{p.dur}</div>
                      {p.items > 0 && <div style={{fontFamily:HF.mono, fontSize:11, color:HF.ink4, fontVariantNumeric:'tabular-nums', marginTop:2}}>{p.items.toLocaleString()} items</div>}
                      {p.status==='running' && (
                        <div style={{position:'absolute', left:0, right:0, bottom:0, height:3, background:HF.accentSoft2, borderRadius:'0 0 5px 5px', overflow:'hidden'}}>
                          <div style={{width:`${p.prog}%`, height:'100%', background:HF.accent}}/>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </HFCard>

        <HFCard title="Throughput" sub="items / minute · live"
                action={<span style={{fontFamily:HF.mono, fontSize:12, color:HF.accentInk, fontVariantNumeric:'tabular-nums'}}>28/min</span>}>
          <div style={{padding:`${HF.cardP}px`}}>
            <HFAreaChart data={throughputData} h={120}/>
            <div style={{display:'flex', justifyContent:'space-between', fontSize:11, color:HF.ink4, fontFamily:HF.mono, marginTop:6, fontVariantNumeric:'tabular-nums'}}>
              <span>-15m</span><span>-10m</span><span>-5m</span><span>now</span>
            </div>
          </div>
        </HFCard>
      </div>

      {/* Events + Params */}
      <div style={{display:'grid', gridTemplateColumns:'1.7fr 1fr', gap:HF.gap}}>
        <HFCard title="Event stream" sub="most recent 10 events · live"
                action={<HFButton size="sm" variant="subtle"><span style={{display:'flex'}}>{HF_ICONS.download}</span> Export</HFButton>}>
          <div style={{padding:`4px 0`}}>
            {timeline.map((e, i) => {
              const tonebg = e.tone==='ok'? HF.okSoft : e.tone==='warn'? HF.warnSoft : e.tone==='accent'? HF.accentSoft : HF.subtle;
              const toneink = e.tone==='ok'? HF.okInk : e.tone==='warn'? HF.warnInk : e.tone==='accent'? HF.accentInk : HF.ink2;
              const toneb = e.tone==='ok'? HF.okBorder : e.tone==='warn'? HF.warnBorder : e.tone==='accent'? HF.accentBorder : HF.border;
              return (
                <div key={i} style={{
                  display:'grid', gridTemplateColumns:'86px 180px 1fr',
                  padding:`8px ${HF.cardP}px`,
                  borderBottom: i < timeline.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
                  fontSize:12.5, alignItems:'center', gap:10,
                }}>
                  <span style={{fontFamily:HF.mono, fontSize:11.5, color:HF.ink4, fontVariantNumeric:'tabular-nums'}}>{e.t}</span>
                  <span style={{
                    display:'inline-flex', alignItems:'center',
                    padding:'1px 8px', borderRadius:4,
                    background:tonebg, border:`1px solid ${toneb}`, color:toneink,
                    fontFamily:HF.mono, fontSize:11, fontWeight:500,
                    width:'fit-content', whiteSpace:'nowrap',
                  }}>{e.ev}</span>
                  <span style={{color:HF.ink2, fontFamily:HF.mono, fontSize:12, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{e.msg}</span>
                </div>
              );
            })}
          </div>
        </HFCard>

        <HFCard title="Parameters">
          <div style={{padding:`4px 0`}}>
            {[
              ['run_id', `#${id}`],
              ['shop', 'vaga'],
              ['phase', 'scan'],
              ['triggered_by', 'cron:hourly'],
              ['started_at', '2026-04-19 14:02:11'],
              ['concurrency', '4'],
              ['timeout_s', '3600'],
              ['seed_size', '1720'],
              ['retry_policy', 'exp · max=3'],
              ['commit_batch', '100'],
            ].map(([k,v], i) => (
              <div key={k} style={{
                display:'grid', gridTemplateColumns:'120px 1fr',
                padding:`7px ${HF.cardP}px`,
                borderBottom: i < 9 ? `1px solid ${HF.borderFaint}` : 'none',
                fontSize:12.5,
              }}>
                <span style={{fontFamily:HF.mono, color:HF.ink3}}>{k}</span>
                <span style={{fontFamily:HF.mono, color:HF.ink, fontWeight:500, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{v}</span>
              </div>
            ))}
          </div>
        </HFCard>
      </div>
    </HFShell>
  );
}

Object.assign(window, { HFRuns, HFRunDetail });
