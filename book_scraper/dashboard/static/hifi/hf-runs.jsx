// Hi-fi Runs list + detail

function HFRuns({ nav, goto }) {
  const HF = getHF();
  const statusTone = { running:'ok', paused:'warn', stopping:'warn', completed:'neutral', failed:'err', queued:'warn' };
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


  // Schedule info — "Next run in Xh", "Last success Xh ago" badges.
  const [scheduleItems, setScheduleItems] = React.useState([]);
  React.useEffect(() => {
    let cancelled = false;
    const load = () => fetch('/api/schedule')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (!cancelled && d) setScheduleItems(d.items || []); })
      .catch(() => {});
    load();
    const id = setInterval(load, 60000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const _fmtSeconds = (s) => {
    if (s == null) return '—';
    if (s < 60) return `${s}s`;
    if (s < 3600) return `${Math.round(s/60)}m`;
    const h = Math.floor(s/3600), m = Math.round((s%3600)/60);
    return m ? `${h}h ${m}m` : `${h}h`;
  };
  const _fmtAgoIso = (iso) => {
    if (!iso) return '—';
    const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    return _fmtSeconds(diff) + ' ago';
  };

  const allRows = data.runs;
  const filtered = allRows;  // backend already filtered; keep alias for table render

  const activeCount =
    (shop!=='all'?1:0) + (phase!=='all'?1:0) +
    (status!=='all'?1:0) + (when!=='any'?1:0) + (q.trim()?1:0);

  const clearAll = () => { setQ(''); setShop('all'); setPhase('all'); setStatus('all'); setWhen('any'); };

  return (
    <HFShell {...nav} activePage="runs"
      title="Runs" subtitle="Every scrape execution — manual and scheduled. Click a row to open details."
      breadcrumb={<><span>BookScraper</span><span style={{color:'var(--hf-ink5)'}}>/</span><span style={{color:'var(--hf-ink)', fontWeight:500}}>Runs</span></>}
      actions={<>
        <HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openNewRun()}><span style={{display:'flex'}}>{HF_ICONS.play}</span> New run</HFButton>
      </>}
    >
      {/* Schedule badges — "Next run in Xh" + "Last success Xh ago" */}
      {scheduleItems.length > 0 && (
        <div style={{display:'flex', gap:8, marginBottom:'var(--hf-gap)', flexWrap:'wrap'}}>
          {scheduleItems.map((s, i) => (
            <div key={i} style={{display:'flex', gap:8, padding:'6px 12px', background:'var(--hf-subtle)', borderRadius:6, fontSize:12, color:'var(--hf-ink3)', fontFamily:'var(--hf-mono)', alignItems:'center'}}>
              <span style={{color:'var(--hf-ink)', fontWeight:500}}>{s.shop}/{s.phase}</span>
              {s.next_run_in_s != null && (
                <span title={s.next_run_at || ''}>next in <strong style={{color:'var(--hf-ink)'}}>{_fmtSeconds(s.next_run_in_s)}</strong></span>
              )}
              <span style={{color:'var(--hf-ink5)'}}>·</span>
              <span title={s.last_success_at || ''}>last ok: <strong style={{color:'var(--hf-ink)'}}>{_fmtAgoIso(s.last_success_at)}</strong></span>
            </div>
          ))}
        </div>
      )}

      {/* Summary strip — clickable filter shortcuts */}
      <HFKpiStrip items={[
        { label:'Running now', value: String(data.kpis.running_now), delta:<span style={{color:'var(--hf-ok-ink)'}}>● live</span>,
          onClick: () => { setStatus('running'); setWhen('any'); } },
        { label:'Last 24h',    value: String(data.kpis.today_total), delta:<span style={{color:'var(--hf-ink3)'}}>{data.kpis.today_ok} ok · {data.kpis.today_failed} failed</span>,
          onClick: () => { setStatus('all'); setWhen('24h'); } },
        { label:'All-time',    value: String(data.kpis.all_time || 0), delta:<span style={{color:'var(--hf-ink3)'}}>total runs</span>,
          onClick: clearAll },
      ]}/>

      {/* Filters — overflow:visible so the dropdown isn't clipped by the card */}
      <HFCard style={{ marginBottom: 'var(--hf-gap)', overflow: 'visible' }} padding={12}>
        <HFFilterBar right={<>
          <span style={{fontSize:12, color: activeCount? 'var(--hf-accent-ink)' : 'var(--hf-ink4)', fontFamily:'var(--hf-mono)', fontVariantNumeric:'tabular-nums', fontWeight: activeCount? 500 : 400}}>
            {data.runs.length.toLocaleString()} of {(data.total || 0).toLocaleString()}
          </span>
          {activeCount > 0 && (
            <HFButton size="sm" variant="subtle" onClick={clearAll}>Clear ({activeCount})</HFButton>
          )}
        </>}>
          <HFSearch placeholder="Search by ID, shop, phase…" width={260} value={q} onChange={setQ}/>
          <HFFilter label="Shop"    value={shop}    onChange={setShop}    options={['all','vaga','pegasas','knygos']}/>
          <HFFilter label="Phase"   value={phase}   onChange={setPhase}   options={['all','discover','scan']}/>
          <HFFilter label="Status"  value={status}  onChange={setStatus}  options={['all','running','paused','queued','completed','failed']}/>
          <HFFilter label="When"    value={when}    onChange={setWhen}    options={['any','1h','24h','7d','30d']}/>
        </HFFilterBar>
      </HFCard>

      <HFCard>
        {loading && data.runs.length === 0 ? (
          <HFTableSkeleton rows={10} columns={[
            { w: '0.5fr',  skelW: 45,  mono: true },
            { w: '0.6fr',  skelW: 55 },
            { w: '1fr',    skelW: 90 },
            { w: '0.8fr',  skelW: 70 },
            { w: '1.1fr',  skelW: 140 },
            { w: '0.5fr',  skelW: 40,  mono: true, align: 'right' },
            { w: '0.55fr', skelW: 45,  mono: true, align: 'right' },
            { w: '0.65fr', skelW: 50,  mono: true, align: 'right' },
            { w: '0.6fr',  skelW: 50,  mono: true, align: 'right' },
            { w: '0.85fr', skelW: 70 },
            { w: '28px',   skelW: 12,  align: 'right' },
          ]}/>
        ) : filtered.length === 0 ? (
          <div style={{padding:'60px 20px', textAlign:'center', color:'var(--hf-ink3)'}}>
            <div style={{fontSize:28, marginBottom:8, color:'var(--hf-ink5)', display:'flex', justifyContent:'center'}}>{HF_ICONS.search}</div>
            <div style={{fontSize:14, color:'var(--hf-ink)', fontWeight:500, marginBottom:4}}>
              {(data.kpis.all_time || 0) === 0 ? 'No runs yet' : 'No runs match these filters'}
            </div>
            {!loading && (
              <div style={{fontSize:13, color:'var(--hf-ink3)', marginBottom:14}}>
                {(data.kpis.all_time || 0) === 0
                  ? 'Trigger a run with the "New run" button.'
                  : `${data.kpis.all_time.toLocaleString()} runs in the database, but none match the active filters.`}
              </div>
            )}
            {!loading && activeCount > 0 && (
              <div style={{fontSize:12, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)', marginBottom:14}}>
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
            { key:'id', label:'Run', w:'0.5fr', mono:true, sortable:true, sortVal:r=>r.id, cell: v => <span style={{color:'var(--hf-accent-ink)', fontWeight:500}}>#{v}</span> },
            { key:'shop', label:'Shop', w:'0.6fr', sortable:true, cell: v => <span style={{color:'var(--hf-ink)', fontWeight:500}}>{v}</span> },
            { key:'phase_type', label:'Phase', w:'1fr', sortable:true, sortVal:r=>r.phase_type+':'+r.phase_mode, cell: (v, r) => (
              <span style={{display:'flex', flexDirection:'column', gap:3, minWidth:0}}>
                <span style={{fontFamily:'var(--hf-mono)', fontSize:12, color:'var(--hf-ink)', fontWeight:500, textTransform:'capitalize'}}>{v}</span>
                <HFPill tone={v==='scan'?'accent':'neutral'} style={{width:'fit-content', height:17, fontSize:11, padding:'0 6px', letterSpacing:0.2}}>{(r.phase_mode||'').replace('_',' ')}</HFPill>
              </span>
            )},
            { key:'status', label:'Status', w:'0.8fr', sortable:true, cell: (v, r) => (
              <span style={{display:'inline-flex', alignItems:'center', gap:7}}>
                <HFDot tone={statusTone[v]} pulse={v==='running'}/>
                <span style={{color: v==='failed'? 'var(--hf-err-ink)' : 'var(--hf-ink)', fontWeight: v==='running'? 500 : 400}}>{v}</span>
              </span>
            )},
            { key:'progress', label:'Progress', w:'1.1fr', sortable:true, sortVal:r=>r.progress, cell: (v, r) => (
              <span style={{display:'flex', alignItems:'center', gap:8, width:'100%'}}>
                <span style={{flex:1, maxWidth:120, height:5, background:'var(--hf-subtle)', borderRadius:3, overflow:'hidden'}}>
                  <span style={{display:'block', width:`${v}%`, height:'100%', background: r.status==='failed'? 'var(--hf-err)' : r.status==='running'? 'var(--hf-accent)' : (r.status==='paused'||r.status==='stopping'||r.status==='queued')? 'var(--hf-warn)' : 'var(--hf-ink4)', borderRadius:3}}/>
                </span>
                <span style={{fontFamily:'var(--hf-mono)', fontSize:12, color:'var(--hf-ink3)', minWidth:28, fontVariantNumeric:'tabular-nums'}}>{v}%</span>
              </span>
            )},
            { key:'items_added',   label:'Added',    w:'0.5fr', mono:true, align:'right', sortable:true, sortVal:r=>r.items_added,   cell: v => v ? <span style={{color:'var(--hf-ok-ink)', fontWeight:500}}>{v.toLocaleString()}</span> : <span style={{color:'var(--hf-ink4)'}}>—</span> },
            { key:'items_updated', label:'Updated',  w:'0.55fr', mono:true, align:'right', sortable:true, sortVal:r=>r.items_updated, cell: v => v ? <span style={{fontVariantNumeric:'tabular-nums'}}>{v.toLocaleString()}</span> : <span style={{color:'var(--hf-ink4)'}}>—</span> },
            { key:'errors', label:'Failures', w:'0.65fr', mono:true, align:'right', sortable:true, sortVal:r=>(r.errors||0)+(r.validation_issues||0), cell: (v, r) => {
              const s = r.errors || 0, vi = r.validation_issues || 0;
              if (!s && !vi) return <span style={{color:'var(--hf-ink4)'}}>—</span>;
              return (
                <span style={{fontVariantNumeric:'tabular-nums'}}>
                  {s > 0 && <span style={{color:'var(--hf-err-ink)', fontWeight:500}}>{s}</span>}
                  {s > 0 && vi > 0 && <span style={{color:'var(--hf-ink4)'}}>/</span>}
                  {vi > 0 && <span style={{color:'var(--hf-warn-ink)'}}>{vi}</span>}
                </span>
              );
            }},
            { key:'elapsed', label:'Dur.', w:'0.6fr', mono:true, muted:true, align:'right', sortable:true, sortVal:r=>r.elapsed },
            { key:'started', label:'Started', w:'0.85fr', muted:true, sortable:true, sortVal:r=>r.startedH },
            { key:'_', label:'', w:'28px', align:'right', cell: () => <span style={{color:'var(--hf-ink4)', display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
          ]}
          rows={filtered}
        />
        )}
      </HFCard>

      {/* Pagination footer */}
      {(data.total || 0) > 0 && (
        <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:14, fontSize:13, color:'var(--hf-ink3)'}}>
          <span>
            Showing {((data.page - 1) * data.per_page + 1).toLocaleString()}–
            {Math.min(data.page * data.per_page, data.total).toLocaleString()} of {data.total.toLocaleString()} match{data.total === 1 ? '' : 'es'}
            {data.kpis.all_time > data.total && (
              <span style={{color:'var(--hf-ink4)'}}> · {data.kpis.all_time.toLocaleString()} total in DB</span>
            )}
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
                const total = data.pages;
                const cur = data.page;
                const push = (n) => buttons.push(
                  <HFButton key={n} size="sm" variant={n === cur ? 'accent' : 'default'}
                    onClick={() => setPage(n)}>{n}</HFButton>
                );
                const ell = (k) => buttons.push(
                  <span key={k} style={{padding:'6px 4px', color:'var(--hf-ink4)'}}>…</span>
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

// Honest UI: the suffix tells the operator how trustworthy the throttle
// number is, based on how it was measured. See live observability spec.
const DELAY_SOURCE_LABELS = {
  autothrottle:      { suffix: 'autothrottle',
    title: 'Adaptive delay enforced inside HttpxMiddleware. Drifts toward response_latency / TARGET_CONCURRENCY, bounded by DOWNLOAD_DELAY (floor) and AUTOTHROTTLE_MAX_DELAY (ceiling).' },
  autothrottle_slot: { suffix: 'verified',
    title: 'Adaptive throttle delay read from Scrapy AUTOTHROTTLE slot.' },
  configured_delay:  { suffix: 'static',
    title: 'Static DOWNLOAD_DELAY enforced inside HttpxMiddleware (AUTOTHROTTLE disabled).' },
  httpx_observed:    { suffix: 'observed',
    title: 'Pre-fix legacy value: wall-clock wait between schedule and dispatch (engine queue time, not actual throttling).' },
};

function _fmtClockTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '—';
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    const ms = String(d.getMilliseconds()).padStart(3, '0');
    return `${hh}:${mm}:${ss}.${ms}`;
  } catch (e) { return '—'; }
}

function _fmtDelay(seconds) {
  if (seconds == null) return '—';
  const s = Number(seconds);
  if (!Number.isFinite(s)) return '—';
  if (s === 0) return '0 ms';
  if (s < 0.001) return '<1 ms';
  if (s < 1) return `${(s * 1000).toFixed(0)} ms`;
  return `${s.toFixed(2)} s`;
}

function _fmtAge(seconds) {
  if (seconds == null) return '—';
  const s = Math.max(0, Number(seconds));
  if (!Number.isFinite(s)) return '—';
  if (s < 1) return '<1s';
  if (s < 60) return `${s.toFixed(0)}s`;
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return r ? `${m}m ${r}s` : `${m}m`;
}

// ── Run-event display metadata ──
// `label` is shown as the row title. `defaultTone` is overridden in
// `_eventTone` for events whose meaning depends on payload (e.g. failed
// from a clean operator-stop is informational, not an error).
const RUN_EVENT_META = {
  started:               { glyph: '▶',  label: 'Run started' },
  paused:                { glyph: '⏸',  label: 'Paused' },
  resumed:               { glyph: '▶',  label: 'Resumed' },
  stop_requested:        { glyph: '⏹',  label: 'Stop pressed' },
  retry_failures:        { glyph: '↻',  label: 'Retry queued' },
  rerun:                 { glyph: '⟲',  label: 'Re-run triggered' },
  continued:             { glyph: '▶',  label: 'Continued' },
  resumed_after_failure: { glyph: '⤴',  label: 'Picked up earlier run' },
  completed:             { glyph: '✓',  label: 'Finished' },
  failed:                { glyph: '✗',  label: 'Failed' },
};

// Pretty labels for the phase value carried in `started` payloads.
const PHASE_LABELS = {
  scan: 'Scan',
  discover_sitemap: 'Discover · sitemap',
  discover_categories: 'Discover · categories',
  discover_full_crawl: 'Discover · full crawl',
  discover_graphql: 'Discover · GraphQL',
  discover_lupasearch: 'Discover · LupaSearch',
};

// Pretty labels for close_reason values.
const CLOSE_REASON_LABELS = {
  finished: 'Finished cleanly',
  shutdown: 'Container shutdown',
  stall_timeout: 'Stalled — no progress',
  heartbeat_timeout: 'Heartbeat timeout',
  stop_timeout: 'Stop never completed',
  orphan_on_boot: 'Killed by restart',
  stale_pre_scan: 'Reaped before next run',
  stopped_by_operator: 'Stopped by operator',
  finished_failed: 'Spider exited with errors',
};

function _nfmt(n) {
  if (n === null || n === undefined) return '—';
  try { return Number(n).toLocaleString(); } catch (e) { return String(n); }
}

// Render a friendly one-liner for an event. Falls back to the event_type
// label alone when there's nothing meaningful to add.
function _eventSummary(eventType, payload) {
  const p = (payload && typeof payload === 'object') ? payload : {};
  switch (eventType) {
    case 'started': {
      const phase = PHASE_LABELS[p.phase] || p.phase || '';
      const total = p.urls_total != null ? `${_nfmt(p.urls_total)} URLs` : null;
      const mods = [];
      if (p.rescrape) mods.push('full re-scrape');
      if (p.mode === 'single_urls' && Array.isArray(p.urls)) mods.push(`${p.urls.length} ad-hoc URL${p.urls.length === 1 ? '' : 's'}`);
      if (p.urls_skipped) mods.push(`${_nfmt(p.urls_skipped)} skipped (already done)`);
      const left = [phase, total].filter(Boolean).join(' · ');
      return mods.length ? `${left} · ${mods.join(' · ')}` : left;
    }
    case 'completed': {
      const processed = p.urls_processed != null ? `${_nfmt(p.urls_processed)} URLs processed` : '';
      const errors = p.error_count ? `${_nfmt(p.error_count)} error${p.error_count === 1 ? '' : 's'}` : 'no errors';
      return [processed, errors].filter(Boolean).join(' · ');
    }
    case 'failed': {
      const reason = CLOSE_REASON_LABELS[p.close_reason] || p.close_reason || '';
      const processed = p.urls_processed != null ? `${_nfmt(p.urls_processed)} URLs processed` : '';
      return [reason, processed].filter(Boolean).join(' · ');
    }
    case 'retry_failures': {
      const n = p.rows_reset || 0;
      const filters = [];
      if (p.error_reason_filter) filters.push(`reason: ${p.error_reason_filter}`);
      if (p.http_status_filter != null) filters.push(`HTTP ${p.http_status_filter}`);
      const base = `${_nfmt(n)} URL${n === 1 ? '' : 's'} reset`;
      return filters.length ? `${base} (${filters.join(', ')})` : base;
    }
    case 'rerun':
      return p.previous_status ? `was ${p.previous_status}` : '';
    case 'continued':
      return p.pending_count != null ? `${_nfmt(p.pending_count)} URL${p.pending_count === 1 ? '' : 's'} still pending` : '';
    case 'resumed_after_failure':
      return p.previous_run_id ? `from run #${p.previous_run_id}` : '';
    case 'paused':
    case 'resumed':
    case 'stop_requested':
      return ''; // label says it all
    default:
      return '';
  }
}

// Tone is derived per-event with a payload-aware override for `failed`:
// an operator-stopped run is conceptually "successful" — don't flag it red.
function _eventTone(ev) {
  if (ev.event_type === 'completed') return 'ok';
  if (ev.event_type === 'failed') {
    const reason = ev.payload && ev.payload.close_reason;
    if (reason === 'stopped_by_operator' || reason === 'shutdown') return 'warn';
    return 'err';
  }
  if (ev.event_type === 'paused' || ev.event_type === 'stop_requested') return 'warn';
  return 'accent';
}

// "10:36" / "10:36 (2m ago)". The full timestamp is on the title attr.
function _fmtEventTime(iso) {
  if (!iso) return { short: '—', full: '—', age: '', absolute: '' };
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return { short: '—', full: '—', age: '', absolute: '' };
    const yyyy = d.getFullYear();
    const moNum = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const ss = String(d.getSeconds()).padStart(2, '0');
    const ageS = Math.max(0, (Date.now() - d.getTime()) / 1000);
    const age = (
      ageS < 60 ? 'just now' :
      ageS < 3600 ? `${Math.floor(ageS / 60)}m ago` :
      ageS < 86400 ? `${Math.floor(ageS / 3600)}h ago` :
      `${Math.floor(ageS / 86400)}d ago`
    );
    return {
      short: `${hh}:${mm}`,
      full: `${yyyy}-${moNum}-${dd} ${hh}:${mm}:${ss}`,
      age,
      absolute: d.toLocaleString(),
    };
  } catch (e) { return { short: '—', full: '—', age: '', absolute: '' }; }
}


function HFRunTimelineCard({ events, style }) {
  const HF = getHF();
  const list = Array.isArray(events) ? events : [];
  const LIMIT = 10;
  const [expanded, setExpanded] = React.useState(false);
  const isClipped = list.length > LIMIT;
  // Latest-N when clipped: operators care about what just happened. Original
  // list is oldest-first; slicing from the tail preserves that ordering.
  const visible = !expanded && isClipped ? list.slice(-LIMIT) : list;

  // Map tone → log level (INFO / WARN / ERROR), with an associated text
  // color from the light-mode semantic ramp. Reuses the same tones already
  // returned by _eventTone so behavior stays consistent.
  const levelFor = (tone) => {
    if (tone === 'err')  return { label: 'ERROR', color: 'var(--hf-err-ink)' };
    if (tone === 'warn') return { label: 'WARN ', color: 'var(--hf-warn-ink)' };
    if (tone === 'ok')   return { label: 'INFO ', color: 'var(--hf-ok-ink)' };
    return { label: 'INFO ', color: 'var(--hf-accent-ink)' };
  };

  return (
    <HFCard
      title="Timeline"
      sub={
        list.length === 0
          ? 'no events'
          : isClipped && !expanded
            ? `${list.length} events · showing latest ${LIMIT}`
            : list.length === 1 ? '1 event' : `${list.length} events`
      }
      style={{ marginBottom: 'var(--hf-gap)', ...style }}
    >
      {visible.length === 0 ? (
        <div style={{ padding: 'var(--hf-card-p)', color: 'var(--hf-ink3)', fontSize: 13 }}>
          No events recorded for this run.
        </div>
      ) : (
        <div style={{
          padding: 14,
          background: 'transparent', color: 'var(--hf-ink)',
          fontFamily: 'var(--hf-mono)', fontSize: 12, lineHeight: 1.7,
          maxHeight: expanded ? 480 : 'none',
          overflow: expanded ? 'auto' : 'visible',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>
          {visible.map((ev) => {
            const meta = RUN_EVENT_META[ev.event_type] || { label: ev.event_type };
            const tone = _eventTone(ev);
            const lvl = levelFor(tone);
            const summary = _eventSummary(ev.event_type, ev.payload);
            const t = _fmtEventTime(ev.created_at);
            // Logger format: <YYYY-MM-DD HH:MM:SS>  <LEVEL>  <label> · <summary>
            return (
              <div key={ev.id}>
                <span style={{color: 'var(--hf-ink4)', fontVariantNumeric: 'tabular-nums'}} title={t.absolute}>{t.full}</span>
                {' '}
                <span style={{color: lvl.color, fontWeight: 600}}>{lvl.label}</span>
                {' '}
                <span style={{color: 'var(--hf-ink)'}}>{meta.label}</span>
                {summary ? <>
                  {' '}<span style={{color: 'var(--hf-ink5)'}}>·</span>{' '}
                  <span style={{color: 'var(--hf-ink3)'}}>{summary}</span>
                </> : null}
              </div>
            );
          })}
        </div>
      )}
      {isClipped && (
        <div style={{
          borderTop: `1px solid ${'var(--hf-border-faint)'}`,
          padding: '8px 0', textAlign: 'center', background: 'var(--hf-bg)',
        }}>
          <button
            onClick={() => setExpanded(v => !v)}
            aria-expanded={expanded}
            style={{
              background: 'transparent', border: 'none', cursor: 'pointer',
              color: 'var(--hf-accent-ink)', fontFamily: 'var(--hf-sans)', fontSize: 12, fontWeight: 500,
              padding: '4px 10px', borderRadius: 'var(--hf-r2)',
            }}
          >
            {expanded ? `Show latest ${LIMIT} only` : `Show all ${list.length} events`}
          </button>
        </div>
      )}
    </HFCard>
  );
}


// ─── History card — URL queue / discovered-URLs table w/ filters & paging ──
// All state stays in HFRunDetail so applyGroupFilter (called from the
// failures card) can reach the setters. Component is pure-render given
// that state.
function HFRunHistoryCard({
  urlData, historyRef, goto,
  urlStatus, setUrlStatus,
  urlSort, urlOrder, toggleSort,
  urlPage, setUrlPage,
  urlPerPage, setUrlPerPage,
  urlReason, setUrlReason,
  urlReasonIsNull, setUrlReasonIsNull,
  urlHttp, setUrlHttp,
  urlHttpIsNull, setUrlHttpIsNull,
  tabAllCount, tabCounts,
  clearAllFilters,
}) {
  const HF = getHF();
  if (!urlData) {
    return (
      <HFCard title="History" sub="loading…" style={{ marginBottom: 'var(--hf-gap)' }}>
        <HFTableSkeleton rows={8} columns={[
          { w: '55px', skelW: 36, mono: true },
          { w: '1fr', skelW: 240 },
          { w: '85px', skelW: 50, mono: true },
          { w: '120px', skelW: 80 },
          { w: '80px', skelW: 60, mono: true },
          { w: '70px', skelW: 50, mono: true },
          { w: '70px', skelW: 50, mono: true },
          { w: '75px', skelW: 50, mono: true },
          { w: '60px', skelW: 40, mono: true },
          { w: '85px', skelW: 60, mono: true },
        ]}/>
      </HFCard>
    );
  }
  if (urlData.source !== 'live' && urlData.total === 0) return null;

  const fmtDur = (ms) => {
    if (ms == null) return '—';
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  return (
    <div ref={historyRef}>
    <HFCard
      title="History"
      sub={urlData.source === 'live'
        ? `${urlData.breakdown.done} done · ${urlData.breakdown.failed} failed · ${urlData.breakdown.pending.toLocaleString()} pending`
        : `${urlData.total.toLocaleString()} URLs from discovered_urls (live queue cleaned up at run finish)`}
      style={{ marginBottom: 'var(--hf-gap)' }}
    >
      {urlData.source === 'live' && (
        <div style={{padding:`12px var(--hf-card-p) 0`}}>
          <HFTabs
            active={urlStatus}
            onChange={setUrlStatus}
            tabs={[
              { id:'all',        label:'all',        count: tabAllCount },
              { id:'pending',    label:'pending',    count: tabCounts.pending ?? 0 },
              { id:'processing', label:'processing', count: tabCounts.processing ?? 0 },
              { id:'done',       label:'done',       count: tabCounts.done ?? 0 },
              { id:'failed',     label:'failed',     count: tabCounts.failed ?? 0 },
            ]}
          />
          {(urlReason || urlReasonIsNull || urlHttp != null || urlHttpIsNull) && (() => {
            const reasonLabel = urlReasonIsNull ? 'unknown' : urlReason;
            const httpLabel = urlHttp != null ? `HTTP ${urlHttp}` : urlHttpIsNull ? 'no response' : '';
            const clearGroupFilter = () => {
              setUrlReason('');
              setUrlReasonIsNull(false);
              setUrlHttp(null);
              setUrlHttpIsNull(false);
            };
            return (
              <div style={{
                display:'inline-flex', alignItems:'center', gap: 6,
                marginTop: 8, padding: '4px 6px 4px 10px',
                background: 'var(--hf-err-soft)', border: `1px solid ${'var(--hf-err-border)'}`,
                borderRadius: 4, fontFamily: 'var(--hf-mono)', fontSize: 12, color: 'var(--hf-err-ink)',
              }}>
                <span>failed{reasonLabel ? ` · ${reasonLabel}` : ''}{httpLabel ? ` · ${httpLabel}` : ''}</span>
                <button onClick={clearGroupFilter} aria-label="Clear group filter" title="Clear group filter" style={{
                  background: 'transparent', border: 'none',
                  cursor:'pointer', padding:'0 4px', color: 'var(--hf-err-ink)', fontWeight: 600,
                  fontFamily: 'var(--hf-sans)', fontSize: 14, lineHeight: 1,
                }}>×</button>
              </div>
            );
          })()}
        </div>
      )}

      {urlData.rows.length === 0 ? (
        <div style={{padding:'24px', textAlign:'center', color:'var(--hf-ink3)', fontSize:13}}>
          No URLs in this filter.
        </div>
      ) : (
        <div style={{padding:`4px 0`}}>
          <div style={{
            display:'grid',
            gridTemplateColumns: urlData.source === 'live'
              ? '55px 1fr 85px 120px 80px 70px 70px 75px 60px 85px'
              : '1fr 60px 70px 150px',
            padding:`8px var(--hf-card-p)`,
            borderBottom: `1px solid ${'var(--hf-border)'}`,
            fontSize: 11, fontFamily: 'var(--hf-mono)', fontWeight: 500,
            color: 'var(--hf-ink3)', textTransform: 'uppercase', letterSpacing: 0.4,
            gap: 10,
          }}>
            {(() => {
              const SortIcon = ({ active, dir }) => (
                <svg aria-hidden="true" width="9" height="11" viewBox="0 0 9 11" style={{flexShrink:0, marginLeft:4, verticalAlign:'middle'}}>
                  <path d="M4.5 0.5 L8 4 L1 4 Z" fill={active && dir==='asc' ? 'var(--hf-ink)' : 'var(--hf-ink5)'}/>
                  <path d="M4.5 10.5 L1 7 L8 7 Z" fill={active && dir==='desc' ? 'var(--hf-ink)' : 'var(--hf-ink5)'}/>
                </svg>
              );
              const SortHdr = ({ k, children, align }) => {
                const active = urlSort === k;
                const ariaSort = active ? (urlOrder === 'asc' ? 'ascending' : 'descending') : 'none';
                return (
                  <button
                    onClick={() => toggleSort(k)}
                    aria-sort={ariaSort}
                    aria-label={`Sort by ${k}${active ? ` (currently ${ariaSort})` : ''}`}
                    style={{
                      cursor: 'pointer', background: 'transparent', border: 'none',
                      padding: 0, font: 'inherit', textTransform: 'inherit', letterSpacing: 'inherit',
                      color: active ? 'var(--hf-accent-ink)' : 'var(--hf-ink3)',
                      userSelect: 'none',
                      textAlign: align || 'left',
                      display: 'inline-flex', alignItems: 'center',
                    }}
                    title={`Sort by ${k}`}
                  >
                    {children}<SortIcon active={active} dir={urlOrder}/>
                  </button>
                );
              };
              return urlData.source === 'live' ? (
                <>
                  <SortHdr k="id">ID</SortHdr>
                  <SortHdr k="title">URL</SortHdr>
                  <span>Disc. URL</span>
                  <SortHdr k="status">Status</SortHdr>
                  <SortHdr k="started">Started</SortHdr>
                  <SortHdr k="url_type">Type</SortHdr>
                  <SortHdr k="duration">Duration</SortHdr>
                  <span>Size</span>
                  <span>Throttle</span>
                  <span>Source</span>
                </>
              ) : (
                <>
                  <span>URL</span>
                  <span>HTTP</span>
                  <span>Type</span>
                  <span>Last checked</span>
                </>
              );
            })()}
          </div>
          {urlData.rows.map((u, i) => {
            const http = u.http_status ?? u.last_http_status;
            const httpTone = http && http >= 400 ? 'err' : http ? 'ok' : 'neutral';
            const statusCell = (() => {
              if (urlData.source !== 'live') return null;
              if (u.status === 'failed') {
                return (
                  <span style={{display:'inline-flex', flexDirection:'column', gap:2, lineHeight:1.2}}>
                    <HFPill tone="err" style={{width:'fit-content'}}>failed{http ? ` · ${http}` : ''}</HFPill>
                    {u.error_reason && (
                      <span style={{fontFamily:'var(--hf-mono)', fontSize:11, color:'var(--hf-err-ink)', paddingLeft:2}}>{u.error_reason}</span>
                    )}
                  </span>
                );
              }
              if (u.status === 'processing') {
                return <HFPill tone="accent" style={{width:'fit-content'}}><HFDot tone="accent" pulse size={6}/>processing</HFPill>;
              }
              if (u.status === 'pending') {
                return <HFPill tone="neutral" style={{width:'fit-content'}}>pending</HFPill>;
              }
              return <HFPill tone="ok" style={{width:'fit-content'}}>{http ? `done · ${http}` : 'done'}</HFPill>;
            })();
            return (
              <div key={i} style={{
                display:'grid',
                gridTemplateColumns: urlData.source === 'live'
                  ? '55px 1fr 85px 120px 80px 70px 70px 75px 60px 85px'
                  : '1fr 60px 70px 150px',
                padding:`7px var(--hf-card-p)`,
                borderBottom: i < urlData.rows.length-1 ? `1px solid ${'var(--hf-border-faint)'}` : 'none',
                fontSize:13, alignItems:'center', gap:10,
              }}>
                {urlData.source === 'live' && (
                  <span style={{fontFamily:'var(--hf-mono)', fontSize:11, color:'var(--hf-accent-ink)', fontVariantNumeric:'tabular-nums', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}
                        title={`item #${u.item_id}`}>
                    {u.item_id ?? '—'}
                  </span>
                )}
                <span style={{display:'flex', alignItems:'center', gap:8, minWidth:0}}>
                  <span style={{display:'flex', flexDirection:'column', gap:2, minWidth:0, flex:1}}>
                    {u.title && (
                      u.shop_book_id != null ? (
                        <a href={(window.HF_BUILD_PATH && window.HF_BUILD_PATH('shop-book-detail', {id: String(u.shop_book_id)})) || '#'}
                           onClick={(e)=>{ if (e.metaKey||e.ctrlKey||e.shiftKey) return; e.preventDefault(); e.stopPropagation(); goto('shop-book-detail', {id: String(u.shop_book_id)});}}
                           title={u.title}
                           style={{display:'block', minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontSize:13, color:'var(--hf-accent-ink)', fontWeight:500, textDecoration:'none', cursor:'pointer'}}>
                          {u.title}
                        </a>
                      ) : (
                        <span style={{display:'block', minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontSize:13, color:'var(--hf-ink)', fontWeight:500}} title={u.title}>{u.title}</span>
                      )
                    )}
                    {u.discovered_url_id != null ? (
                      <a href={(window.HF_BUILD_PATH && window.HF_BUILD_PATH('url-detail', {id: String(u.discovered_url_id)})) || '#'}
                         onClick={(e)=>{ if (e.metaKey||e.ctrlKey||e.shiftKey) return; e.preventDefault(); e.stopPropagation(); goto('url-detail', {id: String(u.discovered_url_id)});}}
                         title={u.url}
                         style={{display:'block', minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontFamily:'var(--hf-mono)', fontSize: u.title ? 11 : 12, color:'var(--hf-accent-ink)', textDecoration:'none', cursor:'pointer'}}>
                        {u.url}
                      </a>
                    ) : (
                      <span style={{display:'block', minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontFamily:'var(--hf-mono)', fontSize: u.title ? 11 : 12, color: u.title ? 'var(--hf-ink4)' : 'var(--hf-ink)'}} title={u.url}>{u.url}</span>
                    )}
                  </span>
                  <HFExtLink href={u.url}/>
                </span>
                {urlData.source === 'live' ? (
                  <>
                    {/* Disc. URL — column 3, right after URL */}
                    {u.discovered_url_id != null ? (
                      <a href={(window.HF_BUILD_PATH && window.HF_BUILD_PATH('url-detail', {id: String(u.discovered_url_id)})) || '#'}
                         onClick={(e)=>{ if (e.metaKey||e.ctrlKey||e.shiftKey) return; e.preventDefault(); goto('url-detail', {id: String(u.discovered_url_id)});}}
                         style={{fontFamily:'var(--hf-mono)', fontSize:11, color:'var(--hf-accent-ink)', fontVariantNumeric:'tabular-nums', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', textDecoration:'none'}}>
                        #{u.discovered_url_id}
                      </a>
                    ) : (
                      <span style={{fontFamily:'var(--hf-mono)', fontSize:11, color:'var(--hf-ink5)'}}>—</span>
                    )}
                    {statusCell}
                    <span style={{fontFamily:'var(--hf-mono)', fontSize:11, color:'var(--hf-ink4)', fontVariantNumeric:'tabular-nums'}}>{u.claimed_at ? new Date(u.claimed_at).toLocaleTimeString() : '—'}</span>
                    <span style={{fontFamily:'var(--hf-mono)', fontSize:12, color:'var(--hf-ink4)'}}>{u.url_type}</span>
                    <span style={{fontFamily:'var(--hf-mono)', fontSize:11, color:'var(--hf-ink4)', fontVariantNumeric:'tabular-nums'}}>{fmtDur(u.duration_ms)}</span>
                    {(() => {
                      // Humanise response_bytes; highlight suspiciously small successful
                      // responses (< 1 KB on a 2xx) — common signature of an anti-bot stub.
                      const b = u.response_bytes;
                      if (b == null) {
                        return <span style={{fontFamily:'var(--hf-mono)', fontSize:11, color:'var(--hf-ink5)', fontVariantNumeric:'tabular-nums'}}>—</span>;
                      }
                      const fmt = b < 1024
                        ? `${b} B`
                        : b < 1024 * 1024
                          ? `${(b / 1024).toFixed(1)} KB`
                          : `${(b / 1024 / 1024).toFixed(2)} MB`;
                      const tiny = b < 1024 && u.status === 'done' && (u.http_status ?? 0) >= 200 && (u.http_status ?? 0) < 300;
                      return (
                        <span title={tiny ? 'Suspiciously small response on a 2xx — possible anti-bot stub' : `${b.toLocaleString()} bytes`}
                              style={{fontFamily:'var(--hf-mono)', fontSize:11, color: tiny ? 'var(--hf-warn-ink)' : 'var(--hf-ink4)', fontVariantNumeric:'tabular-nums'}}>
                          {fmt}
                        </span>
                      );
                    })()}
                    {(() => {
                      const lbl = DELAY_SOURCE_LABELS[u.delay_source] || {};
                      return <>
                        <span style={{fontFamily:'var(--hf-mono)', fontSize:11, color:'var(--hf-ink4)', fontVariantNumeric:'tabular-nums', whiteSpace:'nowrap'}} title={lbl.title || ''}>
                          {_fmtDelay(u.request_delay_s)}
                        </span>
                        <span style={{fontFamily:'var(--hf-mono)', fontSize:11, color:'var(--hf-ink5)', whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}} title={lbl.title || u.delay_source || ''}>
                          {lbl.suffix || u.delay_source || '—'}
                        </span>
                      </>;
                    })()}
                  </>
                ) : (
                  <>
                    <HFPill tone={httpTone} style={{width:'fit-content'}}>{u.last_http_status ?? '—'}</HFPill>
                    <span style={{fontFamily:'var(--hf-mono)', fontSize:12, color:'var(--hf-ink4)'}}>{u.url_type}</span>
                    <span style={{fontFamily:'var(--hf-mono)', fontSize:11, color:'var(--hf-ink4)', fontVariantNumeric:'tabular-nums'}}>{u.last_checked_at ? new Date(u.last_checked_at).toLocaleString() : '—'}</span>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div style={{
        display:'flex', justifyContent:'space-between', alignItems:'center',
        padding:`10px var(--hf-card-p)`, borderTop:`1px solid ${'var(--hf-border-faint)'}`,
        fontSize:12, color:'var(--hf-ink3)', flexWrap:'wrap', gap:8,
      }}>
        <span style={{fontFamily:'var(--hf-mono)', color:'var(--hf-ink4)'}}>
          {urlData.total.toLocaleString()} URLs
        </span>
        <div style={{display:'flex', gap:6, alignItems:'center', flexWrap:'wrap'}}>
          {(urlStatus !== 'all' || urlSort !== 'started' || urlOrder !== 'desc' || urlPage !== 1
            || urlReason || urlReasonIsNull || urlHttp != null || urlHttpIsNull) && (
            <HFButton size="sm" variant="ghost" onClick={clearAllFilters}>Clear</HFButton>
          )}
          <span style={{color:'var(--hf-ink4)', fontSize:12, marginRight:2}}>Per page:</span>
          {[10, 25, 50, 100].map(n => (
            <HFButton key={n} size="sm"
              variant={urlPerPage === n ? 'accent' : 'subtle'}
              onClick={() => setUrlPerPage(n)}>
              {n}
            </HFButton>
          ))}
          <span style={{width:1, height:18, background:'var(--hf-border)', margin:'0 4px'}}/>
          <HFButton size="sm" variant="ghost" disabled={urlData.page <= 1}
            aria-label="Previous page"
            onClick={() => setUrlPage(p => Math.max(1, p - 1))}>
              <span aria-hidden="true" style={{display:'flex', transform:'rotate(180deg)'}}>{HF_ICONS.chevron}</span>
            </HFButton>
          {(() => {
            const cur = urlData.page, total = urlData.pages;
            const btns = [];
            const push = (n) => btns.push(
              <HFButton key={n} size="sm"
                variant={n === cur ? 'accent' : 'subtle'}
                onClick={() => setUrlPage(n)}>{n}</HFButton>
            );
            const ell = (k) => btns.push(
              <span key={k} style={{padding:'0 2px', color:'var(--hf-ink4)'}}>…</span>
            );
            if (total <= 7) {
              for (let i = 1; i <= total; i++) push(i);
            } else {
              push(1);
              if (cur > 4) ell('l');
              const lo = Math.max(2, cur - 1), hi = Math.min(total - 1, cur + 1);
              for (let i = lo; i <= hi; i++) push(i);
              if (cur < total - 3) ell('r');
              push(total);
            }
            return btns;
          })()}
          <HFButton size="sm" variant="ghost" disabled={urlData.page >= urlData.pages}
            aria-label="Next page"
            onClick={() => setUrlPage(p => Math.min(urlData.pages, p + 1))}>
              <span aria-hidden="true" style={{display:'flex'}}>{HF_ICONS.chevron}</span>
            </HFButton>
        </div>
      </div>
    </HFCard>
    </div>
  );
}


// ─── Failures card — server-aggregated failure groups w/ retry & ack ──
// Owns its own disclosure state (expanded group + which example detail is
// open). All actions go to handlers passed in by the parent.
function HFRunFailuresCard({
  failureGroups, showAckedFailures, setShowAckedFailures,
  actionPending, retryRun, ackGroup, applyGroupFilter,
}) {
  const HF = getHF();
  const [expandedFailure, setExpandedFailure] = React.useState(-1);
  const [expandedFailureDetail, setExpandedFailureDetail] = React.useState(null);

  if (failureGroups.length === 0 && !showAckedFailures) return null;

  // Sum unacked / acked across visible groups so the header reflects what's
  // on screen given the toggle. Falls back to legacy `count` when older
  // payloads lack the explicit split.
  const sumUnacked = failureGroups.reduce(
    (a, g) => a + (g.unacked_count ?? g.count ?? 0), 0);
  const sumAcked = failureGroups.reduce(
    (a, g) => a + (g.acked_count ?? 0), 0);
  const total = sumUnacked + sumAcked;
  const subParts = [`${sumUnacked} unacknowledged`];
  if (showAckedFailures) {
    subParts.push(`${sumAcked} acknowledged`);
    subParts.push(`${total} total`);
  }

  return (
    <HFCard
      title="Failures"
      sub={subParts.join(' · ') + ' · grouped by reason'}
      action={<>
        <HFButton size="sm" variant="subtle"
          onClick={() => setShowAckedFailures(v => !v)}
          title="Toggle visibility of failure groups whose latest events have been acknowledged">
          {showAckedFailures ? 'Hide acknowledged' : 'Show acknowledged'}
        </HFButton>
        <HFButton size="sm" variant="subtle" disabled={actionPending} onClick={() => retryRun(null)}>Retry all</HFButton>
        <HFButton size="sm" variant="subtle" onClick={() => applyGroupFilter(null)}>Open issues</HFButton>
      </>}
      style={{marginBottom: 'var(--hf-gap)'}}
    >
      <div style={{padding: 0}}>
        {failureGroups.map((g, i) => {
          const isHttpErr = g.http != null && g.http >= 500;
          const tone = isHttpErr ? 'err' : 'warn';
          const tonebg = tone === 'err' ? 'var(--hf-err-soft)' : 'var(--hf-warn-soft)';
          const tonefg = tone === 'err' ? 'var(--hf-err-ink)' : 'var(--hf-warn-ink)';
          const toneb  = tone === 'err' ? 'var(--hf-err-border)' : 'var(--hf-warn-border)';
          const open = expandedFailure === i;
          return (
            <div key={`${g.reason ?? '__null__'}|${g.http ?? '__null__'}`} style={{
              borderTop: i === 0 ? 'none' : `1px solid ${'var(--hf-border-faint)'}`,
            }}>
              <div role="button"
                tabIndex={0}
                aria-expanded={open}
                aria-label={`${open ? 'Collapse' : 'Expand'} failure group ${g.reason_display ?? g.reason ?? 'unknown'}`}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpandedFailure(open ? -1 : i); } }}
                onClick={() => setExpandedFailure(open ? -1 : i)}
                style={{
                padding: `10px var(--hf-card-p)`,
                display: 'grid', gridTemplateColumns: '1fr auto', gap: 14, alignItems: 'center',
                cursor: 'pointer',
                background: open ? 'var(--hf-subtle)' : 'transparent',
              }}>
                <div style={{display:'flex', alignItems:'center', gap: 10, minWidth: 0}}>
                  <span aria-hidden="true" style={{
                    display:'inline-flex', alignItems:'center', justifyContent:'center',
                    width: 14, height: 14, color: 'var(--hf-ink4)',
                    transform: open ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 120ms',
                  }}>{HF_ICONS.chevron}</span>
                  {g.http != null && (
                    <span style={{
                      display:'inline-flex', alignItems:'center', justifyContent:'center',
                      height: 22, padding: '0 8px',
                      background: tonebg, color: tonefg, border: `1px solid ${toneb}`,
                      borderRadius: 4, fontFamily: 'var(--hf-mono)', fontSize: 12, fontWeight: 600,
                    }}>{g.http}</span>
                  )}
                  <span style={{fontFamily: 'var(--hf-mono)', fontSize: 13, color: 'var(--hf-ink)', fontWeight: 600}}>
                    {g.reason_display ?? g.reason ?? 'unknown'}
                  </span>
                  <span style={{fontFamily: 'var(--hf-mono)', fontSize: 12, color: 'var(--hf-ink3)', fontVariantNumeric:'tabular-nums'}}>
                    × {g.count}
                  </span>
                  {(g.acked_count ?? 0) > 0 && (
                    <span title={`${g.acked_count} acknowledged event${g.acked_count === 1 ? '' : 's'} in this bucket`} style={{
                      display:'inline-flex', alignItems:'center', gap: 4,
                      height: 20, padding: '0 7px',
                      background: 'var(--hf-subtle)', color: 'var(--hf-ink3)',
                      border: `1px solid ${'var(--hf-border)'}`, borderRadius: 4,
                      fontFamily: 'var(--hf-mono)', fontSize: 11, fontWeight: 500,
                    }}>
                      <span aria-hidden="true" style={{display:'inline-flex'}}><HFIcon d={<><path d="M3 8 L7 12 L13 4"/></>} size={11} sw={2}/></span>
                      acked × {g.acked_count}
                    </span>
                  )}
                  {g.recurring_in_runs > 0 && (
                    <span title={`This bucket also failed in ${g.recurring_in_runs} of the last 5 prior runs for this shop`} style={{
                      display:'inline-flex', alignItems:'center', gap: 4,
                      height: 20, padding: '0 7px',
                      background: 'var(--hf-warn-soft)', color: 'var(--hf-warn-ink)',
                      border: `1px solid ${'var(--hf-warn-border)'}`, borderRadius: 4,
                      fontFamily: 'var(--hf-mono)', fontSize: 11, fontWeight: 500,
                    }}>
                      <span aria-hidden="true" style={{display:'inline-flex'}}>{HF_ICONS.cycle}</span>
                      recurring × {g.recurring_in_runs}
                    </span>
                  )}
                </div>
                <div style={{display:'flex', gap: 6, alignItems:'center'}} onClick={(e)=>e.stopPropagation()}>
                  <HFButton size="sm" disabled={actionPending} onClick={() => retryRun(g)}>Retry group</HFButton>
                  <HFButton size="sm" variant="subtle" onClick={() => applyGroupFilter(g)}>Open issues</HFButton>
                </div>
              </div>
              {open && (
                <div style={{padding: `4px var(--hf-card-p) 14px`, paddingLeft: 'calc(var(--hf-card-p) + 24px)'}}>
                  <div style={{display:'flex', flexDirection:'column', gap: 6, marginBottom: 8}}>
                    {g.examples.map((ex, j) => {
                      // Older /live payloads returned plain URL strings;
                      // newer ones return { url, error_detail }. Accept both
                      // so a stale browser tab doesn't break.
                      const exUrl = typeof ex === 'string' ? ex : ex?.url ?? '';
                      const exDetail = typeof ex === 'string' ? null : ex?.error_detail ?? null;
                      const detailKey = `${i}-${j}`;
                      const detailOpen = expandedFailureDetail === detailKey;
                      return (
                        <div key={j} style={{display:'flex', flexDirection:'column', gap: 4}}>
                          <div style={{display:'flex', alignItems:'center', gap: 6, minWidth: 0}}>
                            <span style={{color: 'var(--hf-ink5)'}}>·</span>
                            <span title={exUrl} style={{flex: 1, fontFamily: 'var(--hf-mono)', fontSize: 12, color: 'var(--hf-ink3)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', minWidth: 0}}>
                              {exUrl}
                            </span>
                            {exDetail && (
                              <button
                                aria-expanded={detailOpen}
                                onClick={() => setExpandedFailureDetail(detailOpen ? null : detailKey)}
                                style={{
                                  background: 'transparent', border: 'none', padding: 0, cursor: 'pointer',
                                  fontFamily: 'var(--hf-mono)', fontSize: 11, color: 'var(--hf-accent-ink)',
                                  textDecoration: 'none', whiteSpace: 'nowrap',
                                }}>
                                {detailOpen ? 'Hide details' : 'Show details'}
                              </button>
                            )}
                          </div>
                          {detailOpen && exDetail && (
                            <pre style={{
                              margin: 0, padding: '8px 10px',
                              background: 'var(--hf-subtle)', border: `1px solid ${'var(--hf-border-faint)'}`,
                              borderRadius: 4,
                              fontFamily: 'var(--hf-mono)', fontSize: 11, color: 'var(--hf-ink2)',
                              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                              maxHeight: 240, overflow: 'auto',
                            }}>{exDetail}</pre>
                          )}
                        </div>
                      );
                    })}
                    {g.count > g.examples.length && (
                      <button onClick={() => applyGroupFilter(g)} style={{
                        background: 'transparent', border: 'none', padding: 0, cursor: 'pointer',
                        fontFamily: 'var(--hf-mono)', fontSize: 12, color: 'var(--hf-accent-ink)',
                        textDecoration: 'none', marginLeft: 12, marginTop: 2, textAlign: 'left',
                      }}>+ {g.count - g.examples.length} more (view in History)</button>
                    )}
                  </div>
                  <div style={{display:'flex', gap: 6}}>
                    <HFButton size="sm" variant="subtle" disabled={actionPending} onClick={() => ackGroup(g)}>Mark as known</HFButton>
                    <HFButton size="sm" variant="subtle" onClick={() => applyGroupFilter(g)}>View all {g.count}</HFButton>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </HFCard>
  );
}


// ─── In-flight card — what's happening RIGHT NOW (only when live) ────
// Pure-render given the current liveData snapshot + derived counts.
function HFRunInFlightCard({
  liveData, runStatus, workerCount, inFlightFirst,
  liveHealth, healthTone, liveRate, rateDone, rateFailed,
  ratePerMin, failPct, tabCounts,
}) {
  const HF = getHF();
  if (!liveData || !(runStatus === 'running' || runStatus === 'paused' || runStatus === 'stopping')) {
    return null;
  }
  return (
    <HFCard
      title="In flight"
      sub={`${workerCount} ${workerCount === 1 ? 'URL' : 'URLs'} · ${liveData.eta_min != null ? `ETA ${liveData.eta_min === 0 ? '<1' : liveData.eta_min}m` : 'live'}`}
      action={liveHealth ? <HFPill tone={healthTone}><HFDot tone={healthTone} pulse={liveHealth==='healthy'} size={6}/> health: {liveHealth}</HFPill> : null}
      style={{marginBottom: 'var(--hf-gap)'}}
    >
      <div style={{padding: 'var(--hf-card-p)', display:'grid', gridTemplateColumns:'1.4fr 1fr', gap: 'var(--hf-gap)', alignItems:'stretch'}}>
        {/* Active fetch tile */}
        <div style={{
          background: 'var(--hf-accent-soft)', border: `1px solid ${'var(--hf-accent-border)'}`,
          borderRadius: 'var(--hf-r2)', padding: '14px 16px',
          display:'flex', flexDirection:'column', gap: 8, position:'relative', overflow:'hidden',
          minHeight: 90,
        }}>
          {inFlightFirst ? (
            <>
              <div style={{display:'flex', alignItems:'center', gap: 8, marginBottom: 2}}>
                <HFDot tone="accent" pulse size={7}/>
                <span style={{fontSize: 11, fontWeight: 600, color: 'var(--hf-accent-ink)', letterSpacing: 0.6, textTransform:'uppercase'}}>
                  Now fetching
                </span>
                <span style={{flex: 1}}/>
                <span style={{fontFamily: 'var(--hf-mono)', fontSize: 22, fontWeight: 600, color: 'var(--hf-accent-ink)', fontVariantNumeric:'tabular-nums', lineHeight: 1}}>
                  {_fmtAge(inFlightFirst.claimed_age_s)}
                </span>
              </div>
              <div style={{display:'flex', alignItems:'center', gap: 8, minWidth:0}}>
                <span style={{
                  fontFamily: 'var(--hf-mono)', fontSize: 13, color: 'var(--hf-ink)', fontWeight: 500,
                  overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', minWidth:0, flex: 1,
                }} title={inFlightFirst.url}>{inFlightFirst.url}</span>
                <HFExtLink href={inFlightFirst.url} size={13}/>
              </div>
              {(() => {
                const lbl = DELAY_SOURCE_LABELS[inFlightFirst.delay_source] || {};
                return (
                  <div style={{display:'flex', gap: 16, fontFamily: 'var(--hf-mono)', fontSize: 12, color: 'var(--hf-ink3)', marginTop: 2, flexWrap:'wrap'}}>
                    <span>claimed <span style={{color: 'var(--hf-ink2)'}}>{_fmtClockTime(inFlightFirst.claimed_at)}</span></span>
                    <span title={lbl.title || ''}>
                      throttle <span style={{color: 'var(--hf-warn-ink)'}}>{_fmtDelay(inFlightFirst.request_delay_s)}</span>
                      {lbl.suffix ? <span style={{color: 'var(--hf-ink4)'}}> · {lbl.suffix}</span> : null}
                    </span>
                    {inFlightFirst.retry_count > 0 && (
                      <span>retries <span style={{color: 'var(--hf-ink2)'}}>{inFlightFirst.retry_count}</span></span>
                    )}
                  </div>
                );
              })()}
              <div style={{
                position:'absolute', left:0, right:0, bottom:0, height: 3,
                background: 'var(--hf-accent-soft2)',
              }}>
                <div style={{width:'40%', height:'100%', background: 'var(--hf-accent)', animation:'hfSweep 1.6s ease-in-out infinite'}}/>
              </div>
            </>
          ) : (tabCounts.processing ?? 0) > 0 ? (
            <div style={{display:'flex', alignItems:'center', gap: 8, flex:1, color: 'var(--hf-accent-ink)', fontFamily: 'var(--hf-mono)', fontSize: 13}}>
              <HFDot tone="accent" pulse size={7}/>
              {tabCounts.processing} URL{tabCounts.processing > 1 ? 's' : ''} processing · refreshing…
            </div>
          ) : (
            <div style={{display:'flex', alignItems:'center', justifyContent:'center', flex:1, color: 'var(--hf-ink4)', fontFamily: 'var(--hf-mono)', fontSize: 13}}>
              {liveData ? 'between requests · waiting for next dispatch…' : 'loading…'}
            </div>
          )}
        </div>

        {/* Rate (last 60s) — done vs failed */}
        <div style={{display:'flex', flexDirection:'column', gap: 10}}>
          <div style={{fontSize: 11, fontWeight: 600, color: 'var(--hf-ink4)', letterSpacing: 0.6, textTransform:'uppercase'}}>
            Rate · last {liveRate.window_s}s
          </div>
          <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap: 10, flex: 1}}>
            <div style={{
              background: 'var(--hf-ok-soft)', border: `1px solid ${'var(--hf-ok-border)'}`, borderRadius: 'var(--hf-r2)',
              padding: '10px 12px',
            }}>
              <div style={{fontFamily: 'var(--hf-mono)', fontSize: 24, fontWeight: 600, color: 'var(--hf-ok-ink)', fontVariantNumeric:'tabular-nums', lineHeight: 1}}>
                {rateDone}
              </div>
              <div style={{fontFamily: 'var(--hf-mono)', fontSize: 11, color: 'var(--hf-ok-ink)', marginTop: 5}}>
                done · {ratePerMin}/min
              </div>
            </div>
            <div style={{
              background: rateFailed > 0 ? 'var(--hf-err-soft)' : 'var(--hf-subtle)',
              border: `1px solid ${rateFailed > 0 ? 'var(--hf-err-border)' : 'var(--hf-border)'}`, borderRadius: 'var(--hf-r2)',
              padding: '10px 12px',
            }}>
              <div style={{fontFamily: 'var(--hf-mono)', fontSize: 24, fontWeight: 600, color: rateFailed > 0 ? 'var(--hf-err-ink)' : 'var(--hf-ink3)', fontVariantNumeric:'tabular-nums', lineHeight: 1}}>
                {rateFailed}
              </div>
              <div style={{fontFamily: 'var(--hf-mono)', fontSize: 11, color: rateFailed > 0 ? 'var(--hf-err-ink)' : 'var(--hf-ink3)', marginTop: 5}}>
                failed{rateFailed > 0 ? ` · ${failPct}% rate` : ''}
              </div>
            </div>
          </div>
        </div>
      </div>
    </HFCard>
  );
}


// ─── Books card — books added/updated by this run, paginated ────────
// Self-contained: owns its own tab/page state + data fetch. Parent only
// passes the run id, the added/updated counts (used to choose default
// inner tab), and the SPA navigator.
function HFRunBooksCard({ runId, itemsAdded, itemsUpdated, goto }) {
  const HF = getHF();
  const [booksTab, setBooksTab] = React.useState(null);
  const [booksPage, setBooksPage] = React.useState(1);
  const [booksPerPage, setBooksPerPage] = React.useState(25);
  const [booksData, setBooksData] = React.useState(null);

  // Default inner tab once counts are known: prefer 'added' if any added, else 'updated'.
  React.useEffect(() => {
    if (booksTab !== null) return;
    setBooksTab((itemsAdded ?? 0) > 0 ? 'added' : 'updated');
  }, [itemsAdded, itemsUpdated, booksTab]);

  // Reset page when the inner tab or per-page selection changes.
  React.useEffect(() => { setBooksPage(1); }, [booksTab, booksPerPage]);

  React.useEffect(() => {
    if (!runId || !booksTab) return;
    let cancelled = false;
    const params = new URLSearchParams({
      type: booksTab,
      page: String(booksPage),
      per_page: String(booksPerPage),
    });
    fetch(`/api/runs/${runId}/books?${params}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) setBooksData(d); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [runId, booksTab, booksPage, booksPerPage]);

  const totalCount = (itemsAdded ?? 0) + (itemsUpdated ?? 0);
  if (totalCount === 0 || !booksTab) {
    return (
      <HFCard title="Books" style={{ marginBottom: 'var(--hf-gap)' }}>
        <div style={{padding:'40px 20px', textAlign:'center', color:'var(--hf-ink3)', fontSize:13}}>
          No books were added or updated by this run.
        </div>
      </HFCard>
    );
  }

  return (
    <HFCard title="Books">
      <div style={{padding:`0 var(--hf-card-p)`}}>
        <HFTabs
          active={booksTab}
          onChange={setBooksTab}
          tabs={[
            { id:'added',   label:'Added',   count: itemsAdded ?? 0 },
            { id:'updated', label:'Updated', count: itemsUpdated ?? 0 },
          ]}
        />
      </div>
      {booksData ? (
        <>
          <div style={{overflowX:'auto'}}>
            <table style={{width:'100%', borderCollapse:'collapse', fontSize:13}}>
              <thead>
                <tr style={{borderBottom:`1px solid ${'var(--hf-border)'}`}}>
                  <th style={{padding:`7px var(--hf-card-p)`, textAlign:'left', fontWeight:600, color:'var(--hf-ink3)', fontSize:12}}>Title</th>
                  <th style={{padding:`7px 8px`, textAlign:'left', fontWeight:600, color:'var(--hf-ink3)', fontSize:12}}>Author</th>
                  <th style={{padding:`7px 8px`, textAlign:'right', fontWeight:600, color:'var(--hf-ink3)', fontSize:12}}>Price</th>
                  {booksTab === 'updated' && (
                    <th style={{padding:`7px var(--hf-card-p)`, textAlign:'left', fontWeight:600, color:'var(--hf-ink3)', fontSize:12}}>Changed</th>
                  )}
                </tr>
              </thead>
              <tbody>
                {booksData.books.length === 0 ? (
                  <tr>
                    <td colSpan={booksTab === 'updated' ? 4 : 3} style={{padding:`16px var(--hf-card-p)`, color:'var(--hf-ink3)', fontSize:13}}>
                      No books to show.
                    </td>
                  </tr>
                ) : booksData.books.map((b, i) => (
                  <tr key={b.id} style={{borderBottom: i < booksData.books.length - 1 ? `1px solid ${'var(--hf-border-faint)'}` : 'none'}}>
                    <td style={{padding:`7px var(--hf-card-p)`, maxWidth:320}}>
                      <a
                        href={(window.HF_BUILD_PATH && window.HF_BUILD_PATH('shop-book-detail', {id: String(b.id)})) || '#'}
                        style={{color:'var(--hf-accent)', textDecoration:'none', fontWeight:500}}
                        onClick={e => { if (e.metaKey||e.ctrlKey||e.shiftKey) return; e.preventDefault(); goto('shop-book-detail', {id: String(b.id)}); }}
                        onMouseEnter={e => e.target.style.textDecoration='underline'}
                        onMouseLeave={e => e.target.style.textDecoration='none'}>
                        {b.title}
                      </a>
                    </td>
                    <td style={{padding:`7px 8px`, color:'var(--hf-ink3)', maxWidth:180, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{b.author}</td>
                    <td style={{padding:`7px 8px`, textAlign:'right', fontFamily:'var(--hf-mono)', fontSize:13, whiteSpace:'nowrap'}}>{b.price}</td>
                    {booksTab === 'updated' && (
                      <td style={{padding:`7px var(--hf-card-p)`}}>
                        {(b.changed_fields || '').split(', ').filter(Boolean).map(f => (
                          <code key={f} style={{
                            fontSize:11, padding:'1px 5px', borderRadius:3, marginRight:4,
                            background:'var(--hf-subtle)', color:'var(--hf-ink3)', fontFamily:'var(--hf-mono)',
                          }}>{f}</code>
                        ))}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{
            display:'flex', justifyContent:'space-between', alignItems:'center',
            padding:`10px var(--hf-card-p)`, borderTop:`1px solid ${'var(--hf-border-faint)'}`,
          }}>
            <span style={{fontSize:13, color:'var(--hf-ink3)'}}>{booksData.total.toLocaleString()} books</span>
            <div style={{display:'flex', gap:6, alignItems:'center', flexWrap:'wrap'}}>
              <span style={{fontSize:12, color:'var(--hf-ink3)'}}>Per page:</span>
              {[25, 50, 100].map(n => (
                <HFButton key={n} size="sm" variant={booksPerPage === n ? 'accent' : 'subtle'}
                  onClick={() => setBooksPerPage(n)}>{n}</HFButton>
              ))}
              <HFButton size="sm" variant="subtle" disabled={booksData.page <= 1}
                aria-label="Previous page"
                onClick={() => setBooksPage(p => Math.max(1, p - 1))}>
                  <span aria-hidden="true" style={{display:'flex', transform:'rotate(180deg)'}}>{HF_ICONS.chevron}</span>
                </HFButton>
              {(() => {
                const cur = booksData.page, total = booksData.pages;
                const btns = [];
                const push = n => btns.push(
                  <HFButton key={n} size="sm" variant={n === cur ? 'accent' : 'subtle'}
                    onClick={() => setBooksPage(n)}>{n}</HFButton>
                );
                const ell = k => btns.push(<span key={k} style={{padding:'0 2px', color:'var(--hf-ink3)'}}>…</span>);
                if (total <= 7) {
                  for (let i = 1; i <= total; i++) push(i);
                } else {
                  push(1);
                  if (cur > 4) ell('l');
                  const lo = Math.max(2, cur - 1), hi = Math.min(total - 1, cur + 1);
                  for (let i = lo; i <= hi; i++) push(i);
                  if (cur < total - 3) ell('r');
                  push(total);
                }
                return btns;
              })()}
              <HFButton size="sm" variant="subtle" disabled={booksData.page >= booksData.pages}
                aria-label="Next page"
                onClick={() => setBooksPage(p => Math.min(booksData.pages, p + 1))}>
                  <span aria-hidden="true" style={{display:'flex'}}>{HF_ICONS.chevron}</span>
                </HFButton>
            </div>
          </div>
        </>
      ) : (
        <HFTableSkeleton rows={6} columns={[
          { w: '1fr', skelW: 240 },
          { w: '180px', skelW: 120 },
          { w: '80px', skelW: 50, mono: true, align: 'right' },
          ...(booksTab === 'updated' ? [{ w: '160px', skelW: 100 }] : []),
        ]}/>
      )}
    </HFCard>
  );
}


// ───────────────────────────── Run Detail ─────────────────────────────

function HFRunDetail({ nav, goto, params }) {
  const HF = getHF();
  const runId = params?.id;
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  // Active section tab — persisted in the URL so reload + sharing preserve view.
  const _initialTab = (() => {
    const t = new URLSearchParams(window.location.search).get('tab');
    return ['general', 'history', 'books'].includes(t) ? t : 'general';
  })();
  const [tab, setTab] = React.useState(_initialTab);

  // URL queue / history state (separate fetch — its own filter & pagination)
  // Persisted in the URL query string so reload preserves view.
  const _initialUrlParams = (() => {
    const sp = new URLSearchParams(window.location.search);
    const httpRaw = sp.get('url_http');
    const httpInt = httpRaw != null ? parseInt(httpRaw, 10) : NaN;
    return {
      status: sp.get('url_status') || 'all',
      page: Math.max(parseInt(sp.get('url_page') || '1', 10) || 1, 1),
      sort: sp.get('url_sort') || 'started',
      order: sp.get('url_order') || 'desc',
      reason: sp.get('url_reason') || '',
      reasonIsNull: sp.get('url_reason_is_null') === '1',
      http: Number.isFinite(httpInt) ? httpInt : null,
      httpIsNull: sp.get('url_http_is_null') === '1',
    };
  })();
  const _initialUrlParamsFull = (() => {
    const sp = new URLSearchParams(window.location.search);
    const pp = parseInt(sp.get('url_per_page') || '10', 10);
    return { perPage: [10, 25, 50, 100].includes(pp) ? pp : 10 };
  })();
  const [urlStatus, setUrlStatus] = React.useState(_initialUrlParams.status);
  const [urlPage, setUrlPage] = React.useState(_initialUrlParams.page);
  const [urlSort, setUrlSort] = React.useState(_initialUrlParams.sort);
  const [urlOrder, setUrlOrder] = React.useState(_initialUrlParams.order);
  const [urlPerPage, setUrlPerPage] = React.useState(_initialUrlParamsFull.perPage);
  const [urlReason, setUrlReason] = React.useState(_initialUrlParams.reason);
  const [urlReasonIsNull, setUrlReasonIsNull] = React.useState(_initialUrlParams.reasonIsNull);
  const [urlHttp, setUrlHttp] = React.useState(_initialUrlParams.http);
  const [urlHttpIsNull, setUrlHttpIsNull] = React.useState(_initialUrlParams.httpIsNull);
  const [urlData, setUrlData] = React.useState(null);
  const historyRef = React.useRef(null);
  // Reset to page 1 when filter / sort / per-page changes (but not when paginating).
  React.useEffect(() => { setUrlPage(1); }, [
    runId, urlStatus, urlSort, urlOrder, urlPerPage,
    urlReason, urlReasonIsNull, urlHttp, urlHttpIsNull,
  ]);

  // Mirror state into the URL bar without adding history entries.
  React.useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    if (tab !== 'general') sp.set('tab', tab); else sp.delete('tab');
    if (urlStatus !== 'all') sp.set('url_status', urlStatus); else sp.delete('url_status');
    if (urlPage !== 1) sp.set('url_page', String(urlPage)); else sp.delete('url_page');
    if (urlSort !== 'started') sp.set('url_sort', urlSort); else sp.delete('url_sort');
    if (urlOrder !== 'desc') sp.set('url_order', urlOrder); else sp.delete('url_order');
    if (urlPerPage !== 10) sp.set('url_per_page', String(urlPerPage)); else sp.delete('url_per_page');
    if (urlReason) sp.set('url_reason', urlReason); else sp.delete('url_reason');
    if (urlReasonIsNull) sp.set('url_reason_is_null', '1'); else sp.delete('url_reason_is_null');
    if (urlHttp != null) sp.set('url_http', String(urlHttp)); else sp.delete('url_http');
    if (urlHttpIsNull) sp.set('url_http_is_null', '1'); else sp.delete('url_http_is_null');
    const qs = sp.toString();
    const url = window.location.pathname + (qs ? '?' + qs : '');
    window.history.replaceState(null, '', url);
  }, [tab, urlStatus, urlPage, urlSort, urlOrder, urlPerPage,
      urlReason, urlReasonIsNull, urlHttp, urlHttpIsNull]);

  const toggleSort = (key) => {
    if (urlSort === key) {
      setUrlOrder(urlOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setUrlSort(key);
      setUrlOrder('desc');
    }
  };

  React.useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const load = () => fetch(`/api/runs/${runId}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    load();
    // Re-poll while the run is alive so elapsed / errors / items / urls_processed
    // stay current. Stops as soon as the status flips to a terminal value.
    const status = data?.status;
    const isActive = status === 'running' || status === 'paused' || status === 'stopping';
    const timer = isActive ? setInterval(load, 2000) : null;
    return () => { cancelled = true; if (timer) clearInterval(timer); };
  }, [runId, data?.status]);

  // Live observability — poll /api/runs/{id}/live every 2s while running.
  // Once we've polled at least once, treat the live endpoint as the
  // source of truth for status (the parent /api/runs/{id} fetch is
  // one-shot and would otherwise keep us polling a terminal run forever).
  // Rolling throughput history: append reqPerMin on each live poll tick.
  // Keeps last 60 samples (2s cadence → ~2 min of history). Frozen once
  // the run reaches terminal state — postmortem chart stays visible.
  const THROUGHPUT_MAX_SAMPLES = 60;
  const [throughputHistory, setThroughputHistory] = React.useState([]);

  const [liveData, setLiveData] = React.useState(null);
  // Failures card: show acknowledged groups too. Default off — triage stays
  // focused on what hasn't been seen yet. Flipping on re-fetches /live with
  // include_acked=true.
  const [showAckedFailures, setShowAckedFailures] = React.useState(false);
  React.useEffect(() => {
    if (!runId || !data) return;
    const currentStatus = liveData?.status ?? data.status;
    const isActive = currentStatus === 'running' || currentStatus === 'stopping' || currentStatus === 'paused';
    const liveUrl = `/api/runs/${runId}/live${showAckedFailures ? '?include_acked=true' : ''}`;
    if (!isActive) {
      // Run reached terminal state. Mirror the status into `data` for
      // pills/KPIs, then do ONE final fetch to populate `liveData` if we
      // never polled (e.g. page loaded against an already-finished run).
      // Keep the panel rendered with the last known state — operators
      // want the post-mortem snapshot, not a blank panel.
      if (liveData?.status && data.status !== liveData.status) {
        setData(d => d ? { ...d, status: liveData.status } : d);
      }
      // Always re-fetch on terminal runs when showAckedFailures flips so the
      // toggle works post-mortem too, not just for live runs.
      let cancelled = false;
      fetch(liveUrl)
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (!cancelled && d) setLiveData(d); })
        .catch(() => {});
      return () => { cancelled = true; };
    }
    let cancelled = false;
    const load = () => fetch(liveUrl)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (!cancelled && d) setLiveData(d); })
      .catch(() => {});
    load();
    const id = setInterval(load, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, [runId, data?.status, liveData?.status, showAckedFailures]);

  // Accumulate throughput samples whenever liveData arrives.
  // For terminal runs a single postmortem fetch arrives; pre-seed the
  // history with a flat line so the chart renders instead of a placeholder.
  React.useEffect(() => {
    if (!liveData) return;
    const rate = liveData.rate || { done: 0, window_s: 60 };
    const ratePerMin = rate.window_s > 0 ? Math.round((rate.done / rate.window_s) * 60) : 0;
    setThroughputHistory(prev => {
      if (prev.length === 0 && ratePerMin === 0) return prev; // nothing to show
      const next = [...prev, ratePerMin];
      if (next.length === 1) {
        // Duplicate so HFAreaChart has at least 2 points; the flat line
        // honestly represents "this is the last-known rate in the 60s window".
        return [ratePerMin, ratePerMin];
      }
      return next.length > THROUGHPUT_MAX_SAMPLES
        ? next.slice(next.length - THROUGHPUT_MAX_SAMPLES) : next;
    });
  }, [liveData]);

  React.useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const params = new URLSearchParams({
      status: urlStatus,
      page: String(urlPage),
      per_page: String(urlPerPage),
      sort: urlSort,
      order: urlOrder,
    });
    if (urlReasonIsNull) params.set('error_reason_is_null', 'true');
    else if (urlReason) params.set('error_reason', urlReason);
    if (urlHttpIsNull) params.set('http_status_is_null', 'true');
    else if (urlHttp != null) params.set('http_status', String(urlHttp));
    const load = () => fetch(`/api/runs/${runId}/urls?${params.toString()}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) setUrlData(d); })
      .catch(() => {});
    load();
    // Auto-refresh while the run is still live.
    const isLive = data?.status === 'running';
    const id = isLive ? setInterval(load, 3000) : null;
    return () => { cancelled = true; if (id) clearInterval(id); };
  }, [runId, urlStatus, urlPage, urlPerPage, urlSort, urlOrder,
      urlReason, urlReasonIsNull, urlHttp, urlHttpIsNull, data?.status]);

  const id = data?.id ?? runId;
  const [actionPending, setActionPending] = React.useState(false);
  // Action feedback flows through window.HF_APP.toast — short helper keeps
  // the call sites tight. Falls back to no-op if the host isn't mounted yet.
  const toast = React.useCallback((opts) => {
    if (window.HF_APP && typeof window.HF_APP.toast === 'function') {
      window.HF_APP.toast(opts);
    }
  }, []);
  // (Failure-group disclosure state lives inside HFRunFailuresCard now.)
  // Confirm-action dialog state. `confirmDialog` carries title/body/onConfirm
  // for stop/rerun/continue/retry; `ackDialog` carries the failure group for
  // the labelled-note ack flow (replaces window.prompt).
  const [confirmDialog, setConfirmDialog] = React.useState(null);
  const [ackDialog, setAckDialog] = React.useState(null);
  const closeConfirm = React.useCallback(() => setConfirmDialog(null), []);
  const closeAck = React.useCallback(() => setAckDialog(null), []);
  // Drives every group-aware button on the Failures card so behavior is
  // uniform — pass `null` to clear (card-level "all groups" link) or a
  // failure-group dict to narrow History to that bucket.
  const applyGroupFilter = React.useCallback((group) => {
    setUrlReason(group?.reason ?? '');
    setUrlReasonIsNull(!!group?.reason_is_null);
    setUrlHttp(group?.http ?? null);
    setUrlHttpIsNull(!!group?.http_is_null);
    setUrlStatus('failed');
    // The History card lives in the History tab — switch to it first, then
    // wait for React to mount the card before scrolling. Double rAF gives
    // the new tab content one paint to appear in the DOM before
    // historyRef.current resolves.
    setTab('history');
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        historyRef.current?.scrollIntoView({behavior:'smooth', block:'start'});
      });
    });
  }, []);
  // Retry all failed URLs (group=null) or just one bucket. POST /retry
  // resets matching rows to `pending`; for terminal runs it also
  // re-spawns the spider, mirroring /continue.
  const doRetry = React.useCallback((group) => {
    if (!id) return;
    const params = new URLSearchParams();
    if (group) {
      if (group.reason_is_null) params.set('error_reason_is_null', 'true');
      else if (group.reason) params.set('error_reason', group.reason);
      if (group.http_is_null) params.set('http_status_is_null', 'true');
      else if (group.http != null) params.set('http_status', String(group.http));
    }
    setActionPending(true);
    fetch(`/api/runs/${id}/retry?${params.toString()}`, {method:'POST'})
      .then(r => r.ok ? r.json() : r.text().then(t => { throw new Error(t || r.statusText); }))
      .then(d => {
        const n = (d && (d.reset_count ?? d.queued_count)) ?? null;
        toast({
          tone: 'ok',
          message: group ? 'Group queued for retry' : 'Failed URLs queued for retry',
          detail: n != null ? `${n.toLocaleString()} URL${n === 1 ? '' : 's'} reset to pending.` : '',
        });
        // Refresh the three live data sources so the Failures card,
        // History card, and run-level KPIs all reflect the reset.
        fetch(`/api/runs/${id}`).then(r => r.ok ? r.json() : null).then(rd => { if (rd) setData(rd); });
        fetch(`/api/runs/${id}/live`).then(r => r.ok ? r.json() : null).then(ld => { if (ld) setLiveData(ld); });
        // The urlData fetch effect is keyed on filter state — filters
        // didn't change here, so re-fetch directly with the current
        // params to pick up the row-status flip.
        const sp = new URLSearchParams({
          status: urlStatus,
          page: String(urlPage),
          per_page: String(urlPerPage),
          sort: urlSort,
          order: urlOrder,
        });
        if (urlReasonIsNull) sp.set('error_reason_is_null', 'true');
        else if (urlReason) sp.set('error_reason', urlReason);
        if (urlHttpIsNull) sp.set('http_status_is_null', 'true');
        else if (urlHttp != null) sp.set('http_status', String(urlHttp));
        fetch(`/api/runs/${id}/urls?${sp.toString()}`)
          .then(r => r.ok ? r.json() : null)
          .then(ud => { if (ud) setUrlData(ud); });
      })
      .catch(e => toast({ tone: 'err', message: 'Retry failed', detail: String(e.message || e) }))
      .finally(() => { setActionPending(false); closeConfirm(); });
  }, [id, urlStatus, urlPage, urlPerPage, urlSort, urlOrder,
      urlReason, urlReasonIsNull, urlHttp, urlHttpIsNull, closeConfirm, toast]);

  // Open the styled confirm dialog before kicking off a retry.
  const retryRun = React.useCallback((group) => {
    if (!id) return;
    const label = group
      ? `${group.reason_display ?? group.reason ?? 'unknown'}${group.http != null ? ` · HTTP ${group.http}` : ''}`
      : 'all failed URLs';
    const willRespawn = data?.status === 'completed' || data?.status === 'failed';
    setConfirmDialog({
      title: group ? `Retry group on run #${id}` : `Retry all failed URLs on run #${id}`,
      body: `${group ? `Group "${label}"` : 'All failed URLs'} will be flipped back to pending.${
        willRespawn ? ' The spider will be re-spawned to pick them up.' : ''
      }`,
      confirmLabel: group ? 'Retry group' : 'Retry all',
      onConfirm: () => doRetry(group),
    });
  }, [id, data?.status, doRetry]);
  // Acknowledge a failure-card group: flips all matching scrape_failures
  // events to lifecycle_state='already_seen' so the bucket stops showing
  // up on the card. PR 2d of the migration.
  const doAck = React.useCallback((group, note) => {
    if (!id || !group) return;
    const params = new URLSearchParams();
    if (group.reason_is_null) params.set('error_reason_is_null', 'true');
    else if (group.reason) params.set('error_reason', group.reason);
    if (group.http_is_null) params.set('http_status_is_null', 'true');
    else if (group.http != null) params.set('http_status', String(group.http));
    if (note) params.set('note', note);
    const label = `${group.reason_display ?? group.reason ?? 'unknown'}${group.http != null ? ` · HTTP ${group.http}` : ''}`;
    setActionPending(true);
    fetch(`/api/runs/${id}/failures/ack?${params.toString()}`, {method:'POST'})
      .then(r => r.ok ? r.json() : r.text().then(t => { throw new Error(t || r.statusText); }))
      .then(_d => {
        toast({ tone: 'ok', message: 'Group acknowledged', detail: label });
        // Refresh the live failure_groups so the bucket disappears.
        fetch(`/api/runs/${id}/live`).then(r => r.ok ? r.json() : null).then(ld => { if (ld) setLiveData(ld); });
      })
      .catch(e => toast({ tone: 'err', message: 'Acknowledge failed', detail: String(e.message || e) }))
      .finally(() => { setActionPending(false); closeAck(); });
  }, [id, closeAck, toast]);
  // Open the ack-group dialog (replaces window.prompt).
  const ackGroup = React.useCallback((group) => {
    if (!id || !group) return;
    setAckDialog({ group });
  }, [id]);
  const doStop = React.useCallback(() => {
    if (!id) return;
    setActionPending(true);
    fetch(`/api/runs/${id}/stop`, {method:'POST'})
      .then(r => r.ok ? r.json() : r.text().then(t=>{throw new Error(t||r.statusText);}))
      .then(d => {
        setData(prev => prev ? {...prev, status: d.status} : prev);
        toast({ tone: 'ok', message: `Run #${id} stopping`, detail: 'Spider will exit on its next heartbeat tick.' });
      })
      .catch(e => toast({ tone: 'err', message: 'Stop failed', detail: String(e.message || e) }))
      .finally(() => { setActionPending(false); closeConfirm(); });
  }, [id, closeConfirm, toast]);
  const stopRun = React.useCallback(() => {
    if (actionPending || !id) return;
    setConfirmDialog({
      title: `Stop run #${id}?`,
      body: 'The spider will exit cleanly on its next heartbeat tick. In-flight URLs may finish before shutdown.',
      confirmLabel: 'Stop run',
      danger: true,
      onConfirm: doStop,
    });
  }, [id, actionPending, doStop]);
  const pauseRun = React.useCallback(() => {
    if (actionPending || !id) return;
    setActionPending(true);
    fetch(`/api/runs/${id}/pause`, {method:'POST'})
      .then(r => r.ok ? r.json() : r.text().then(t=>{throw new Error(t||r.statusText);}))
      .then(d => {
        setData(prev => prev ? {...prev, status: d.status} : prev);
        toast({ tone: 'ok', message: `Run #${id} paused` });
      })
      .catch(e => toast({ tone: 'err', message: 'Pause failed', detail: String(e.message || e) }))
      .finally(() => setActionPending(false));
  }, [id, actionPending, toast]);
  const resumeRun = React.useCallback(() => {
    if (actionPending || !id) return;
    setActionPending(true);
    fetch(`/api/runs/${id}/resume`, {method:'POST'})
      .then(r => r.ok ? r.json() : r.text().then(t=>{throw new Error(t||r.statusText);}))
      .then(d => {
        setData(prev => prev ? {...prev, status: d.status} : prev);
        toast({ tone: 'ok', message: `Run #${id} resumed` });
      })
      .catch(e => toast({ tone: 'err', message: 'Resume failed', detail: String(e.message || e) }))
      .finally(() => setActionPending(false));
  }, [id, actionPending, toast]);
  const doRerun = React.useCallback(() => {
    if (!id) return;
    setActionPending(true);
    fetch(`/api/runs/${id}/rerun`, {method:'POST'})
      .then(r => r.ok ? r.json() : r.text().then(t=>{throw new Error(t||r.statusText);}))
      .then(d => {
        const newId = d && d.id;
        toast({ tone: 'ok', message: 'New run created', detail: newId ? `Run #${newId} is queued for the same shop+phase.` : '' });
        goto('runs');
      })  // back to list — new run will appear
      .catch(e => toast({ tone: 'err', message: 'Re-run failed', detail: String(e.message || e) }))
      .finally(() => { setActionPending(false); closeConfirm(); });
  }, [id, goto, closeConfirm, toast]);
  const rerunRun = React.useCallback(() => {
    if (actionPending || !id) return;
    setConfirmDialog({
      title: `Re-run #${id}?`,
      body: `A new run will be created for the same shop+phase. The current run's records stay intact.`,
      confirmLabel: 'Re-run',
      onConfirm: doRerun,
    });
  }, [id, actionPending, doRerun]);
  const doContinue = React.useCallback(() => {
    if (!id) return;
    setActionPending(true);
    fetch(`/api/runs/${id}/continue`, {method:'POST'})
      .then(r => r.ok ? r.json() : r.text().then(t=>{throw new Error(t||r.statusText);}))
      .then(_d => {
        // Drop the stale terminal-state liveData snapshot so the live-poll
        // effect (which treats liveData.status as source of truth) doesn't
        // immediately mirror 'failed' back over our optimistic 'running'.
        setLiveData(null);
        setThroughputHistory([]);
        setData(prev => prev ? {...prev, status: 'running', close_reason: null, finished_at: null} : prev);
        toast({ tone: 'ok', message: `Run #${id} continuing`, detail: 'Pending URLs picked up on the same run.' });
      })
      .catch(e => toast({ tone: 'err', message: 'Continue failed', detail: String(e.message || e) }))
      .finally(() => { setActionPending(false); closeConfirm(); });
  }, [id, closeConfirm, toast]);
  const continueRun = React.useCallback(() => {
    if (actionPending || !id) return;
    setConfirmDialog({
      title: `Continue run #${id}?`,
      body: 'Pending URLs will be picked up on the same run. The spider will resume from where it stopped.',
      confirmLabel: 'Continue',
      onConfirm: doContinue,
    });
  }, [id, actionPending, doContinue]);

  const runsHref = (window.HF_BUILD_PATH && window.HF_BUILD_PATH('runs')) || '/runs';
  const onBreadcrumbClick = (e) => { if (e.metaKey||e.ctrlKey||e.shiftKey) return; e.preventDefault(); goto('runs'); };
  if (loading || !data) {
    return (
      <HFShell {...nav} activePage="runs" title={`Run #${runId}`}
        breadcrumb={<>
          <a href={runsHref} onClick={onBreadcrumbClick} style={{color:'var(--hf-ink3)', textDecoration:'none'}}>Runs</a>
          <span style={{color:'var(--hf-ink5)'}}>/</span>
          <span style={{fontFamily:'var(--hf-mono)'}}>#{runId}</span>
        </>}>
        <HFKpiStripSkeleton count={5}/>
        <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:'var(--hf-gap)', marginBottom:'var(--hf-gap)'}}>
          <HFCard title="Timeline" sub="loading…">
            <div style={{padding: 'var(--hf-card-p)', display:'flex', flexDirection:'column', gap: 10}}>
              {[0,1,2,3,4].map(i => (
                <div key={i} style={{display:'flex', alignItems:'center', gap: 10}}>
                  <HFSkeleton w={140} h={11}/>
                  <HFSkeleton w={50} h={11}/>
                  <HFSkeleton w="100%" h={11}/>
                </div>
              ))}
            </div>
          </HFCard>
          <HFCard title="Throughput" sub="loading…">
            <div style={{padding: 'var(--hf-card-p)'}}>
              <HFSkeleton w="100%" h={140}/>
            </div>
          </HFCard>
        </div>
      </HFShell>
    );
  }

  const runStatus = data.status || 'completed';
  const runStatusTone = {
    running: 'ok', stopping: 'warn', paused: 'warn', completed: 'neutral', failed: 'err',
  };
  const isTerminal = runStatus === 'completed' || runStatus === 'failed';
  const closeReason = data.close_reason || null;
  // Prefer the live breakdown — `data.pending_count` lags behind the queue
  // state on freshly-failed runs, which would hide the Continue button.
  const pendingCount = data.pending_count ?? urlData?.breakdown?.pending ?? 0;
  const canContinue = (
    runStatus === 'failed' &&
    pendingCount > 0
  );
  const closeReasonTone = (
    runStatus === 'failed' ? 'err' :
    runStatus === 'completed' && closeReason === 'completed_with_errors' ? 'warn' :
    runStatus === 'completed' ? 'ok' : 'neutral'
  );

  // ── Worker / in-flight ──
  // Stale `processing` rows linger in the DB after a reaped failure, so
  // ignore in_flight for terminal runs to avoid a misleading worker count.
  const isTerminalForLive = runStatus === 'completed' || runStatus === 'failed';
  const inFlight = isTerminalForLive ? [] : (liveData?.in_flight || []);
  const inFlightFirst = inFlight[0];
  const workerCount = inFlight.length;

  // ── Rate (last 60s) ──
  const liveRate = liveData?.rate || { window_s: 60, done: 0, failed: 0 };
  const rateDone = liveRate.done || 0;
  const rateFailed = liveRate.failed || 0;
  const rateTotal = rateDone + rateFailed;
  const failPct = rateTotal > 0 ? Math.round((rateFailed / rateTotal) * 100) : 0;
  const ratePerMin = liveRate.window_s > 0 ? Math.round((rateDone / liveRate.window_s) * 60) : 0;

  // ── Failure groups — server-side aggregation covers all error types.
  // Previously computed client-side from recent_failures (capped at 10),
  // which silently excluded error types not in the 10 most-recent rows.
  const failureGroups = liveData?.failure_groups || [];

  const validationIssueCount = (data.issues || []).reduce((s, g) => s + g.count, 0);

  // ── Health pill (in-flight panel header) ──
  const liveHealth = liveData?.health || null;
  const healthTone = (
    liveHealth === 'healthy' ? 'ok' :
    liveHealth === 'stuck'   ? 'warn' :
    liveHealth === 'dead'    ? 'err'  : 'neutral'
  );

  // ── Tabs for History card map straight onto urlStatus ──
  const tabCounts = urlData?.breakdown || {};
  // Always sum the breakdown — urlData.total reflects the *active filter*'s
  // row count, not the grand total, so it's wrong for the "all" pill when a
  // filtered tab is selected.
  const tabAllCount = Object.values(tabCounts).reduce((a, b) => a + (b || 0), 0);

  // ── Progress numerator + error count ──
  // The run row's `urls_processed` and `error_count` counters lag the
  // actual queue state (spider-driven, reaped/aborted rows often
  // missed). Prefer breakdown.done+failed when we have it — that's the
  // honest "what really happened" number. Falls back to the run row.
  const terminalCount =
    (tabCounts.done ?? 0) + (tabCounts.failed ?? 0);
  const progressNumerator = terminalCount > 0
    ? terminalCount
    : (data.urls_processed ?? 0);
  const errorCount = (tabCounts.failed ?? 0) > 0
    ? (tabCounts.failed ?? 0)
    : (data.errors ?? 0);

  return (
    <HFShell {...nav} activePage="runs"
      title={<span style={{display:'flex', alignItems:'center', gap:10, flexWrap:'wrap'}}>
        <span style={{fontFamily:'var(--hf-mono)', fontSize:24, fontWeight:600, color:'var(--hf-ink)'}}>Run #{id}</span>
        <HFPill tone={runStatusTone[runStatus] || 'neutral'}><HFDot tone={runStatusTone[runStatus] || 'neutral'} pulse={runStatus==='running'} size={6}/> {runStatus}</HFPill>
        {/* Live indicator — page is auto-refreshing every 2s while the run
            is in an active state. Distinct from the run-status pill: even
            a paused run is still being polled, so this tells operators the
            data they're seeing is fresh. */}
        {(runStatus === 'running' || runStatus === 'stopping' || runStatus === 'paused') && (
          <HFPill tone="muted" title="This page is auto-refreshing every 2 seconds">
            <HFDot tone="ok" pulse size={6}/>
            <span style={{fontFamily:'var(--hf-mono)', fontSize:11, letterSpacing:0.4, textTransform:'uppercase'}}>Live</span>
          </HFPill>
        )}
        {isTerminal && closeReason && (
          <HFPill tone={closeReasonTone} title={`close_reason: ${closeReason}`}>
            <span style={{fontFamily:'var(--hf-mono)', fontSize:11}}>{closeReason}</span>
          </HFPill>
        )}
      </span>}
      subtitle={<span style={{fontFamily:'var(--hf-mono)', fontSize:13, color:'var(--hf-ink3)'}}>shop={data.shop} · phase={data.phase} · started {data.started_ago} · triggered by {data.by}</span>}
      breadcrumb={<>
        <a href={runsHref} onClick={onBreadcrumbClick} style={{color:'var(--hf-ink3)', textDecoration:'none'}}>Runs</a>
        <span style={{color:'var(--hf-ink5)'}}>/</span>
        <span style={{color:'var(--hf-ink)', fontWeight:500, fontFamily:'var(--hf-mono)'}}>#{id}</span>
      </>}
      actions={<>
        <HFButton disabled><span style={{display:'flex'}}>{HF_ICONS.download}</span> Logs</HFButton>
        {runStatus === 'running' && (
          <HFButton disabled={actionPending} onClick={pauseRun}>
            <span style={{display:'flex'}}>{HF_ICONS.pause}</span> Pause
          </HFButton>
        )}
        {runStatus === 'paused' && (
          <HFButton variant="primary" disabled={actionPending} onClick={resumeRun}>
            <span style={{display:'flex'}}>{HF_ICONS.play}</span> Resume
          </HFButton>
        )}
        {(runStatus === 'running' || runStatus === 'stopping' || runStatus === 'paused') && (
          <HFButton variant="danger" disabled={actionPending || runStatus === 'stopping'} onClick={stopRun}>
            <span style={{display:'flex'}}>{HF_ICONS.stop}</span>
            {runStatus === 'stopping' ? 'Stopping…' : 'Stop run'}
          </HFButton>
        )}
        {canContinue ? (
          <HFButton variant="primary" disabled={actionPending} onClick={continueRun}>
            <span style={{display:'flex'}}>{HF_ICONS.play}</span> Continue
          </HFButton>
        ) : (runStatus === 'failed' || runStatus === 'completed') && (
          <HFButton variant="primary" disabled={actionPending} onClick={rerunRun}>
            <span style={{display:'flex'}}>{HF_ICONS.cycle}</span> Re-run
          </HFButton>
        )}
      </>}
    >
      {/* KPI strip — Progress · Elapsed · Errors · Workers */}
      <HFKpiStrip items={[
        { label:'Progress', value:`${data.progress}%`,
          delta:<span style={{color:'var(--hf-ink3)'}}>
            {data.urls_total
              ? `${progressNumerator.toLocaleString()} of ${data.urls_total.toLocaleString()}`
              : (data.items ? `${data.items.toLocaleString()} items` : '—')}
          </span> },
        { label:'Elapsed', value:data.elapsed || '—',
          delta:<span style={{color:'var(--hf-ink3)'}}>
            {liveData?.eta_min != null
              ? `ETA ${liveData.eta_min === 0 ? '<1' : liveData.eta_min}m`
              : 'duration'}
          </span> },
        { label:'Failures', value:errorCount.toLocaleString(),
          ...(errorCount > 0 ? { onClick: () => { setTab('history'); setUrlStatus('failed'); } } : {}),
          delta: (() => {
            const a = data.errors_4xx ?? 0, b = data.errors_5xx ?? 0;
            if (errorCount > 0) return <span style={{color:'var(--hf-accent-ink)'}}>view →</span>;
            if (a === 0 && b === 0) return <span style={{color:'var(--hf-ink3)'}}>failed URLs</span>;
            return <span style={{color:'var(--hf-ink3)'}}>{a} 4xx · {b} 5xx</span>;
          })() },
        { label:'Workers', value:String(workerCount),
          delta:<span style={{color:'var(--hf-ink3)'}} title="CONCURRENT_REQUESTS_PER_DOMAIN controls max simultaneous fetches">in flight</span> },
        { label:'Val. Issues', value:validationIssueCount.toLocaleString(),
          ...(validationIssueCount > 0 ? { href: `/issues?run_id=${id}` } : {}),
          delta:<span style={{color: validationIssueCount > 0 ? 'var(--hf-accent-ink)' : 'var(--hf-ink3)'}}>
            {validationIssueCount > 0 ? 'view →' : 'none'}
          </span> },
      ]}/>

      {/* Paused callout — visible banner so it's impossible to miss */}
      {runStatus === 'paused' && (
        <div style={{
          display:'flex', alignItems:'center', gap:12,
          padding:'12px 16px',
          background:'var(--hf-warn-bg)',
          border:'1px solid var(--hf-warn)',
          borderRadius:'var(--hf-radius)',
          marginBottom:'var(--hf-gap)',
        }}>
          <span style={{fontSize:18, lineHeight:1}}>{HF_ICONS.pause}</span>
          <span style={{flex:1}}>
            <strong style={{color:'var(--hf-warn-ink)'}}>Run paused</strong>
            <span style={{color:'var(--hf-ink3)', marginLeft:8, fontSize:13}}>Spider is idle but alive — heartbeat is still ticking. Resume to continue scraping.</span>
          </span>
          <HFButton variant="primary" disabled={actionPending} onClick={resumeRun}><span style={{display:'flex'}}>{HF_ICONS.play}</span> Resume</HFButton>
        </div>
      )}

      {/* Section tabs — pivot between run health, URL history, and books */}
      <div style={{marginBottom: 'var(--hf-gap)'}}>
        <HFTabs
          active={tab}
          onChange={setTab}
          tabs={[
            { id: 'general', label: 'General' },
            { id: 'history', label: 'History', count: urlData?.total ?? null },
            { id: 'books',   label: 'Books',   count: ((data.items_added ?? 0) + (data.items_updated ?? 0)) || null },
          ]}
        />
      </div>

      {tab === 'general' && <>
      {/* Timeline + Throughput — paired summary row */}
      <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap:'var(--hf-gap)', marginBottom:'var(--hf-gap)'}}>
        <HFRunTimelineCard events={liveData?.events ?? data.events ?? []} style={{marginBottom: 0}}/>
        {(() => {
          const ratePerMinFailed = liveRate.window_s > 0
            ? Math.round((rateFailed / liveRate.window_s) * 60) : 0;
          // Scale the Y-axis to the rolling max so spikes don't pin the chart.
          const peak = Math.max(0, ...throughputHistory, ratePerMinFailed);
          // Round up to a clean multiple of 5 (min of 5).
          const yMax = Math.max(5, Math.ceil(peak / 5) * 5);
          const yTicks = [yMax, Math.round(yMax * 0.75), Math.round(yMax / 2), Math.round(yMax / 4), 0];
          const sampleAgeS = (n) => Math.round(n * 2);
          return (
            <HFCard
              title="Throughput"
              sub={`items / minute · 2s samples · last ${Math.round(THROUGHPUT_MAX_SAMPLES * 2 / 60)}m window`}
              action={<div style={{display:'flex', gap:14, fontFamily:'var(--hf-mono)', fontSize:12}}>
                <span style={{display:'flex', alignItems:'center', gap:5}}>
                  <span style={{width:8, height:8, borderRadius:2, background:'var(--hf-ok)'}}/>
                  <span style={{color:'var(--hf-ink3)'}}>done</span>
                  <span style={{color:'var(--hf-ink2)', fontWeight:600}}>
                    {throughputHistory.length > 0 ? `${throughputHistory[throughputHistory.length-1]}/min` : '—'}
                  </span>
                </span>
                <span style={{display:'flex', alignItems:'center', gap:5}}>
                  <span style={{width:8, height:8, borderRadius:2, background:'var(--hf-err)'}}/>
                  <span style={{color:'var(--hf-ink3)'}}>failed</span>
                  <span style={{color: rateFailed > 0 ? 'var(--hf-err-ink)' : 'var(--hf-ink3)', fontWeight:600}}>
                    {ratePerMinFailed}/min
                  </span>
                </span>
              </div>}
            >
              <div style={{padding: 'var(--hf-card-p)'}}>
                <div style={{display:'grid', gridTemplateColumns:'34px 1fr', gap: 8}}>
                  <div style={{display:'flex', flexDirection:'column', justifyContent:'space-between', alignItems:'flex-end', fontFamily:'var(--hf-mono)', fontSize:11, color:'var(--hf-ink4)', fontVariantNumeric:'tabular-nums', height: 140, paddingRight: 4}}>
                    {yTicks.map(v => <span key={v}>{v}</span>)}
                  </div>
                  <div style={{minWidth: 0}}>
                    {throughputHistory.length > 1 ? (
                      <HFAreaChart data={throughputHistory} h={140} label="Throughput per sample"/>
                    ) : (
                      <div style={{height:140, display:'flex', alignItems:'center', justifyContent:'center', color:'var(--hf-ink4)', fontSize:12}}>
                        {throughputHistory.length === 0 ? 'Waiting for first poll…' : 'Collecting samples…'}
                      </div>
                    )}
                    <div style={{display:'flex', justifyContent:'space-between', fontFamily:'var(--hf-mono)', fontSize:11, color:'var(--hf-ink4)', fontVariantNumeric:'tabular-nums', marginTop: 6}}>
                      <span>−{sampleAgeS(throughputHistory.length)}s</span>
                      <span>−{sampleAgeS(Math.floor(throughputHistory.length * 3 / 4))}s</span>
                      <span>−{sampleAgeS(Math.floor(throughputHistory.length / 2))}s</span>
                      <span>−{sampleAgeS(Math.floor(throughputHistory.length / 4))}s</span>
                      <span>now</span>
                    </div>
                  </div>
                </div>
              </div>
            </HFCard>
          );
        })()}
      </div>

      {/* In-flight card — what's happening RIGHT NOW (only when live) */}
      <HFRunInFlightCard
        liveData={liveData}
        runStatus={runStatus}
        workerCount={workerCount}
        inFlightFirst={inFlightFirst}
        liveHealth={liveHealth}
        healthTone={healthTone}
        liveRate={liveRate}
        rateDone={rateDone}
        rateFailed={rateFailed}
        ratePerMin={ratePerMin}
        failPct={failPct}
        tabCounts={tabCounts}
      />

      {/* Failures card — grouped by error_reason from recent_failures */}
      <HFRunFailuresCard
        failureGroups={failureGroups}
        showAckedFailures={showAckedFailures}
        setShowAckedFailures={setShowAckedFailures}
        actionPending={actionPending}
        retryRun={retryRun}
        ackGroup={ackGroup}
        applyGroupFilter={applyGroupFilter}
      />

      </>}

      {tab === 'history' && <>
      {/* History card — tabbed URL queue / discovered URL history */}
      <HFRunHistoryCard
        urlData={urlData}
        historyRef={historyRef}
        goto={goto}
        urlStatus={urlStatus} setUrlStatus={setUrlStatus}
        urlSort={urlSort} urlOrder={urlOrder} toggleSort={toggleSort}
        urlPage={urlPage} setUrlPage={setUrlPage}
        urlPerPage={urlPerPage} setUrlPerPage={setUrlPerPage}
        urlReason={urlReason} setUrlReason={setUrlReason}
        urlReasonIsNull={urlReasonIsNull} setUrlReasonIsNull={setUrlReasonIsNull}
        urlHttp={urlHttp} setUrlHttp={setUrlHttp}
        urlHttpIsNull={urlHttpIsNull} setUrlHttpIsNull={setUrlHttpIsNull}
        tabAllCount={tabAllCount} tabCounts={tabCounts}
        clearAllFilters={() => {
          setUrlStatus('all');
          setUrlSort('started');
          setUrlOrder('desc');
          setUrlPage(1);
          setUrlReason('');
          setUrlReasonIsNull(false);
          setUrlHttp(null);
          setUrlHttpIsNull(false);
        }}
      />

      </>}

      {tab === 'books' && (
        <HFRunBooksCard
          runId={id}
          itemsAdded={data.items_added}
          itemsUpdated={data.items_updated}
          goto={goto}
        />
      )}

      {/* Action dialogs — replaces window.confirm/prompt for stop/retry/ack/etc. */}
      <HFConfirmDialog
        open={!!confirmDialog}
        title={confirmDialog?.title}
        body={confirmDialog?.body}
        confirmLabel={confirmDialog?.confirmLabel}
        danger={confirmDialog?.danger}
        busy={actionPending}
        onCancel={closeConfirm}
        onConfirm={() => confirmDialog?.onConfirm && confirmDialog.onConfirm()}
      />
      <HFAckGroupDialog
        open={!!ackDialog}
        group={ackDialog?.group}
        runId={id}
        busy={actionPending}
        onCancel={closeAck}
        onConfirm={(note) => doAck(ackDialog?.group, note)}
      />
    </HFShell>
  );
}


Object.assign(window, { HFRuns, HFRunDetail });
