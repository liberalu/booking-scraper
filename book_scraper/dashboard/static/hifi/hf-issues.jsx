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

const HF_ISSUE_SCALE = {
  missing_price: 36242,
  match_isbn_drift: 9995,
  invalid_isbn: 6660,
  non_product_active: 5107,
  price_spike: 2929,
  discover_fetch_failed: 2591,
  unmatched_has_isbn: 2200,
  scrape_run_failed: 1218,
  product_url_non_book: 779,
};
// Trend curves: 14 daily counts ending today. Encodes whether the type is
// growing (regression!), flat (known), or shrinking (being fixed).
const HF_ISSUE_TREND = {
  missing_price:         [200, 220, 210, 230, 215, 240, 260, 280, 310, 350, 420, 600, 1900, 4200],   // spike
  match_isbn_drift:      [710, 720, 715, 710, 705, 700, 695, 700, 708, 712, 705, 700, 698, 690],     // flat
  invalid_isbn:          [820, 800, 780, 760, 720, 700, 680, 660, 640, 620, 600, 580, 560, 540],     // shrinking
  non_product_active:    [340, 350, 360, 365, 370, 380, 385, 390, 395, 400, 405, 410, 415, 420],     // gentle rise
  price_spike:           [180, 190, 200, 210, 220, 230, 220, 215, 210, 205, 200, 195, 190, 185],     // hump
  discover_fetch_failed: [60,  65,  62,  70,  75,  80,  78,  82,  90,  120, 140, 180, 220, 260],     // spike
  unmatched_has_isbn:    [170, 165, 168, 170, 172, 168, 170, 172, 175, 170, 168, 172, 170, 168],     // flat
  scrape_run_failed:     [85,  88,  90,  92,  95,  98,  100, 102, 105, 108, 110, 112, 115, 118],     // creep
  product_url_non_book:  [55,  58,  56,  60,  62,  58,  55,  52,  50,  48,  45,  42,  40,  38],     // shrinking
};
const HF_ISSUE_ACK = { match_isbn_drift: 4 };
const HF_ISSUE_LIFECYCLE_COUNTS = { new: 67721, acknowledged: 4, snoozed: 0, resolved: 0, all: 67725 };
const HF_NEW_TREND = [62000, 62300, 62700, 63100, 63600, 64100, 64600, 65000, 65500, 66100, 66400, 66700, 67100, 67721];

// Hand-authored waves. type × shop × run. Splits into item-level vs run-level.
const HF_ISSUE_WAVES = [
  { id:'W-407-missing_price-patogupirkti',     type:'missing_price',         shop:'patogupirkti', run:407, count:36242, ack:0,
    firstSeen:'4d ago',   lastSeen:'4d ago',   span:'parser hit at 07:14, 36,242 URLs by 09:42', sample:'/knyga/arturas-ir-maltazaro-kerstas-dvd' },
  { id:'W-406-match_isbn_drift-vaga',          type:'match_isbn_drift',      shop:'vaga',         run:406, count:9995, ack:4,
    firstSeen:'5d ago',   lastSeen:'5d ago',   span:'mid-run · ISBN selector drift on /knyga/* template', sample:'/knyga/sapiens' },
  { id:'W-407-invalid_isbn-knygos',            type:'invalid_isbn',          shop:'knygos.lt',    run:407, count:6660, ack:0,
    firstSeen:'4d ago',   lastSeen:'4d ago',   span:'all 6,660 from a single batch', sample:'/sapiens' },
  { id:'W-405-non_product_active-vaga',        type:'non_product_active',    shop:'vaga',         run:405, count:5107, ack:0,
    firstSeen:'7d ago',   lastSeen:'2d ago',   span:'recurring since classifier v2.13 rollout', sample:'/autoriai/yuval-noah-harari' },
  { id:'W-407-price_spike-vaga',               type:'price_spike',           shop:'vaga',         run:407, count:2929, ack:0,
    firstSeen:'4d ago',   lastSeen:'4d ago',   span:'site-wide promo banner picked up as list price', sample:'/knyga/atomic-habits' },
  { id:'W-408-discover_fetch_failed-knygos',   type:'discover_fetch_failed', shop:'knygos.lt',    run:408, count:2591, ack:0,
    firstSeen:'3d ago',   lastSeen:'3d ago',   span:'sitemap section /old-pages now returns 404', sample:'/sitemap-old.xml' },
  { id:'W-406-unmatched_has_isbn-patogupirkti',type:'unmatched_has_isbn',    shop:'patogupirkti', run:406, count:2200, ack:0,
    firstSeen:'5d ago',   lastSeen:'5d ago',   span:'matcher missed canonical books with diacritic-stripped titles', sample:'/knyga/baltoji-gulbe' },
  { id:'W-407-product_url_non_book-vaga',      type:'product_url_non_book',  shop:'vaga',         run:407, count:779, ack:0,
    firstSeen:'4d ago',   lastSeen:'4d ago',   span:'DVDs + stationery picked up by /knyga/* product matcher', sample:'/knyga/lietuva-sieninis-kalendorius' },
  // Run-failure waves are singular events — rendered in their own section.
  { id:'W-429-scrape_run_failed', type:'scrape_run_failed', shop:null, run:429, count:1, ack:0,
    firstSeen:'1d ago', lastSeen:'1d ago', span:'phase=scan · failed at 67% · timeout', sample:null, runFailure:true },
  { id:'W-427-scrape_run_failed', type:'scrape_run_failed', shop:null, run:427, count:1, ack:0,
    firstSeen:'1d ago', lastSeen:'1d ago', span:'phase=discover · failed at 12% · auth_required', sample:null, runFailure:true },
];

// Reconcile wave totals with global lifecycle counts.
(() => {
  const sum = HF_ISSUE_WAVES.reduce((s, w) => s + w.count, 0);
  const diff = HF_ISSUE_LIFECYCLE_COUNTS.new + HF_ISSUE_LIFECYCLE_COUNTS.acknowledged - sum;
  if (diff > 0) HF_ISSUE_WAVES[0].count += diff;
})();

const HF_LIFECYCLE_HELP = {
  new:          'Automatically generated, not yet reviewed by anyone.',
  acknowledged: 'Operator has seen it and accepted it as a real problem to work on.',
  snoozed:      'Hidden from the New tab until a wake-up date.',
  resolved:     'Fixed — either verified clean by a follow-up run, or manually closed.',
  all:          'Every issue regardless of lifecycle state.',
};

const HF_SAVED_FILTERS = [
  { id:'critical_today',  label:'Critical · today',      pin:true,  vals:{ sev:'critical', run:'407' } },
  { id:'parser_regress',  label:'Parser regressions',    pin:true,  vals:{ type:'missing_price' } },
  { id:'isbn_problems',   label:'ISBN problems',         pin:false, vals:{ type:'invalid_isbn' } },
  { id:'patogupirkti',    label:'patogupirkti only',     pin:false, vals:{ shop:'patogupirkti' } },
];

// Per-row seed for the List view.
function makeHFIssueSeed() {
  const URLS = {
    vaga:        ['/knyga/sapiens', '/knyga/atomic-habits', '/knyga/mazasis-princas', '/knyga/dune-lt', '/knyga/1984', '/lietuva-sieninis-kalendorius', '/laimes-kalendorius-darbo-kny', '/uzrasu-knyga-a5', '/coliuke-perskaityk-ir-nuspalvink'],
    'knygos.lt': ['/sapiens', '/atomic-habits', '/dune', '/1984-orwell', '/educated', '/lean-startup', '/zero-to-one'],
    patogupirkti:['/knyga/arturas-ir-maltazaro-kerstas-dvd', '/knyga/hello-kitty-atostogu', '/knyga/rytai-vakarai', '/knyga/baltoji-gulbe', '/knyga/saulute-debesy'],
    krisostomus: ['/en/sapiens', '/en/atomic-habits', '/en/dune'],
  };
  const BOOKS = {
    vaga: ['Sapiens', 'Atomic Habits', 'Mažasis princas', 'Dune', '1984', 'Lietuva, sieninis kalendorius', 'Laimės kalendorius - darbo kny…', 'Užrašų knyga A5 80g linija LEAF', 'Coliukė. Perskaityk ir nuspalvin…'],
    'knygos.lt': ['Sapiens', 'Atomic Habits', 'Dune', '1984', 'Educated', 'The Lean Startup', 'Zero to One'],
    patogupirkti: ['Arturas ir Maltazaro kerštas (DVD)', 'Hello Kitty. Atostogų išvyka (lipdukų knygelė su užduotėlėmis)', 'Rytai - Vakarai: komparatyvistinės studijos IX', 'Baltoji gulbė', 'Saulute debesy'],
    krisostomus: ['Sapiens', 'Atomic Habits', 'Dune'],
  };
  const dist = [
    ['missing_price',         6, 'patogupirkti', 407],
    ['match_isbn_drift',      4, 'vaga',         406],
    ['invalid_isbn',          3, 'knygos.lt',    407],
    ['non_product_active',    3, 'vaga',         405],
    ['price_spike',           3, 'vaga',         407],
    ['discover_fetch_failed', 2, 'knygos.lt',    408],
    ['unmatched_has_isbn',    2, 'patogupirkti', 406],
    ['scrape_run_failed',     2, null,           429],
    ['product_url_non_book',  6, 'vaga',         407],
  ];
  const ages = ['12m ago', '1h ago', '4h ago', '1d ago', '2d ago', '4d ago'];
  const lifecycles = ['new', 'new', 'new', 'new', 'acknowledged', 'snoozed'];
  const out = [];
  let n = 327467;
  let runIdSeq = 429;
  for (const [type, count, fixShop, runId] of dist) {
    const meta = HF_ISSUE_TYPES.find(t => t.type === type);
    for (let i = 0; i < count; i++) {
      const shop = type === 'scrape_run_failed' ? null : fixShop;
      const urls = shop ? URLS[shop] : [];
      const books = shop ? BOOKS[shop] : [];
      const u = urls[i % urls.length] || null;
      const b = books[i % books.length] || null;
      const thisRun = type === 'scrape_run_failed' ? runIdSeq-- : runId;
      const fullUrl = shop && u ? `https://${shop === 'knygos.lt' ? 'knygos.lt' : shop + '.lt'}${u}` : null;
      out.push({
        id: 'ISS-' + (n--).toString(),
        type,
        sev: meta.sev,
        tone: meta.tone,
        shop,
        book: type === 'scrape_run_failed' ? null : b,
        url: type === 'scrape_run_failed' ? null : fullUrl,
        urlType: ['product', 'category', 'sitemap'][i % 3],
        bookType: ['book', 'dvd', 'stationery'][i % 3],
        detail: hfIssueDetailLine(type, b, i),
        run: type === 'scrape_run_failed' ? 'run:' + thisRun : null,
        runRef: thisRun,
        age: ages[i % ages.length],
        lifecycle: lifecycles[i % lifecycles.length],
      });
    }
  }
  return out;
}

function hfIssueDetailLine(type, book, i) {
  switch (type) {
    case 'missing_price':         return 'No price scraped. Parser likely hit a broken or restructured product page.';
    case 'match_isbn_drift':      return 'ISBN disagrees with the canonical book matched by other shops.';
    case 'invalid_isbn':          return 'ISBN failed check-digit / length validation';
    case 'non_product_active':    return 'A URL classified as a non-product page is being scraped as a product';
    case 'price_spike':           return ['−18.4% in one run', '+22.1% in one run', '−14.0% in one run'][i % 3];
    case 'discover_fetch_failed': return 'HTTP 404 on discovery URL';
    case 'unmatched_has_isbn':    return 'Valid ISBN but no canonical book match';
    case 'scrape_run_failed':     return 'A scrape run ended with status=failed before completing its phase';
    case 'product_url_non_book':  return 'A URL classified as a product page resolved to something that is not a book';
    default: return '—';
  }
}

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

function HFIssues({ nav, goto }) {
  const HF = getHF();
  const [tab, setTab] = React.useState('new');
  const [view, setView] = React.useState('by_type');           // by_type | list
  const [byTypeSort, setByTypeSort] = React.useState('priority');  // priority | count | type
  const [selected, setSelected] = React.useState(new Set());
  const [expanded, setExpanded] = React.useState(null);

  const seed = React.useMemo(() => makeHFIssueSeed(), []);
  const tabSource = React.useMemo(() => tab === 'all' ? seed : seed.filter(r => r.lifecycle === tab), [seed, tab]);

  const filters = useHFFilters(tabSource, {
    search: { fields: i => `${i.id} ${i.type} ${i.book || ''} ${i.url || ''} ${i.detail} ${i.shop || ''}` },
    filters: [
      { id: 'shop',     default: 'all', match: (i, v) => i.shop === v },
      { id: 'sev',      default: 'all', match: (i, v) => i.sev === v },
      { id: 'type',     default: 'all', match: (i, v) => i.type === v },
      { id: 'urlType',  default: 'all', match: (i, v) => i.urlType === v },
      { id: 'bookType', default: 'all', match: (i, v) => i.bookType === v },
      { id: 'run',      default: 'any', match: (i, v) => v === 'any' ? true : (i.runRef && String(i.runRef) === v) },
    ],
  });

  React.useEffect(() => { setSelected(new Set()); }, [view, tab]);

  const sevTone = { critical: 'err', high: 'warn', medium: 'warn', low: 'neutral' };
  const sevRank = { critical: 4, high: 3, medium: 2, low: 1 };

  const byTypeRows = HF_ISSUE_TYPES.map(t => {
    const total = HF_ISSUE_SCALE[t.type] || 0;
    const ack = HF_ISSUE_ACK[t.type] || 0;
    const trend = HF_ISSUE_TREND[t.type] || [];
    // Priority = severity × open count (with mild log scaling so 36K doesn't bury everything)
    const priority = sevRank[t.sev] * Math.log10(Math.max(2, total - ack));
    // Trend direction
    const head = trend.slice(-7).reduce((s, v) => s + v, 0) / 7;
    const tail = trend.slice(0, 7).reduce((s, v) => s + v, 0) / 7;
    const direction = head > tail * 1.15 ? 'up' : head < tail * 0.85 ? 'down' : 'flat';
    const deltaPct = tail > 0 ? Math.round(((head - tail) / tail) * 100) : 0;
    return { ...t, total, ack, newCount: total - ack, trend, priority, direction, deltaPct };
  }).sort((a, b) => {
    if (byTypeSort === 'priority') return b.priority - a.priority;
    if (byTypeSort === 'count')    return b.total - a.total;
    return a.type.localeCompare(b.type);
  });

  const SHOPS_FOR_VIEW = ['vaga', 'knygos.lt', 'patogupirkti', 'krisostomus'];
  const SHARE = [0.42, 0.28, 0.20, 0.10];
  const byTypeShopRows = byTypeRows.flatMap(t =>
    SHOPS_FOR_VIEW.map((shop, i) => ({
      ...t, shop,
      total: Math.round(t.total * SHARE[i]),
      ack:   Math.round(t.ack   * SHARE[i]),
    })).filter(r => r.total > 0)
  );

  const itemWaves = HF_ISSUE_WAVES.filter(w => !w.runFailure);
  const runFailureWaves = HF_ISSUE_WAVES.filter(w => w.runFailure);

  // Bulk selection helpers
  const toggleOne = (id) => setSelected(prev => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const toggleAllVisible = () => {
    const visible = filters.filtered.map(r => r.id);
    const allOn = visible.every(id => selected.has(id));
    setSelected(prev => {
      const next = new Set(prev);
      visible.forEach(id => allOn ? next.delete(id) : next.add(id));
      return next;
    });
  };
  const selectedCount = selected.size;
  const allVisibleSelected = filters.filtered.length > 0 && filters.filtered.every(r => selected.has(r.id));
  const someVisibleSelected = filters.filtered.some(r => selected.has(r.id));

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
            { id:'new',          label:'New',          count: HF_ISSUE_LIFECYCLE_COUNTS.new },
            { id:'acknowledged', label:'Acknowledged', count: HF_ISSUE_LIFECYCLE_COUNTS.acknowledged },
            { id:'snoozed',      label:'Snoozed',      count: HF_ISSUE_LIFECYCLE_COUNTS.snoozed },
            { id:'resolved',     label:'Resolved',     count: HF_ISSUE_LIFECYCLE_COUNTS.resolved },
            { id:'all',          label:'All',          count: HF_ISSUE_LIFECYCLE_COUNTS.all },
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
            <HFButton size="sm" variant="primary">Mark acknowledged</HFButton>
            <HFButton size="sm">Snooze 7d…</HFButton>
            <HFButton size="sm">Assign…</HFButton>
            <HFButton size="sm">Mark resolved</HFButton>
            <HFButton size="sm" variant="subtle" onClick={() => setSelected(new Set())}>Clear</HFButton>
          </div>
        </HFCard>
      ) : (
        <HFCard style={{marginBottom:HF.gap, overflow:'visible'}} padding={12}>
          <HFFilterBar right={<>
            <span style={{fontSize:11.5, color: HF.ink3, fontFamily:HF.mono, fontVariantNumeric:'tabular-nums'}}>
              {(HF_ISSUE_LIFECYCLE_COUNTS[tab] ?? HF_ISSUE_LIFECYCLE_COUNTS.all).toLocaleString()} total
            </span>
          </>}>
            <HFSearch placeholder="Search ID, book, URL, detail…" width={260} value={filters.q} onChange={filters.setQ}/>
            <HFFilter label="Shop"      value={filters.vals.shop}     options={['all','vaga','knygos.lt','patogupirkti','krisostomus']} onChange={v=>filters.setVal('shop',v)}/>
            <HFFilter label="Severity"  value={filters.vals.sev}      options={['all','critical','high','medium','low']}                 onChange={v=>filters.setVal('sev',v)}/>
            <HFFilter label="Type"      value={filters.vals.type}     options={['all', ...HF_ISSUE_TYPES.map(t=>t.type)]}                onChange={v=>filters.setVal('type',v)}/>
            <HFFilter label="URL type"  value={filters.vals.urlType}  options={['all','product','category','sitemap']}                   onChange={v=>filters.setVal('urlType',v)}/>
            <HFFilter label="Book type" value={filters.vals.bookType} options={['all','book','dvd','stationery']}                        onChange={v=>filters.setVal('bookType',v)}/>
            <span style={{display:'inline-flex', alignItems:'center', gap:6}}>
              <span style={{fontSize:12.5, color:HF.ink3}}>Run</span>
              <input
                type="text" placeholder="any"
                value={filters.vals.run === 'any' ? '' : filters.vals.run}
                onChange={e => filters.setVal('run', e.target.value || 'any')}
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
                    <HFButton size="sm" onClick={() => { setView('list'); filters.setVal('type', w.type); if (w.shop) filters.setVal('shop', w.shop); filters.setVal('run', String(w.run)); }}>View</HFButton>
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
              <HFButton size="sm" variant="primary" onClick={() => { setView('list'); filters.setVal('type', r.type); }}>View</HFButton>
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
          {filters.filtered.length === 0 ? (
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
              onClear={filters.activeCount > 0 ? filters.clearAll : undefined}
            />
          ) : (
          <ListRows
            HF={HF}
            rows={filters.filtered}
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
                    Part of a wave of <b style={{color:HF.ink}}>{(HF_ISSUE_SCALE[r.type] || 0).toLocaleString()}</b> {r.type} issues
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
