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
    next: '—',
    avgDur: '—',
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
      breadcrumb={<><span>BookScraper</span><span style={{color:HF.ink5}}>/</span><span style={{color:HF.ink, fontWeight:500}}>Schedules</span></>}
      actions={<HFButton variant="primary" onClick={() => window.HF_APP && window.HF_APP.openNewSchedule()}><span style={{display:'flex'}}>{HF_ICONS.plus}</span> New schedule</HFButton>}
    >
      <HFKpiStrip items={[
        { label:'Schedules',   value: String(jobs.length), delta:<span style={{color:HF.ink3}}>{jobs.filter(j=>j.enabled).length} enabled</span> },
      ]}/>

      <HFCard style={{marginBottom:HF.gap, overflow:"visible"}} padding={12}>
        <HFFilterBar right={<>
          <span style={{fontSize:11.5, color: filters.activeCount? HF.accentInk : HF.ink4, fontFamily:HF.mono, fontVariantNumeric:'tabular-nums', fontWeight: filters.activeCount? 500 : 400}}>
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
          onRowClick={(r) => goto('schedule-detail', { name: r.name, cron: r.cron, shop: r.shop, enabled: r.enabled, lastStatus: r.lastStatus })}
          columns={[
            { key:'name', label:'Name', w:'1.8fr', mono:true, sortable:true, cell:(v,r) => <span style={{color: r.enabled? HF.ink : HF.ink4, fontWeight:500}}>{v}</span> },
            { key:'cron', label:'Cron', w:'0.9fr', mono:true, muted:true, sortable:true },
            { key:'shop', label:'Shop', w:'0.6fr', sortable:true },
            { key:'lastStatus', label:'Last', w:'0.7fr', sortable:true, cell:(v,r) => <span style={{display:'inline-flex', alignItems:'center', gap:7}}><HFDot tone={v==='ok'?'ok':'err'}/> <span style={{color: v==='fail'? HF.errInk : HF.ink}}>{r.last}</span></span> },
            { key:'next', label:'Next run', w:'0.8fr', mono:true, sortable:true, cell:(v,r) => <span style={{color: r.enabled? HF.accentInk : HF.ink4, fontWeight:500}}>{r.enabled? v : 'disabled'}</span> },
            { key:'avgDur', label:'Avg duration', w:'0.7fr', mono:true, muted:true, align:'right', sortable:true },
            { key:'enabled', label:'', w:'0.5fr', align:'right', cell:(v, r) => (
              <span
                onClick={(e) => { e.stopPropagation(); toggleJob(r); }}
                style={{
                  display:'inline-flex', width:32, height:18, borderRadius:10,
                  background: v? HF.accent : HF.border, padding:2, alignItems:'center',
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
  const [data, setData] = React.useState({ issues: [], total: 0, counts: { new: 0, recurring: 0, already_seen: 0, open: 0 } });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    const stateParam = tab === 'known' ? 'already_seen' : tab === 'all' ? '' : tab;
    fetch(`/api/issues?state=${stateParam}&per_page=100`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [tab]);

  const seed = data.issues.map(i => ({
    id: `ISS-${i.id}`,
    type: i.issue,
    sev: i.severity === 'critical' ? 'high' : i.severity === 'warning' ? 'medium' : 'low',
    shop: '—',
    book: i.shop_book_title || '—',
    url: i.url || '—',
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
        border:`1.5px solid ${checked ? HF.accentInk : HF.ink5}`,
        background: checked ? HF.accentInk : 'transparent',
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
          border:`1.5px solid ${state !== 'none' ? HF.accentInk : HF.ink5}`,
          background: state !== 'none' ? HF.accentInk : 'transparent',
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
      title="Issues" subtitle="Individual validation failures, parser errors, and data-quality events across all shops."
      breadcrumb={<><span>BookScraper</span><span style={{color:HF.ink5}}>/</span><span style={{color:HF.ink, fontWeight:500}}>Issues</span></>}
      actions={<><HFButton>Assign</HFButton><HFButton variant="primary">Mark resolved</HFButton></>}
    >
      <HFKpiStrip items={[
        { label:'Open',      value: String(byTab.open), delta:<span style={{color:HF.errInk}}>open</span>, tone: byTab.open > 0 ? 'err' : 'ok' },
        { label:'Known',     value: String(byTab.known), delta:<span style={{color:HF.ink3}}>acknowledged</span> },
      ]}/>

      <HFCard style={{marginBottom:HF.gap}}>
        <div style={{padding:`0 ${HF.cardP}px`}}>
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
        <HFCard style={{marginBottom:HF.gap, background:HF.accentSoft, border:`1px solid ${HF.accentBorder}`}} padding={12}>
          <div style={{display:'flex', alignItems:'center', gap:12, padding:'2px 4px'}}>
            <span style={{
              display:'inline-flex', alignItems:'center', justifyContent:'center',
              width:22, height:22, borderRadius:4, background:HF.accentInk, color:'#fff',
              fontFamily:HF.mono, fontSize:11, fontWeight:600, fontVariantNumeric:'tabular-nums',
            }}>{selectedCount}</span>
            <span style={{fontSize:12.5, color:HF.ink, fontWeight:500}}>
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
        <HFCard style={{marginBottom:HF.gap, overflow:"visible"}} padding={12}>
          <HFFilterBar right={<>
            <span style={{fontSize:11.5, color: filters.activeCount? HF.accentInk : HF.ink4, fontFamily:HF.mono, fontVariantNumeric:'tabular-nums', fontWeight: filters.activeCount? 500 : 400}}>
              {filters.filtered.length} of {tabSource.length}
            </span>
            {filters.activeCount > 0 && <HFButton size="sm" variant="subtle" onClick={filters.clearAll}>Clear ({filters.activeCount})</HFButton>}
          </>}>
            <HFSearch placeholder="Search ID, book, URL, detail…" width={320} value={filters.q} onChange={filters.setQ}/>
            <HFFilter label="Severity" value={filters.vals.sev}  options={['all','high','medium','low']} onChange={v=>filters.setVal('sev',v)}/>
            <HFFilter label="Shop"     value={filters.vals.shop} options={['all','vaga','knygos']}       onChange={v=>filters.setVal('shop',v)}/>
            <HFFilter label="Type"     value={filters.vals.type} options={typeOptions}                   onChange={v=>filters.setVal('type',v)}/>
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
              cell:(v, r) => dimIfKnown(r, <span style={{color:HF.ink3, fontVariantNumeric:'tabular-nums'}}>{v}</span>) },
            { key:'sev',  label:'Severity', w:'0.75fr', sortable:true, sortVal:r=>({high:3,medium:2,low:1}[r.sev]||0),
              cell:(v, r) => dimIfKnown(r, <span style={{display:'inline-flex', alignItems:'center', gap:6}}>
                <HFPill tone={sevTone[v]}>{v}</HFPill>
                {r.known && <HFPill tone="neutral">known</HFPill>}
              </span>) },
            { key:'type', label:'Type',     w:'1fr',   mono:true, sortable:true,
              cell:(v, r) => dimIfKnown(r, <span style={{color:HF.ink2}}>{v}</span>) },
            { key:'shop', label:'Shop',     w:'0.6fr', sortable:true, muted:true, mono:true,
              cell:(v, r) => dimIfKnown(r, <span style={{color:HF.ink3}}>{v}</span>) },
            { key:'book', label:'Book',     w:'1.3fr', sortable:true,
              cell:(v, r) => dimIfKnown(r, v === '—' ? <span style={{color:HF.ink4}}>—</span> : <span style={{color:HF.ink, fontWeight:500}}>{v}</span>) },
            { key:'url',  label:'URL',      w:'1.2fr', mono:true, muted:true,
              cell:(v, r) => dimIfKnown(r, <span style={{color:HF.ink3, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', display:'block'}}>{v}</span>) },
            { key:'detail', label:'Detail', w:'1.6fr',
              cell:(v, r) => dimIfKnown(r, <span style={{color:HF.ink2, fontSize:12.5}}>{v}</span>) },
            { key:'age',  label:'When',     w:'0.8fr', mono:true, muted:true, sortable:true,
              cell:(v, r) => dimIfKnown(r, <span style={{color:HF.ink3}}>{v}</span>) },
            { key:'_',    label:'',         w:'28px',  align:'right', cell:() => <span style={{color:HF.ink4, display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
          ]}
          rows={filters.filtered}
        />
        )}
      </HFCard>
    </HFShell>
  );
}

// ─────────────────────────────── Prices ───────────────────────────────

function HFPrices({ nav, goto }) {
  const HF = getHF();
  const [data, setData] = React.useState({ changes: [] });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch('/api/prices?days=7')
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  const rows = data.changes.map(c => ({
    id: c.shop_book_id,
    title: c.title,
    prev: c.prev_price !== null ? `€${c.prev_price.toFixed(2)}` : '—',
    new: c.new_price !== null ? `€${c.new_price.toFixed(2)}` : '—',
    change: c.change !== null ? `${c.change >= 0 ? '+' : ''}€${Math.abs(c.change).toFixed(2)}` : '—',
    when: c.scraped_ago,
    pct: c.prev_price && c.prev_price !== 0 ? Math.round(c.change / c.prev_price * 100) : 0,
    shop: c.shop || '—',
    book: c.title || '—',
    old: c.prev_price !== null ? `€${c.prev_price.toFixed(2)}` : '—',
  }));

  const deltas = [-1.10, -0.50, -0.20, 0, 0, 0.10, 0.20, 0.50, 1.00, 1.50, 2.00, 2.50, 3.00];

  const filters = useHFFilters(rows, {
    search: { fields: c => `${c.book} ${c.shop}` },
    filters: [
      { id:'shop', default:'all', match:(c,v) => c.shop === v },
      { id:'dir',  default:'all', match:(c,v) => v==='drop' ? c.pct < 0 : v==='rise' ? c.pct > 0 : c.pct === 0 },
      { id:'mag',  default:'any', match:(c,v) => v==='big' ? Math.abs(c.pct) >= 10 : Math.abs(c.pct) < 10 },
    ],
  });

  return (
    <HFShell {...nav} activePage="prices"
      title="Prices" subtitle="Price records across all books and shops."
      breadcrumb={<><span>BookScraper</span><span style={{color:HF.ink5}}>/</span><span style={{color:HF.ink, fontWeight:500}}>Prices</span></>}
      actions={<HFButton><span style={{display:'flex'}}>{HF_ICONS.download}</span> Export CSV</HFButton>}
    >
      <HFKpiStrip items={[
        { label:'Recent changes', value: String(rows.length), delta:<span style={{color:HF.ink3}}>last 7 days</span>, tone:'ok' },
      ]}/>

      <div style={{display:'grid', gridTemplateColumns:'1.4fr 1fr', gap:HF.gap, marginBottom:HF.gap}}>
        <HFCard title="Change distribution" sub="daily price deltas · last 7 days">
          <div style={{padding:`${HF.cardP}px`}}>
            <HFBarChart data={deltas} h={140} colorFn={(v,i,h) => v < 0 ? h.err : v > 0 ? h.ok : h.ink4}/>
            <div style={{display:'flex', justifyContent:'space-between', fontSize:11, color:HF.ink4, fontFamily:HF.mono, marginTop:8, fontVariantNumeric:'tabular-nums'}}>
              <span>−€2</span><span>−€1</span><span>0</span><span>+€1</span><span>+€2</span><span>+€3</span>
            </div>
          </div>
        </HFCard>
        <HFCard title="Category averages" sub="active listings · today">
          <div style={{padding:`6px 0`}}>
            {[
              ['Fiction',    12.40, -0.3],
              ['Non-fiction',18.90, -0.8],
              ['Children',    9.20, +1.2],
              ['Tech / CS',  24.50, -1.4],
              ['Academic',   32.10,  0.0],
              ['Art',        28.70, +0.4],
            ].map(([cat, avg, chg], i, arr) => (
              <div key={cat} style={{padding:`8px ${HF.cardP}px`, display:'grid', gridTemplateColumns:'1fr 80px 60px', alignItems:'center', borderBottom: i<arr.length-1 ? `1px solid ${HF.borderFaint}` : 'none', fontSize:12.5}}>
                <span style={{color:HF.ink, fontWeight:500}}>{cat}</span>
                <span style={{fontFamily:HF.mono, color:HF.ink, fontWeight:500, textAlign:'right', fontVariantNumeric:'tabular-nums'}}>€{avg.toFixed(2)}</span>
                <span style={{fontFamily:HF.mono, color: chg<0?HF.errInk:chg>0?HF.okInk:HF.ink4, textAlign:'right', fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{chg>0?'+':''}{chg.toFixed(1)}%</span>
              </div>
            ))}
          </div>
        </HFCard>
      </div>

      <HFCard title="Recent changes" sub="non-zero price movements · last 7 days"
              action={<a href="#" style={hfLink(HF)}>All changes {HF_ICONS.arrow}</a>}>
        <div style={{padding:`10px ${HF.cardP}px`, borderBottom:`1px solid ${HF.borderFaint}`}}>
          <HFFilterBar right={<>
            <span style={{fontSize:11.5, color: filters.activeCount? HF.accentInk : HF.ink4, fontFamily:HF.mono, fontVariantNumeric:'tabular-nums', fontWeight: filters.activeCount? 500 : 400}}>
              {filters.filtered.length} of {rows.length}
            </span>
            {filters.activeCount > 0 && <HFButton size="sm" variant="subtle" onClick={filters.clearAll}>Clear ({filters.activeCount})</HFButton>}
          </>}>
            <HFSearch placeholder="Search book…" width={240} value={filters.q} onChange={filters.setQ}/>
            <HFFilter label="Shop"      value={filters.vals.shop} options={['all','vaga','knygos']}     onChange={v=>filters.setVal('shop',v)}/>
            <HFFilter label="Direction" value={filters.vals.dir}  options={['all','drop','rise']}       onChange={v=>filters.setVal('dir',v)}/>
            <HFFilter label="Magnitude" value={filters.vals.mag}  options={['any','big','small']}       onChange={v=>filters.setVal('mag',v)} allLabel="any"/>
          </HFFilterBar>
        </div>
        {filters.filtered.length === 0 ? (
          <HFEmptyState title="No price changes match" sub="Try clearing filters or broadening the search." onClear={filters.clearAll}/>
        ) : (
        <HFTable
          columns={[
            { key:'book', label:'Book', w:'2fr', sortable:true, cell:v => <span style={{color:HF.ink, fontWeight:500}}>{v}</span> },
            { key:'shop', label:'Shop', w:'0.7fr', sortable:true },
            { key:'old', label:'Was', w:'0.7fr', mono:true, align:'right', muted:true, sortable:true },
            { key:'new', label:'Now', w:'0.7fr', mono:true, align:'right', sortable:true, cell:v => <span style={{color:HF.ink, fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v}</span> },
            { key:'pct', label:'Δ %', w:'0.7fr', mono:true, align:'right', sortable:true, sortVal:r=>r.pct, cell:v => <span style={{color: v<0?HF.errInk:v>0?HF.okInk:HF.ink3, fontWeight:600, fontVariantNumeric:'tabular-nums'}}>{v>0?'+':''}{v}%</span> },
            { key:'when', label:'When', w:'1fr', mono:true, muted:true, sortable:true },
          ]}
          rows={filters.filtered}
        />
        )}
      </HFCard>
    </HFShell>
  );
}

Object.assign(window, { HFCron, HFIssues, HFPrices });
