// Hi-fi Cron (schedules), Issues, Prices pages

function HFCron({ nav, goto }) {
  const HF = getHF();

  const jobsRaw = [
    { name:'vaga.scan.hourly',      cron:'0 * * * *',    next:'in 48m',  last:'12m ago',  lastStatus:'ok',   avgDur:'12m',  enabled:true,  shop:'vaga'   },
    { name:'vaga.discover.daily',   cron:'0 3 * * *',    next:'in 12h',  last:'11h ago',  lastStatus:'ok',   avgDur:'42m',  enabled:true,  shop:'vaga'   },
    { name:'vaga.prices.daily',     cron:'0 5 * * *',    next:'in 14h',  last:'9h ago',   lastStatus:'ok',   avgDur:'1h 02m', enabled:true, shop:'vaga'   },
    { name:'knygos.scan.daily',     cron:'0 4 * * *',    next:'in 13h',  last:'10h ago',  lastStatus:'ok',   avgDur:'18m',  enabled:true,  shop:'knygos' },
    { name:'knygos.discover.daily', cron:'0 2 * * *',    next:'in 11h',  last:'3h ago',   lastStatus:'fail', avgDur:'22m',  enabled:true,  shop:'knygos' },
    { name:'knygos.prices.daily',   cron:'30 5 * * *',   next:'in 14h',  last:'9h ago',   lastStatus:'ok',   avgDur:'22m',  enabled:true,  shop:'knygos' },
    { name:'cleanup.stale.weekly',  cron:'0 0 * * 0',    next:'in 3d',   last:'4d ago',   lastStatus:'ok',   avgDur:'4m',   enabled:true,  shop:'—'      },
    { name:'validate.all.nightly',  cron:'0 1 * * *',    next:'in 10h',  last:'14h ago',  lastStatus:'ok',   avgDur:'8m',   enabled:false, shop:'—'      },
  ];

  const jobs = jobsRaw.map(j => ({ ...j, state: j.enabled ? (j.lastStatus==='fail'?'failing':'active') : 'disabled' }));

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
        { label:'Schedules',   value:'8', delta:<span style={{color:HF.ink3}}>7 enabled · 1 disabled</span> },
        { label:'Next run',    value:'48m', delta:<span style={{color:HF.accentInk}}>vaga.scan.hourly</span>, tone:'accent' },
        { label:'Last 24h',    value:'38 runs', delta:<span style={{color:HF.okInk}}>36 ok · 2 failed</span> },
        { label:'Success rate',value:'94.7%',   delta:<span style={{color:HF.okInk}}>30d</span>, tone:'ok' },
        { label:'CPU used',    value:'4.2h',    delta:<span style={{color:HF.ink3}}>today</span> },
      ]}/>

      <HFCard style={{marginBottom:HF.gap}} padding={12}>
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
            { key:'enabled', label:'', w:'0.5fr', align:'right', cell:v => (
              <span style={{
                display:'inline-flex', width:32, height:18, borderRadius:10,
                background: v? HF.accent : HF.border, padding:2, alignItems:'center',
                justifyContent: v? 'flex-end' : 'flex-start', transition:'all 120ms',
              }}>
                <span style={{width:14, height:14, borderRadius:'50%', background:'#fff', boxShadow:'0 1px 2px rgba(0,0,0,.2)'}}/>
              </span>
            )},
            { key:'_', label:'', w:'40px', align:'right', cell:() => <HFButton size="sm" variant="subtle"><span style={{display:'flex'}}>{HF_ICONS.play}</span></HFButton> },
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

  // Flat list of actual issues — each row is a single detected event, not a group.
  // `known: true` = someone has acknowledged it's expected behavior, not a bug.
  const seed = [
    { id:'ISS-4128', type:'parser_error',     sev:'high',   shop:'knygos', book:'—',                                 url:'/discover?p=7',                  detail:'CSS selector .price returned null',       age:'3m ago',    known:false },
    { id:'ISS-4127', type:'price_regression', sev:'high',   shop:'vaga',   book:'Clean Code',                        url:'/p/clean-code',                  detail:'€32.90 → €28.50  (−13.4%)',               age:'1h ago',    known:false },
    { id:'ISS-4126', type:'duplicate_sku',    sev:'high',   shop:'vaga',   book:'Sapiens',                           url:'/p/sapiens-3',                   detail:'SKU 9780062316097 matches 2 other URLs',  age:'2h ago',    known:false },
    { id:'ISS-4125', type:'broken_url',       sev:'medium', shop:'vaga',   book:'Atomic Habits',                     url:'/popular/atomic-habits-old',     detail:'HTTP 404 for 3 consecutive checks',       age:'4h ago',    known:false },
    { id:'ISS-4124', type:'missing_isbn',     sev:'medium', shop:'vaga',   book:'Lietuvos istorija, t. II',          url:'/p/lietuvos-istorija-2',         detail:'ISBN field empty after 2 retries',        age:'5h ago',    known:false },
    { id:'ISS-4123', type:'parser_error',     sev:'high',   shop:'knygos', book:'—',                                 url:'/discover?p=12',                 detail:'Timeout after 30s · rate-limited?',       age:'6h ago',    known:false },
    { id:'ISS-4122', type:'price_regression', sev:'high',   shop:'vaga',   book:'Dune',                              url:'/p/dune',                        detail:'€14.20 → €13.50  (−4.9%)',                age:'8h ago',    known:false },
    { id:'ISS-4121', type:'missing_isbn',     sev:'medium', shop:'knygos', book:'Thinking, Fast and Slow',           url:'/p/thinking-fast-slow',          detail:'ISBN field empty',                        age:'10h ago',   known:true  },
    { id:'ISS-4120', type:'title_too_short',  sev:'low',    shop:'knygos', book:'—',                                 url:'/p/untitled-4a2f',               detail:'Title is 3 chars · minimum 8',            age:'11h ago',   known:false },
    { id:'ISS-4119', type:'broken_url',       sev:'medium', shop:'vaga',   book:'—',                                 url:'/popular/2019-summer',           detail:'HTTP 404',                                age:'14h ago',   known:true  },
    { id:'ISS-4118', type:'stale_listing',    sev:'low',    shop:'vaga',   book:'The Pragmatic Programmer',          url:'/p/pragmatic-programmer',        detail:'Not updated in 42 days',                  age:'18h ago',   known:false },
    { id:'ISS-4117', type:'missing_isbn',     sev:'medium', shop:'vaga',   book:'Educated',                          url:'/p/educated',                    detail:'ISBN field empty',                        age:'1 day ago', known:false },
    { id:'ISS-4116', type:'invalid_year',     sev:'low',    shop:'knygos', book:'Pan Tadeusz',                       url:'/p/pan-tadeusz',                 detail:'Year = 1834 · min 1900',                  age:'1 day ago', known:true  },
    { id:'ISS-4115', type:'price_regression', sev:'high',   shop:'vaga',   book:'Zero to One',                       url:'/p/zero-to-one',                 detail:'€18.50 → €14.90  (−19.5%)',               age:'1 day ago', known:false },
    { id:'ISS-4114', type:'duplicate_sku',    sev:'high',   shop:'vaga',   book:'Sapiens',                           url:'/p/sapiens-compact',             detail:'SKU 9780062316097 matches 1 other URL',   age:'1 day ago', known:false },
    { id:'ISS-4113', type:'broken_url',       sev:'medium', shop:'vaga',   book:'—',                                 url:'/popular/best-of-2018',          detail:'HTTP 410 Gone',                           age:'2 days ago',known:true  },
    { id:'ISS-4112', type:'missing_isbn',     sev:'medium', shop:'knygos', book:'Baltoji gulbė',                     url:'/p/baltoji-gulbe',               detail:'ISBN field empty',                        age:'2 days ago',known:false },
    { id:'ISS-4111', type:'parser_error',     sev:'high',   shop:'knygos', book:'—',                                 url:'/discover?p=3',                  detail:'Expected <div.price>, got <span>',         age:'3 days ago',known:false },
    { id:'ISS-4110', type:'title_too_short',  sev:'low',    shop:'knygos', book:'—',                                 url:'/p/ab',                          detail:'Title is 2 chars · minimum 8',            age:'3 days ago',known:false },
    { id:'ISS-4109', type:'stale_listing',    sev:'low',    shop:'vaga',   book:'Homo Deus',                         url:'/p/homo-deus',                   detail:'Not updated in 38 days',                  age:'4 days ago',known:true  },
  ];

  // Persist known state + selection in component state (prototype — resets on reload).
  const [knownMap, setKnownMap] = React.useState(() => {
    const m = {}; seed.forEach(r => { m[r.id] = !!r.known; }); return m;
  });
  const [selected, setSelected] = React.useState(() => new Set());

  const allIssues = React.useMemo(
    () => seed.map(r => ({ ...r, known: !!knownMap[r.id] })),
    [knownMap]
  );

  const sevTone = { high:'err', medium:'warn', low:'neutral' };

  const byTab = {
    open:     allIssues.filter(i => !i.known),   // not-yet-acknowledged
    triage:   allIssues.filter(i => i.sev === 'high' && !i.known),
    known:    allIssues.filter(i => i.known),     // acknowledged / expected
    snoozed:  [],
    resolved: [],
    all:      allIssues,
  };
  const tabSource = byTab[tab] || allIssues;

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
        { label:'Open',      value:byTab.open.length, delta:<span style={{color:HF.errInk}}>▲ 12 · 24h</span>, tone:'err' },
        { label:'High sev',  value:byTab.triage.length,  delta:<span style={{color:HF.errInk}}>price + parser</span>, tone:'err' },
        { label:'Known',     value:byTab.known.length,  delta:<span style={{color:HF.ink3}}>acknowledged</span> },
        { label:'Resolved 7d', value:'321', delta:<span style={{color:HF.okInk}}>▲ 42 vs prev</span>, tone:'ok' },
        { label:'MTTR',      value:'2.4d', delta:<span style={{color:HF.ink3}}>median</span> },
      ]}/>

      <HFCard style={{marginBottom:HF.gap}}>
        <div style={{padding:`0 ${HF.cardP}px`}}>
          <HFTabs active={tab} onChange={setTab} tabs={[
            { id:'open', label:'Open', count:byTab.open.length },
            { id:'triage', label:'Needs triage', count:byTab.triage.length },
            { id:'known', label:'Known', count:byTab.known.length },
            { id:'snoozed', label:'Snoozed', count:byTab.snoozed.length },
            { id:'resolved', label:'Resolved', count:321 },
            { id:'all', label:'All', count:byTab.all.length },
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
        <HFCard style={{marginBottom:HF.gap}} padding={12}>
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

  const deltas = [-1.10, -0.50, -0.20, 0, 0, 0.10, 0.20, 0.50, 1.00, 1.50, 2.00, 2.50, 3.00];
  const changes = [
    { book:'Sapiens',                        shop:'vaga',   old:'€21.00', new:'€19.90', pct:-5.2,  when:'12m ago' },
    { book:'Clean Code',                     shop:'vaga',   old:'€32.90', new:'€28.50', pct:-13.4, when:'1h ago'  },
    { book:'Atomic Habits',                  shop:'vaga',   old:'€16.50', new:'€17.90', pct:+8.5,  when:'2h ago'  },
    { book:'Thinking, Fast and Slow',        shop:'knygos', old:'€21.00', new:'€22.50', pct:+7.1,  when:'4h ago'  },
    { book:'Dune',                           shop:'vaga',   old:'€14.20', new:'€13.50', pct:-4.9,  when:'6h ago'  },
    { book:'The Lean Startup',               shop:'knygos', old:'€17.80', new:'€19.90', pct:+11.8, when:'8h ago'  },
    { book:'Zero to One',                    shop:'knygos', old:'€18.50', new:'€17.90', pct:-3.2,  when:'10h ago' },
    { book:'Educated',                       shop:'vaga',   old:'€13.90', new:'€14.90', pct:+7.2,  when:'12h ago' },
  ];

  const filters = useHFFilters(changes, {
    search: { fields: c => `${c.book} ${c.shop}` },
    filters: [
      { id:'shop', default:'all', match:(c,v) => c.shop === v },
      { id:'dir',  default:'all', match:(c,v) => v==='drop' ? c.pct < 0 : v==='rise' ? c.pct > 0 : c.pct === 0 },
      { id:'mag',  default:'any', match:(c,v) => v==='big' ? Math.abs(c.pct) >= 10 : Math.abs(c.pct) < 10 },
    ],
  });

  return (
    <HFShell {...nav} activePage="prices"
      title="Prices" subtitle="Price records across all books and shops. 412,550 data points since Feb 2024."
      breadcrumb={<><span>BookScraper</span><span style={{color:HF.ink5}}>/</span><span style={{color:HF.ink, fontWeight:500}}>Prices</span></>}
      actions={<HFButton><span style={{display:'flex'}}>{HF_ICONS.download}</span> Export CSV</HFButton>}
    >
      <HFKpiStrip items={[
        { label:'Price records',   value:'412,550', delta:<span style={{color:HF.okInk}}>▲ 1,204 · 24h</span>, tone:'ok' },
        { label:'Books tracked',   value:'15,140',  delta:<span style={{color:HF.ink3}}>with ≥1 price</span> },
        { label:'Avg change · 7d', value:'−0.8%',   delta:<span style={{color:HF.okInk}}>slight deflation</span>, tone:'ok' },
        { label:'Volatility',      value:'3.2%',    delta:<span style={{color:HF.ink3}}>σ · 30d</span> },
        { label:'Drops > 10%',     value:'42',      delta:<span style={{color:HF.errInk}}>last 7d</span>, tone:'err' },
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

      <HFCard title="Recent changes" sub="non-zero price movements"
              action={<a href="#" style={hfLink(HF)}>All changes {HF_ICONS.arrow}</a>}>
        <div style={{padding:`10px ${HF.cardP}px`, borderBottom:`1px solid ${HF.borderFaint}`}}>
          <HFFilterBar right={<>
            <span style={{fontSize:11.5, color: filters.activeCount? HF.accentInk : HF.ink4, fontFamily:HF.mono, fontVariantNumeric:'tabular-nums', fontWeight: filters.activeCount? 500 : 400}}>
              {filters.filtered.length} of {changes.length}
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
            { key:'old', label:'Was', w:'0.7fr', mono:true, align:'right', muted:true, sortable:true, sortVal:r=>parseFloat((r.old||'').replace(/[^\d.]/g,''))||0 },
            { key:'new', label:'Now', w:'0.7fr', mono:true, align:'right', sortable:true, sortVal:r=>parseFloat((r.new||'').replace(/[^\d.]/g,''))||0, cell:v => <span style={{color:HF.ink, fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v}</span> },
            { key:'pct', label:'Δ %', w:'0.7fr', mono:true, align:'right', sortable:true, sortVal:r=>r.pct, cell:v => <span style={{color: v<0?HF.errInk:v>0?HF.okInk:HF.ink3, fontWeight:600, fontVariantNumeric:'tabular-nums'}}>{v>0?'+':''}{v.toFixed(1)}%</span> },
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
