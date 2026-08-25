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
      const body = { shop: job.shop, phase: job.phase, strategy: job.strategy || '', mode: 'delta', cron_job_id: job.id };
      const resp = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (resp.ok) goto('runs');
    } catch (e) { console.error(e); }
  };

  const jobsRaw = data.jobs;
  const jobsFlat = (() => {
    const byParent = {};
    jobsRaw.forEach(j => {
      const parentKey = j.chain_to_id ? j.chain_to_name : '__root__';
      (byParent[parentKey] = byParent[parentKey] || []).push(j);
    });
    const out = [];
    const visit = (parent, depth) => {
      (byParent[parent] || []).forEach(j => {
        out.push({ ...j, depth: Math.min(depth, 1) });
        visit(j.name, depth + 1);
      });
    };
    visit('__root__', 0);
    jobsRaw.forEach(j => {
      if (!out.find(o => o.name === j.name)) out.push({ ...j, depth: 0 });
    });
    return out;
  })();

  const jobs = jobsFlat.map(j => ({
    ...j,
    state: j.enabled ? 'active' : 'disabled',
    lastStatus: j.last_status || 'ok',
    next: j.next || '—',
    avgDur: j.avg_dur || '—',
  }));

  const shopNames = useShopNames();
  const filters = useHFFilters(jobs, {
    search: { fields: j => `${j.name} ${j.cron || ''} ${j.shop} ${j.chain_to_name || ''}` },
    filters: [
      { id:'shop',  default:'all', match:(j,v) => j.shop === v },
      { id:'state', default:'all', match:(j,v) => j.state === v },
    ],
  });

  return (
    <HFShell {...nav} activePage="cron"
      title="Schedules" subtitle="Time-driven and chain-triggered scrape jobs. Disable, edit, or trigger manually."
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
          <HFFilter label="Shop"  value={filters.vals.shop}  options={[...shopNames,'—']} onChange={v=>filters.setVal('shop',v)}/>
          <HFFilter label="State" value={filters.vals.state} options={['all','active','failing','disabled']} onChange={v=>filters.setVal('state',v)}/>
        </HFFilterBar>
      </HFCard>

      <HFCard>
        {filters.filtered.length === 0 ? (
          <HFEmptyState title="No schedules match" sub="Try clearing filters." onClear={filters.clearAll}/>
        ) : (
        <HFTable
          onRowClick={(r) => goto('schedule-detail', { id: r.id, name: r.name, cron: r.cron, shop: r.shop, enabled: r.enabled, lastStatus: r.lastStatus, chain_to_id: r.chain_to_id, chain_to_name: r.chain_to_name })}
          columns={[
            { key:'name', label:'Name', w:'1.8fr', mono:true, sortable:true,
              cell:(v, r) => {
                const depth = r.depth || 0;
                return (
                  <span style={{display:'inline-flex', alignItems:'center', minWidth:0}}>
                    {depth > 0 && (
                      <span style={{
                        display:'inline-flex', alignItems:'center',
                        marginRight:6, flexShrink:0, color:'var(--hf-ink5)',
                      }}>
                        <svg width="18" height="16" viewBox="0 0 18 16" fill="none" style={{flexShrink:0}}>
                          <path d="M5 0 V8 Q5 11 8 11 H16"
                                stroke="var(--hf-ink5)"
                                strokeWidth="1.25"
                                strokeLinecap="round"
                                fill="none"/>
                        </svg>
                      </span>
                    )}
                    <span style={{
                      color: r.enabled ? 'var(--hf-ink)' : 'var(--hf-ink4)',
                      fontWeight:500,
                      overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
                    }}>{v}</span>
                  </span>
                );
              }
            },
            { key:'cron', label:'Cron', w:'0.9fr', mono:true, muted:true, sortable:true },
            { key:'shop', label:'Shop', w:'0.6fr', sortable:true },
            { key:'_trigger', label:'Trigger', w:'1.4fr',
              cell:(_, r) => {
                if (r.chain_to_id) {
                  return (
                    <span style={{display:'inline-flex', alignItems:'center', gap:6, minWidth:0}}>
                      <span style={{
                        display:'inline-flex', alignItems:'center', justifyContent:'center',
                        width:18, height:18, borderRadius:4,
                        background:'var(--hf-accent-soft)',
                        border:'1px solid var(--hf-accent-border)',
                        color:'var(--hf-accent-ink)', flexShrink:0,
                      }}>
                        <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
                          <path d="M6.5 9.5 L9.5 6.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
                          <path d="M6 6 L4 8 Q2 10 4 12 Q6 14 8 12 L10 10"
                                stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                          <path d="M10 10 L12 8 Q14 6 12 4 Q10 2 8 4 L6 6"
                                stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
                        </svg>
                      </span>
                      <span style={{fontSize:12, color:'var(--hf-ink3)'}}>chain</span>
                    </span>
                  );
                }
                return (
                  <span style={{display:'inline-flex', alignItems:'center', gap:6, minWidth:0}}>
                    <span style={{
                      display:'inline-flex', alignItems:'center', justifyContent:'center',
                      width:18, height:18, borderRadius:4,
                      background:'var(--hf-bg)',
                      border:'1px solid var(--hf-border-faint)',
                      color:'var(--hf-ink3)', flexShrink:0,
                    }}>
                      <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
                        <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.6"/>
                        <path d="M8 5.5 V8 L10 9.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
                      </svg>
                    </span>
                    <span style={{
                      fontFamily:'var(--hf-mono)', color:'var(--hf-ink2)',
                      fontSize:12, fontVariantNumeric:'tabular-nums',
                      overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
                    }}>{r.cron || '—'}</span>
                  </span>
                );
              }
            },
            { key:'lastStatus', label:'Last', w:'0.7fr', sortable:true, cell:(v,r) => <span style={{display:'inline-flex', alignItems:'center', gap:7}}><HFDot tone={v==='ok'?'ok':'err'}/> <span style={{color: v==='fail'? 'var(--hf-err-ink)' : 'var(--hf-ink)'}}>{r.last}</span></span> },
            { key:'next', label:'Next run', w:'0.8fr', mono:true, sortable:true,
              cell:(v, r) => {
                if (!r.enabled) return <span style={{color:'var(--hf-ink4)', fontWeight:500}}>disabled</span>;
                if (r.chain_to_id) return <span style={{color:'var(--hf-ink5)'}}>—</span>;
                return <span style={{color:'var(--hf-accent-ink)', fontWeight:500}}>{v}</span>;
              }
            },
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

const SNOOZE_ICON = (
  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="8" cy="8" r="6.5"/>
    <path d="M8 4.5v3.75L10.5 10"/>
    <path d="M11 2.5 L13.5 2.5 L11 5 L13.5 5" strokeWidth="1.2"/>
  </svg>
);

function HFIssues({ nav, goto }) {
  const HF = getHF();
  const PER_PAGE = 30;

  // Read all filter/page state from URL on mount so bookmarks and reloads restore view.
  const _sp = () => new URLSearchParams(window.location.search);
  const [tab,           setTab]           = React.useState(() => { const t = _sp().get('tab'); return ['new','acknowledged','snoozed','resolved','all'].includes(t) ? t : 'new'; });
  const [page,          setPage]          = React.useState(() => Math.max(parseInt(_sp().get('page') || '1', 10) || 1, 1));
  const [severity,      setSeverity]      = React.useState(() => _sp().get('severity')   || 'all');
  const [issueType,     setIssueType]     = React.useState(() => _sp().get('issue_type') || 'all');
  const [shopFilter,    setShopFilter]    = React.useState(() => _sp().get('shop')       || 'all');
  const [q,             setQ]             = React.useState(() => _sp().get('q')          || '');
  const [data, setData] = React.useState({
    issues: [], total: 0, page: 1, per_page: PER_PAGE, pages: 1,
    counts: { new: 0, acknowledged: 0, snoozed: 0, resolved: 0, total: 0 },
  });
  const [loading, setLoading] = React.useState(true);

  // Remaining server-side filters
  const [runIdInput,    setRunIdInput]    = React.useState(() => _sp().get('run_id')    || '');
  const [urlTypeFilter, setUrlTypeFilter] = React.useState(() => _sp().get('url_type')  || 'all');
  const [bookTypeFilter,setBookTypeFilter]= React.useState(() => _sp().get('book_type') || 'all');

  const runId = parseInt(runIdInput, 10) > 0 ? parseInt(runIdInput, 10) : null;
  const [showHelp, setShowHelp] = React.useState(false);
  const [snoozeOpenFor, setSnoozeOpenFor] = React.useState(null);
  const [reloadKey, setReloadKey] = React.useState(0);
  const [undoToast, setUndoToast] = React.useState(null); // {issue_type, shop, count, timerId}

  const [shopsList, setShopsList] = React.useState([]);
  React.useEffect(() => {
    fetch('/api/shops')
      .then(r => r.json())
      .then(d => setShopsList(d.shops || []))
      .catch(() => {});
  }, []);

  const [viewMode, setViewMode] = React.useState('list');
  const [groups, setGroups] = React.useState([]);
  const [groupsLoading, setGroupsLoading] = React.useState(false);

  React.useEffect(() => {
    if (viewMode === 'list') return;
    const groupBy = viewMode === 'by_type_shop' ? 'type_shop' : 'type';
    const params = new URLSearchParams();
    params.set('group_by', groupBy);
    if (shopFilter && shopFilter !== 'all') params.set('shop', shopFilter);
    if (tab && tab !== 'all') params.set('state', tab);
    setGroupsLoading(true);
    fetch(`/api/issues/groups?${params}`)
      .then(r => r.json())
      .then(d => { setGroups(d.groups || []); setGroupsLoading(false); })
      .catch(() => setGroupsLoading(false));
  }, [viewMode, shopFilter, tab]);

  const ISSUE_REFERENCE = [
    // critical
    { key:'isbn_duplicate',      sev:'critical', desc:'Same ISBN, two rows in same shop' },
    { key:'in_stock_no_price',   sev:'critical', desc:'In-stock book has no price' },
    { key:'non_product_active',  sev:'critical', desc:'URL marked non-product but shop_book is active' },
    { key:'unreachable_active',  sev:'critical', desc:'URL is unreachable but shop_book still active' },
    // warning
    { key:'slug_title_mismatch', sev:'warning',  desc:'URL slug shares zero tokens with book title' },
    { key:'active_no_price',     sev:'warning',  desc:'Active book has no price at all' },
    { key:'stale_active',        sev:'warning',  desc:'Active but not seen in last 28 days' },
    { key:'non_book_has_isbn',   sev:'warning',  desc:'Type=non_book but has a valid ISBN' },
    { key:'unmatched_has_isbn',  sev:'warning',  desc:'Has ISBN but not matched to canonical book' },
    { key:'match_isbn_drift',    sev:'warning',  desc:'Matched book\'s ISBN differs from shop_book ISBN' },
    // info
    { key:'book_no_metadata',       sev:'info', desc:'type=book but no ISBN, author, or year' },
    { key:'no_price_history',       sev:'info', desc:'Active but zero rows in prices table' },
    { key:'year_out_of_range',      sev:'info', desc:'Year < 1800 or > current year + 2' },
    { key:'price_zero',             sev:'info', desc:'Price is exactly 0' },
    { key:'format_is_dimensions',   sev:'info', desc:'Format field looks like dimensions (e.g. 210×148)' },
    { key:'book_no_signals',        sev:'info', desc:'type=book but no ISBN, author, year, or format' },
    { key:'orphan_no_url',          sev:'info', desc:'shop_book has no linked discovered_url row' },
    { key:'url_aliases',            sev:'info', desc:'Same shop_book linked from multiple URLs' },
    { key:'product_url_non_book',   sev:'info', desc:'URL type=product but shop_book type=non_book' },
    { key:'title_author_duplicate', sev:'info', desc:'Same title+author, two rows in same shop' },
  ];
  const SEV_TONE = { critical:'err', warning:'warn', info:'neutral' };

  // Reset to page 1 when any filter or tab changes (but not on page changes themselves).
  React.useEffect(() => { setPage(1); }, [tab, runId, severity, issueType, shopFilter, q, urlTypeFilter, bookTypeFilter]);

  // Fetch from server whenever any server-side param changes.
  React.useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const stateParam = tab === 'all' ? '' : tab;
    const params = new URLSearchParams({ state: stateParam, page: String(page), per_page: String(PER_PAGE), kind: 'validation' });
    if (runId)                           params.set('run_id',     String(runId));
    if (urlTypeFilter  !== 'all')        params.set('url_type',   urlTypeFilter);
    if (bookTypeFilter !== 'all')        params.set('book_type',  bookTypeFilter);
    if (severity       !== 'all')        params.set('severity',   severity);
    if (issueType      !== 'all')        params.set('issue_type', issueType);
    if (shopFilter     !== 'all')        params.set('shop',       shopFilter);
    if (q.trim())                        params.set('q',          q.trim());
    fetch(`/api/issues?${params.toString()}`)
      .then(r => r.json())
      .then(d => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tab, page, runId, severity, issueType, shopFilter, q, urlTypeFilter, bookTypeFilter, reloadKey]);

  // Mirror all filter state into the URL bar (replaceState — no history entries).
  React.useEffect(() => {
    const sp = new URLSearchParams(window.location.search);
    tab           !== 'new'  ? sp.set('tab',       tab)            : sp.delete('tab');
    page          !== 1      ? sp.set('page',      String(page))   : sp.delete('page');
    severity      !== 'all'  ? sp.set('severity',  severity)       : sp.delete('severity');
    issueType     !== 'all'  ? sp.set('issue_type',issueType)      : sp.delete('issue_type');
    shopFilter    !== 'all'  ? sp.set('shop',      shopFilter)     : sp.delete('shop');
    q.trim()                 ? sp.set('q',         q.trim())       : sp.delete('q');
    runId                    ? sp.set('run_id',    String(runId))  : sp.delete('run_id');
    urlTypeFilter !== 'all'  ? sp.set('url_type',  urlTypeFilter)  : sp.delete('url_type');
    bookTypeFilter!== 'all'  ? sp.set('book_type', bookTypeFilter) : sp.delete('book_type');
    const qs = sp.toString();
    window.history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : ''));
  }, [tab, page, severity, issueType, shopFilter, q, runId, urlTypeFilter, bookTypeFilter]);

  const seed = data.issues.map(i => ({
    id: `ISS-${i.id}`,
    rawId: i.id,
    type: i.issue,
    sev: i.severity === 'critical' ? 'high' : i.severity === 'warning' ? 'medium' : 'low',
    shop: i.shop_name || '—',
    book: i.shop_book_title || '—',
    shopBookId: i.shop_book_id || null,
    url: i.url || '—',
    url_type: i.url_type || '—',
    run_id: i.scrape_run_id,
    detail: i.description || i.raw_value || '—',
    age: i.added_ago,
    known: i.lifecycle_state === 'acknowledged',
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

  const counts = data.counts || { new: 0, acknowledged: 0, snoozed: 0, resolved: 0, total: 0 };
  const byTab = {
    new:          counts.new || 0,
    acknowledged: counts.acknowledged || 0,
    snoozed:      counts.snoozed || 0,
    resolved:     counts.resolved || 0,
    all:          counts.total || data.total || 0,
  };

  // When tab changes, clear selection (selection is only meaningful within a tab).
  React.useEffect(() => { setSelected(new Set()); }, [tab]);

  // All filters are server-side — allIssues is already the filtered page.
  const filters = { filtered: allIssues, activeCount: 0 };
  const typeOptions = ['all', ...ISSUE_REFERENCE.map(r => r.key)];

  const toggleOne = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };
  const toggleAllVisible = () => {
    const visibleIds = allIssues.map(r => r.id);
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

  const allVisibleSelected = allIssues.length > 0 &&
    allIssues.every(r => selected.has(r.id));
  const someVisibleSelected = allIssues.some(r => selected.has(r.id));

  const selectedCount = selected.size;
  const selectedAreKnown = tab === 'acknowledged';   // if we're in Acknowledged tab, bulk action is "Mark open"

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
        <HFButton size="sm" variant={showHelp ? 'primary' : 'subtle'} onClick={() => setShowHelp(h => !h)}
          title="Show all issue types and severities">?</HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'New',          value: String(byTab.new),          delta:<span style={{color:'var(--hf-err-ink)'}}>new</span>,          tone: byTab.new > 0 ? 'err' : 'ok' },
        { label:'Acknowledged', value: String(byTab.acknowledged), delta:<span style={{color:'var(--hf-ink3)'}}>acknowledged</span> },
        { label:'Snoozed',      value: String(byTab.snoozed),      delta:<span style={{color:'var(--hf-ink3)'}}>snoozed</span> },
        { label:'Resolved',     value: String(byTab.resolved),     delta:<span style={{color:'var(--hf-ok-ink)'}}>resolved</span> },
      ]}/>

      <HFCard style={{marginBottom:'var(--hf-gap)'}}>
        <div style={{padding:`0 var(--hf-card-p)`}}>
          <HFTabs active={tab} onChange={t => { setTab(t); }} tabs={[
            { id:'new',          label:'New',          count: byTab.new },
            { id:'acknowledged', label:'Acknowledged', count: byTab.acknowledged },
            { id:'snoozed',      label:'Snoozed',      count: byTab.snoozed },
            { id:'resolved',     label:'Resolved',     count: byTab.resolved },
            { id:'all',          label:'All',          count: byTab.all },
          ]}/>
        </div>
      </HFCard>

      {/* Issue type reference modal */}
      <HFModal open={showHelp} onClose={() => setShowHelp(false)} width={560}>
        <HFModalHead title="Issue type reference" sub="21 check types across 5 groups" onClose={() => setShowHelp(false)}/>
        <HFModalBody>
          <div style={{display:'flex', flexDirection:'column', gap:0}}>
            {ISSUE_REFERENCE.map((r, i) => (
              <div key={r.key} style={{
                display:'flex', alignItems:'center', gap:10,
                padding:'8px 0',
                borderBottom: i < ISSUE_REFERENCE.length - 1 ? '1px solid var(--hf-border-faint)' : 'none',
              }}>
                <HFPill tone={SEV_TONE[r.sev]} style={{flexShrink:0, fontSize:10, width:60, textAlign:'center'}}>{r.sev}</HFPill>
                <span style={{fontFamily:'var(--hf-mono)', fontSize:11, color:'var(--hf-ink)', flexShrink:0, width:190}}>{r.key}</span>
                <span style={{fontSize:12, color:'var(--hf-ink4)'}}>{r.desc}</span>
              </div>
            ))}
          </div>
        </HFModalBody>
        <HFModalFoot>
          <HFButton variant="primary" onClick={() => setShowHelp(false)}>Close</HFButton>
        </HFModalFoot>
      </HFModal>

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
            <span style={{fontSize:12, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)', fontVariantNumeric:'tabular-nums'}}>
              {data.total.toLocaleString()} total
            </span>
            {(severity !== 'all' || issueType !== 'all' || shopFilter !== 'all' || q || runId || urlTypeFilter !== 'all' || bookTypeFilter !== 'all') && (
              <HFButton size="sm" variant="subtle" onClick={() => {
                setSeverity('all'); setIssueType('all'); setShopFilter('all'); setQ('');
                setRunIdInput(''); setUrlTypeFilter('all'); setBookTypeFilter('all');
              }}>Clear filters</HFButton>
            )}
          </>}>
            <HFSearch placeholder="Search ID, book, URL, detail…" width={260} value={q} onChange={setQ}/>
            <HFFilter label="Shop"     value={shopFilter}  options={['all', ...shopsList.map(s => s.name)]} onChange={setShopFilter}/>
            <HFFilter label="Severity" value={severity}    options={['all','critical','warning','info']}  onChange={setSeverity}/>
            <HFFilter label="Type"     value={issueType}   options={typeOptions}                          onChange={setIssueType}/>
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

      {undoToast && (
        <div style={{
          position: 'fixed', bottom: 24, left: '50%', transform: 'translateX(-50%)',
          background: 'var(--hf-ink)', color: '#fff',
          padding: '10px 20px', borderRadius: '8px',
          display: 'flex', alignItems: 'center', gap: 16,
          fontSize: 13, fontWeight: 500, zIndex: 1000,
          boxShadow: '0 4px 16px rgba(0,0,0,0.25)',
        }}>
          <span>{(undoToast.count || 0).toLocaleString()} issues acknowledged</span>
          <button onClick={() => {
            clearTimeout(undoToast.timerId);
            fetch('/api/issues/bulk-unacknowledge', {
              method: 'POST',
              headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({ issue_type: undoToast.issue_type, shop: undoToast.shop }),
            }).then(() => { setUndoToast(null); setGroups([]); setViewMode(v => v); });
          }} style={{
            background: 'rgba(255,255,255,0.2)', border: 'none', color: '#fff',
            borderRadius: '4px', padding: '3px 10px', cursor: 'pointer',
            fontWeight: 600, fontSize: 12,
          }}>Undo</button>
          <button onClick={() => { clearTimeout(undoToast.timerId); setUndoToast(null); }}
            style={{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.6)', cursor: 'pointer', fontSize: 14, padding: '0 4px' }}>✕</button>
        </div>
      )}

      <HFCard>
        <div style={{display:'flex', alignItems:'center', padding:'10px var(--hf-card-p) 10px', borderBottom:'1px solid var(--hf-border-faint)', marginBottom:'0'}}>
          {(() => {
            const modes = [
              { id:'list',         label:'List',          icon:(
                <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                  <line x1="1" y1="3" x2="13" y2="3"/><line x1="1" y1="7" x2="13" y2="7"/><line x1="1" y1="11" x2="13" y2="11"/>
                </svg>
              )},
              { id:'by_type',      label:'By type',       icon:(
                <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="1" y="1" width="5" height="5" rx="1.5"/><rect x="8" y="1" width="5" height="5" rx="1.5"/>
                  <rect x="1" y="8" width="5" height="5" rx="1.5"/><rect x="8" y="8" width="5" height="5" rx="1.5"/>
                </svg>
              )},
              { id:'by_type_shop', label:'By type × shop', icon:(
                <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="1" y="1" width="5" height="3" rx="1"/><rect x="8" y="1" width="5" height="3" rx="1"/>
                  <rect x="1" y="5.5" width="5" height="3" rx="1"/><rect x="8" y="5.5" width="5" height="3" rx="1"/>
                  <rect x="1" y="10" width="5" height="3" rx="1"/><rect x="8" y="10" width="5" height="3" rx="1"/>
                </svg>
              )},
            ];
            return (
              <div style={{
                display:'inline-flex', gap:'2px',
                background:'var(--hf-subtle)', border:'1px solid var(--hf-border)',
                borderRadius:'9px', padding:'3px',
              }}>
                {modes.map(m => (
                  <button key={m.id} onClick={() => setViewMode(m.id)} style={{
                    display:'flex', alignItems:'center', gap:'6px',
                    padding:'4px 12px', border:'none', cursor:'pointer', fontSize:12.5,
                    fontWeight: viewMode === m.id ? 500 : 400,
                    borderRadius:'6px',
                    background: viewMode === m.id
                      ? 'var(--pico-background-color, #fff)'
                      : 'transparent',
                    color: viewMode === m.id ? 'var(--hf-ink)' : 'var(--hf-ink3)',
                    boxShadow: viewMode === m.id
                      ? '0 1px 3px rgba(0,0,0,0.10), 0 0 0 1px var(--hf-border)'
                      : 'none',
                    transition: 'background 150ms, color 150ms, box-shadow 150ms',
                  }}>
                    <span style={{display:'flex', opacity: viewMode === m.id ? 1 : 0.55}}>{m.icon}</span>
                    {m.label}
                  </button>
                ))}
              </div>
            );
          })()}
        </div>

        {viewMode === 'list' ? (
          allIssues.length === 0 ? (
          <HFEmptyState
            title={
              tab === 'acknowledged' ? 'No acknowledged issues yet' :
              tab === 'snoozed'      ? 'No snoozed issues' :
              tab === 'resolved'     ? 'Resolved issues appear here' :
              'No issues match these filters'
            }
            sub={
              tab === 'acknowledged' ? 'Tick an issue\u2019s checkbox and click "Mark as known" to acknowledge it as expected.' :
              tab === 'snoozed'      ? 'Snooze an issue to hide it until later.' :
              'Try clearing filters or switching tabs.'
            }
          />
        ) : (
        <div style={{overflowX:'auto'}}>
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
              cell:(v, r) => dimIfKnown(r, v === '—' ? <span style={{color:'var(--hf-ink4)'}}>—</span> :
                r.shopBookId
                  ? <a onClick={e => { e.stopPropagation(); goto('shop-book-detail', {id: r.shopBookId}); }} style={{color:'var(--hf-ink)', fontWeight:500, cursor:'pointer', textDecoration:'underline', textDecorationColor:'var(--hf-ink4)'}}>{v}</a>
                  : <span style={{color:'var(--hf-ink)', fontWeight:500}}>{v}</span>
              ) },
            { key:'url',  label:'URL',      w:'1.2fr', mono:true, muted:true,
              cell:(v, r) => dimIfKnown(r, v === '—' ? <span style={{color:'var(--hf-ink4)'}}>—</span> :
                <a href={v} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={{color:'var(--hf-ink3)', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', display:'block'}}>{v}</a>
              ) },
            { key:'detail', label:'Detail', w:'1.6fr',
              cell:(v, r) => dimIfKnown(r, <span style={{color:'var(--hf-ink2)', fontSize:13}}>{v}</span>) },
            { key:'age',  label:'When',     w:'0.8fr', mono:true, muted:true, sortable:true,
              cell:(v, r) => dimIfKnown(r, <span style={{color:'var(--hf-ink3)'}}>{v}</span>) },
            { key:'_',    label:'',         w:'80px',  align:'right', cell:(_, r) => (
              <div style={{display:'flex', alignItems:'center', justifyContent:'flex-end', gap:4}}>
                <div style={{position:'relative', display:'inline-block'}}>
                  <button
                    onClick={e => { e.stopPropagation(); setSnoozeOpenFor(snoozeOpenFor === r.id ? null : r.id); }}
                    title="Snooze issue"
                    aria-label="Snooze issue"
                    style={{padding:'8px 10px', fontSize:'0.8em', borderRadius:'4px', border:'1px solid var(--pico-muted-border-color)', cursor:'pointer', background:'transparent', lineHeight:1.4, color:'var(--hf-ink3)', display:'flex', alignItems:'center'}}
                  >{SNOOZE_ICON}</button>
                  {snoozeOpenFor === r.id && (
                    <div style={{position:'absolute', right:0, top:'100%', background:'var(--hf-surface)', border:'1px solid var(--hf-border-strong)', borderRadius:'6px', padding:'4px', zIndex:100, display:'flex', flexDirection:'column', gap:'2px', minWidth:'80px'}}>
                      {[7, 30, 90].map(d => (
                        <button key={d} onClick={e => {
                          e.stopPropagation();
                          fetch(`/api/issues/${r.id}/snooze`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({days: d})})
                            .then(() => { setSnoozeOpenFor(null); setReloadKey(k => k + 1); });
                        }} style={{padding:'4px 8px', fontSize:'0.8em', cursor:'pointer', border:'none', background:'transparent', textAlign:'left', borderRadius:'4px'}}>
                          {d}d
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <span style={{color:'var(--hf-ink4)', display:'flex'}}>{HF_ICONS.chevron}</span>
              </div>
            ) },
          ]}
          rows={allIssues}
        />
        </div>
          )
        ) : (
          <div>
            {groupsLoading && <div style={{padding:'20px', color:'var(--hf-ink3)'}}>Loading…</div>}
            {groups.map(g => {
              const key = viewMode === 'by_type_shop' ? `${g.shop_name}/${g.issue_type}` : g.issue_type;
              const sevColor = g.severity === 'critical' ? '#e53e3e' : g.severity === 'warning' ? '#d69e2e' : '#718096';
              return (
                <div key={key} style={{display:'flex',alignItems:'center',gap:'12px',padding:'10px 14px',marginBottom:'6px',border:'1px solid var(--hf-border-strong)',borderRadius:'8px',background:'var(--hf-surface)'}}>
                  <span style={{width:'10px',height:'10px',borderRadius:'50%',background:sevColor,flexShrink:0}}/>
                  {viewMode === 'by_type_shop' && <span style={{fontWeight:500,color:'var(--hf-ink3)',fontSize:'0.85em',fontFamily:'var(--hf-mono)'}}>{g.shop_name}</span>}
                  <span style={{flex:1,fontWeight:500,fontFamily:'var(--hf-mono)',fontSize:'0.9em'}}>{g.issue_type}</span>
                  {(g.by_state && g.by_state.new > 0) && (() => {
                    const badgeColor = g.severity === 'critical' ? '#e53e3e'
                      : g.severity === 'warning' ? '#d97706'
                      : '#718096';
                    return (
                      <span style={{
                        background: badgeColor, color: '#fff', borderRadius: '12px',
                        padding: '1px 8px', fontSize: '0.8em', fontWeight: 600, flexShrink: 0,
                      }}>{g.by_state.new} new</span>
                    );
                  })()}
                  <span style={{color:'var(--hf-ink3)',fontSize:'0.85em'}}>{g.total} total</span>
                  <button onClick={() => {
                    const payload = {
                      issue_type: g.issue_type,
                      shop: viewMode === 'by_type_shop' ? g.shop_name : (shopFilter !== 'all' ? shopFilter : undefined),
                    };
                    fetch('/api/issues/bulk-acknowledge', {
                      method: 'POST',
                      headers: {'Content-Type': 'application/json'},
                      body: JSON.stringify(payload),
                    }).then(r => r.json()).then(d => {
                      if (undoToast?.timerId) clearTimeout(undoToast.timerId);
                      const timerId = setTimeout(() => setUndoToast(null), 5000);
                      setUndoToast({ ...payload, count: d.acknowledged, timerId });
                      setFilters && setFilters(f => ({...f}));
                      setGroups(gs => gs.map(x => x === g ? {...x, by_state: {...(x.by_state||{}), new: 0}} : x));
                    });
                  }} style={{
                    padding: '4px 12px', borderRadius: '5px', border: '1px solid var(--pico-muted-border-color)',
                    cursor: 'pointer', fontSize: '0.8em', background: 'transparent',
                    color: 'var(--hf-ink3)',
                  }}>{`Ack (${(g.by_state?.new || 0).toLocaleString()})`}</button>
                  <button onClick={() => {
                    setIssueType(g.issue_type);
                    if (viewMode === 'by_type_shop') setShopFilter(g.shop_name || 'all');
                    setViewMode('list');
                  }} style={{
                    padding: '4px 12px', borderRadius: '5px', border: '1px solid var(--hf-accent)',
                    cursor: 'pointer', fontSize: '0.8em', background: 'var(--hf-accent)',
                    color: '#fff', fontWeight: 500,
                  }}>View</button>
                </div>
              );
            })}
            {!groupsLoading && groups.length === 0 && <div style={{textAlign:'center',color:'var(--hf-ink3)',padding:'40px'}}>No issues in this view.</div>}
          </div>
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
  const shopNames = useShopNames();
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
            <HFFilter label="Shop"      value={shop} options={shopNames}   onChange={setShop}/>
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
