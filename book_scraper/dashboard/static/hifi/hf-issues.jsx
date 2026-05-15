// Hi-fi Issues page — production-aligned + scale features.
//
// Versus the legacy hf-other.jsx HFIssues:
//   • 4-tile lifecycle KPI strip (NEW / ACKNOWLEDGED / SNOOZED / RESOLVED) with sparkline + delta.
//   • Lifecycle tabs with hover-help — each state explained.
//   • Saved-filter chips row — one-click jump to common filter combos.
//   • Filter row: Search · Shop · Severity · Type · URL type · Book type · Run.
//   • View modes: Waves · By type · By type × shop · List. Waves group
//     (type × shop × run) so one parser regression that fires 36,242 times
//     shows up as ONE row. Run-failure waves are split into their own section.
//   • Bulk-action toolbar in List view — multi-select then ack/snooze/assign/resolve thousands.
//   • Inline row preview in List view — click the chevron to reveal raw HTML snippet
//     and a per-row "Fix this" mini-panel without leaving the list.

const HF_ISSUE_TYPES = [
  { type:'missing_price',         sev:'critical', tone:'err',     description:'No price scraped. Parser likely hit a broken or restructured product page.' },
  { type:'match_isbn_drift',      sev:'high',     tone:'warn',    description:'Shop reports an ISBN that disagrees with the canonical book matched by other shops.' },
  { type:'invalid_isbn',          sev:'high',     tone:'warn',    description:'ISBN check digit fails validation or the value is not 10/13 digits.' },
  { type:'non_product_active',    sev:'low',      tone:'neutral', description:'A URL classified as non-product is still being scraped as if it were a book listing.' },
  { type:'price_spike',           sev:'medium',   tone:'warn',    description:'Price moved by more than the configured threshold in a single run, with no promo marker.' },
  { type:'discover_fetch_failed', sev:'medium',   tone:'warn',    description:'Sitemap / discovery URL returned 4xx or 5xx — likely permanent removal.' },
  { type:'unmatched_has_isbn',    sev:'low',      tone:'neutral', description:'Shop book carries a valid ISBN but did not link to any canonical book.' },
  { type:'scrape_run_failed',     sev:'high',     tone:'err',     description:'A scrape run ended with status=failed before completing its phase.' },
  { type:'product_url_non_book',  sev:'low',      tone:'neutral', description:'A URL classified as a product page resolved to something that is not a book.' },
];

const HF_LIFECYCLE_HELP = {
  new:          'Automatically generated, not yet reviewed by anyone.',
  acknowledged: 'Operator has seen it and accepted it as a real problem to work on.',
  snoozed:      'Hidden from the New tab until a wake-up date.',
  resolved:     'Fixed — either verified clean by a follow-up run, or manually closed.',
  all:          'Every issue regardless of lifecycle state.',
};

// Sparkline — 14 daily counts → tiny SVG. Tone-aware fill.
function HFIssueSparkline({ data, tone = 'neutral', w = 88, h = 24 }) {
  const HF = getHF();
  const color = tone === 'err' ? HF.errInk : tone === 'warn' ? HF.warnInk : tone === 'ok' ? HF.okInk : HF.ink3;
  const fill  = tone === 'err' ? HF.errSoft : tone === 'warn' ? HF.warnSoft : tone === 'ok' ? HF.okSoft : HF.subtle;
  if (!data || data.length === 0) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = Math.max(1, max - min);
  const step = data.length > 1 ? w / (data.length - 1) : 0;
  const points = data.map((v, i) => {
    const x = i * step;
    const y = h - 2 - ((v - min) / span) * (h - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const lastY = h - 2 - ((data[data.length - 1] - min) / span) * (h - 4);
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{display:'block', overflow:'visible'}}>
      <polyline points={`0,${h} ${points.join(' ')} ${w},${h}`} fill={fill} opacity={0.6}/>
      <polyline points={points.join(' ')} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round"/>
      <circle cx={(data.length - 1) * step} cy={lastY} r={2.2} fill={color}/>
    </svg>
  );
}

function formatRelativeAge(isoStr) {
  if (!isoStr) return '—';
  const secs = Math.max(0, Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000));
  if (secs < 60)   return 'just now';
  const m = Math.floor(secs / 60);
  if (m < 60)      return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24)      return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 7)       return `${d}d ago`;
  const w = Math.floor(d / 7);
  if (w < 5)       return `${w}w ago`;
  const mo = Math.floor(d / 30);
  if (mo < 12)     return `${mo}mo ago`;
  return `${Math.floor(d / 365)}y ago`;
}

function hfIssueDetailLine(issueType, bookTitle) {
  const meta = HF_ISSUE_TYPES.find(t => t.type === issueType);
  const base = meta ? meta.description : issueType;
  return bookTitle ? `${base} — ${bookTitle}` : base;
}

function HFIssues({ nav, goto }) {
  const HF = getHF();

  // Filter+tab+view state is mirrored to the URL so the view is shareable.
  const _initialParams = React.useMemo(() => {
    const sp = new URLSearchParams(typeof window !== 'undefined' ? window.location.search : '');
    const TABS = ['new','acknowledged','snoozed','resolved','all'];
    const VIEWS = ['by_type','list'];
    return {
      tab:  TABS.includes(sp.get('tab'))   ? sp.get('tab')   : 'new',
      view: VIEWS.includes(sp.get('view')) ? sp.get('view')  : 'by_type',
      shop: sp.get('shop') || 'all',
      type: sp.get('type') || 'all',
      sev:  ['all','critical','warning'].includes(sp.get('sev')) ? sp.get('sev') : 'all',
      q:    sp.get('q')    || '',
      run:  sp.get('run')  || 'any',
    };
  }, []);

  const [tab, setTab] = React.useState(_initialParams.tab);
  const [view, setView] = React.useState(_initialParams.view);
  const [byTypeSort, setByTypeSort] = React.useState('priority');  // priority | count | type
  const [selected, setSelected] = React.useState(new Set());
  const [expanded, setExpanded] = React.useState(null);

  // API state
  const [lifecycleCounts, setLifecycleCounts] = React.useState({ new: 0, acknowledged: 0, snoozed: 0, resolved: 0, total: 0 });
  const [groupsData, setGroupsData] = React.useState([]);
  const [wavesData, setWavesData] = React.useState([]);
  const [listData, setListData] = React.useState({ issues: [], total: 0 });
  const [listLoading, setListLoading] = React.useState(false);
  const [listPage, setListPage] = React.useState(1);

  // Filter state for list view (managed locally; API-driven when view===list)
  const [shopFilter, setShopFilter] = React.useState(_initialParams.shop);
  const [sevFilter, setSevFilter] = React.useState(_initialParams.sev);
  const [typeFilter, setTypeFilter] = React.useState(_initialParams.type);
  const [searchQ, setSearchQ] = React.useState(_initialParams.q);
  const [runFilter, setRunFilter] = React.useState(_initialParams.run);
  const [availableShops, setAvailableShops] = React.useState([]);

  React.useEffect(() => {
    fetch('/api/shops')
      .then(r => r.json())
      .then(d => setAvailableShops((d.shops || []).map(s => s.name)))
      .catch(() => {});
  }, []);

  // Sync state → URL query params
  React.useEffect(() => {
    const sp = new URLSearchParams();
    if (tab !== 'new')         sp.set('tab', tab);
    if (view !== 'by_type')    sp.set('view', view);
    if (shopFilter !== 'all')  sp.set('shop', shopFilter);
    if (sevFilter !== 'all')   sp.set('sev', sevFilter);
    if (typeFilter !== 'all')  sp.set('type', typeFilter);
    if (searchQ)               sp.set('q', searchQ);
    if (runFilter !== 'any')   sp.set('run', runFilter);
    const qs = sp.toString();
    const url = '/issues' + (qs ? '?' + qs : '');
    const cur = window.location.pathname + window.location.search;
    if (url !== cur) window.history.replaceState(null, '', url);
  }, [tab, view, shopFilter, sevFilter, typeFilter, searchQ, runFilter]);

  // Fetch lifecycle counts on mount (and whenever tab changes to keep counts fresh)
  React.useEffect(() => {
    fetch('/api/issues?per_page=1')
      .then(r => r.json())
      .then(d => { if (d.counts) setLifecycleCounts(d.counts); })
      .catch(() => {});
  }, []);

  // Per-type 14-day trend, keyed by issue_type
  const [trendData, setTrendData] = React.useState({});
  React.useEffect(() => {
    fetch('/api/issues/trend?days=14&state=new')
      .then(r => r.json())
      .then(d => setTrendData(d || {}))
      .catch(() => {});
  }, []);

  // Aggregated 14-day trend across all types — used by the lifecycle "new" KPI tile.
  const newTrend = Object.values(trendData).reduce((acc, series) => {
    if (!Array.isArray(series)) return acc;
    if (acc.length === 0) return [...series];
    return acc.map((v, i) => v + (series[i] || 0));
  }, []);

  // Fetch by-type groups whenever tab or shop filter changes.
  React.useEffect(() => {
    const params = new URLSearchParams({ group_by: 'type' });
    if (tab !== 'all') params.set('state', tab);
    if (shopFilter !== 'all') params.set('shop', shopFilter);
    fetch(`/api/issues/groups?${params}`)
      .then(r => r.json())
      .then(d => setGroupsData(Array.isArray(d) ? d : (d.groups || [])))
      .catch(() => {});
  }, [tab, shopFilter]);

  // Fetch type×shop groups for the waves view
  React.useEffect(() => {
    if (view !== 'waves') return;
    const params = new URLSearchParams({ group_by: 'type_shop' });
    if (tab !== 'all') params.set('state', tab);
    fetch(`/api/issues/groups?${params}`)
      .then(r => r.json())
      .then(d => setWavesData(Array.isArray(d) ? d : (d.groups || [])))
      .catch(() => {});
  }, [view, tab]);

  // Fetch list when in list view
  React.useEffect(() => {
    if (view !== 'list') return;
    setListLoading(true);
    const params = new URLSearchParams({ page: listPage, per_page: 50 });
    if (tab !== 'all') params.set('state', tab);
    if (shopFilter !== 'all') params.set('shop', shopFilter);
    if (typeFilter !== 'all') params.set('issue_type', typeFilter);
    if (sevFilter !== 'all') params.set('severity', sevFilter);
    if (searchQ) params.set('q', searchQ);
    if (runFilter !== 'any') params.set('run_id', runFilter);
    fetch(`/api/issues?${params}`)
      .then(r => r.json())
      .then(d => { setListData(d); setListLoading(false); })
      .catch(() => { setListLoading(false); });
  }, [view, tab, shopFilter, sevFilter, typeFilter, searchQ, runFilter, listPage]);

  // Reset page and selection when tab/view/filters change
  React.useEffect(() => { setListPage(1); setSelected(new Set()); }, [view, tab, shopFilter, sevFilter, typeFilter, searchQ, runFilter]);

  React.useEffect(() => { setSelected(new Set()); }, [view, tab]);

  const sevTone = { critical: 'err', high: 'warn', medium: 'warn', low: 'neutral' };
  const sevRank = { critical: 4, high: 3, medium: 2, low: 1 };

  const byTypeRows = groupsData
  .filter(row => {
    if (typeFilter !== 'all' && row.issue_type !== typeFilter) return false;
    if (sevFilter === 'critical') {
      const meta = HF_ISSUE_TYPES.find(t => t.type === row.issue_type);
      if (!meta || meta.sev !== 'critical') return false;
    } else if (sevFilter === 'warning') {
      const meta = HF_ISSUE_TYPES.find(t => t.type === row.issue_type);
      if (!meta || meta.sev === 'critical') return false;
    }
    if (searchQ && !row.issue_type.includes(searchQ.toLowerCase())) return false;
    return true;
  })
  .map(row => {
    const meta = HF_ISSUE_TYPES.find(t => t.type === row.issue_type) || { sev: 'low', tone: 'neutral' };
    const total = row.total || 0;
    const ack = (row.by_state?.acknowledged ?? row.cnt_acknowledged) || 0;
    const newCount = (row.by_state?.new ?? row.cnt_new) || 0;
    const priority = sevRank[meta.sev || 'low'] * Math.log10(Math.max(2, newCount));
    const trend = trendData[row.issue_type] || Array(14).fill(0);
    const recent = trend.slice(-7).reduce((a, b) => a + b, 0);
    const prev = trend.slice(-14, -7).reduce((a, b) => a + b, 0);
    const deltaPct = prev > 0 ? Math.round((recent - prev) / prev * 100) : 0;
    const direction = recent > prev * 1.1 ? 'up' : recent < prev * 0.9 ? 'down' : 'flat';
    return { ...meta, type: row.issue_type, total, ack, newCount, trend, priority, direction, deltaPct };
  }).sort((a, b) => {
    if (byTypeSort === 'priority') return b.priority - a.priority;
    if (byTypeSort === 'count')    return b.total - a.total;
    return a.type.localeCompare(b.type);
  });

  // Map API list rows to the shape expected by ListRows
  const listRows = (listData.issues || []).map(issue => {
    const meta = HF_ISSUE_TYPES.find(t => t.type === issue.issue) || { sev: 'low', tone: 'neutral' };
    return {
      id: String(issue.id),
      type: issue.issue,
      sev: meta.sev,
      tone: meta.tone,
      shop: issue.shop_name || null,
      book: issue.shop_book_title || null,
      url: issue.url || null,
      urlType: 'product',
      bookType: 'book',
      detail: hfIssueDetailLine(issue.issue, issue.shop_book_title, 0),
      run: issue.scrape_run_id ? `run:${issue.scrape_run_id}` : null,
      runRef: issue.scrape_run_id || null,
      age: issue.added_at ? formatRelativeAge(issue.added_at) : '—',
      lifecycle: issue.lifecycle_state || 'new',
    };
  });

  // Bulk selection helpers
  const toggleOne = (id) => setSelected(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const toggleAllVisible = () => {
    const visible = listRows.map(r => r.id);
    const allOn = visible.every(id => selected.has(id));
    setSelected(prev => {
      const next = new Set(prev);
      visible.forEach(id => allOn ? next.delete(id) : next.add(id));
      return next;
    });
  };
  const selectedCount = selected.size;
  const allVisibleSelected = listRows.length > 0 && listRows.every(r => selected.has(r.id));
  const someVisibleSelected = listRows.some(r => selected.has(r.id));

  // Type-specific "Fix this" actions
  const fixActionsFor = (type) => {
    const open = (page, params) => () => goto(page, params);
    switch (type) {
      case 'missing_price':
      case 'invalid_isbn':
      case 'price_spike':
        return [
          { label:'Open parser', primary:true, action:open('parser', { shop:'patogupirkti' }) },
          { label:'Re-scrape URL', action:() => {} },
          { label:'Bulk ack pattern', action:() => {} },
        ];
      case 'match_isbn_drift':
      case 'unmatched_has_isbn':
        return [
          { label:'Open book', primary:true, action:open('book', {}) },
          { label:'Re-run matcher', action:() => {} },
          { label:'Bulk ack pattern', action:() => {} },
        ];
      case 'discover_fetch_failed':
        return [
          { label:'Edit sitemap', primary:true, action:open('shop-detail', { name:'knygos.lt' }) },
          { label:'Remove URL', action:() => {} },
        ];
      case 'scrape_run_failed':
        return [
          { label:'Open run', primary:true, action:open('run-detail', {}) },
          { label:'Re-run', action:() => {} },
        ];
      default:
        return [
          { label:'Open parser', primary:true, action:open('parser', {}) },
          { label:'Re-scrape', action:() => {} },
        ];
    }
  };

  // Dead-code stubs for disabled {false && ...} render blocks
  const itemWaves = wavesData
    .filter(w => w.issue_type !== 'scrape_run_failed')
    .map(w => ({
      id: `${w.issue_type}-${w.shop_name || 'all'}`,
      type: w.issue_type,
      shop: w.shop_name || '—',
      count: w.total || 0,
      ack: (w.by_state?.acknowledged ?? 0),
      firstSeen: '—', lastSeen: '—', span: '', sample: null, runFailure: false,
    }));
  const runFailureWaves = wavesData
    .filter(w => w.issue_type === 'scrape_run_failed')
    .map(w => ({
      id: `${w.issue_type}-${w.shop_name || 'all'}`,
      type: w.issue_type,
      shop: w.shop_name || '—',
      count: w.total || 0,
      ack: (w.by_state?.acknowledged ?? 0),
      firstSeen: '—', lastSeen: '—', span: '', sample: null, runFailure: true,
    }));
  const byTypeShopRows = [];

  // Bulk-acknowledge: POST with optional type+shop filters derived from selected rows
  const bulkAcknowledge = () => {
    // Derive a common type/shop if all selected rows share one (enables server-side batch)
    const selectedRows = listRows.filter(r => selected.has(r.id));
    const types = [...new Set(selectedRows.map(r => r.type).filter(Boolean))];
    const shops = [...new Set(selectedRows.map(r => r.shop).filter(Boolean))];
    const body = {};
    if (types.length === 1) body.issue_type = types[0];
    if (shops.length === 1) body.shop = shops[0];
    fetch('/api/issues/bulk-acknowledge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(() => {
        setSelected(new Set());
        // Refresh counts and list
        fetch('/api/issues?per_page=1').then(r => r.json()).then(d => { if (d.counts) setLifecycleCounts(d.counts); }).catch(() => {});
        setListPage(p => p); // trigger list re-fetch via effect dep noop — force by toggling
        setListLoading(true);
        const params = new URLSearchParams({ page: listPage, per_page: 50 });
        if (tab !== 'all') params.set('state', tab);
        if (shopFilter !== 'all') params.set('shop', shopFilter);
        if (typeFilter !== 'all') params.set('issue_type', typeFilter);
        if (sevFilter !== 'all') params.set('severity', sevFilter);
        if (searchQ) params.set('q', searchQ);
        fetch(`/api/issues?${params}`).then(r => r.json()).then(d => { setListData(d); setListLoading(false); }).catch(() => { setListLoading(false); });
      })
      .catch(() => {});
  };

  const _refreshList = () => {
    setSelected(new Set());
    fetch('/api/issues?per_page=1').then(r => r.json()).then(d => { if (d.counts) setLifecycleCounts(d.counts); }).catch(() => {});
    setListLoading(true);
    const rp = new URLSearchParams({ page: listPage, per_page: 50 });
    if (tab !== 'all') rp.set('state', tab);
    if (shopFilter !== 'all') rp.set('shop', shopFilter);
    if (typeFilter !== 'all') rp.set('issue_type', typeFilter);
    if (sevFilter !== 'all') rp.set('severity', sevFilter);
    if (searchQ) rp.set('q', searchQ);
    if (runFilter !== 'any') rp.set('run_id', runFilter);
    fetch(`/api/issues?${rp}`).then(r => r.json()).then(d => { setListData(d); setListLoading(false); }).catch(() => { setListLoading(false); });
  };

  const bulkSnooze = (days = 7) => {
    const ids = [...selected].map(Number).filter(Boolean);
    if (!ids.length) return;
    Promise.all(ids.map(id =>
      fetch(`/api/issues/${id}/snooze`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days }),
      })
    )).then(_refreshList).catch(() => {});
  };

  const bulkResolve = () => {
    const ids = [...selected].map(Number).filter(Boolean);
    if (!ids.length) return;
    Promise.all(ids.map(id =>
      fetch(`/api/issues/${id}/lifecycle?state=resolved`, { method: 'PATCH' })
    )).then(_refreshList).catch(() => {});
  };

  return (
    <HFShell {...nav} activePage="issues"
      title="Issues" subtitle="Individual validation failures, parser errors, and data-quality events across all shops."
      breadcrumb={<><span>BookScraper</span><span style={{color:HF.ink5}}>/</span><span style={{color:HF.ink, fontWeight:500}}>Issues</span></>}
      actions={<>
        <HFButton>Assign</HFButton>
        <HFButton variant="primary">Mark resolved</HFButton>
        <HFButton size="md" variant="subtle" style={{padding:'0 10px', minWidth:32, justifyContent:'center'}} title="Open issue-handling runbook">?</HFButton>
      </>}
    >
      {/* Lifecycle tabs — counts live here, no separate KPI strip */}
      <HFCard style={{marginBottom:HF.gap, overflow:'visible'}}>
        <div style={{padding:`0 ${HF.cardP}px`, display:'flex', alignItems:'center', justifyContent:'space-between'}}>
          <HFTabs active={tab} onChange={setTab} tabs={[
            { id:'new',          label:'New',          count: lifecycleCounts.new },
            { id:'acknowledged', label:'Acknowledged', count: lifecycleCounts.acknowledged },
            { id:'snoozed',      label:'Snoozed',      count: lifecycleCounts.snoozed },
            { id:'resolved',     label:'Resolved',     count: lifecycleCounts.resolved },
            { id:'all',          label:'All',          count: lifecycleCounts.total },
          ]}/>
          <span title={HF_LIFECYCLE_HELP[tab]} style={{
            fontSize:11.5, color:HF.ink3, fontStyle:'italic', cursor:'help', paddingRight:4,
          }}>{HF_LIFECYCLE_HELP[tab]}</span>
        </div>
      </HFCard>

      {/* Filter row OR bulk action bar */}
      {view === 'list' && selectedCount > 0 ? (
        <HFCard style={{marginBottom:HF.gap, background:HF.accentSoft, border:`1px solid ${HF.accentBorder}`, overflow:'visible'}} padding={12}>
          <div style={{display:'flex', alignItems:'center', gap:12, padding:'2px 4px'}}>
            <span style={{
              display:'inline-flex', alignItems:'center', justifyContent:'center',
              width:24, height:24, borderRadius:5, background:HF.accentInk, color:'#fff',
              fontFamily:HF.mono, fontSize:11.5, fontWeight:600, fontVariantNumeric:'tabular-nums',
            }}>{selectedCount}</span>
            <span style={{fontSize:13, color:HF.ink, fontWeight:500}}>
              {selectedCount === 1 ? '1 issue' : `${selectedCount.toLocaleString()} issues`} selected
            </span>
            <span style={{flex:1}}/>
            <HFButton size="sm" variant="primary" onClick={bulkAcknowledge}>Mark acknowledged</HFButton>
            <HFButton size="sm" onClick={() => bulkSnooze(7)}>Snooze 7d…</HFButton>
            <HFButton size="sm">Assign…</HFButton>
            <HFButton size="sm" onClick={bulkResolve}>Mark resolved</HFButton>
            <HFButton size="sm" variant="subtle" onClick={() => setSelected(new Set())}>Clear</HFButton>
          </div>
        </HFCard>
      ) : (
        <HFCard style={{marginBottom:HF.gap, overflow:'visible'}} padding={12}>
          <HFFilterBar right={<>
            <span style={{fontSize:11.5, color: HF.ink3, fontFamily:HF.mono, fontVariantNumeric:'tabular-nums'}}>
              {view === 'list'
                ? (listData.total ?? 0).toLocaleString()
                : (tab === 'all' ? lifecycleCounts.total : (lifecycleCounts[tab] ?? 0)).toLocaleString()
              } total
            </span>
          </>}>
            <HFSearch placeholder="Search ID, book, URL, detail…" width={260} value={searchQ} onChange={setSearchQ}/>
            <HFFilter label="Shop"      value={shopFilter}  options={['all', ...availableShops]} onChange={setShopFilter}/>
            <HFFilter label="Severity"  value={sevFilter}   options={['all','critical','warning']}                            onChange={setSevFilter}/>
            <HFFilter label="Type"      value={typeFilter}  options={['all', ...HF_ISSUE_TYPES.map(t=>t.type)]}                onChange={setTypeFilter}/>
            <span style={{display:'inline-flex', alignItems:'center', gap:6}}>
              <span style={{fontSize:12.5, color:HF.ink3}}>Run</span>
              <input
                type="text" placeholder="any"
                value={runFilter === 'any' ? '' : runFilter}
                onChange={e => setRunFilter(e.target.value || 'any')}
                style={{
                  width: 80, height: 30, padding:'4px 8px',
                  border:`1px solid ${HF.borderStrong}`, borderRadius:6,
                  fontSize:12.5, fontFamily: HF.mono, color: HF.ink,
                  background: HF.surface,
                }}
              />
            </span>
          </HFFilterBar>
        </HFCard>
      )}

      {/* View toggle — segmented control. Two equal-weight options, joined pill. */}
      <div style={{marginBottom: HF.gap, display:'flex', gap:12, alignItems:'center', flexWrap:'wrap'}}>
        <span style={{
          display:'inline-flex',
          border:`1px solid ${HF.borderStrong}`,
          borderRadius:7,
          padding:2,
          background:HF.subtle,
          boxShadow:'inset 0 1px 0 rgba(16,24,40,.02)',
        }}>
          {[
            { id:'by_type', label:'By type' },
            { id:'list',    label:'List' },
          ].map(m => {
            const active = view === m.id;
            return (
              <button key={m.id} onClick={() => setView(m.id)} style={{
                all:'unset', cursor:'pointer',
                padding:'5px 14px', minWidth:88,
                fontSize:12.5, fontWeight: active ? 600 : 500,
                fontFamily:HF.sans,
                color: active ? HF.ink : HF.ink3,
                background: active ? HF.surface : 'transparent',
                border: active ? `1px solid ${HF.border}` : '1px solid transparent',
                borderRadius:5,
                boxShadow: active ? '0 1px 2px rgba(16,24,40,.06)' : 'none',
                textAlign:'center',
                transition:'background 120ms, color 120ms',
              }}>{m.label}</button>
            );
          })}
        </span>
        {view === 'by_type' && (
          <span style={{display:'inline-flex', alignItems:'center', gap:6, marginLeft:'auto', fontSize:12, color:HF.ink3}}>
            Sort
            <HFFilter
              label="" value={byTypeSort}
              options={['priority','count','type']}
              onChange={v => setByTypeSort(v)}
              allLabel="priority"
            />
          </span>
        )}
      </div>

      {false && (
        <>
          <HFCard flush style={{marginBottom:HF.gap}}>
            <div style={{
              padding:`10px ${HF.cardP}px`,
              background:HF.subtle, borderBottom:`1px solid ${HF.border}`,
              fontSize:12, color:HF.ink3, lineHeight:1.5,
            }}>
              Waves removed — use filters (Shop + Type + Run) on the List view to get the same grouping.
            </div>
            {itemWaves.map((w, i, arr) => {
              const meta = HF_ISSUE_TYPES.find(t => t.type === w.type) || {};
              const tone = meta.tone || 'neutral';
              const newCount = w.count - w.ack;
              return (
                <div key={w.id} style={{
                  padding:`14px ${HF.cardP}px`,
                  borderBottom: i < arr.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
                  display:'grid', gridTemplateColumns:'auto 1fr auto auto', gap:16, alignItems:'center',
                }}>
                  <span style={{
                    width:32, height:32, borderRadius:6,
                    background: tone==='err'? HF.errSoft : tone==='warn'? HF.warnSoft : HF.subtle,
                    border:`1px solid ${tone==='err'? HF.errBorder : tone==='warn'? HF.warnBorder : HF.border}`,
                    color: tone==='err'? HF.errInk : tone==='warn'? HF.warnInk : HF.ink3,
                    display:'flex', alignItems:'center', justifyContent:'center',
                    fontFamily:HF.mono, fontSize:14, fontWeight:700, flexShrink:0,
                  }}>{tone==='err'?'!':tone==='warn'?'⚠':'·'}</span>
                  <div style={{display:'flex', flexDirection:'column', gap:4, minWidth:0}}>
                    <div style={{display:'flex', alignItems:'center', gap:10, flexWrap:'wrap'}}>
                      <span style={{fontFamily:HF.mono, fontSize:13, color:HF.ink, fontWeight:600}}>{w.type}</span>
                      {w.shop && <>
                        <span style={{color:HF.ink5}}>·</span>
                        <span style={{fontSize:12.5, color:HF.ink2}}>{w.shop}</span>
                      </>}
                      <span style={{color:HF.ink5}}>·</span>
                      <a href="#" onClick={(e)=>{e.preventDefault(); goto('run-detail', {id:w.run});}} style={{
                        fontFamily:HF.mono, fontSize:12, color:HF.accentInk, textDecoration:'none', fontWeight:500,
                      }}>run #{w.run}</a>
                      {w.ack > 0 && <HFPill tone="accent">{w.ack} acked</HFPill>}
                    </div>
                    <div style={{fontSize:12, color:HF.ink3, lineHeight:1.5, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>
                      {w.span}
                      {w.sample && <span style={{color:HF.ink4, fontFamily:HF.mono, marginLeft:8}}>e.g. {w.sample}</span>}
                    </div>
                  </div>
                  <div style={{display:'flex', flexDirection:'column', alignItems:'flex-end', gap:2}}>
                    <span style={{
                      fontFamily:HF.mono, fontSize:18, fontWeight:600, lineHeight:1,
                      color: tone==='err'? HF.errInk : tone==='warn'? HF.warnInk : HF.ink,
                      fontVariantNumeric:'tabular-nums',
                    }}>{newCount.toLocaleString()}</span>
                    <span style={{fontFamily:HF.mono, fontSize:10.5, color:HF.ink4, textTransform:'uppercase', letterSpacing:0.4}}>new</span>
                  </div>
                  <div style={{display:'flex', gap:6, alignItems:'center'}}>
                    <HFButton size="sm" variant="primary">Ack wave</HFButton>
                    <HFButton size="sm" onClick={() => { setTypeFilter(w.type); if (w.shop) setShopFilter(w.shop); setRunFilter(String(w.run)); setView('list'); }}>View</HFButton>
                  </div>
                </div>
              );
            })}
          </HFCard>

          {/* Run failures — separate section, different shape */}
          <HFCard
            title="Run failures"
            sub={`${runFailureWaves.length} runs failed — these are run-level, not item-level. Click to open the run.`}
            flush
          >
            {runFailureWaves.map((w, i, arr) => (
              <div key={w.id} style={{
                padding:`12px ${HF.cardP}px`,
                borderBottom: i < arr.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
                display:'grid', gridTemplateColumns:'auto 1fr auto', gap:14, alignItems:'center',
                cursor:'pointer',
              }}
              className="hf-row"
              onClick={() => goto('run-detail', { id:w.run })}>
                <span style={{
                  display:'inline-flex', alignItems:'center', justifyContent:'center',
                  width:28, height:28, borderRadius:6,
                  background:HF.errSoft, border:`1px solid ${HF.errBorder}`,
                  color:HF.errInk, fontFamily:HF.mono, fontWeight:700,
                }}>!</span>
                <div style={{display:'flex', flexDirection:'column', gap:2, minWidth:0}}>
                  <div style={{display:'flex', alignItems:'center', gap:8}}>
                    <span style={{fontFamily:HF.mono, fontSize:13, color:HF.ink, fontWeight:600}}>run #{w.run}</span>
                    <HFPill tone="err">failed</HFPill>
                  </div>
                  <span style={{fontSize:12, color:HF.ink3, fontFamily:HF.mono, lineHeight:1.5}}>{w.span} · {w.firstSeen}</span>
                </div>
                <div style={{display:'flex', gap:6}}>
                  <HFButton size="sm">Re-run</HFButton>
                  <HFButton size="sm">Open run</HFButton>
                </div>
              </div>
            ))}
          </HFCard>
        </>
      )}

      {view === 'by_type' && (
        <HFCard flush>
          {byTypeRows.map((r, i, arr) => (
            <div key={r.type} style={{
              padding:`14px ${HF.cardP}px`,
              borderBottom: i < arr.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
              display:'grid', gridTemplateColumns:'auto 1fr auto auto auto', gap:18, alignItems:'center',
            }}>
              <span style={{
                width:8, height:8, borderRadius:'50%', flexShrink:0,
                background: r.tone === 'err' ? HF.err : r.tone === 'warn' ? HF.warn : HF.ink4,
              }}/>
              <div style={{display:'flex', flexDirection:'column', gap:3, minWidth:0}}>
                <span style={{fontFamily: HF.mono, fontSize: 13, color: HF.ink, fontWeight: 600}}>{r.type}</span>
                <span style={{fontSize:11.5, color: HF.ink3}}>
                  <HFPill tone={sevTone[r.sev]} style={{marginRight:6}}>{r.sev}</HFPill>
                  {r.direction === 'up'   && <span style={{color:HF.errInk, fontFamily:HF.mono, fontWeight:500}}>▲ {r.deltaPct}% / 14d</span>}
                  {r.direction === 'down' && <span style={{color:HF.okInk, fontFamily:HF.mono, fontWeight:500}}>▼ {Math.abs(r.deltaPct)}% / 14d</span>}
                  {r.direction === 'flat' && <span style={{color:HF.ink4, fontFamily:HF.mono}}>flat / 14d</span>}
                </span>
              </div>
              <HFIssueSparkline data={r.trend} tone={r.direction === 'up' ? 'err' : r.direction === 'down' ? 'ok' : 'neutral'} w={100} h={28}/>
              <div style={{display:'flex', alignItems:'center', gap:18, fontFamily: HF.mono, fontVariantNumeric:'tabular-nums', fontSize:12.5}}>
                <HFPill tone={r.tone}>{r.newCount.toLocaleString()} new</HFPill>
                <span style={{color: HF.ink3, minWidth:60, textAlign:'right'}}>{r.total.toLocaleString()} total</span>
                <span style={{color: HF.ink4, minWidth:60, textAlign:'right'}}>Ack ({r.ack.toLocaleString()})</span>
              </div>
              <HFButton size="sm" variant="primary" onClick={() => { setTypeFilter(r.type); setView('list'); }}>View</HFButton>
            </div>
          ))}
        </HFCard>
      )}

      {false && (
        <HFCard flush>
          <div style={{
            display:'grid', gridTemplateColumns:'1fr 0.8fr 90px 90px 90px 80px',
            padding:`8px ${HF.cardP}px`, alignItems:'center',
            background:HF.subtle, borderBottom:`1px solid ${HF.border}`,
            fontSize:11, fontWeight:600, color:HF.ink3, textTransform:'uppercase', letterSpacing:0.5,
            gap: 14,
          }}>
            <span>Type</span><span>Shop</span><span style={{textAlign:'right'}}>New</span><span style={{textAlign:'right'}}>Total</span><span style={{textAlign:'right'}}>Ack</span><span/>
          </div>
          {byTypeShopRows.map((r, i, arr) => (
            <div key={r.type + r.shop} style={{
              padding:`9px ${HF.cardP}px`,
              borderBottom: i < arr.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
              display:'grid', gridTemplateColumns:'1fr 0.8fr 90px 90px 90px 80px',
              gap:14, alignItems:'center',
            }}>
              <div style={{display:'flex', alignItems:'center', gap:10, minWidth:0}}>
                <span style={{
                  width:7, height:7, borderRadius:'50%', flexShrink:0,
                  background: r.tone === 'err' ? HF.err : r.tone === 'warn' ? HF.warn : HF.ink4,
                }}/>
                <span style={{fontFamily: HF.mono, fontSize: 12.5, color: HF.ink, fontWeight: 500}}>{r.type}</span>
              </div>
              <span style={{fontSize: 12.5, color: HF.ink2}}>{r.shop}</span>
              <span style={{fontFamily: HF.mono, fontSize: 12, color: r.tone === 'err' ? HF.errInk : HF.warnInk, fontVariantNumeric:'tabular-nums', textAlign:'right', fontWeight:500}}>{(r.total - r.ack).toLocaleString()}</span>
              <span style={{fontFamily: HF.mono, fontSize: 12, color: HF.ink3, fontVariantNumeric:'tabular-nums', textAlign:'right'}}>{r.total.toLocaleString()}</span>
              <span style={{fontFamily: HF.mono, fontSize: 12, color: HF.ink4, fontVariantNumeric:'tabular-nums', textAlign:'right'}}>{r.ack.toLocaleString()}</span>
              <HFButton size="sm">View</HFButton>
            </div>
          ))}
        </HFCard>
      )}

      {view === 'list' && (
        <HFCard flush>
          {listLoading ? (
            <div style={{padding:'32px 0', textAlign:'center', color:HF.ink3, fontSize:13}}>Loading…</div>
          ) : listRows.length === 0 ? (
            <HFEmptyState
              title={
                tab === 'resolved' ? 'No resolved issues yet' :
                tab === 'snoozed'  ? 'No snoozed issues' :
                tab === 'acknowledged' ? 'Nothing acknowledged in this filter' :
                'No issues match these filters'
              }
              sub={
                tab === 'resolved' ? 'Issues move here automatically when the next clean run passes for the same URL.' :
                tab === 'snoozed'  ? 'Snooze an issue to hide it from New until a wake-up date.' :
                tab === 'acknowledged' ? 'Tick rows in List view and click "Mark acknowledged" to move them here.' :
                'Try clearing filters or switching tabs.'
              }
            />
          ) : (
          <>
          <ListRows
            HF={HF}
            rows={listRows}
            selected={selected}
            toggleOne={toggleOne}
            toggleAllVisible={toggleAllVisible}
            allVisibleSelected={allVisibleSelected}
            someVisibleSelected={someVisibleSelected}
            expanded={expanded}
            setExpanded={setExpanded}
            sevTone={sevTone}
            fixActionsFor={fixActionsFor}
            goto={goto}
          />
          {listData.total > 50 && (
            <div style={{padding:'12px 16px', display:'flex', alignItems:'center', gap:8, borderTop:`1px solid ${HF.border}`, justifyContent:'flex-end'}}>
              <HFButton size="sm" disabled={listPage <= 1} onClick={() => setListPage(p => Math.max(1, p - 1))}>← Prev</HFButton>
              <span style={{fontSize:12.5, color:HF.ink3, fontFamily:HF.mono}}>
                {listPage} / {Math.ceil(listData.total / 50)}
              </span>
              <HFButton size="sm" disabled={listPage >= Math.ceil(listData.total / 50)} onClick={() => setListPage(p => p + 1)}>Next →</HFButton>
            </div>
          )}
          </>
          )}
        </HFCard>
      )}
    </HFShell>
  );
}

// ── List view with bulk select + inline expand-row preview ──
function ListRows({ HF, rows, selected, toggleOne, toggleAllVisible, allVisibleSelected, someVisibleSelected, expanded, setExpanded, sevTone, fixActionsFor, goto }) {
  const COLS = '36px 1.1fr 0.7fr 1.2fr 0.7fr 1.3fr 1.4fr 1.8fr 0.7fr 28px';
  return (
    <div>
      {/* Header */}
      <div style={{
        display:'grid', gridTemplateColumns:COLS, gap:0,
        padding:`8px ${HF.cardP}px`,
        background:HF.subtle, borderBottom:`1px solid ${HF.border}`,
        fontSize:11, fontWeight:600, color:HF.ink3, textTransform:'uppercase', letterSpacing:0.5,
        alignItems:'center',
      }}>
        <span onClick={toggleAllVisible} style={{display:'flex', alignItems:'center', justifyContent:'center', cursor:'pointer'}}>
          <span style={{
            width:14, height:14, borderRadius:3,
            border:`1.5px solid ${(allVisibleSelected || someVisibleSelected) ? HF.accentInk : HF.ink5}`,
            background: (allVisibleSelected || someVisibleSelected) ? HF.accentInk : 'transparent',
            display:'flex', alignItems:'center', justifyContent:'center',
          }}>
            {allVisibleSelected && (
              <svg width="9" height="9" viewBox="0 0 10 10" fill="none">
                <path d="M2 5.5L4 7.5L8 2.5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            )}
            {!allVisibleSelected && someVisibleSelected && <span style={{width:7, height:1.8, background:'#fff', borderRadius:1}}/>}
          </span>
        </span>
        <span>ID</span>
        <span>SEVERITY</span>
        <span>TYPE</span>
        <span>SHOP</span>
        <span>BOOK</span>
        <span>URL</span>
        <span>DETAIL</span>
        <span>WHEN</span>
        <span/>
      </div>
      {rows.map((r) => {
        const checked = selected.has(r.id);
        const isExpanded = expanded === r.id;
        return (
          <React.Fragment key={r.id}>
            <div
              className="hf-row"
              onClick={() => goto('issue-detail', { id: r.id, type: r.type, sev: r.sev, lifecycle: r.lifecycle, shop: r.shop, book: r.book, url: r.url, age: r.age })}
              style={{
                display:'grid', gridTemplateColumns:COLS, gap:0,
                padding:`10px ${HF.cardP}px`,
                borderBottom: `1px solid ${HF.borderFaint}`,
                alignItems:'center', cursor:'pointer',
                background: checked ? HF.accentSoft : isExpanded ? HF.subtle : 'transparent',
                fontSize:13,
              }}
            >
              <span onClick={(e) => { e.stopPropagation(); toggleOne(r.id); }} style={{display:'flex', alignItems:'center', justifyContent:'center', cursor:'pointer'}}>
                <span style={{
                  width:14, height:14, borderRadius:3,
                  border:`1.5px solid ${checked ? HF.accentInk : HF.ink5}`,
                  background: checked ? HF.accentInk : 'transparent',
                  display:'flex', alignItems:'center', justifyContent:'center',
                }}>
                  {checked && (
                    <svg width="9" height="9" viewBox="0 0 10 10" fill="none">
                      <path d="M2 5.5L4 7.5L8 2.5" stroke="#fff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                    </svg>
                  )}
                </span>
              </span>
              <span style={{fontFamily:HF.mono, color:HF.accentInk, fontWeight:500, fontVariantNumeric:'tabular-nums', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', paddingRight:8}}>{r.id}</span>
              <span><HFPill tone={sevTone[r.sev]}>{r.sev}</HFPill></span>
              <span style={{fontFamily:HF.mono, fontSize:12.5, color:HF.ink2, paddingRight:8, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{r.type}</span>
              <span style={{fontFamily:HF.mono, fontSize:12.5, color: r.shop?HF.ink3:HF.ink4, paddingRight:8}}>{r.shop || '—'}</span>
              <span style={{paddingRight:8, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', color:r.book?HF.ink:HF.ink4, fontSize:12.5}}>{r.book || '—'}</span>
              <span style={{fontFamily:HF.mono, fontSize:12, paddingRight:8, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>
                {r.url ? <span style={{color:HF.ink2, textDecoration:'underline', textDecorationColor:HF.ink4, textUnderlineOffset:2}}>{r.url.replace(/^https?:\/\//, '').slice(0, 38)}</span> : r.run ? <span style={{color:HF.accentInk, textDecoration:'underline', textUnderlineOffset:2}}>{r.run}</span> : <span style={{color:HF.ink4}}>—</span>}
              </span>
              <span style={{color:HF.ink2, fontSize:12.5, paddingRight:8, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{r.detail}</span>
              <span style={{fontFamily:HF.mono, fontSize:12, color:HF.ink3}}>◷ {r.age}</span>
              <span
                onClick={(e) => { e.stopPropagation(); setExpanded(isExpanded ? null : r.id); }}
                style={{display:'flex', justifyContent:'flex-end', cursor:'pointer', color:HF.ink4, transform: isExpanded ? 'rotate(90deg)' : 'none', transition:'transform 120ms'}}
              >{HF_ICONS.chevron}</span>
            </div>
            {isExpanded && (
              <div style={{
                padding:`14px ${HF.cardP}px 14px 52px`,
                borderBottom:`1px solid ${HF.borderFaint}`,
                background:HF.subtle,
                display:'grid', gridTemplateColumns:'1.4fr 1fr', gap:HF.gap,
              }}>
                <div style={{display:'flex', flexDirection:'column', gap:8, minWidth:0}}>
                  <div style={{fontSize:10.5, color:HF.ink4, textTransform:'uppercase', letterSpacing:0.6, fontWeight:600}}>Raw extraction snippet</div>
                  <pre style={{
                    margin:0, padding:'10px 12px',
                    background:'#0F1419', color:'#D9E0E6', borderRadius:6,
                    fontFamily:HF.mono, fontSize:11, lineHeight:1.5,
                    overflow:'auto', whiteSpace:'pre',
                  }}>{rawSnippetFor(r)}</pre>
                </div>
                <div style={{display:'flex', flexDirection:'column', gap:8}}>
                  <div style={{fontSize:10.5, color:HF.ink4, textTransform:'uppercase', letterSpacing:0.6, fontWeight:600}}>Fix this</div>
                  <div style={{display:'flex', flexWrap:'wrap', gap:6}}>
                    {fixActionsFor(r.type).map((a, idx) => (
                      <HFButton key={idx} size="sm" variant={a.primary?'primary':'default'} onClick={(e) => { e.stopPropagation(); a.action && a.action(); }}>{a.label}</HFButton>
                    ))}
                  </div>
                  <div style={{fontSize:11.5, color:HF.ink3, lineHeight:1.5, marginTop:4}}>
                    Part of a wave of <b style={{color:HF.ink}}>{((groupsData.find(g => g.issue_type === r.type)?.total) || 0).toLocaleString()}</b> {r.type} issues
                    {r.shop ? <> in <b style={{color:HF.ink}}>{r.shop}</b></> : ''}
                    {r.runRef ? <> · run <a href="#" onClick={(e)=>{e.preventDefault(); e.stopPropagation(); goto('run-detail', {id:r.runRef});}} style={{color:HF.accentInk, textDecoration:'none', fontFamily:HF.mono}}>#{r.runRef}</a></> : ''}.
                  </div>
                </div>
              </div>
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
}

// Synthetic raw-HTML / JSON snippet illustrating what the parser saw.
function rawSnippetFor(r) {
  switch (r.type) {
    case 'missing_price':
      return `<div class="product-page">
  <h1>${r.book || 'Unknown'}</h1>
  <span class="price-tag">         </span>   ← empty, selector matched but text empty
  <span class="old-price">€19.90</span>
</div>`;
    case 'match_isbn_drift':
      return `extracted_isbn:  9780062316098   ← shop reports
canonical_isbn:  9780062316097   ← matched book ID 1841
edit_distance:   1`;
    case 'invalid_isbn':
      return `extracted_isbn:  978006231609X   ← non-digit 'X' in middle
length:          13 (ok)
check_digit:     FAILED`;
    case 'price_spike':
      return `previous_price:  16.50 EUR (run #405)
current_price:   12.99 EUR (run ${r.runRef})
delta:           -21.3%   threshold ±15%`;
    case 'discover_fetch_failed':
      return `GET ${r.url || '/sitemap-old.xml'}
HTTP/1.1 404 Not Found
content-length: 0`;
    case 'scrape_run_failed':
      return `run.status:   failed
phase:        scan
progress:     67%
close_reason: timeout · worker w-1 unresponsive 91s`;
    default:
      return `(no preview available for ${r.type})`;
  }
}

Object.assign(window, { HFIssues, HFIssueSparkline });
