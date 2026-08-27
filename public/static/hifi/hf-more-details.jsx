// Hi-fi Schedule detail + tab content panels (Runs, Prices)

// ═══════════════════════ Shared tab panels ═══════════════════════

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
          { key:'id', label:'Run', w:'0.5fr', mono:true, sortable:true, sortVal:r=>r.id, cell:v => <span style={{color:'var(--hf-accent-ink)', fontWeight:500}}>#{v}</span> },
          { key:'phase', label:'Phase', w:'0.8fr', mono:true, sortable:true },
          { key:'started', label:'Started', w:'0.9fr', mono:true, muted:true, sortable:true },
          { key:'dur', label:'Duration', w:'0.8fr', mono:true, muted:true, align:'right', sortable:true },
          { key:'items', label:'Items', w:'0.6fr', mono:true, align:'right', sortable:true, sortVal:r=>r.items, cell:v => <span style={{color:'var(--hf-ink)', fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v.toLocaleString()}</span> },
          { key:'errors', label:'Errors', w:'0.5fr', mono:true, align:'right', sortable:true, sortVal:r=>r.errors, cell:v => v ? <span style={{color:'var(--hf-err-ink)', fontWeight:500}}>{v}</span> : <span style={{color:'var(--hf-ink4)'}}>—</span> },
          { key:'status', label:'Status', w:'0.8fr', sortable:true, cell:v => <HFPill tone={statusTone[v]}>{v}</HFPill> },
          { key:'_', label:'', w:'28px', align:'right', cell:() => <span style={{color:'var(--hf-ink4)', display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
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
        { label:'Current',      value:'€19.90', delta:<span style={{color:'var(--hf-err-ink)'}}>−€1.10 · 12m ago</span>, tone:'err' },
        { label:'30d avg',      value:'€19.92', delta:<span style={{color:'var(--hf-ink3)'}}>σ €0.84</span> },
        { label:'All-time low', value:'€18.50', delta:<span style={{color:'var(--hf-ink3)'}}>Mar 22</span> },
        { label:'All-time high',value:'€21.00', delta:<span style={{color:'var(--hf-ink3)'}}>Apr 2</span> },
        { label:'Changes',      value:'12',     delta:<span style={{color:'var(--hf-ink3)'}}>of 127 scrapes</span> },
      ]}/>

      <HFCard title="Price trajectory" sub="30 data points · last 30 days" style={{marginBottom:'var(--hf-gap)'}}
              action={<HFPill tone="err">−5.2% vs 30d avg</HFPill>}>
        <div style={{padding:'var(--hf-card-p)'}}>
          <HFAreaChart data={history} h={200} label="Price per day"/>
          <div style={{display:'flex', justifyContent:'space-between', fontSize:11, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)', marginTop:10, fontVariantNumeric:'tabular-nums'}}>
            <span>Mar 20</span><span>Mar 27</span><span>Apr 3</span><span>Apr 10</span><span>Apr 17</span>
          </div>
        </div>
      </HFCard>

      <HFCard title="All price changes" sub={`${changes.length} recorded movements`}>
        <HFTable
          columns={[
            { key:'ts', label:'When', w:'1.1fr', mono:true, sortable:true, cell:v => <span style={{color:'var(--hf-ink2)'}}>{v}</span> },
            { key:'old', label:'Was', w:'0.7fr', mono:true, align:'right', muted:true, sortable:true, sortVal:r=>parseFloat((r.old||'').replace(/[^\d.]/g,''))||0 },
            { key:'neo', label:'Now', w:'0.7fr', mono:true, align:'right', sortable:true, sortVal:r=>parseFloat((r.neo||'').replace(/[^\d.]/g,''))||0, cell:v => <span style={{color:'var(--hf-ink)', fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v}</span> },
            { key:'pct', label:'Δ %', w:'0.6fr', mono:true, align:'right', sortable:true, sortVal:r=>r.pct||0, cell:v => v == null ? <span style={{color:'var(--hf-ink4)'}}>—</span> : <span style={{color: v<0?'var(--hf-err-ink)':v>0?'var(--hf-ok-ink)':'var(--hf-ink3)', fontWeight:600, fontVariantNumeric:'tabular-nums'}}>{v>0?'+':''}{v.toFixed(1)}%</span> },
            { key:'reason', label:'Reason', w:'1.2fr', cell:v => <span style={{color:'var(--hf-ink2)', fontSize:12}}>{v}</span> },
            { key:'run', label:'Run', w:'0.5fr', mono:true, align:'right', cell:v => <span style={{color:'var(--hf-accent-ink)', fontWeight:500}}>#{v}</span> },
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
  const jobId = params?.id ? parseInt(params.id, 10) : null;
  const [tab, setTab] = React.useState('runs');
  const [detail, setDetail] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [toggling, setToggling] = React.useState(false);
  const [editOpen, setEditOpen] = React.useState(false);
  const [deleteState, setDeleteState] = React.useState({ open: false, dependents: null, error: null, busy: false });

  const reload = React.useCallback(() => {
    if (!jobId) { setLoading(false); return; }
    setLoading(true);
    fetch(`/api/cron/${jobId}/detail`)
      .then(r => r.json())
      .then(d => { setDetail(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [jobId]);

  React.useEffect(() => { reload(); }, [reload]);

  const toggleEnabled = async () => {
    if (!jobId || toggling) return;
    setToggling(true);
    try {
      await fetch(`/api/cron/${jobId}/toggle`, { method: 'POST' });
      reload();
    } finally {
      setToggling(false);
    }
  };

  const runJobNow = async () => {
    if (!detail) return;
    try {
      const body = { shop: detail.shop, phase: detail.phase, strategy: detail.strategy || '', mode: 'delta' };
      const resp = await fetch('/api/runs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (resp.ok) goto('runs');
    } catch (e) { console.error(e); }
  };

  const name = detail?.name || params?.name || '—';
  const cron = detail?.cron || params?.cron || '';
  const shop = detail?.shop || params?.shop || '—';
  const enabledState = detail ? detail.enabled : (params?.enabled !== false);
  const stats = detail?.stats || {};
  const lastStatus = stats.last_status || params?.lastStatus || null;
  const upcoming = detail?.upcoming || [];
  const last24 = detail?.last24 || [];
  const runs = detail?.runs || [];
  const statusTone = { completed:'neutral', failed:'err', running:'ok', queued:'warn', stopping:'warn' };

  const nextKpi = upcoming[0]
    ? { value: upcoming[0].when, delta: <span style={{color:'var(--hf-ink3)'}}>{upcoming[0].at} · {upcoming[0].date}</span> }
    : { value: '—', delta: <span style={{color:'var(--hf-ink3)'}}>disabled</span> };

  return (
    <HFShell {...nav} activePage="cron"
      title={<span style={{display:'flex', alignItems:'center', gap:12, minWidth:0}}>
        <HFDot tone={enabledState ? (lastStatus==='fail'?'err':'ok') : 'neutral'} size={10}/>
        <span style={{fontFamily:'var(--hf-mono)', fontSize:18, color:'var(--hf-ink)', fontWeight:500}}>{name}</span>
        {enabledState
          ? <HFPill tone={lastStatus==='fail'?'err':'ok'}>{lastStatus==='fail'?'failing':'active'}</HFPill>
          : <HFPill tone="neutral">disabled</HFPill>}
      </span>}
      subtitle={<span style={{fontFamily:'var(--hf-mono)', fontSize:13, color:'var(--hf-ink3)'}}>{cron} · shop={shop}</span>}
      breadcrumb={<>
        <HFBreadcrumbLink page="cron" goto={goto}>Schedules</HFBreadcrumbLink>
        <span style={{color:'var(--hf-ink5)'}}>/</span>
        <span style={{color:'var(--hf-ink)', fontWeight:500, fontFamily:'var(--hf-mono)'}}>{name}</span>
      </>}
      actions={<>
        <HFButton onClick={toggleEnabled} disabled={toggling}>
          <span style={{display:'flex'}}>{enabledState ? HF_ICONS.stop : HF_ICONS.play}</span>
          {enabledState ? 'Disable' : 'Enable'}
        </HFButton>
        <HFButton onClick={() => setEditOpen(true)}>
          <span style={{display:'flex'}}>{HF_ICONS.settings}</span> Edit
        </HFButton>
        <HFButton variant="danger" onClick={() => setDeleteState({ open: true, dependents: null, error: null, busy: false })}>
          Delete
        </HFButton>
        <HFButton variant="primary" onClick={runJobNow}>
          <span style={{display:'flex'}}>{HF_ICONS.play}</span> Run now
        </HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Next run',     value: enabledState ? nextKpi.value : '—', tone: enabledState ? 'accent' : undefined, delta: enabledState ? nextKpi.delta : <span style={{color:'var(--hf-ink3)'}}>disabled</span> },
        { label:'Last 24h',     value: stats.total_24h != null ? `${stats.total_24h} runs` : '—', delta: stats.total_24h != null ? <span style={{color:'var(--hf-ok-ink)'}}>{stats.ok_24h} ok · {stats.fail_24h} failed</span> : null },
        { label:'Success rate', value: stats.success_rate_30d != null ? `${stats.success_rate_30d}%` : '—', delta: <span style={{color:'var(--hf-ink3)'}}>30d</span>, tone: stats.success_rate_30d != null ? 'ok' : undefined },
        { label:'Avg duration', value: stats.avg_dur || '—', delta: <span style={{color:'var(--hf-ink3)'}}>30d</span> },
        { label:'Last run',     value: stats.last_run_ago || '—', delta: <span style={{color: lastStatus==='fail'? 'var(--hf-err-ink)' : 'var(--hf-ok-ink)'}}>{lastStatus === 'fail' ? 'failed' : lastStatus === 'ok' ? 'ok' : '—'}</span>, tone: lastStatus==='fail'? 'err' : lastStatus==='ok'? 'ok' : undefined },
      ]}/>

      {/* Schedule card + upcoming runs */}
      <div style={{display:'grid', gridTemplateColumns:'1.4fr 1fr', gap:'var(--hf-gap)', marginBottom:'var(--hf-gap)'}}>
        <HFCard title="Schedule" sub="when this job fires">
          <div style={{padding:'var(--hf-card-p)', display:'grid', gridTemplateColumns:'1fr 1fr', gap:14}}>
            {[
              ['Cron expression', cron, true],
              ['Shop', shop],
              ['Phase', detail?.phase || '—'],
              ['Strategy', detail?.strategy || '—'],
            ].map(([k,v,mono]) => (
              <div key={k}>
                <div style={{fontSize:11, color:'var(--hf-ink4)', textTransform:'uppercase', letterSpacing:0.5, fontWeight:600}}>{k}</div>
                <div style={{marginTop:3, fontSize:13, color:'var(--hf-ink)', fontFamily: mono? 'var(--hf-mono)' : 'var(--hf-sans)', fontWeight:500}}>{v}</div>
              </div>
            ))}
          </div>
          <div style={{padding:`12px var(--hf-card-p)`, borderTop:`1px solid ${'var(--hf-border-faint)'}`, background:'var(--hf-subtle)'}}>
            <div style={{fontSize:11, color:'var(--hf-ink4)', textTransform:'uppercase', letterSpacing:0.5, fontWeight:600, marginBottom:8}}>
              Last {last24.length} runs
            </div>
            {last24.length === 0 ? (
              <div style={{fontSize:13, color:'var(--hf-ink4)'}}>No runs yet.</div>
            ) : (
              <div style={{display:'flex', gap:3}}>
                {last24.map((s, i) => (
                  <div key={i} title={`run ${last24.length - i} ago: ${s}`} style={{
                    flex:1, height:22, borderRadius:2,
                    background: s==='fail' ? 'var(--hf-err)' : 'var(--hf-ok)',
                    opacity: s==='fail' ? 1 : 0.85,
                  }}/>
                ))}
              </div>
            )}
            <div style={{display:'flex', justifyContent:'space-between', fontSize:11, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)', marginTop:6, fontVariantNumeric:'tabular-nums'}}>
              <span>oldest</span><span>newest</span>
            </div>
          </div>
        </HFCard>

        <HFCard title="Upcoming runs" sub={enabledState ? 'next 5 scheduled' : 'job is disabled'}>
          {!enabledState ? (
            <div style={{padding:'28px 16px', textAlign:'center'}}>
              <div style={{color:'var(--hf-ink4)', marginBottom:6, display:'flex', justifyContent:'center'}}>{HF_ICONS.stop}</div>
              <div style={{fontSize:13, color:'var(--hf-ink3)'}}>No upcoming runs — job is disabled.</div>
            </div>
          ) : upcoming.length === 0 && !loading ? (
            <div style={{padding:'28px 16px', textAlign:'center'}}>
              <div style={{fontSize:13, color:'var(--hf-ink3)'}}>Could not compute schedule.</div>
            </div>
          ) : (
            <div style={{padding:'4px 0'}}>
              {upcoming.map((r, i, arr) => (
                <div key={i} style={{padding:`11px var(--hf-card-p)`, borderBottom: i<arr.length-1? `1px solid ${'var(--hf-border-faint)'}` : 'none', display:'flex', alignItems:'center', gap:12, fontSize:13}}>
                  <span style={{color: i===0? 'var(--hf-accent-ink)' : 'var(--hf-ink3)', fontFamily:'var(--hf-mono)', fontWeight: i===0? 600 : 400, minWidth:80, fontVariantNumeric:'tabular-nums'}}>{r.when}</span>
                  <span style={{color:'var(--hf-ink2)', fontFamily:'var(--hf-mono)'}}>{r.at}</span>
                  <span style={{color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)', fontSize:12}}>{r.date}</span>
                  {i===0 && <HFPill tone="accent" style={{marginLeft:'auto'}}>next</HFPill>}
                </div>
              ))}
            </div>
          )}
        </HFCard>
      </div>

      {/* Tabs: runs / logs */}
      <HFCard style={{marginBottom:'var(--hf-gap)'}}>
        <div style={{padding:`0 var(--hf-card-p)`}}>
          <HFTabs active={tab} onChange={setTab} tabs={[
            { id:'runs', label:'Run history', count: runs.length || undefined },
            { id:'logs', label:'Latest logs' },
          ]}/>
        </div>
      </HFCard>

      {tab === 'runs' && (
        <HFCard>
          {runs.length === 0 ? (
            <HFEmptyState title="No runs yet" sub="This job has not run yet." onClear={null}/>
          ) : (
            <HFTable
              onRowClick={r => goto('run-detail', { id:r.id })}
              columns={[
                { key:'id', label:'Run', w:'0.5fr', mono:true, sortable:true, sortVal:r=>r.id, cell:v => <span style={{color:'var(--hf-accent-ink)', fontWeight:500}}>#{v}</span> },
                { key:'started', label:'Started', w:'0.9fr', mono:true, muted:true, sortable:true },
                { key:'dur', label:'Duration', w:'0.8fr', mono:true, muted:true, align:'right', sortable:true },
                { key:'items', label:'Items', w:'0.6fr', mono:true, align:'right', sortable:true, sortVal:r=>r.items, cell:v => <span style={{color:'var(--hf-ink)', fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{(v||0).toLocaleString()}</span> },
                { key:'errors', label:'Errors', w:'0.5fr', mono:true, align:'right', sortable:true, sortVal:r=>r.errors, cell:v => v ? <span style={{color:'var(--hf-err-ink)', fontWeight:500}}>{v}</span> : <span style={{color:'var(--hf-ink4)'}}>—</span> },
                { key:'status', label:'Status', w:'0.8fr', sortable:true, cell:v => <HFPill tone={statusTone[v]||'neutral'}>{v}</HFPill> },
                { key:'_', label:'', w:'28px', align:'right', cell:() => <span style={{color:'var(--hf-ink4)', display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
              ]}
              rows={runs}
            />
          )}
        </HFCard>
      )}

      {tab === 'logs' && (
        <HFCard title="Latest logs" sub="log streaming not yet available">
          <div style={{padding:'32px 16px', textAlign:'center'}}>
            <div style={{color:'var(--hf-ink4)', marginBottom:8, display:'flex', justifyContent:'center'}}>{HF_ICONS.books}</div>
            <div style={{fontSize:13, color:'var(--hf-ink3)', fontWeight:500}}>Log streaming not yet available</div>
            <div style={{fontSize:12, color:'var(--hf-ink4)', marginTop:4}}>Run events and detailed logs will appear here in a future release.</div>
          </div>
        </HFCard>
      )}

      {editOpen && (
        <HFEditScheduleDialog
          open={editOpen}
          job={{ id: jobId, name, shop, phase: detail?.phase, strategy: detail?.strategy, cron, chain_to_id: detail?.chain_to_id ?? null }}
          onClose={(saved) => { setEditOpen(false); if (saved) reload(); }}
        />
      )}

      <HFModal open={deleteState.open}
               onClose={() => setDeleteState(s => ({ ...s, open: false }))}
               width={520}>
        <HFModalHead
          title="Delete schedule"
          sub={name ? `Confirm deletion of ${name}` : undefined}
          onClose={() => setDeleteState(s => ({ ...s, open: false }))}
        />
        <HFModalBody>
          {deleteState.dependents && deleteState.dependents.length > 0 ? (
            <>
              <div style={{ fontSize: 13, color: 'var(--hf-ink2)', marginBottom: 10 }}>
                Cannot delete — these schedules chain to this one. Unlink each
                one first (open it, click Edit, clear the chain), then come
                back to delete.
              </div>
              <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 6 }}>
                {deleteState.dependents.map(d => (
                  <li key={d.id}>
                    <button
                      type="button"
                      onClick={() => goto('schedule-detail', { id: d.id })}
                      style={{
                        background: 'var(--hf-subtle)', border: '1px solid var(--hf-border)',
                        borderRadius: 6, padding: '8px 12px', cursor: 'pointer',
                        width: '100%', textAlign: 'left',
                        fontFamily: 'var(--hf-mono)', fontSize: 12, color: 'var(--hf-ink)',
                      }}
                    >{d.name} →</button>
                  </li>
                ))}
              </ul>
            </>
          ) : deleteState.error ? (
            <div style={{ fontSize: 13, color: 'var(--hf-err-ink)' }}>
              {deleteState.error}
            </div>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--hf-ink2)' }}>
              Delete schedule <strong>{name}</strong>? This cannot be undone.
            </div>
          )}
        </HFModalBody>
        <HFModalFoot>
          <HFButton size="sm" variant="ghost"
                    onClick={() => setDeleteState(s => ({ ...s, open: false }))}>
            {deleteState.dependents ? 'Close' : 'Cancel'}
          </HFButton>
          {!deleteState.dependents && (
            <HFButton size="sm" variant="danger" disabled={deleteState.busy}
                      onClick={async () => {
                        setDeleteState(s => ({ ...s, busy: true, error: null }));
                        try {
                          const resp = await fetch(`/api/cron/${jobId}`, { method: 'DELETE' });
                          if (resp.status === 200) {
                            window.HF_APP?.toast?.({ tone: 'ok', message: 'Schedule deleted' });
                            goto('cron');
                            return;
                          }
                          if (resp.status === 409) {
                            const body = await resp.json().catch(() => ({}));
                            const detail = body?.detail || {};
                            setDeleteState({
                              open: true, busy: false, error: null,
                              dependents: Array.isArray(detail.dependents) ? detail.dependents : [],
                            });
                            return;
                          }
                          const body = await resp.json().catch(() => ({}));
                          setDeleteState(s => ({
                            ...s, busy: false,
                            error: (body?.detail && typeof body.detail === 'string')
                              ? body.detail : `Error ${resp.status}`,
                          }));
                        } catch (e) {
                          setDeleteState(s => ({ ...s, busy: false, error: String(e) }));
                        }
                      }}>
              {deleteState.busy ? 'Deleting…' : 'Delete'}
            </HFButton>
          )}
        </HFModalFoot>
      </HFModal>
    </HFShell>
  );
}

Object.assign(window, { HFScheduleDetail, HFRunsPanel, HFPricesPanel });
