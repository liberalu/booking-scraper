// Hi-fi Runs list + detail

function HFRuns({ nav, goto }) {
  const HF = getHF();
  const statusTone = { running:'ok', completed:'neutral', failed:'err', queued:'warn' };
  const typeTone = { full: 'accent', sitemap: 'neutral', discovered: 'muted' };

  // Filter state — backend handles the actual filtering and pagination.
  const [q, setQ] = React.useState('');
  const [shop, setShop]     = React.useState('all');
  const [phase, setPhase]   = React.useState('all');
  const [status, setStatus] = React.useState('all');
  const [when, setWhen]     = React.useState('any');
  const [page, setPage]     = React.useState(1);
  const PER_PAGE = 30;

  // Reset to page 1 whenever a filter changes.
  React.useEffect(() => { setPage(1); }, [q, shop, phase, status, when]);

  const [data, setData] = React.useState({
    runs: [], total: 0, page: 1, per_page: PER_PAGE, pages: 1,
    kpis: { running_now: 0, today_total: 0, today_ok: 0, today_failed: 0, all_time: 0 },
  });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({ page: String(page), per_page: String(PER_PAGE) });
    if (shop !== 'all') params.set('shop', shop);
    if (phase !== 'all') params.set('phase', phase);
    if (status !== 'all') params.set('status', status);
    if (when !== 'any') params.set('when', when);
    if (q.trim()) params.set('q', q.trim());
    const load = () => fetch(`/api/runs?${params.toString()}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    load();
    const id = setInterval(load, 5000);
    return () => { cancelled = true; clearInterval(id); };
  }, [q, shop, phase, status, when, page]);

  const allRows = data.runs;
  const filtered = allRows;  // backend already filtered; keep alias for table render

  const activeCount =
    (shop!=='all'?1:0) + (phase!=='all'?1:0) +
    (status!=='all'?1:0) + (when!=='any'?1:0) + (q.trim()?1:0);

  const clearAll = () => { setQ(''); setShop('all'); setPhase('all'); setStatus('all'); setWhen('any'); };

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
        { label:'Running now', value: String(data.kpis.running_now), delta:<span style={{color:HF.okInk}}>● live</span> },
        { label:'Today',       value: String(data.kpis.today_total), delta:<span style={{color:HF.ink3}}>{data.kpis.today_ok} ok · {data.kpis.today_failed} failed</span> },
        { label:'All-time',    value: String(data.kpis.all_time || 0), delta:<span style={{color:HF.ink3}}>total runs</span> },
      ]}/>

      {/* Filters — overflow:visible so the dropdown isn't clipped by the card */}
      <HFCard style={{ marginBottom: HF.gap, overflow: 'visible' }} padding={12}>
        <HFFilterBar right={<>
          <span style={{fontSize:11.5, color: activeCount? HF.accentInk : HF.ink4, fontFamily:HF.mono, fontVariantNumeric:'tabular-nums', fontWeight: activeCount? 500 : 400}}>
            {data.runs.length.toLocaleString()} of {(data.total || 0).toLocaleString()}
          </span>
          {activeCount > 0 && (
            <HFButton size="sm" variant="subtle" onClick={clearAll}>Clear ({activeCount})</HFButton>
          )}
        </>}>
          <HFSearch placeholder="Search by ID, shop, phase…" width={260} value={q} onChange={setQ}/>
          <HFFilter label="Shop"    value={shop}    onChange={setShop}    options={['all','vaga','knygos']}/>
          <HFFilter label="Phase"   value={phase}   onChange={setPhase}   options={['all','discover','scan']}/>
          <HFFilter label="Status"  value={status}  onChange={setStatus}  options={['all','running','queued','completed','failed']}/>
          <HFFilter label="When"    value={when}    onChange={setWhen}    options={['any','1h','24h','7d','30d']}/>
        </HFFilterBar>
      </HFCard>

      <HFCard>
        {filtered.length === 0 ? (
          <div style={{padding:'60px 20px', textAlign:'center', color:HF.ink3}}>
            <div style={{fontSize:28, marginBottom:8, color:HF.ink5, display:'flex', justifyContent:'center'}}>{HF_ICONS.search}</div>
            <div style={{fontSize:14, color:HF.ink, fontWeight:500, marginBottom:4}}>
              {loading ? 'Loading…' : (data.kpis.all_time || 0) === 0 ? 'No runs yet' : 'No runs match these filters'}
            </div>
            {!loading && (
              <div style={{fontSize:12.5, color:HF.ink3, marginBottom:14}}>
                {(data.kpis.all_time || 0) === 0
                  ? 'Trigger a run with the "New run" button.'
                  : `${data.kpis.all_time.toLocaleString()} runs in the database, but none match the active filters.`}
              </div>
            )}
            {!loading && activeCount > 0 && (
              <div style={{fontSize:11.5, color:HF.ink4, fontFamily:HF.mono, marginBottom:14}}>
                shop={shop} · phase={phase} · status={status} · when={when}{q ? ` · q="${q}"` : ''}
              </div>
            )}
            {!loading && activeCount > 0 && (
              <HFButton size="sm" onClick={clearAll}>Reset filters</HFButton>
            )}
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
            { key:'progress', label:'Progress', w:'1.3fr', sortable:true, sortVal:r=>r.progress, cell: (v, r) => (
              <span style={{display:'flex', alignItems:'center', gap:10, width:'100%'}}>
                <span style={{flex:1, maxWidth:160, height:5, background:HF.subtle, borderRadius:3, overflow:'hidden'}}>
                  <span style={{display:'block', width:`${v}%`, height:'100%', background: r.status==='failed'? HF.err : r.status==='running'? HF.accent : r.status==='queued'? HF.warn : HF.ink4, borderRadius:3}}/>
                </span>
                <span style={{fontFamily:HF.mono, fontSize:11.5, color:HF.ink3, minWidth:32, fontVariantNumeric:'tabular-nums'}}>{v}%</span>
              </span>
            )},
            { key:'items', label:'Items', w:'0.6fr', mono:true, align:'right', sortable:true, sortVal:r=>r.items, cell: v => v ? v.toLocaleString() : '—' },
            { key:'elapsed', label:'Duration', w:'0.65fr', mono:true, muted:true, align:'right', sortable:true, sortVal:r=>r.elapsed },
            { key:'started', label:'Started', w:'0.9fr', muted:true, sortable:true, sortVal:r=>r.startedH },
            { key:'by', label:'Trigger', w:'0.9fr', mono:true, muted:true, sortable:true },
            { key:'_', label:'', w:'28px', align:'right', cell: () => <span style={{color:HF.ink4, display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
          ]}
          rows={filtered}
        />
        )}
      </HFCard>

      {/* Pagination footer */}
      {(data.total || 0) > 0 && (
        <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:14, fontSize:12.5, color:HF.ink3}}>
          <span>
            Showing {((data.page - 1) * data.per_page + 1).toLocaleString()}–
            {Math.min(data.page * data.per_page, data.total).toLocaleString()} of {data.total.toLocaleString()} match{data.total === 1 ? '' : 'es'}
            {data.kpis.all_time > data.total && (
              <span style={{color:HF.ink4}}> · {data.kpis.all_time.toLocaleString()} total in DB</span>
            )}
          </span>
          {data.pages > 1 && (
            <div style={{display:'flex', gap:6, alignItems:'center'}}>
              <HFButton size="sm" variant="ghost"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={data.page <= 1}>‹ Prev</HFButton>
              {(() => {
                const buttons = [];
                const total = data.pages;
                const cur = data.page;
                const push = (n) => buttons.push(
                  <HFButton key={n} size="sm" variant={n === cur ? 'accent' : 'default'}
                    onClick={() => setPage(n)}>{n}</HFButton>
                );
                const ell = (k) => buttons.push(
                  <span key={k} style={{padding:'6px 4px', color:HF.ink4}}>…</span>
                );
                if (total <= 7) {
                  for (let i = 1; i <= total; i++) push(i);
                } else {
                  push(1);
                  if (cur > 4) ell('l');
                  const lo = Math.max(2, cur - 1);
                  const hi = Math.min(total - 1, cur + 1);
                  for (let i = lo; i <= hi; i++) push(i);
                  if (cur < total - 3) ell('r');
                  push(total);
                }
                return buttons;
              })()}
              <HFButton size="sm" variant="ghost"
                onClick={() => setPage(p => Math.min(data.pages, p + 1))}
                disabled={data.page >= data.pages}>Next ›</HFButton>
            </div>
          )}
        </div>
      )}
    </HFShell>
  );
}

// ───────────────────────────── Run Detail ─────────────────────────────

function HFRunDetail({ nav, goto, params }) {
  const HF = getHF();
  const runId = params?.id;
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    if (!runId) return;
    fetch(`/api/runs/${runId}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [runId]);

  if (loading || !data) {
    return (
      <HFShell {...nav} activePage="runs" title={`Run #${runId}`} subtitle="Loading…"
        breadcrumb={<><a href="#" onClick={e=>{e.preventDefault();goto('runs');}}>Runs</a><span style={{color:nav.HF?.ink5||'#c7cbd3'}}>/</span><span>#{runId}</span></>}>
        <div style={{padding:40, color:HF.ink3}}>Loading…</div>
      </HFShell>
    );
  }

  const id = data.id;

  const timeline = [];

  const throughputData = [22, 28, 34, 30, 18, 26, 32, 35, 33, 29, 31, 34, 36, 33, 30, 28];

  const phases = [];

  const runStatus = data.status || 'completed';
  const runStatusTone = { running: 'ok', completed: 'neutral', failed: 'err' };

  return (
    <HFShell {...nav} activePage="runs"
      title={<span style={{display:'flex', alignItems:'center', gap:12}}>
        <span style={{fontFamily:HF.mono, fontSize:24, fontWeight:600, color:HF.ink}}>Run #{id}</span>
        <HFPill tone={runStatusTone[runStatus] || 'neutral'}><HFDot tone={runStatusTone[runStatus] || 'neutral'} pulse={runStatus==='running'} size={6}/> {runStatus}</HFPill>
      </span>}
      subtitle={<span style={{fontFamily:HF.mono, fontSize:12.5, color:HF.ink3}}>shop={data.shop} · phase={data.phase} · started {data.started_ago} · triggered by {data.by}</span>}
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
        { label:'Progress',       value:`${data.progress}%`, delta:<span style={{color:HF.ink3}}>{data.items ? data.items.toLocaleString() + ' items' : '—'}</span> },
        { label:'Elapsed',        value:data.elapsed || '—', delta:<span style={{color:HF.ink3}}>duration</span> },
        { label:'Items',          value:data.items ? data.items.toLocaleString() : '0', delta:<span style={{color:HF.ink3}}>scraped</span> },
        { label:'Status',         value:data.status, tone: runStatusTone[runStatus] || 'neutral', delta:<span style={{color:HF.ink3}}>current</span> },
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
              ['shop', data.shop || '—'],
              ['phase', data.phase || '—'],
              ['triggered_by', data.by || '—'],
              ['started', data.started_ago || '—'],
              ['duration', data.elapsed || '—'],
              ['items', data.items != null ? String(data.items) : '—'],
              ['status', data.status || '—'],
            ].map(([k,v], i, arr) => (
              <div key={k} style={{
                display:'grid', gridTemplateColumns:'120px 1fr',
                padding:`7px ${HF.cardP}px`,
                borderBottom: i < arr.length - 1 ? `1px solid ${HF.borderFaint}` : 'none',
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
