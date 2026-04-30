// Hi-fi URL detail + Issue detail pages

function HFUrlDetail({ nav, goto, params }) {
  const HF = getHF();
  const urlId = params?.id;
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    if (!urlId) return;
    fetch(`/api/urls/${urlId}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [urlId]);

  if (loading || !data) {
    return (
      <HFShell {...nav} activePage="urls" title="URL detail" subtitle="Loading…"
        breadcrumb={<><HFBreadcrumbLink page="urls" goto={goto}>URLs</HFBreadcrumbLink><span>/</span><span>#{urlId}</span></>}>
        <div style={{padding:40, color:'var(--hf-ink3)'}}>Loading…</div>
      </HFShell>
    );
  }

  const urlPath = data.url;
  const shop = data.shop;
  const status = data.fail_count >= 3 ? 'error' : 'ok';
  const code = data.fail_count >= 3 ? 404 : 200;
  const sTone = { ok: 'ok', warn: 'warn', error: 'err' };
  const sInk = { ok: 'var(--hf-ok-ink)', warn: 'var(--hf-warn-ink)', error: 'var(--hf-err-ink)' };

  const history = [];
  const runs = [];

  return (
    <HFShell {...nav} activePage="urls"
      title={
        <span style={{display:'flex', alignItems:'center', gap:10, minWidth:0}}>
          <HFDot tone={sTone[status]} size={10} pulse={status==='error'}/>
          <span style={{fontFamily:'var(--hf-mono)', fontSize:18, color:'var(--hf-ink)', fontWeight:500, overflow:'hidden', textOverflow:'ellipsis'}}>
            {shop}.lt<span style={{color:'var(--hf-ink3)'}}>{urlPath}</span>
          </span>
          <HFPill tone={sTone[status]}>{status}</HFPill>
          <HFPill tone={code>=400?'err':code>=300?'warn':'ok'}>HTTP {code}</HFPill>
        </span>
      }
      subtitle={<span style={{fontFamily:'var(--hf-mono)', fontSize:13, color:'var(--hf-ink3)'}}>fail_count={data.fail_count} · discovered {data.discovered_ago || '—'}</span>}
      breadcrumb={<>
        <HFBreadcrumbLink page="urls" goto={goto}>URLs</HFBreadcrumbLink>
        <span style={{color:'var(--hf-ink5)'}}>/</span>
        <span style={{color:'var(--hf-ink)', fontWeight:500, fontFamily:'var(--hf-mono)', overflow:'hidden', textOverflow:'ellipsis', maxWidth:320}}>{urlPath}</span>
      </>}
      actions={<>
        <HFButton onClick={() => {
          const fullUrl = data.url && (data.url.startsWith('http') ? data.url : `https://${shop}.lt${urlPath}`);
          if (fullUrl) window.open(fullUrl, '_blank', 'noopener,noreferrer');
        }}><span style={{display:'flex'}}>{HF_ICONS.external}</span> Open in browser</HFButton>
        <HFButton variant="primary" onClick={async () => {
          const resp = await fetch('/api/runs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ shop, phase: 'scan', mode: 'sample' }),
          });
          if (resp.ok) goto('runs');
        }}><span style={{display:'flex'}}>{HF_ICONS.refresh}</span> Recheck now</HFButton>
      </>}
    >
      {/* Error banner */}
      {status === 'error' && (
        <HFCard style={{marginBottom:'var(--hf-gap)', borderColor:'var(--hf-err-border)', background:'var(--hf-err-soft)' || '#FEF2F2'}} padding={14}>
          <div style={{display:'flex', gap:12, alignItems:'flex-start'}}>
            <div style={{color:'var(--hf-err)', display:'flex', marginTop:1}}>{HF_ICONS.bang}</div>
            <div style={{flex:1, minWidth:0}}>
              <div style={{fontSize:13, fontWeight:600, color:'var(--hf-err-ink)', marginBottom:2}}>URL has been failing for 6 consecutive checks</div>
              <div style={{fontSize:13, color:'var(--hf-ink2)', lineHeight:1.5}}>
                Returns <span style={{fontFamily:'var(--hf-mono)', fontWeight:500}}>HTTP 404</span> since <span style={{fontFamily:'var(--hf-mono)'}}>2d ago</span>. Last successful response on <span style={{fontFamily:'var(--hf-mono)'}}>4d ago</span> was <span style={{fontFamily:'var(--hf-mono)'}}>HTTP 200</span>. This URL resolves to <span style={{color:'var(--hf-ink)', fontWeight:500}}>Sapiens (alias)</span> — consider removing the alias or updating the parser.
              </div>
            </div>
            <div style={{display:'flex', gap:6, flexShrink:0}}>
              <HFButton size="sm">Mark as broken</HFButton>
              <HFButton size="sm" variant="accent">Remove URL</HFButton>
            </div>
          </div>
        </HFCard>
      )}

      <HFKpiStrip items={[
        { label:'Status',       value:status, tone: sTone[status], delta:<span style={{color:sInk[status]}}>HTTP {code}</span> },
        { label:'Last scraped', value: data.last_scraped_ago || '—', delta:<span style={{color:'var(--hf-ink3)'}}>last check</span> },
        { label:'Fail count',   value: String(data.fail_count || 0), tone: data.fail_count >= 3 ? 'err' : 'ok', delta:<span style={{color:data.fail_count >= 3 ? 'var(--hf-err-ink)' : 'var(--hf-ok-ink)'}}>{data.fail_count >= 3 ? 'failing' : 'ok'}</span> },
      ]}/>

      <div style={{display:'grid', gridTemplateColumns:'1.5fr 1fr', gap:'var(--hf-gap)', marginBottom:'var(--hf-gap)'}}>
        <HFCard title="Response code history" sub="check history not yet available">
          <div style={{padding:`var(--hf-card-p)`}}>
            <div style={{height:140, display:'flex', alignItems:'center', justifyContent:'center', color:'var(--hf-ink4)', fontSize:13}}>No history data yet</div>
            <div style={{display:'flex', gap:14, marginTop:10, fontSize:11, color:'var(--hf-ink3)', fontFamily:'var(--hf-mono)'}}>
              <span><span style={{color:'var(--hf-accent)'}}>━</span> response time (ms)</span>
              <span style={{marginLeft:'auto'}}>{history.length} checks</span>
            </div>
          </div>
        </HFCard>

        <HFCard title="URL metadata">
          <div style={{padding:`4px 0`}}>
            {[
              ['Full URL',      `https://${shop}.lt${urlPath}`, true],
              ['Shop',          shop],
              ['Fail count',    String(data.fail_count || 0), true],
              ['Discovered',    data.discovered_ago || '—'],
              ['Last scraped',  data.last_scraped_ago || '—'],
            ].map(([k,v,mono], i, arr) => (
              <div key={k} style={{
                display:'flex', padding:`8px var(--hf-card-p)`,
                borderBottom: i<arr.length-1 ? `1px solid ${'var(--hf-border-faint)'}` : 'none',
                fontSize:13, gap:12, alignItems:'center',
              }}>
                <span style={{color:'var(--hf-ink4)', minWidth:110}}>{k}</span>
                <span style={{
                  color: v==='—'?'var(--hf-ink4)':'var(--hf-ink)', flex:1,
                  fontFamily: mono ? 'var(--hf-mono)' : 'var(--hf-sans)',
                  fontSize: mono ? 11.5 : 12.5,
                  overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
                }}>{v}</span>
              </div>
            ))}
          </div>
        </HFCard>
      </div>

      {/* Check history table */}
      <HFCard title="Check history" sub={`${history.length} most recent checks`} style={{marginBottom:'var(--hf-gap)'}}>
        <HFTable
          columns={[
            { key:'t', label:'When', w:'1fr', mono:true, muted:true, sortable:true },
            { key:'status', label:'Status', w:'0.8fr', sortable:true, cell:v => (
              <span style={{display:'inline-flex', alignItems:'center', gap:7}}>
                <HFDot tone={sTone[v]}/> <span style={{color: v==='error'?'var(--hf-err-ink)':'var(--hf-ink)'}}>{v}</span>
              </span>
            )},
            { key:'code', label:'HTTP', w:'0.5fr', mono:true, align:'right', sortable:true, sortVal:r=>r.code, cell:v => (
              <span style={{color: v>=400?'var(--hf-err-ink)':v>=300?'var(--hf-warn-ink)':'var(--hf-ink2)', fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v}</span>
            )},
            { key:'ms', label:'Response', w:'0.8fr', mono:true, align:'right', sortable:true, sortVal:r=>r.ms, cell:v => <span style={{color:'var(--hf-ink3)'}}>{v}ms</span> },
            { key:'bar', label:'', w:'2fr', cell:(_, r) => (
              <span style={{display:'flex', alignItems:'center', gap:10, width:'100%'}}>
                <span style={{flex:1, maxWidth:240, height:4, background:'var(--hf-subtle)', borderRadius:2, overflow:'hidden'}}>
                  <span style={{display:'block', width:`${Math.min(100, r.ms/5)}%`, height:'100%', background: r.status==='error'?'var(--hf-err)':r.status==='warn'?'var(--hf-warn)':'var(--hf-ok)', borderRadius:2}}/>
                </span>
              </span>
            )},
          ]}
          rows={history}
        />
      </HFCard>

      {/* Runs that touched this URL */}
      <HFCard title="Runs that visited this URL" sub={`${runs.length} recent · tap to open run`}>
        <HFTable
          onRowClick={(r) => goto('run-detail', { id: r.id })}
          columns={[
            { key:'id', label:'Run', w:'0.5fr', mono:true, sortable:true, sortVal:r=>r.id, cell:v => <span style={{color:'var(--hf-accent-ink)', fontWeight:500}}>#{v}</span> },
            { key:'phase', label:'Phase', w:'0.8fr', mono:true, sortable:true },
            { key:'started', label:'Started', w:'1fr', mono:true, muted:true, sortable:true },
            { key:'dur', label:'Duration', w:'0.7fr', mono:true, muted:true, align:'right', sortable:true },
            { key:'outcome', label:'Outcome', w:'0.9fr', sortable:true, cell:v => (
              <HFPill tone={v==='resolved'?'ok':v==='found'?'neutral':'warn'}>{v}</HFPill>
            )},
            { key:'code', label:'HTTP', w:'0.5fr', mono:true, align:'right', sortable:true, sortVal:r=>r.code, cell:v => (
              <span style={{color: v>=400?'var(--hf-err-ink)':v>=300?'var(--hf-warn-ink)':'var(--hf-ink2)', fontWeight:500}}>{v}</span>
            )},
            { key:'_', label:'', w:'28px', align:'right', cell:() => <span style={{color:'var(--hf-ink4)', display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
          ]}
          rows={runs}
        />
      </HFCard>
    </HFShell>
  );
}

// ─────────────────────────────── Issue detail ───────────────────────────────

function HFIssueDetail({ nav, goto, params }) {
  const HF = getHF();
  const type = params?.type || 'price_regression';
  const sev = params?.sev || 'high';
  const count = params?.n || 48;

  const sevTone = { high:'err', medium:'warn', low:'neutral' };
  const sevInk  = { high:'var(--hf-err-ink)', medium:'var(--hf-warn-ink)', low:'var(--hf-ink3)' };

  // Titles & descriptions per issue type
  const meta = {
    price_regression: {
      title: 'Price regression detected',
      desc:  'Price dropped by more than 10% in a single run without a corresponding promo marker. Likely a parser misalignment picking up a discount banner instead of the list price.',
      rule:  'abs(delta_pct) > 10  AND  promo_flag = false',
    },
    missing_isbn: {
      title: 'Missing ISBN',
      desc:  'Book was scraped successfully but the ISBN-13 field could not be extracted. Parser likely needs a new selector.',
      rule:  'isbn IS NULL  AND  status = "active"',
    },
    parser_error: {
      title: 'Parser threw exception',
      desc:  'Extraction code raised an exception on this page. Check the shop\'s parser version and recent selector changes.',
      rule:  'exception_raised = true',
    },
    broken_url: {
      title: 'Broken URL',
      desc:  'URL returned 4xx or 5xx for 3+ consecutive checks.',
      rule:  'status_code >= 400  AND  consecutive_failures >= 3',
    },
  };
  const m = meta[type] || { title:type, desc:'—', rule:'—' };

  // Affected items
  const affected = [
    { id:3421, book:'Clean Code',            shop:'vaga', old:'€32.90', neo:'€28.50', pct:-13.4, detected:'12m ago',  st:'open' },
    { id:3418, book:'The Pragmatic Programmer', shop:'vaga', old:'€29.90', neo:'€24.90', pct:-16.7, detected:'1h ago',   st:'open' },
    { id:3412, book:'Refactoring',           shop:'vaga', old:'€44.00', neo:'€35.00', pct:-20.5, detected:'2h ago',   st:'open' },
    { id:3405, book:'Domain-Driven Design',  shop:'vaga', old:'€58.00', neo:'€49.50', pct:-14.7, detected:'3h ago',   st:'open' },
    { id:3398, book:'Design Patterns (GoF)', shop:'vaga', old:'€52.00', neo:'€44.00', pct:-15.4, detected:'5h ago',   st:'snoozed' },
    { id:3391, book:'Code Complete',         shop:'vaga', old:'€42.00', neo:'€36.00', pct:-14.3, detected:'7h ago',   st:'open' },
    { id:3384, book:'Working Effectively with Legacy Code', shop:'vaga', old:'€48.00', neo:'€39.00', pct:-18.8, detected:'10h ago', st:'open' },
    { id:3377, book:'You Don\'t Know JS',    shop:'vaga', old:'€22.00', neo:'€18.50', pct:-15.9, detected:'1d ago',   st:'open' },
    { id:3370, book:'The Mythical Man-Month', shop:'vaga', old:'€26.00', neo:'€21.50', pct:-17.3, detected:'1d 4h ago', st:'open' },
    { id:3363, book:'Peopleware',            shop:'vaga', old:'€24.00', neo:'€20.00', pct:-16.7, detected:'2d ago',   st:'open' },
  ];

  // 14d trend
  const trend = [6, 8, 4, 5, 7, 12, 15, 18, 22, 28, 35, 41, 45, 48];

  return (
    <HFShell {...nav} activePage="issues"
      title={<span style={{display:'flex', alignItems:'center', gap:12, minWidth:0}}>
        <span style={{color:sevInk[sev], display:'flex'}}>{HF_ICONS.bang}</span>
        <span>{m.title}</span>
        <HFPill tone={sevTone[sev]}>{sev} severity</HFPill>
      </span>}
      subtitle={<span style={{fontFamily:'var(--hf-mono)', fontSize:13, color:'var(--hf-ink3)'}}>type={type} · first seen 2 days ago · {count} affected</span>}
      breadcrumb={<>
        <HFBreadcrumbLink page="issues" goto={goto}>Issues</HFBreadcrumbLink>
        <span style={{color:'var(--hf-ink5)'}}>/</span>
        <span style={{color:'var(--hf-ink)', fontWeight:500, fontFamily:'var(--hf-mono)'}}>{type}</span>
      </>}
      actions={<>
        <HFButton>Snooze 7d</HFButton>
        <HFButton>Assign…</HFButton>
        <HFButton variant="primary"><span style={{display:'flex'}}>{HF_ICONS.check}</span> Mark all resolved</HFButton>
      </>}
    >
      {/* Description card */}
      <HFCard style={{marginBottom:'var(--hf-gap)'}}>
        <div style={{padding:`var(--hf-card-p)`, display:'grid', gridTemplateColumns:'1.4fr 1fr', gap:'var(--hf-gap)'}}>
          <div>
            <div style={{fontSize:11, color:'var(--hf-ink4)', textTransform:'uppercase', letterSpacing:0.5, fontWeight:600, marginBottom:6}}>What this means</div>
            <div style={{fontSize:13, color:'var(--hf-ink)', lineHeight:1.55, textWrap:'pretty'}}>{m.desc}</div>
            <div style={{
              marginTop:14, padding:'8px 10px',
              background:'var(--hf-subtle)', border:`1px solid ${'var(--hf-border-faint)'}`, borderRadius:5,
              fontFamily:'var(--hf-mono)', fontSize:12, color:'var(--hf-ink2)',
            }}>
              <span style={{color:'var(--hf-ink4)', marginRight:8}}>rule:</span>{m.rule}
            </div>
          </div>
          <div style={{borderLeft:`1px solid ${'var(--hf-border-faint)'}`, paddingLeft:'var(--hf-gap)', display:'grid', gridTemplateColumns:'1fr 1fr', gap:14}}>
            {[
              ['Severity',     sev, sevInk[sev]],
              ['First seen',   '2 days ago'],
              ['Last seen',    '12m ago'],
              ['Affected',     count, 'var(--hf-ink)'],
              ['Shops',        'vaga'],
              ['Assigned',     'unassigned', 'var(--hf-ink4)'],
            ].map(([k,v,c]) => (
              <div key={k}>
                <div style={{fontSize:11, color:'var(--hf-ink4)', textTransform:'uppercase', letterSpacing:0.5, fontWeight:600}}>{k}</div>
                <div style={{fontSize:14, color: c||'var(--hf-ink)', marginTop:3, fontWeight: c?500:400, fontFamily: typeof v==='number'||['2 days ago','12m ago'].includes(v)?'var(--hf-mono)':'var(--hf-sans)', fontVariantNumeric:'tabular-nums'}}>{v}</div>
              </div>
            ))}
          </div>
        </div>
      </HFCard>

      <HFKpiStrip items={[
        { label:'Affected now', value:String(count), tone:sevTone[sev], delta:<span style={{color:sevInk[sev]}}>+3 today</span> },
        { label:'Affected 7d',  value:'84',  delta:<span style={{color:'var(--hf-err-ink)'}}>+36 vs prev</span> },
        { label:'Resolved 7d',  value:'12',  delta:<span style={{color:'var(--hf-ok-ink)'}}>manually</span>, tone:'ok' },
        { label:'Avg delta',    value:'-15.9%', delta:<span style={{color:'var(--hf-err-ink)'}}>abs · worsening</span>, tone:'err' },
        { label:'MTTR',         value:'1.8d',    delta:<span style={{color:'var(--hf-ink3)'}}>median</span> },
      ]}/>

      <div style={{display:'grid', gridTemplateColumns:'1.5fr 1fr', gap:'var(--hf-gap)', marginBottom:'var(--hf-gap)'}}>
        <HFCard title="Occurrences over time" sub="new issues per day · last 14 days">
          <div style={{padding:`var(--hf-card-p)`}}>
            <HFAreaChart data={trend} h={160} label="Issues per day"/>
          </div>
        </HFCard>
        <HFCard title="Suggested actions">
          <div style={{padding:`4px 0`}}>
            {[
              { t:'Review parser selector',  d:'price.v3 → price_value', act:'Open parser', tone:'accent' },
              { t:'Exclude books on promo', d:'add promo_flag=true guard', act:'Edit rule' },
              { t:'Snooze until Monday',     d:'re-triage after weekend', act:'Snooze' },
              { t:'Mark all as resolved',    d:'mark without changes',    act:'Resolve', tone:'danger' },
            ].map((a, i, arr) => (
              <div key={a.t} style={{padding:`12px var(--hf-card-p)`, borderBottom: i<arr.length-1?`1px solid ${'var(--hf-border-faint)'}`:'none', display:'flex', gap:12, alignItems:'flex-start'}}>
                <div style={{flex:1, minWidth:0}}>
                  <div style={{fontSize:13, color:'var(--hf-ink)', fontWeight:500}}>{a.t}</div>
                  <div style={{fontSize:12, color:'var(--hf-ink3)', marginTop:2, fontFamily:'var(--hf-mono)'}}>{a.d}</div>
                </div>
                <HFButton size="sm" variant={a.tone || 'default'}>{a.act}</HFButton>
              </div>
            ))}
          </div>
        </HFCard>
      </div>

      {/* Affected items table */}
      <HFCard title="Affected items" sub={`${affected.length} of ${count} · tap to open`}>
        <div style={{padding:`8px var(--hf-card-p)`, borderBottom:`1px solid ${'var(--hf-border-faint)'}`, display:'flex', gap:8, alignItems:'center'}}>
          <HFSearch placeholder="Search affected items…" width={280}/>
          <HFFilter label="Shop" value="all" options={['all','vaga','knygos']} onChange={()=>{}}/>
          <HFFilter label="Status" value="open" options={['open','snoozed','resolved','all']} onChange={()=>{}}/>
          <span style={{flex:1}}/>
          <HFButton size="sm"><span style={{display:'flex'}}>{HF_ICONS.download}</span> Export</HFButton>
        </div>
        <HFTable
          onRowClick={(r) => goto('shop-book-detail', { id: r.id })}
          columns={[
            { key:'id', label:'ID', w:'0.4fr', mono:true, sortable:true, sortVal:r=>r.id, cell:v => <span style={{color:'var(--hf-accent-ink)', fontWeight:500}}>#{v}</span> },
            { key:'book', label:'Book', w:'2fr', sortable:true, cell:v => <span style={{color:'var(--hf-ink)', fontWeight:500}}>{v}</span> },
            { key:'shop', label:'Shop', w:'0.6fr', mono:true, muted:true, sortable:true },
            { key:'old', label:'Was', w:'0.6fr', mono:true, align:'right', muted:true, sortable:true },
            { key:'neo', label:'Now', w:'0.6fr', mono:true, align:'right', sortable:true, cell:v => <span style={{color:'var(--hf-ink)', fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v}</span> },
            { key:'pct', label:'Δ', w:'0.6fr', mono:true, align:'right', sortable:true, sortVal:r=>r.pct, cell:v => (
              <span style={{color: v<0?'var(--hf-err-ink)':'var(--hf-ok-ink)', fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v>0?'+':''}{v.toFixed(1)}%</span>
            )},
            { key:'detected', label:'Detected', w:'0.9fr', mono:true, muted:true, sortable:true },
            { key:'st', label:'Status', w:'0.7fr', sortable:true, cell:v => <HFPill tone={v==='open'?'err':v==='snoozed'?'warn':'ok'}>{v}</HFPill> },
            { key:'_', label:'', w:'28px', align:'right', cell:() => <span style={{color:'var(--hf-ink4)', display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
          ]}
          rows={affected}
        />
      </HFCard>
    </HFShell>
  );
}

Object.assign(window, { HFUrlDetail, HFIssueDetail });
