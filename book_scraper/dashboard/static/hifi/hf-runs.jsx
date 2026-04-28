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

  // Repeated-failure banner — refresh every 30s.
  const [repeatedFailures, setRepeatedFailures] = React.useState([]);
  React.useEffect(() => {
    let cancelled = false;
    const load = () => fetch('/api/runs/repeated-failures')
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (!cancelled && d) setRepeatedFailures(d.items || []); })
      .catch(() => {});
    load();
    const id = setInterval(load, 30000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

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
      breadcrumb={<><span>BookScraper</span><span style={{color:HF.ink5}}>/</span><span style={{color:HF.ink, fontWeight:500}}>Runs</span></>}
      actions={<>
        <HFButton><span style={{display:'flex'}}>{HF_ICONS.download}</span> Export CSV</HFButton>
        <HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openNewRun()}><span style={{display:'flex'}}>{HF_ICONS.play}</span> New run</HFButton>
      </>}
    >
      {/* Repeated-failure banner — shows shops whose last N terminal
          runs all failed with the same error_reason. */}
      {repeatedFailures.length > 0 && (
        <div style={{margin:`0 0 ${HF.gap}px`, padding:'12px 16px', background:'rgba(239,68,68,0.08)', border:'1px solid rgba(239,68,68,0.3)', borderRadius:8, color:HF.ink}}>
          <div style={{display:'flex', alignItems:'center', gap:10, marginBottom:6}}>
            <span style={{color:'#ef4444', fontWeight:600}}>● Repeated failures detected</span>
            <span style={{fontSize:12, color:HF.ink3}}>The last {repeatedFailures[0].count} runs for these shops failed with the same reason — likely systemic, not transient.</span>
          </div>
          <div style={{display:'flex', flexWrap:'wrap', gap:8}}>
            {repeatedFailures.map((rf, i) => (
              <a key={i} href="#" onClick={e=>{e.preventDefault(); goto('run-detail',{id:rf.latest_run_id});}}
                 style={{padding:'4px 10px', borderRadius:4, background:'rgba(239,68,68,0.15)', color:HF.ink, textDecoration:'none', fontFamily:HF.mono, fontSize:12.5}}>
                {rf.shop}/{rf.phase} <span style={{color:HF.ink3}}>·</span> {rf.error_reason}
              </a>
            ))}
          </div>
        </div>
      )}

      {/* Schedule badges — "Next run in Xh" + "Last success Xh ago" */}
      {scheduleItems.length > 0 && (
        <div style={{display:'flex', gap:8, marginBottom:HF.gap, flexWrap:'wrap'}}>
          {scheduleItems.map((s, i) => (
            <div key={i} style={{display:'flex', gap:8, padding:'6px 12px', background:HF.subtle, borderRadius:6, fontSize:12, color:HF.ink3, fontFamily:HF.mono, alignItems:'center'}}>
              <span style={{color:HF.ink, fontWeight:500}}>{s.shop}/{s.phase}</span>
              {s.next_run_in_s != null && (
                <span title={s.next_run_at || ''}>next in <strong style={{color:HF.ink}}>{_fmtSeconds(s.next_run_in_s)}</strong></span>
              )}
              <span style={{color:HF.ink5}}>·</span>
              <span title={s.last_success_at || ''}>last ok: <strong style={{color:HF.ink}}>{_fmtAgoIso(s.last_success_at)}</strong></span>
            </div>
          ))}
        </div>
      )}

      {/* Summary strip — clickable filter shortcuts */}
      <HFKpiStrip items={[
        { label:'Running now', value: String(data.kpis.running_now), delta:<span style={{color:HF.okInk}}>● live</span>,
          onClick: () => { setStatus('running'); setWhen('any'); } },
        { label:'Today',       value: String(data.kpis.today_total), delta:<span style={{color:HF.ink3}}>{data.kpis.today_ok} ok · {data.kpis.today_failed} failed</span>,
          onClick: () => { setStatus('all'); setWhen('24h'); } },
        { label:'All-time',    value: String(data.kpis.all_time || 0), delta:<span style={{color:HF.ink3}}>total runs</span>,
          onClick: clearAll },
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
const RUN_EVENT_META = {
  started:               { glyph: '▶',  label: 'Started',          tone: 'accent'  },
  paused:                { glyph: '⏸',  label: 'Paused',           tone: 'warn'    },
  resumed:               { glyph: '▶',  label: 'Resumed',          tone: 'accent'  },
  stop_requested:        { glyph: '⏹',  label: 'Stop requested',   tone: 'warn'    },
  retry_failures:        { glyph: '↻',  label: 'Retry failures',   tone: 'accent'  },
  rerun:                 { glyph: '↻',  label: 'Rerun triggered',  tone: 'accent'  },
  continued:             { glyph: '▶',  label: 'Continued',        tone: 'accent'  },
  resumed_after_failure: { glyph: '↺',  label: 'Resumed (inherited queue)', tone: 'accent' },
  completed:             { glyph: '✓',  label: 'Completed',        tone: 'ok'      },
  failed:                { glyph: '✗',  label: 'Failed',           tone: 'err'     },
};

function _fmtEventPayload(eventType, payload) {
  if (!payload || typeof payload !== 'object') return '';
  const parts = [];
  // Pull the most operator-relevant keys first.
  const order = [
    'close_reason', 'previous_status', 'previous_run_id',
    'phase', 'mode', 'rescrape', 'urls_total', 'urls_skipped',
    'rows_reset', 'error_reason_filter', 'http_status_filter',
    'pending_count', 'urls_processed', 'error_count',
  ];
  const seen = new Set();
  for (const k of order) {
    if (!(k in payload)) continue;
    const v = payload[k];
    if (v === null || v === undefined || v === '' || v === false) {
      if (!(k === 'rescrape' && v === false)) {
        // skip falsy noise unless it carries meaning (rescrape=false matters)
        seen.add(k);
        continue;
      }
    }
    parts.push(`${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`);
    seen.add(k);
  }
  return parts.join(' · ');
}


function HFRunTimelineCard({ events }) {
  const HF = getHF();
  const list = Array.isArray(events) ? events : [];
  const toneColor = (tone) => {
    if (tone === 'ok')     return HF.okInk || '#16a34a';
    if (tone === 'warn')   return HF.warnInk || '#d97706';
    if (tone === 'err')    return HF.errInk || '#dc2626';
    if (tone === 'accent') return HF.accentInk || '#2563eb';
    return HF.ink2 || HF.ink || '#444';
  };
  return (
    <HFCard
      title="Timeline"
      sub={list.length === 1 ? '1 event' : `${list.length} events`}
      style={{ marginBottom: HF.gap }}
    >
      {list.length === 0 ? (
        <div style={{ padding: HF.cardP, color: HF.ink3, fontSize: 13 }}>
          No events recorded for this run.
        </div>
      ) : (
        <div style={{ padding: HF.cardP }}>
          <ol style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {list.map((ev) => {
              const meta = RUN_EVENT_META[ev.event_type] || { glyph: '•', label: ev.event_type, tone: 'neutral' };
              const summary = _fmtEventPayload(ev.event_type, ev.payload);
              const absoluteTime = ev.created_at ? new Date(ev.created_at).toLocaleString() : '';
              return (
                <li key={ev.id} style={{
                  display: 'grid',
                  gridTemplateColumns: '20px 160px 1fr auto',
                  alignItems: 'baseline',
                  gap: 10,
                  padding: '6px 8px',
                  borderRadius: HF.r2,
                  fontSize: 13,
                  background: 'rgba(0,0,0,0.02)',
                }}>
                  <span style={{ color: toneColor(meta.tone), fontSize: 14, lineHeight: 1, textAlign: 'center' }}>
                    {meta.glyph}
                  </span>
                  <span style={{ color: toneColor(meta.tone), fontWeight: 600 }}>
                    {meta.label}
                    {ev.actor && ev.actor !== 'system' ? (
                      <span style={{ color: HF.ink3, fontWeight: 400, marginLeft: 6 }}>
                        ({ev.actor})
                      </span>
                    ) : null}
                  </span>
                  <span style={{
                    fontFamily: HF.mono, color: HF.ink2, overflow: 'hidden',
                    textOverflow: 'ellipsis', whiteSpace: 'nowrap', minWidth: 0,
                  }} title={summary}>
                    {summary}
                  </span>
                  <span
                    style={{ color: HF.ink3, fontFamily: HF.mono, fontSize: 12 }}
                    title={absoluteTime}
                  >
                    {_fmtClockTime(ev.created_at)}
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
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
  }, [urlStatus, urlPage, urlSort, urlOrder, urlPerPage,
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
  React.useEffect(() => {
    if (!runId || !data) return;
    const currentStatus = liveData?.status ?? data.status;
    const isActive = currentStatus === 'running' || currentStatus === 'stopping' || currentStatus === 'paused';
    if (!isActive) {
      // Run reached terminal state. Mirror the status into `data` for
      // pills/KPIs, then do ONE final fetch to populate `liveData` if we
      // never polled (e.g. page loaded against an already-finished run).
      // Keep the panel rendered with the last known state — operators
      // want the post-mortem snapshot, not a blank panel.
      if (liveData?.status && data.status !== liveData.status) {
        setData(d => d ? { ...d, status: liveData.status } : d);
      }
      if (!liveData) {
        let cancelled = false;
        fetch(`/api/runs/${runId}/live`)
          .then(r => r.ok ? r.json() : null)
          .then(d => { if (!cancelled && d) setLiveData(d); })
          .catch(() => {});
        return () => { cancelled = true; };
      }
      return;
    }
    let cancelled = false;
    const load = () => fetch(`/api/runs/${runId}/live`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (!cancelled && d) setLiveData(d); })
      .catch(() => {});
    load();
    const id = setInterval(load, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, [runId, data?.status, liveData?.status]);

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
  const [actionError, setActionError] = React.useState(null);
  const [expandedFailure, setExpandedFailure] = React.useState(-1);
  // Drives every group-aware button on the Failures card so behavior is
  // uniform — pass `null` to clear (card-level "all groups" link) or a
  // failure-group dict to narrow History to that bucket.
  const applyGroupFilter = React.useCallback((group) => {
    setUrlReason(group?.reason ?? '');
    setUrlReasonIsNull(!!group?.reason_is_null);
    setUrlHttp(group?.http ?? null);
    setUrlHttpIsNull(!!group?.http_is_null);
    setUrlStatus('failed');
    // Defer scroll until React has reconciled and the History card is
    // visible (the chip + filter change can shift layout).
    requestAnimationFrame(() => {
      historyRef.current?.scrollIntoView({behavior:'smooth', block:'start'});
    });
  }, []);
  // Retry all failed URLs (group=null) or just one bucket. POST /retry
  // resets matching rows to `pending`; for terminal runs it also
  // re-spawns the spider, mirroring /continue.
  const retryRun = React.useCallback((group) => {
    if (!id) return;
    const label = group
      ? `${group.reason_display ?? group.reason ?? 'unknown'}${group.http != null ? ` · HTTP ${group.http}` : ''}`
      : 'all failed URLs';
    if (!confirm(`Retry ${group ? `group "${label}"` : label} on run #${id}?\nFailed URLs will be flipped back to pending.`)) return;
    const params = new URLSearchParams();
    if (group) {
      if (group.reason_is_null) params.set('error_reason_is_null', 'true');
      else if (group.reason) params.set('error_reason', group.reason);
      if (group.http_is_null) params.set('http_status_is_null', 'true');
      else if (group.http != null) params.set('http_status', String(group.http));
    }
    setActionPending(true); setActionError(null);
    fetch(`/api/runs/${id}/retry?${params.toString()}`, {method:'POST'})
      .then(r => r.ok ? r.json() : r.text().then(t => { throw new Error(t || r.statusText); }))
      .then(d => {
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
      .catch(e => setActionError(String(e.message || e)))
      .finally(() => setActionPending(false));
  }, [id, urlStatus, urlPage, urlPerPage, urlSort, urlOrder,
      urlReason, urlReasonIsNull, urlHttp, urlHttpIsNull]);
  // Acknowledge a failure-card group: flips all matching scrape_failures
  // events to lifecycle_state='already_seen' so the bucket stops showing
  // up on the card. PR 2d of the migration.
  const ackGroup = React.useCallback((group) => {
    if (!id || !group) return;
    const label = `${group.reason_display ?? group.reason ?? 'unknown'}${group.http != null ? ` · HTTP ${group.http}` : ''}`;
    if (!confirm(`Mark group "${label}" as known on run #${id}?\nThe bucket will stop appearing on the Failures card.`)) return;
    const params = new URLSearchParams();
    if (group.reason_is_null) params.set('error_reason_is_null', 'true');
    else if (group.reason) params.set('error_reason', group.reason);
    if (group.http_is_null) params.set('http_status_is_null', 'true');
    else if (group.http != null) params.set('http_status', String(group.http));
    setActionPending(true); setActionError(null);
    fetch(`/api/runs/${id}/failures/ack?${params.toString()}`, {method:'POST'})
      .then(r => r.ok ? r.json() : r.text().then(t => { throw new Error(t || r.statusText); }))
      .then(_d => {
        // Refresh the live failure_groups so the bucket disappears.
        fetch(`/api/runs/${id}/live`).then(r => r.ok ? r.json() : null).then(ld => { if (ld) setLiveData(ld); });
      })
      .catch(e => setActionError(String(e.message || e)))
      .finally(() => setActionPending(false));
  }, [id]);
  const stopRun = React.useCallback(() => {
    if (actionPending || !id) return;
    if (!confirm(`Stop run #${id}? Spider will exit cleanly on its next heartbeat tick.`)) return;
    setActionPending(true); setActionError(null);
    fetch(`/api/runs/${id}/stop`, {method:'POST'})
      .then(r => r.ok ? r.json() : r.text().then(t=>{throw new Error(t||r.statusText);}))
      .then(d => { setData(prev => prev ? {...prev, status: d.status} : prev); })
      .catch(e => setActionError(String(e.message || e)))
      .finally(() => setActionPending(false));
  }, [id, actionPending]);
  const pauseRun = React.useCallback(() => {
    if (actionPending || !id) return;
    setActionPending(true); setActionError(null);
    fetch(`/api/runs/${id}/pause`, {method:'POST'})
      .then(r => r.ok ? r.json() : r.text().then(t=>{throw new Error(t||r.statusText);}))
      .then(d => { setData(prev => prev ? {...prev, status: d.status} : prev); })
      .catch(e => setActionError(String(e.message || e)))
      .finally(() => setActionPending(false));
  }, [id, actionPending]);
  const resumeRun = React.useCallback(() => {
    if (actionPending || !id) return;
    setActionPending(true); setActionError(null);
    fetch(`/api/runs/${id}/resume`, {method:'POST'})
      .then(r => r.ok ? r.json() : r.text().then(t=>{throw new Error(t||r.statusText);}))
      .then(d => { setData(prev => prev ? {...prev, status: d.status} : prev); })
      .catch(e => setActionError(String(e.message || e)))
      .finally(() => setActionPending(false));
  }, [id, actionPending]);
  const rerunRun = React.useCallback(() => {
    if (actionPending || !id) return;
    if (!confirm(`Re-run #${id}? A new run will be created for the same shop+phase.`)) return;
    setActionPending(true); setActionError(null);
    fetch(`/api/runs/${id}/rerun`, {method:'POST'})
      .then(r => r.ok ? r.json() : r.text().then(t=>{throw new Error(t||r.statusText);}))
      .then(_d => { goto('runs'); })  // back to list — new run will appear
      .catch(e => setActionError(String(e.message || e)))
      .finally(() => setActionPending(false));
  }, [id, actionPending, goto]);
  const continueRun = React.useCallback(() => {
    if (actionPending || !id) return;
    if (!confirm(`Continue run #${id}? Pending URLs will be picked up on the same run.`)) return;
    setActionPending(true); setActionError(null);
    fetch(`/api/runs/${id}/continue`, {method:'POST'})
      .then(r => r.ok ? r.json() : r.text().then(t=>{throw new Error(t||r.statusText);}))
      .then(_d => {
        // Drop the stale terminal-state liveData snapshot so the live-poll
        // effect (which treats liveData.status as source of truth) doesn't
        // immediately mirror 'failed' back over our optimistic 'running'.
        setLiveData(null);
        setThroughputHistory([]);
        setData(prev => prev ? {...prev, status: 'running', close_reason: null, finished_at: null} : prev);
      })
      .catch(e => setActionError(String(e.message || e)))
      .finally(() => setActionPending(false));
  }, [id, actionPending]);

  if (loading || !data) {
    return (
      <HFShell {...nav} activePage="runs" title={`Run #${runId}`} subtitle="Loading…"
        breadcrumb={<><a href="#" onClick={e=>{e.preventDefault();goto('runs');}}>Runs</a><span style={{color:nav.HF?.ink5||'#c7cbd3'}}>/</span><span>#{runId}</span></>}>
        <div style={{padding:40, color:HF.ink3}}>Loading…</div>
      </HFShell>
    );
  }

  const runStatus = data.status || 'completed';
  const runStatusTone = {
    running: 'ok', stopping: 'warn', paused: 'warn', completed: 'neutral', failed: 'err',
  };
  const isTerminal = runStatus === 'completed' || runStatus === 'failed';
  const closeReason = data.close_reason || null;
  const canContinue = (
    runStatus === 'failed' &&
    data.phase === 'scan' &&
    (data.pending_count || 0) > 0
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
        <span style={{fontFamily:HF.mono, fontSize:24, fontWeight:600, color:HF.ink}}>Run #{id}</span>
        <HFPill tone={runStatusTone[runStatus] || 'neutral'}><HFDot tone={runStatusTone[runStatus] || 'neutral'} pulse={runStatus==='running'} size={6}/> {runStatus}</HFPill>
        {isTerminal && closeReason && (
          <HFPill tone={closeReasonTone} title={`close_reason: ${closeReason}`}>
            <span style={{fontFamily:HF.mono, fontSize:11}}>{closeReason}</span>
          </HFPill>
        )}
      </span>}
      subtitle={<span style={{fontFamily:HF.mono, fontSize:12.5, color:HF.ink3}}>shop={data.shop} · phase={data.phase} · started {data.started_ago} · triggered by {data.by}</span>}
      breadcrumb={<>
        <a href="#" onClick={(e)=>{e.preventDefault(); goto('runs');}} style={{color:HF.ink3, textDecoration:'none'}}>Runs</a>
        <span style={{color:HF.ink5}}>/</span>
        <span style={{color:HF.ink, fontWeight:500, fontFamily:HF.mono}}>#{id}</span>
      </>}
      actions={<>
        <HFButton disabled><span style={{display:'flex'}}>{HF_ICONS.download}</span> Logs</HFButton>
        {runStatus === 'running' && (
          <HFButton disabled={actionPending} onClick={pauseRun}>⏸ Pause</HFButton>
        )}
        {runStatus === 'paused' && (
          <HFButton variant="primary" disabled={actionPending} onClick={resumeRun}>▶ Resume</HFButton>
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
            <span style={{display:'flex'}}>{HF_ICONS.play}</span> Re-run
          </HFButton>
        )}
      </>}
    >
      {actionError && (
        <div style={{margin:`0 0 ${HF.gap}px`, padding:'10px 14px', background:'rgba(239,68,68,0.08)', border:'1px solid rgba(239,68,68,0.3)', borderRadius:6, color:HF.ink, fontSize:13}}>
          <strong style={{color:'#ef4444'}}>Action failed:</strong> {actionError}
        </div>
      )}
      {/* KPI strip — Progress · Elapsed · Errors · Workers */}
      <HFKpiStrip items={[
        { label:'Progress', value:`${data.progress}%`,
          delta:<span style={{color:HF.ink3}}>
            {data.urls_total
              ? `${progressNumerator.toLocaleString()} of ${data.urls_total.toLocaleString()}`
              : (data.items ? `${data.items.toLocaleString()} items` : '—')}
          </span> },
        { label:'Elapsed', value:data.elapsed || '—',
          delta:<span style={{color:HF.ink3}}>
            {liveData?.eta_min != null
              ? `ETA ${liveData.eta_min === 0 ? '<1' : liveData.eta_min}m`
              : 'duration'}
          </span> },
        { label:'Errors', value:String(errorCount),
          delta: (() => {
            const a = data.errors_4xx ?? 0, b = data.errors_5xx ?? 0;
            if (a === 0 && b === 0) return <span style={{color:HF.ink3}}>failed URLs</span>;
            return <span style={{color:HF.ink3}}>{a} 4xx · {b} 5xx</span>;
          })() },
        { label:'Workers', value:String(workerCount),
          delta:<span style={{color:HF.ink3}} title="CONCURRENT_REQUESTS_PER_DOMAIN controls max simultaneous fetches">in flight</span> },
        { label:'Val. Issues', value:String(validationIssueCount),
          href: validationIssueCount > 0 ? `/issues?run_id=${id}` : '#',
          delta:<span style={{color: validationIssueCount > 0 ? HF.accentInk : HF.ink3}}>
            {validationIssueCount > 0 ? 'view →' : 'none'}
          </span> },
      ]}/>

      {/* Timeline — operator and lifecycle events for this run, oldest first */}
      <HFRunTimelineCard events={liveData?.events ?? data.events ?? []} />

      {/* In-flight card — what's happening RIGHT NOW (only when live) */}
      {liveData && (runStatus === 'running' || runStatus === 'paused' || runStatus === 'stopping') && (
        <HFCard
          title="In flight"
          sub={`${workerCount} ${workerCount === 1 ? 'URL' : 'URLs'} · ${liveData.eta_min != null ? `ETA ${liveData.eta_min === 0 ? '<1' : liveData.eta_min}m` : 'live'}`}
          action={liveHealth ? <HFPill tone={healthTone}><HFDot tone={healthTone} pulse={liveHealth==='healthy'} size={6}/> health: {liveHealth}</HFPill> : null}
          style={{marginBottom: HF.gap}}
        >
          <div style={{padding: HF.cardP, display:'grid', gridTemplateColumns:'1.4fr 1fr', gap: HF.gap, alignItems:'stretch'}}>
            {/* Active fetch tile */}
            <div style={{
              background: HF.accentSoft, border: `1px solid ${HF.accentBorder}`,
              borderRadius: HF.r2, padding: '14px 16px',
              display:'flex', flexDirection:'column', gap: 8, position:'relative', overflow:'hidden',
              minHeight: 90,
            }}>
              {inFlightFirst ? (
                <>
                  <div style={{display:'flex', alignItems:'center', gap: 8, marginBottom: 2}}>
                    <HFDot tone="accent" pulse size={7}/>
                    <span style={{fontSize: 10.5, fontWeight: 600, color: HF.accentInk, letterSpacing: 0.6, textTransform:'uppercase'}}>
                      Now fetching
                    </span>
                    <span style={{flex: 1}}/>
                    <span style={{fontFamily: HF.mono, fontSize: 22, fontWeight: 600, color: HF.accentInk, fontVariantNumeric:'tabular-nums', lineHeight: 1}}>
                      {_fmtAge(inFlightFirst.claimed_age_s)}
                    </span>
                  </div>
                  <div style={{display:'flex', alignItems:'center', gap: 8, minWidth:0}}>
                    <span style={{
                      fontFamily: HF.mono, fontSize: 13, color: HF.ink, fontWeight: 500,
                      overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', minWidth:0, flex: 1,
                    }} title={inFlightFirst.url}>{inFlightFirst.url}</span>
                    <HFExtLink href={inFlightFirst.url} size={13}/>
                  </div>
                  {(() => {
                    const lbl = DELAY_SOURCE_LABELS[inFlightFirst.delay_source] || {};
                    return (
                      <div style={{display:'flex', gap: 16, fontFamily: HF.mono, fontSize: 11.5, color: HF.ink3, marginTop: 2, flexWrap:'wrap'}}>
                        <span>claimed <span style={{color: HF.ink2}}>{_fmtClockTime(inFlightFirst.claimed_at)}</span></span>
                        <span title={lbl.title || ''}>
                          throttle <span style={{color: HF.warnInk}}>{_fmtDelay(inFlightFirst.request_delay_s)}</span>
                          {lbl.suffix ? <span style={{color: HF.ink4}}> · {lbl.suffix}</span> : null}
                        </span>
                        {inFlightFirst.retry_count > 0 && (
                          <span>retries <span style={{color: HF.ink2}}>{inFlightFirst.retry_count}</span></span>
                        )}
                      </div>
                    );
                  })()}
                  <div style={{
                    position:'absolute', left:0, right:0, bottom:0, height: 3,
                    background: HF.accentSoft2,
                  }}>
                    <div style={{width:'40%', height:'100%', background: HF.accent, animation:'hfSweep 1.6s ease-in-out infinite'}}/>
                  </div>
                </>
              ) : (tabCounts.processing ?? 0) > 0 ? (
                <div style={{display:'flex', alignItems:'center', gap: 8, flex:1, color: HF.accentInk, fontFamily: HF.mono, fontSize: 12.5}}>
                  <HFDot tone="accent" pulse size={7}/>
                  {tabCounts.processing} URL{tabCounts.processing > 1 ? 's' : ''} processing · refreshing…
                </div>
              ) : (
                <div style={{display:'flex', alignItems:'center', justifyContent:'center', flex:1, color: HF.ink4, fontFamily: HF.mono, fontSize: 12.5}}>
                  {liveData ? 'between requests · waiting for next dispatch…' : 'loading…'}
                </div>
              )}
            </div>

            {/* Rate (last 60s) — done vs failed */}
            <div style={{display:'flex', flexDirection:'column', gap: 10}}>
              <div style={{fontSize: 10.5, fontWeight: 600, color: HF.ink4, letterSpacing: 0.6, textTransform:'uppercase'}}>
                Rate · last {liveRate.window_s}s
              </div>
              <div style={{display:'grid', gridTemplateColumns:'1fr 1fr', gap: 10, flex: 1}}>
                <div style={{
                  background: HF.okSoft, border: `1px solid ${HF.okBorder}`, borderRadius: HF.r2,
                  padding: '10px 12px',
                }}>
                  <div style={{fontFamily: HF.mono, fontSize: 24, fontWeight: 600, color: HF.okInk, fontVariantNumeric:'tabular-nums', lineHeight: 1}}>
                    {rateDone}
                  </div>
                  <div style={{fontFamily: HF.mono, fontSize: 11, color: HF.okInk, marginTop: 5}}>
                    done · {ratePerMin}/min
                  </div>
                </div>
                <div style={{
                  background: rateFailed > 0 ? HF.errSoft : HF.subtle,
                  border: `1px solid ${rateFailed > 0 ? HF.errBorder : HF.border}`, borderRadius: HF.r2,
                  padding: '10px 12px',
                }}>
                  <div style={{fontFamily: HF.mono, fontSize: 24, fontWeight: 600, color: rateFailed > 0 ? HF.errInk : HF.ink3, fontVariantNumeric:'tabular-nums', lineHeight: 1}}>
                    {rateFailed}
                  </div>
                  <div style={{fontFamily: HF.mono, fontSize: 11, color: rateFailed > 0 ? HF.errInk : HF.ink3, marginTop: 5}}>
                    failed{rateFailed > 0 ? ` · ${failPct}% rate` : ''}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </HFCard>
      )}

      {/* Failures card — grouped by error_reason from recent_failures */}
      {failureGroups.length > 0 && (
        <HFCard
          title="Failures"
          sub={`${failureGroups.reduce((a, g) => a + g.count, 0)} recent failure${failureGroups.reduce((a, g) => a + g.count, 0) === 1 ? '' : 's'} · grouped by reason`}
          action={<>
            <HFButton size="sm" variant="subtle" disabled={actionPending} onClick={() => retryRun(null)}>Retry all</HFButton>
            <HFButton size="sm" variant="subtle" onClick={() => applyGroupFilter(null)}>Open issues</HFButton>
          </>}
          style={{marginBottom: HF.gap}}
        >
          <div style={{padding: 0}}>
            {failureGroups.map((g, i) => {
              const isHttpErr = g.http != null && g.http >= 500;
              const tone = isHttpErr ? 'err' : 'warn';
              const tonebg = tone === 'err' ? HF.errSoft : HF.warnSoft;
              const tonefg = tone === 'err' ? HF.errInk : HF.warnInk;
              const toneb  = tone === 'err' ? HF.errBorder : HF.warnBorder;
              const open = expandedFailure === i;
              return (
                <div key={`${g.reason ?? '__null__'}|${g.http ?? '__null__'}`} style={{
                  borderTop: i === 0 ? 'none' : `1px solid ${HF.borderFaint}`,
                }}>
                  <div style={{
                    padding: `10px ${HF.cardP}px`,
                    display: 'grid', gridTemplateColumns: '1fr auto', gap: 14, alignItems: 'center',
                    cursor: 'pointer',
                    background: open ? HF.subtle : 'transparent',
                  }} onClick={() => setExpandedFailure(open ? -1 : i)}>
                    <div style={{display:'flex', alignItems:'center', gap: 10, minWidth: 0}}>
                      <span style={{
                        display:'inline-flex', alignItems:'center', justifyContent:'center',
                        width: 14, height: 14, color: HF.ink4, fontSize: 10,
                        transform: open ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 120ms',
                      }}>▶</span>
                      {g.http != null && (
                        <span style={{
                          display:'inline-flex', alignItems:'center', justifyContent:'center',
                          height: 22, padding: '0 8px',
                          background: tonebg, color: tonefg, border: `1px solid ${toneb}`,
                          borderRadius: 4, fontFamily: HF.mono, fontSize: 11.5, fontWeight: 600,
                        }}>{g.http}</span>
                      )}
                      <span style={{fontFamily: HF.mono, fontSize: 12.5, color: HF.ink, fontWeight: 600}}>
                        {g.reason_display ?? g.reason ?? 'unknown'}
                      </span>
                      <span style={{fontFamily: HF.mono, fontSize: 11.5, color: HF.ink3, fontVariantNumeric:'tabular-nums'}}>
                        × {g.count}
                      </span>
                      {g.recurring_in_runs > 0 && (
                        <span title={`This bucket also failed in ${g.recurring_in_runs} of the last 5 prior runs for this shop`} style={{
                          display:'inline-flex', alignItems:'center', gap: 4,
                          height: 20, padding: '0 7px',
                          background: HF.warnSoft, color: HF.warnInk,
                          border: `1px solid ${HF.warnBorder}`, borderRadius: 4,
                          fontFamily: HF.mono, fontSize: 11, fontWeight: 500,
                        }}>↻ recurring × {g.recurring_in_runs}</span>
                      )}
                    </div>
                    <div style={{display:'flex', gap: 6, alignItems:'center'}} onClick={(e)=>e.stopPropagation()}>
                      <HFButton size="sm" disabled={actionPending} onClick={() => retryRun(g)}>Retry group</HFButton>
                      <HFButton size="sm" variant="subtle" onClick={() => applyGroupFilter(g)}>Open issues</HFButton>
                    </div>
                  </div>
                  {open && (
                    <div style={{padding: `4px ${HF.cardP}px 14px`, paddingLeft: HF.cardP + 24}}>
                      <div style={{display:'flex', flexDirection:'column', gap: 3, marginBottom: 8}}>
                        {g.examples.map((u, j) => (
                          <div key={j} style={{fontFamily: HF.mono, fontSize: 11.5, color: HF.ink3, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>
                            <span style={{color: HF.ink5, marginRight: 6}}>·</span>{u}
                          </div>
                        ))}
                        {g.count > g.examples.length && (
                          <a href="#" onClick={(e)=>{e.preventDefault(); applyGroupFilter(g);}} style={{
                            fontFamily: HF.mono, fontSize: 11.5, color: HF.accentInk,
                            textDecoration: 'none', marginLeft: 12, marginTop: 2,
                          }}>+ {g.count - g.examples.length} more (view in History)</a>
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
      )}

      {/* Throughput chart — done/min, with Y-axis ticks scaled to history */}
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
            action={<div style={{display:'flex', gap:14, fontFamily:HF.mono, fontSize:11.5}}>
              <span style={{display:'flex', alignItems:'center', gap:5}}>
                <span style={{width:8, height:8, borderRadius:2, background:HF.ok}}/>
                <span style={{color:HF.ink3}}>done</span>
                <span style={{color:HF.ink2, fontWeight:600}}>
                  {throughputHistory.length > 0 ? `${throughputHistory[throughputHistory.length-1]}/min` : '—'}
                </span>
              </span>
              <span style={{display:'flex', alignItems:'center', gap:5}}>
                <span style={{width:8, height:8, borderRadius:2, background:HF.err}}/>
                <span style={{color:HF.ink3}}>failed</span>
                <span style={{color: rateFailed > 0 ? HF.errInk : HF.ink3, fontWeight:600}}>
                  {ratePerMinFailed}/min
                </span>
              </span>
            </div>}
            style={{marginBottom: HF.gap}}
          >
            <div style={{padding: HF.cardP}}>
              <div style={{display:'grid', gridTemplateColumns:'34px 1fr', gap: 8}}>
                <div style={{display:'flex', flexDirection:'column', justifyContent:'space-between', alignItems:'flex-end', fontFamily:HF.mono, fontSize:10.5, color:HF.ink4, fontVariantNumeric:'tabular-nums', height: 140, paddingRight: 4}}>
                  {yTicks.map(v => <span key={v}>{v}</span>)}
                </div>
                <div style={{minWidth: 0}}>
                  {throughputHistory.length > 1 ? (
                    <HFAreaChart data={throughputHistory} h={140}/>
                  ) : (
                    <div style={{height:140, display:'flex', alignItems:'center', justifyContent:'center', color:HF.ink4, fontSize:12}}>
                      {throughputHistory.length === 0 ? 'Waiting for first poll…' : 'Collecting samples…'}
                    </div>
                  )}
                  <div style={{display:'flex', justifyContent:'space-between', fontFamily:HF.mono, fontSize:10.5, color:HF.ink4, fontVariantNumeric:'tabular-nums', marginTop: 6}}>
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

      {/* History card — tabbed URL queue / discovered URL history */}
      {urlData && (urlData.source === 'live' || urlData.total > 0) && (
        <div ref={historyRef}>
        <HFCard
          title="History"
          sub={urlData.source === 'live'
            ? `${urlData.breakdown.done} done · ${urlData.breakdown.failed} failed · ${urlData.breakdown.pending.toLocaleString()} pending`
            : `${urlData.total.toLocaleString()} URLs from discovered_urls (live queue cleaned up at run finish)`}
          style={{ marginBottom: HF.gap }}
        >
          {urlData.source === 'live' && (
            <div style={{padding:`12px ${HF.cardP}px 0`}}>
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
                    background: HF.errSoft, border: `1px solid ${HF.errBorder}`,
                    borderRadius: 4, fontFamily: HF.mono, fontSize: 11.5, color: HF.errInk,
                  }}>
                    <span>failed{reasonLabel ? ` · ${reasonLabel}` : ''}{httpLabel ? ` · ${httpLabel}` : ''}</span>
                    <span onClick={clearGroupFilter} title="Clear group filter" style={{
                      cursor:'pointer', padding:'0 4px', color: HF.errInk, fontWeight: 600,
                    }}>×</span>
                  </div>
                );
              })()}
            </div>
          )}

          {urlData.rows.length === 0 ? (
            <div style={{padding:'24px', textAlign:'center', color:HF.ink3, fontSize:12.5}}>
              No URLs in this filter.
            </div>
          ) : (
            <div style={{padding:`4px 0`}}>
              <div style={{
                display:'grid',
                gridTemplateColumns: urlData.source === 'live'
                  ? '55px 1fr 85px 120px 80px 70px 70px 95px'
                  : '1fr 60px 70px 150px',
                padding:`8px ${HF.cardP}px`,
                borderBottom: `1px solid ${HF.border}`,
                fontSize: 11, fontFamily: HF.mono, fontWeight: 500,
                color: HF.ink3, textTransform: 'uppercase', letterSpacing: 0.4,
                gap: 10,
              }}>
                {(() => {
                  const SortHdr = ({ k, children, align }) => {
                    const active = urlSort === k;
                    const arrow = active ? (urlOrder === 'asc' ? ' ▲' : ' ▼') : '';
                    return (
                      <span
                        onClick={() => toggleSort(k)}
                        style={{
                          cursor: 'pointer',
                          color: active ? HF.accentInk : HF.ink3,
                          userSelect: 'none',
                          textAlign: align || 'left',
                        }}
                        title={`Sort by ${k}`}
                      >
                        {children}{arrow}
                      </span>
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
                      <span>Throttle</span>
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
                const tone = u.status === 'done' ? 'ok'
                  : u.status === 'failed' ? 'err'
                  : u.status === 'processing' ? 'accent'
                  : 'neutral';
                const http = u.http_status ?? u.last_http_status;
                const httpTone = http && http >= 400 ? 'err' : http ? 'ok' : 'neutral';
                const fmtDur = (ms) => {
                  if (ms == null) return '—';
                  if (ms < 1000) return `${ms}ms`;
                  return `${(ms / 1000).toFixed(1)}s`;
                };
                const statusCell = (() => {
                  if (urlData.source !== 'live') return null;
                  if (u.status === 'failed') {
                    return (
                      <span style={{display:'inline-flex', flexDirection:'column', gap:2, lineHeight:1.2}}>
                        <HFPill tone="err" style={{width:'fit-content'}}>failed{http ? ` · ${http}` : ''}</HFPill>
                        {u.error_reason && (
                          <span style={{fontFamily:HF.mono, fontSize:10.5, color:HF.errInk, paddingLeft:2}}>{u.error_reason}</span>
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
                      ? '55px 1fr 85px 120px 80px 70px 70px 95px'
                      : '1fr 60px 70px 150px',
                    padding:`7px ${HF.cardP}px`,
                    borderBottom: i < urlData.rows.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
                    fontSize:12.5, alignItems:'center', gap:10,
                  }}>
                    {urlData.source === 'live' && (
                      <span style={{fontFamily:HF.mono, fontSize:11, color:HF.accentInk, fontVariantNumeric:'tabular-nums', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}
                            title={`item #${u.item_id}`}>
                        {u.item_id ?? '—'}
                      </span>
                    )}
                    <span style={{display:'flex', alignItems:'center', gap:8, minWidth:0}}>
                      <span style={{display:'flex', flexDirection:'column', gap:2, minWidth:0, flex:1}}>
                        {u.title && (
                          u.shop_book_id != null ? (
                            <a href="#" onClick={(e)=>{e.preventDefault(); e.stopPropagation(); goto('shop-book-detail', {id: String(u.shop_book_id)});}}
                               title={u.title}
                               style={{display:'block', minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontSize:12.5, color:HF.accentInk, fontWeight:500, textDecoration:'none', cursor:'pointer'}}>
                              {u.title}
                            </a>
                          ) : (
                            <span style={{display:'block', minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontSize:12.5, color:HF.ink, fontWeight:500}} title={u.title}>{u.title}</span>
                          )
                        )}
                        {u.discovered_url_id != null ? (
                          <a href="#" onClick={(e)=>{e.preventDefault(); e.stopPropagation(); goto('url-detail', {id: String(u.discovered_url_id)});}}
                             title={u.url}
                             style={{display:'block', minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontFamily:HF.mono, fontSize: u.title ? 11 : 12, color:HF.accentInk, textDecoration:'none', cursor:'pointer'}}>
                            {u.url}
                          </a>
                        ) : (
                          <span style={{display:'block', minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', fontFamily:HF.mono, fontSize: u.title ? 11 : 12, color: u.title ? HF.ink4 : HF.ink}} title={u.url}>{u.url}</span>
                        )}
                      </span>
                      <HFExtLink href={u.url}/>
                    </span>
                    {urlData.source === 'live' ? (
                      <>
                        {/* Disc. URL — column 3, right after URL */}
                        {u.discovered_url_id != null ? (
                          <a href="#" onClick={(e)=>{e.preventDefault(); goto('url-detail', {id: String(u.discovered_url_id)});}}
                             style={{fontFamily:HF.mono, fontSize:11, color:HF.accentInk, fontVariantNumeric:'tabular-nums', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', textDecoration:'none'}}>
                            #{u.discovered_url_id}
                          </a>
                        ) : (
                          <span style={{fontFamily:HF.mono, fontSize:11, color:HF.ink5}}>—</span>
                        )}
                        {statusCell}
                        <span style={{fontFamily:HF.mono, fontSize:11, color:HF.ink4, fontVariantNumeric:'tabular-nums'}}>{u.claimed_at ? new Date(u.claimed_at).toLocaleTimeString() : '—'}</span>
                        <span style={{fontFamily:HF.mono, fontSize:11.5, color:HF.ink4}}>{u.url_type}</span>
                        <span style={{fontFamily:HF.mono, fontSize:11, color:HF.ink4, fontVariantNumeric:'tabular-nums'}}>{fmtDur(u.duration_ms)}</span>
                        {(() => {
                          const lbl = DELAY_SOURCE_LABELS[u.delay_source] || {};
                          return (
                            <span style={{fontFamily:HF.mono, fontSize:11, color:HF.ink4, fontVariantNumeric:'tabular-nums'}} title={lbl.title || ''}>
                              {_fmtDelay(u.request_delay_s)}
                              {lbl.suffix ? <span style={{color:HF.ink5}}> {lbl.suffix.slice(0,4)}</span> : null}
                            </span>
                          );
                        })()}
                      </>
                    ) : (
                      <>
                        <HFPill tone={httpTone} style={{width:'fit-content'}}>{u.last_http_status ?? '—'}</HFPill>
                        <span style={{fontFamily:HF.mono, fontSize:11.5, color:HF.ink4}}>{u.url_type}</span>
                        <span style={{fontFamily:HF.mono, fontSize:11, color:HF.ink4, fontVariantNumeric:'tabular-nums'}}>{u.last_checked_at ? new Date(u.last_checked_at).toLocaleString() : '—'}</span>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div style={{
            display:'flex', justifyContent:'space-between', alignItems:'center',
            padding:`10px ${HF.cardP}px`, borderTop:`1px solid ${HF.borderFaint}`,
            fontSize:12, color:HF.ink3, flexWrap:'wrap', gap:8,
          }}>
            <span style={{fontFamily:HF.mono, color:HF.ink4}}>
              {urlData.total.toLocaleString()} URLs
            </span>
            <div style={{display:'flex', gap:6, alignItems:'center', flexWrap:'wrap'}}>
              {(urlStatus !== 'all' || urlSort !== 'started' || urlOrder !== 'desc' || urlPage !== 1
                || urlReason || urlReasonIsNull || urlHttp != null || urlHttpIsNull) && (
                <HFButton size="sm" variant="ghost" onClick={() => {
                  setUrlStatus('all');
                  setUrlSort('started');
                  setUrlOrder('desc');
                  setUrlPage(1);
                  setUrlReason('');
                  setUrlReasonIsNull(false);
                  setUrlHttp(null);
                  setUrlHttpIsNull(false);
                }}>Clear</HFButton>
              )}
              <span style={{color:HF.ink4, fontSize:11.5, marginRight:2}}>Per page:</span>
              {[10, 25, 50, 100].map(n => (
                <HFButton key={n} size="sm"
                  variant={urlPerPage === n ? 'accent' : 'subtle'}
                  onClick={() => setUrlPerPage(n)}>
                  {n}
                </HFButton>
              ))}
              <span style={{width:1, height:18, background:HF.border, margin:'0 4px'}}/>
              <HFButton size="sm" variant="ghost" disabled={urlData.page <= 1}
                onClick={() => setUrlPage(p => Math.max(1, p - 1))}>‹</HFButton>
              {(() => {
                const cur = urlData.page, total = urlData.pages;
                const btns = [];
                const push = (n) => btns.push(
                  <HFButton key={n} size="sm"
                    variant={n === cur ? 'accent' : 'subtle'}
                    onClick={() => setUrlPage(n)}>{n}</HFButton>
                );
                const ell = (k) => btns.push(
                  <span key={k} style={{padding:'0 2px', color:HF.ink4}}>…</span>
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
                onClick={() => setUrlPage(p => Math.min(urlData.pages, p + 1))}>›</HFButton>
            </div>
          </div>
        </HFCard>
        </div>
      )}

      {/* Parameters */}
      <HFCard title="Parameters">
        <div style={{padding:`4px 0`}}>
          {[
            ['items_added', String(data.items_added ?? 0)],
            ['items_updated', String(data.items_updated ?? 0)],
            ['errors', `${data.errors ?? 0} (${data.errors_4xx ?? 0} · 4xx, ${data.errors_5xx ?? 0} · 5xx)`],
            ...(closeReason ? [['close_reason', closeReason]] : []),
          ].map(([k,v], i, arr) => (
            <div key={k} style={{
              display:'grid', gridTemplateColumns:'160px 1fr',
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
    </HFShell>
  );
}


Object.assign(window, { HFRuns, HFRunDetail });
