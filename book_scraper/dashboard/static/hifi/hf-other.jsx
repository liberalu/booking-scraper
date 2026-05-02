// Hi-fi Cron (schedules), Issues, Prices pages

function HFCron({ nav, goto }) {
  const HF = getHF();
  const [data, setData] = React.useState({ jobs: [] });
  const [loading, setLoading] = React.useState(true);

  const reload = React.useCallback(() => {
    fetch('/api/cron')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  React.useEffect(() => { reload(); }, [reload]);

  const toggleJob = async (job) => {
    try {
      await fetch(`/api/cron/${job.id}/toggle`, { method: 'POST' });
      reload();
    } catch (e) { console.error(e); }
  };

  const runJobNow = async (job) => {
    try {
      const body = { shop: job.shop, phase: job.phase, strategy: job.strategy || '', mode: 'delta' };
      const resp = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (resp.ok) goto('runs');
    } catch (e) { console.error(e); }
  };

  const jobsRaw = data.jobs;
  const jobs = jobsRaw.map(j => ({
    ...j,
    state: j.enabled ? 'active' : 'disabled',
    lastStatus: j.last_status || 'ok',
    next: j.next || '—',
    avgDur: j.avg_dur || '—',
  }));

  const filters = useHFFilters(jobs, {
    search: { fields: j => `${j.name} ${j.cron} ${j.shop}` },
    filters: [
      { id:'shop',  default:'all', match:(j,v) => j.shop === v },
      { id:'state', default:'all', match:(j,v) => j.state === v },
    ],
  });

  return (
    <HFShell {...nav} activePage="cron"
      title="Schedules" subtitle="Cron-driven scrape jobs. Disable, edit, or trigger manually."
      breadcrumb={<><span>BookScraper</span><span style={{color:'var(--hf-ink5)'}}>/</span><span style={{color:'var(--hf-ink)', fontWeight:500}}>Schedules</span></>}
      actions={<HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openNewSchedule()}><span style={{display:'flex'}}>{HF_ICONS.plus}</span> New schedule</HFButton>}
    >
      <HFKpiStrip items={[
        { label:'Schedules',   value: String(jobs.length), delta:<span style={{color:'var(--hf-ink3)'}}>{jobs.filter(j=>j.enabled).length} enabled</span> },
      ]}/>

      <HFCard style={{marginBottom:'var(--hf-gap)', overflow:"visible"}} padding={12}>
        <HFFilterBar right={<>
          <span style={{fontSize:12, color: filters.activeCount? 'var(--hf-accent-ink)' : 'var(--hf-ink4)', fontFamily:'var(--hf-mono)', fontVariantNumeric:'tabular-nums', fontWeight: filters.activeCount? 500 : 400}}>
            {filters.filtered.length} of {jobs.length}
          </span>
          {filters.activeCount > 0 && <HFButton size="sm" variant="subtle" onClick={filters.clearAll}>Clear ({filters.activeCount})</HFButton>}
        </>}>
          <HFSearch placeholder="Search jobs…" width={260} value={filters.q} onChange={filters.setQ}/>
          <HFFilter label="Shop"  value={filters.vals.shop}  options={['all','vaga','knygos','—']} onChange={v=>filters.setVal('shop',v)}/>
          <HFFilter label="State" value={filters.vals.state} options={['all','active','failing','disabled']} onChange={v=>filters.setVal('state',v)}/>
        </HFFilterBar>
      </HFCard>

      <HFCard>
        {filters.filtered.length === 0 ? (
          <HFEmptyState title="No schedules match" sub="Try clearing filters." onClear={filters.clearAll}/>
        ) : (
        <HFTable
          onRowClick={(r) => goto('schedule-detail', { id: r.id, name: r.name, cron: r.cron, shop: r.shop, enabled: r.enabled, lastStatus: r.lastStatus })}
          columns={[
            { key:'name', label:'Name', w:'1.8fr', mono:true, sortable:true, cell:(v,r) => <span style={{color: r.enabled? 'var(--hf-ink)' : 'var(--hf-ink4)', fontWeight:500}}>{v}</span> },
            { key:'cron', label:'Cron', w:'0.9fr', mono:true, muted:true, sortable:true },
            { key:'shop', label:'Shop', w:'0.6fr', sortable:true },
            { key:'lastStatus', label:'Last', w:'0.7fr', sortable:true, cell:(v,r) => <span style={{display:'inline-flex', alignItems:'center', gap:7}}><HFDot tone={v==='ok'?'ok':'err'}/> <span style={{color: v==='fail'? 'var(--hf-err-ink)' : 'var(--hf-ink)'}}>{r.last}</span></span> },
            { key:'next', label:'Next run', w:'0.8fr', mono:true, sortable:true, cell:(v,r) => <span style={{color: r.enabled? 'var(--hf-accent-ink)' : 'var(--hf-ink4)', fontWeight:500}}>{r.enabled? v : 'disabled'}</span> },
            { key:'avgDur', label:'Avg duration', w:'0.7fr', mono:true, muted:true, align:'right', sortable:true },
            { key:'enabled', label:'', w:'0.5fr', align:'right', cell:(v, r) => (
              <span
                onClick={(e) => { e.stopPropagation(); toggleJob(r); }}
                style={{
                  display:'inline-flex', width:32, height:18, borderRadius:10,
                  background: v? 'var(--hf-accent)' : 'var(--hf-border)', padding:2, alignItems:'center',
                  justifyContent: v? 'flex-end' : 'flex-start', transition:'all 120ms',
                  cursor:'pointer',
                }}>
                <span style={{width:14, height:14, borderRadius:'50%', background:'#fff', boxShadow:'0 1px 2px rgba(0,0,0,.2)'}}/>
              </span>
            )},
            { key:'_', label:'', w:'40px', align:'right', cell:(_v, r) => (
              <HFButton size="sm" variant="subtle" onClick={(e) => { e.stopPropagation(); runJobNow(r); }}>
                <span style={{display:'flex'}}>{HF_ICONS.play}</span>
              </HFButton>
            )},
          ]}
          rows={filters.filtered}
        />
        )}
      </HFCard>
    </HFShell>
  );
}

// ─────────────────────────────── Issues ───────────────────────────────

function HFIssues({ nav, goto }) {
  const HF = getHF();
  const [tab, setTab] = React.useState('open');
  const [page, setPage] = React.useState(1);
  const PER_PAGE = 30;
  const [data, setData] = React.useState({
    issues: [], total: 0, page: 1, per_page: PER_PAGE, pages: 1,
    counts: { new: 0, recurring: 0, already_seen: 0, open: 0 },
  });
  const [loading, setLoading] = React.useState(true);

  // Server-side filters — changes trigger a fresh API fetch
  const [runIdInput, setRunIdInput] = React.useState(() =>
    new URLSearchParams(window.location.search).get('run_id') || ''
  );
  const [urlTypeFilter, setUrlTypeFilter] = React.useState('all');
  const [bookTypeFilter, setBookTypeFilter] = React.useState('all');

  const runId = parseInt(runIdInput, 10) > 0 ? parseInt(runIdInput, 10) : null;

  // Reset to page 1 when any filter or tab changes.
  React.useEffect(() => { setPage(1); }, [tab, runId, urlTypeFilter, bookTypeFilter]);

  React.useEffect(() => {
    let cancelled = false;
    const stateParam = tab === 'known' ? 'already_seen' : tab === 'all' ? '' : tab;
    const params = new URLSearchParams({ state: stateParam, page: String(page), per_page: String(PER_PAGE), kind: 'validation' });
    if (runId) params.set('run_id', String(runId));
    if (urlTypeFilter && urlTypeFilter !== 'all') params.set('url_type', urlTypeFilter);
    if (bookTypeFilter && bookTypeFilter !== 'all') params.set('book_type', bookTypeFilter);
    fetch(`/api/issues?${params.toString()}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tab, page, runId, urlTypeFilter, bookTypeFilter]);

  const seed = data.issues.map(i => ({
    id: `ISS-${i.id}`,
    type: i.issue,
    sev: i.severity === 'critical' ? 'high' : i.severity === 'warning' ? 'medium' : 'low',
    shop: '—',
    book: i.shop_book_title || '—',
    url: i.url || '—',
    url_type: i.url_type || '—',
    run_id: i.scrape_run_id,
    detail: i.description || i.raw_value || '—',
    age: i.added_ago,
    known: i.lifecycle_state === 'already_seen',
  }));

  // Persist known state + selection in component state (prototype — resets on reload).
  const [knownMap, setKnownMap] = React.useState({});
  const [selected, setSelected] = React.useState(() => new Set());

  const allIssues = React.useMemo(
    () => seed.map(r => ({ ...r, known: !!knownMap[r.id] })),
    [knownMap, seed]
  );

  const sevTone = { high:'err', medium:'warn', low:'neutral' };

  const tabSource = allIssues;  // API already filtered by tab

  const byTab = {
    open:     data.counts.open || 0,
    triage:   0,
    known:    data.counts.already_seen || 0,
    snoozed:  0,
    resolved: 0,
    all:      data.total || 0,
  };

  // When tab changes, clear selection (selection is only meaningful within a tab).
  React.useEffect(() => { setSelected(new Set()); }, [tab]);

  const filters = useHFFilters(tabSource, {
    search: { fields: i => `${i.id} ${i.type} ${i.book} ${i.url} ${i.detail} ${i.shop}` },
    filters: [
      { id:'sev',  default:'all', match:(i,v) => i.sev === v },
      { id:'shop', default:'all', match:(i,v) => i.shop === v },
      { id:'type', default:'all', match:(i,v) => i.type === v },
    ],
  });

  const typeOptions = ['all', ...Array.from(new Set(allIssues.map(i => i.type)))];

  const toggleOne = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const toggleAllVisible = () => {
    const visibleIds = filters.filtered.map(r => r.id);
    const allOn = visibleIds.every(id => selected.has(id));
    setSelected(prev => {
      const next = new Set(prev);
      if (allOn) visibleIds.forEach(id => next.delete(id));
      else visibleIds.forEach(id => next.add(id));
      return next;
    });
  };
  const markSelected = (asKnown) => {
    setKnownMap(prev => {
      const next = { ...prev };
      selected.forEach(id => { next[id] = asKnown; });
      return next;
    });
    setSelected(new Set());
  };
  const clearSelection = () => setSelected(new Set());

  const allVisibleSelected = filters.filtered.length > 0 &&
    filters.filtered.every(r => selected.has(r.id));
  const someVisibleSelected = filters.filtered.some(r => selected.has(r.id));

  const selectedCount = selected.size;
  const selectedAreKnown = tab === 'known';   // if we're in Known tab, bulk action is "Mark open"

  // Checkbox cell component (prevents row click, controls selection)
  const CheckCell = ({ id, checked }) => (
    <span
      onClick={(e) => { e.stopPropagation(); toggleOne(id); }}
      style={{ display:'flex', alignItems:'center', justifyContent:'center', cursor:'pointer', padding:2 }}
    >
      <span style={{
        width:14, height:14, borderRadius:3,
        border:`1.5px solid ${checked ? 'var(--hf-accent-ink)' : 'var(--hf-ink5)'}`,
        background: checked ? 'var(--hf-accent-ink)' : 'transparent',
        display:'flex', alignItems:'center', justifyContent:'center',
        transition:'all 0.12s',
      }}>
        {checked && (
          <svg width="9" height="9" viewBox="0 0 10 10" fill="none">
            <path d="M2 5.5L4 7.5L8 2.5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        )}
      </span>
    </span>
  );

  // Header checkbox (select-all-visible, indeterminate state)
  const HeaderCheck = () => {
    const state = allVisibleSelected ? 'all' : someVisibleSelected ? 'some' : 'none';
    return (
      <span
        onClick={(e) => { e.stopPropagation(); toggleAllVisible(); }}
        style={{ display:'flex', alignItems:'center', justifyContent:'center', cursor:'pointer', padding:2 }}
        title={allVisibleSelected ? 'Deselect all' : 'Select all visible'}
      >
        <span style={{
          width:14, height:14, borderRadius:3,
          border:`1.5px solid ${state !== 'none' ? 'var(--hf-accent-ink)' : 'var(--hf-ink5)'}`,
          background: state !== 'none' ? 'var(--hf-accent-ink)' : 'transparent',
          display:'flex', alignItems:'center', justifyContent:'center',
        }}>
          {state === 'all' && (
            <svg width="9" height="9" viewBox="0 0 10 10" fill="none">
              <path d="M2 5.5L4 7.5L8 2.5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          )}
          {state === 'some' && (
            <span style={{width:7, height:1.8, background:'#fff', borderRadius:1}}/>
          )}
        </span>
      </span>
    );
  };

  // Dim the contents of known rows inline
  const dimIfKnown = (row, node) => row.known
    ? <span style={{ opacity: 0.48 }}>{node}</span>
    : node;

  return (
    <HFShell {...nav} activePage="issues"
      title={<span style={{display:'flex', alignItems:'center', gap:10}}>
        Issues
        {runId && <HFPill tone="accent"><span style={{fontFamily:'var(--hf-mono)', fontSize:11}}>run #{runId}</span></HFPill>}
        {urlTypeFilter !== 'all' && <HFPill tone="warn"><span style={{fontFamily:'var(--hf-mono)', fontSize:11}}>{urlTypeFilter}</span></HFPill>}
        {bookTypeFilter !== 'all' && <HFPill tone="neutral"><span style={{fontFamily:'var(--hf-mono)', fontSize:11}}>{bookTypeFilter}</span></HFPill>}
      </span>}
      subtitle="Individual validation failures, parser errors, and data-quality events across all shops."
      breadcrumb={<><span>BookScraper</span><span style={{color:'var(--hf-ink5)'}}>/</span><span style={{color:'var(--hf-ink)', fontWeight:500}}>Issues</span></>}
      actions={<>
        {(runId || urlTypeFilter !== 'all' || bookTypeFilter !== 'all') && (
          <HFButton size="sm" variant="subtle" onClick={() => { setRunIdInput(''); setUrlTypeFilter('all'); setBookTypeFilter('all'); }}>
            Clear filters
          </HFButton>
        )}
        <HFButton>Assign</HFButton><HFButton variant="primary">Mark resolved</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Open',      value: String(byTab.open), delta:<span style={{color:'var(--hf-err-ink)'}}>open</span>, tone: byTab.open > 0 ? 'err' : 'ok' },
        { label:'Known',     value: String(byTab.known), delta:<span style={{color:'var(--hf-ink3)'}}>acknowledged</span> },
      ]}/>

      <HFCard style={{marginBottom:'var(--hf-gap)'}}>
        <div style={{padding:`0 var(--hf-card-p)`}}>
          <HFTabs active={tab} onChange={setTab} tabs={[
            { id:'open', label:'Open', count: byTab.open },
            { id:'triage', label:'Needs triage' },
            { id:'known', label:'Known', count: byTab.known },
            { id:'snoozed', label:'Snoozed' },
            { id:'resolved', label:'Resolved' },
            { id:'all', label:'All', count: byTab.all },
          ]}/>
        </div>
      </HFCard>

      {/* Bulk action bar — replaces filter bar when ≥1 selected */}
      {selectedCount > 0 ? (
        <HFCard style={{marginBottom:'var(--hf-gap)', background:'var(--hf-accent-soft)', border:`1px solid ${'var(--hf-accent-border)'}`}} padding={12}>
          <div style={{display:'flex', alignItems:'center', gap:12, padding:'2px 4px'}}>
            <span style={{
              display:'inline-flex', alignItems:'center', justifyContent:'center',
              width:22, height:22, borderRadius:4, background:'var(--hf-accent-ink)', color:'#fff',
              fontFamily:'var(--hf-mono)', fontSize:11, fontWeight:600, fontVariantNumeric:'tabular-nums',
            }}>{selectedCount}</span>
            <span style={{fontSize:13, color:'var(--hf-ink)', fontWeight:500}}>
              {selectedCount === 1 ? '1 issue' : `${selectedCount} issues`} selected
            </span>
            <span style={{flex:1}}/>
            {selectedAreKnown ? (
              <HFButton size="sm" variant="primary" onClick={() => markSelected(false)}>
                Move back to Open
              </HFButton>
            ) : (
              <HFButton size="sm" variant="primary" onClick={() => markSelected(true)}>
                Mark as known
              </HFButton>
            )}
            <HFButton size="sm">Assign…</HFButton>
            <HFButton size="sm">Snooze 7d</HFButton>
            <HFButton size="sm" variant="subtle" onClick={clearSelection}>Clear selection</HFButton>
          </div>
        </HFCard>
      ) : (
        <HFCard style={{marginBottom:'var(--hf-gap)', overflow:"visible"}} padding={12}>
          <HFFilterBar right={<>
            <span style={{fontSize:12, color: filters.activeCount? 'var(--hf-accent-ink)' : 'var(--hf-ink4)', fontFamily:'var(--hf-mono)', fontVariantNumeric:'tabular-nums', fontWeight: filters.activeCount? 500 : 400}}>
              {data.total.toLocaleString()} total
            </span>
            {filters.activeCount > 0 && <HFButton size="sm" variant="subtle" onClick={filters.clearAll}>Clear ({filters.activeCount})</HFButton>}
          </>}>
            <HFSearch placeholder="Search ID, book, URL, detail…" width={260} value={filters.q} onChange={filters.setQ}/>
            <HFFilter label="Severity" value={filters.vals.sev}  options={['all','high','medium','low']} onChange={v=>filters.setVal('sev',v)}/>
            <HFFilter label="Type"     value={filters.vals.type} options={typeOptions}                   onChange={v=>filters.setVal('type',v)}/>
            <HFFilter label="URL type" value={urlTypeFilter} options={['all','product','non_product','unreachable']} onChange={setUrlTypeFilter}/>
            <HFFilter label="Book type" value={bookTypeFilter} options={['all','book','non_book','audio','ebook']} onChange={setBookTypeFilter}/>
            <div style={{display:'flex', alignItems:'center', gap:6}}>
              <span style={{fontSize:12, color:'var(--hf-ink4)', whiteSpace:'nowrap'}}>Run</span>
              <input
                type="number"
                placeholder="any"
                value={runIdInput}
                onChange={e => setRunIdInput(e.target.value)}
                style={{
                  width:80, height:30, padding:'0 8px',
                  border:`1px solid ${'var(--hf-border-strong)'}`, borderRadius:6,
                  background:'var(--hf-surface)', color:'var(--hf-ink)',
                  fontFamily:'var(--hf-mono)', fontSize:12,
                  outline:'none',
                }}
              />
            </div>
          </HFFilterBar>
        </HFCard>
      )}

      <HFCard>
        {filters.filtered.length === 0 ? (
          <HFEmptyState
            title={
              tab === 'known'    ? 'No known issues yet' :
              tab === 'snoozed'  ? 'No snoozed issues' :
              tab === 'resolved' ? 'Resolved issues appear here' :
              'No issues match these filters'
            }
            sub={
              tab === 'known'   ? 'Tick an issue\u2019s checkbox and click "Mark as known" to acknowledge it as expected.' :
              tab === 'snoozed' ? 'Snooze an issue to hide it until later.' :
              'Try clearing filters or switching tabs.'
            }
            onClear={filters.activeCount > 0 ? filters.clearAll : undefined}
          />
        ) : (
        <HFTable
          onRowClick={(r) => goto('issue-detail', { type: r.type, sev: r.sev, id: r.id, book: r.book, url: r.url, shop: r.shop })}
          columns={[
            { key:'_chk',  label:(<HeaderCheck/>), w:'36px', align:'center',
              cell:(_, r) => <CheckCell id={r.id} checked={selected.has(r.id)}/> },
            { key:'id',   label:'ID',       w:'0.7fr', mono:true, sortable:true,
              cell:(v, r) => dimIfKnown(r, <span style={{color:'var(--hf-ink3)', fontVariantNumeric:'tabular-nums'}}>{v}</span>) },
            { key:'sev',  label:'Severity', w:'0.75fr', sortable:true, sortVal:r=>({high:3,medium:2,low:1}[r.sev]||0),
              cell:(v, r) => dimIfKnown(r, <span style={{display:'inline-flex', alignItems:'center', gap:6}}>
                <HFPill tone={sevTone[v]}>{v}</HFPill>
                {r.known && <HFPill tone="neutral">known</HFPill>}
              </span>) },
            { key:'type', label:'Type',     w:'1fr',   mono:true, sortable:true,
              cell:(v, r) => dimIfKnown(r, <span style={{color:'var(--hf-ink2)'}}>{v}</span>) },
            { key:'shop', label:'Shop',     w:'0.6fr', sortable:true, muted:true, mono:true,
              cell:(v, r) => dimIfKnown(r, <span style={{color:'var(--hf-ink3)'}}>{v}</span>) },
            { key:'book', label:'Book',     w:'1.3fr', sortable:true,
              cell:(v, r) => dimIfKnown(r, v === '—' ? <span style={{color:'var(--hf-ink4)'}}>—</span> : <span style={{color:'var(--hf-ink)', fontWeight:500}}>{v}</span>) },
            { key:'url',  label:'URL',      w:'1.2fr', mono:true, muted:true,
              cell:(v, r) => dimIfKnown(r, <span style={{color:'var(--hf-ink3)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', display:'block'}}>{v}</span>) },
            { key:'detail', label:'Detail', w:'1.6fr',
              cell:(v, r) => dimIfKnown(r, <span style={{color:'var(--hf-ink2)', fontSize:13}}>{v}</span>) },
            { key:'age',  label:'When',     w:'0.8fr', mono:true, muted:true, sortable:true,
              cell:(v, r) => dimIfKnown(r, <span style={{color:'var(--hf-ink3)'}}>{v}</span>) },
            { key:'_',    label:'',         w:'28px',  align:'right', cell:() => <span style={{color:'var(--hf-ink4)', display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
          ]}
          rows={filters.filtered}
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

// ─────────────────────────────── Prices ───────────────────────────────

function HFPrices({ nav, goto }) {
  const HF = getHF();
  const [page, setPage] = React.useState(1);
  const [days, setDays] = React.useState(7);
  const [shop, setShop] = React.useState('all');
  const [dir, setDir]   = React.useState('all');
  const [q, setQ]       = React.useState('');
  const PER_PAGE = 30;
  const [data, setData] = React.useState({ changes: [], total: 0, page: 1, per_page: PER_PAGE, pages: 1 });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => { setPage(1); }, [days, shop, dir, q]);

  React.useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({ days: String(days), page: String(page), per_page: String(PER_PAGE) });
    if (shop !== 'all') params.set('shop', shop);
    fetch(`/api/prices?${params.toString()}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [days, shop, page]);

  const allRows = data.changes.map(c => ({
    id: c.shop_book_id,
    title: c.title,
    prev: c.prev_price !== null ? `€${Number(c.prev_price).toFixed(2)}` : '—',
    now: c.new_price !== null ? `€${Number(c.new_price).toFixed(2)}` : '—',
    pct: c.prev_price && c.prev_price !== 0 ? ((c.change / c.prev_price) * 100) : 0,
    absChg: c.change,
    when: c.scraped_ago,
    date: c.scraped_at ? c.scraped_at.slice(0, 10) : '—',
    shop: c.shop || '—',
  }));

  const rows = allRows.filter(r => {
    if (q.trim() && !r.title?.toLowerCase().includes(q.trim().toLowerCase())) return false;
    if (dir === 'drop' && r.pct >= 0) return false;
    if (dir === 'rise' && r.pct <= 0) return false;
    return true;
  });

  const drops = allRows.filter(r => r.pct < 0).length;
  const rises = allRows.filter(r => r.pct > 0).length;
  const biggestDrop = allRows.reduce((best, r) => r.pct < (best?.pct ?? 0) ? r : best, null);
  const biggestRise = allRows.reduce((best, r) => r.pct > (best?.pct ?? 0) ? r : best, null);

  // sparkline: % changes as bar heights
  const pctVals = allRows.map(r => r.pct).filter(v => v !== 0);

  return (
    <HFShell {...nav} activePage="prices"
      title="Prices" subtitle="Price movements across all scraped listings."
      breadcrumb={<><span>BookScraper</span><span style={{color:'var(--hf-ink5)'}}>/</span><span style={{color:'var(--hf-ink)', fontWeight:500}}>Prices</span></>}
      actions={<>
        <HFSegmented value={String(days)} onChange={v => setDays(Number(v))} options={[
          {value:'7',label:'7d'},{value:'14',label:'14d'},{value:'30',label:'30d'},{value:'90',label:'90d'},
        ]}/>
      </>}
    >
      <HFKpiStrip items={[
        { label:'Changes', value:(data.total||0).toLocaleString(), delta:<span style={{color:'var(--hf-ink3)'}}>last {days}d</span> },
        { label:'Price drops', value:String(drops), tone: drops>0?'err':undefined, delta:<span style={{color:'var(--hf-err-ink)'}}>{drops>0?'↓ cheaper':''}</span>,
          onClick: ()=>setDir('drop') },
        { label:'Price rises', value:String(rises), tone: rises>0?'ok':undefined, delta:<span style={{color:'var(--hf-ok-ink)'}}>{rises>0?'↑ pricier':''}</span>,
          onClick: ()=>setDir('rise') },
        ...(biggestDrop ? [{ label:'Biggest drop', value:`${Math.round(biggestDrop.pct)}%`, tone:'err',
          delta:<span style={{color:'var(--hf-ink3)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', maxWidth:120, display:'block'}}>{biggestDrop.title}</span>,
          onClick: ()=>goto('shop-book-detail',{id:biggestDrop.id}) }] : []),
        ...(biggestRise ? [{ label:'Biggest rise', value:`+${Math.round(biggestRise.pct)}%`, tone:'ok',
          delta:<span style={{color:'var(--hf-ink3)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', maxWidth:120, display:'block'}}>{biggestRise.title}</span>,
          onClick: ()=>goto('shop-book-detail',{id:biggestRise.id}) }] : []),
      ]}/>

      <HFCard style={{marginBottom:'var(--hf-gap)'}}>
        <div style={{padding:`10px var(--hf-card-p)`, borderBottom:`1px solid ${'var(--hf-border-faint)'}`}}>
          <HFFilterBar right={<>
            <span style={{fontSize:12, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)', fontVariantNumeric:'tabular-nums'}}>
              {rows.length} of {allRows.length}
            </span>
            {(dir!=='all' || q.trim()) && <HFButton size="sm" variant="subtle" onClick={()=>{setDir('all');setQ('');}}>Clear</HFButton>}
          </>}>
            <HFSearch placeholder="Search book…" width={260} value={q} onChange={setQ}/>
            <HFFilter label="Shop"      value={shop} options={['all','vaga','knygos']}   onChange={setShop}/>
            <HFFilter label="Direction" value={dir}  options={['all','drop','rise']}     onChange={setDir}/>
          </HFFilterBar>
        </div>
        {loading && rows.length === 0 ? (
          <div style={{padding:'40px 20px', textAlign:'center', color:'var(--hf-ink3)'}}>Loading…</div>
        ) : rows.length === 0 ? (
          <HFEmptyState title="No price changes" sub={`No price movements in the last ${days} days.`} onClear={null}/>
        ) : (
        <HFTable
          onRowClick={r => goto('shop-book-detail', { id: r.id })}
          columns={[
            { key:'id',   label:'ID',   w:'0.45fr', mono:true, muted:true, sortable:true,
              cell:v => <span style={{color:'var(--hf-ink4)', fontVariantNumeric:'tabular-nums'}}>{v}</span> },
            { key:'title', label:'Book', w:'2.5fr', sortable:true, cell:(v,r) => (
              <span style={{display:'flex', flexDirection:'column', gap:2}}>
                <span style={{color:'var(--hf-ink)', fontWeight:500, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{v}</span>
                <span style={{fontSize:11, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)'}}>{r.shop}</span>
              </span>
            )},
            { key:'prev', label:'Was', w:'0.7fr', mono:true, align:'right', muted:true, sortable:true },
            { key:'now',  label:'Now', w:'0.7fr', mono:true, align:'right', sortable:true, cell:v => <span style={{fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v}</span> },
            { key:'pct',  label:'Δ %', w:'0.65fr', mono:true, align:'right', sortable:true, sortVal:r=>r.pct, cell:v => {
              const rounded = Math.round(v * 10) / 10;
              return <span style={{color: v<0?'var(--hf-err-ink)':v>0?'var(--hf-ok-ink)':'var(--hf-ink3)', fontWeight:600, fontVariantNumeric:'tabular-nums'}}>
                {v>0?'+':''}{rounded.toFixed(1)}%
              </span>;
            }},
            { key:'date', label:'Date', w:'0.85fr', mono:true, muted:true, sortable:true },
            { key:'when', label:'When', w:'0.9fr', mono:true, muted:true, sortable:true },
            { key:'_', label:'', w:'28px', align:'right', cell:() => <span style={{color:'var(--hf-ink4)', display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
          ]}
          rows={rows}
        />
        )}
      </HFCard>

      {(data.total || 0) > 0 && (
        <div style={{display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:14, fontSize:13, color:'var(--hf-ink3)'}}>
          <span>
            Showing {((data.page-1)*data.per_page+1).toLocaleString()}–
            {Math.min(data.page*data.per_page, data.total).toLocaleString()} of {data.total.toLocaleString()}
          </span>
          {data.pages > 1 && (
            <div style={{display:'flex', gap:6}}>
              <HFButton size="sm" variant="ghost" onClick={()=>setPage(p=>Math.max(1,p-1))} disabled={data.page<=1}>
                <span style={{display:'flex', transform:'rotate(180deg)'}}>{HF_ICONS.chevron}</span> Prev
              </HFButton>
              <HFButton size="sm" variant="ghost" onClick={()=>setPage(p=>Math.min(data.pages,p+1))} disabled={data.page>=data.pages}>
                Next <span style={{display:'flex'}}>{HF_ICONS.chevron}</span>
              </HFButton>
            </div>
          )}
        </div>
      )}
    </HFShell>
  );
}

Object.assign(window, { HFCron, HFIssues, HFPrices });
