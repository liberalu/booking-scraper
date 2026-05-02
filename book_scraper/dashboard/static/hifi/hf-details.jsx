// Hi-fi URL detail + Issue detail pages

function HFUrlDetail({ nav, goto, params }) {
  const HF = getHF();
  const urlId = params?.id;
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [rechecking, setRechecking] = React.useState(false);

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

  const fullUrl = data.url;
  const shop = data.shop;
  const httpCode = data.last_http_status;
  const isFailing = data.fail_count >= 3;
  const statusTone = isFailing ? 'err' : 'ok';
  const statusLabel = isFailing ? 'failing' : 'ok';
  const checkHistory = data.check_history || [];

  const recheck = async () => {
    if (rechecking) return;
    setRechecking(true);
    try {
      const resp = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, phase: 'scan', mode: 'full', urls: fullUrl }),
      });
      if (resp.ok) goto('runs');
    } finally { setRechecking(false); }
  };

  return (
    <HFShell {...nav} activePage="urls"
      title={
        <span style={{display:'flex', alignItems:'center', gap:10, minWidth:0}}>
          <HFDot tone={statusTone} size={10} pulse={isFailing}/>
          <span style={{fontFamily:'var(--hf-mono)', fontSize:15, color:'var(--hf-ink)', fontWeight:500, overflow:'hidden', textOverflow:'ellipsis'}}>{fullUrl}</span>
          <HFPill tone={statusTone}>{statusLabel}</HFPill>
          {httpCode && <HFPill tone={httpCode>=400?'err':httpCode>=300?'warn':'ok'}>HTTP {httpCode}</HFPill>}
        </span>
      }
      subtitle={<span style={{fontFamily:'var(--hf-mono)', fontSize:13, color:'var(--hf-ink3)'}}>
        {data.url_type} · fail_count={data.fail_count} · discovered {data.discovered_ago || '—'}
      </span>}
      breadcrumb={<>
        <HFBreadcrumbLink page="urls" goto={goto}>URLs</HFBreadcrumbLink>
        <span style={{color:'var(--hf-ink5)'}}>/</span>
        <span style={{color:'var(--hf-ink)', fontWeight:500, fontFamily:'var(--hf-mono)', overflow:'hidden', textOverflow:'ellipsis', maxWidth:320}}>#{urlId}</span>
      </>}
      actions={<>
        <HFButton onClick={() => window.open(fullUrl, '_blank', 'noopener,noreferrer')}>
          <span style={{display:'flex'}}>{HF_ICONS.external}</span> Open in browser
        </HFButton>
        <HFButton variant="primary" onClick={recheck} disabled={rechecking}>
          <span style={{display:'flex'}}>{HF_ICONS.refresh}</span> {rechecking ? 'Queuing…' : 'Recheck now'}
        </HFButton>
      </>}
    >
      <HFKpiStrip items={[
        { label:'HTTP status',  value: httpCode ? String(httpCode) : '—', tone: httpCode ? (httpCode>=400?'err':httpCode>=300?'warn':'ok') : undefined, delta:<span style={{color:'var(--hf-ink3)'}}>last check</span> },
        { label:'Last checked', value: data.last_checked_ago || data.last_scraped_ago || '—', delta:<span style={{color:'var(--hf-ink3)'}}>scraped</span> },
        { label:'Fail count',   value: String(data.fail_count || 0), tone: isFailing ? 'err' : 'ok', delta:<span style={{color: isFailing ? 'var(--hf-err-ink)' : 'var(--hf-ok-ink)'}}>{isFailing ? 'failing' : 'ok'}</span> },
        { label:'Checks',       value: String(checkHistory.length), delta:<span style={{color:'var(--hf-ink3)'}}>recorded</span> },
      ]}/>

      <div style={{display:'grid', gridTemplateColumns:'1.5fr 1fr', gap:'var(--hf-gap)', marginBottom:'var(--hf-gap)'}}>
        {/* Response code history heatmap */}
        <HFCard title="Response code history" sub={`last ${checkHistory.length} checks`}>
          <div style={{padding:'var(--hf-card-p)'}}>
            {checkHistory.length === 0 ? (
              <div style={{height:60, display:'flex', alignItems:'center', justifyContent:'center', color:'var(--hf-ink4)', fontSize:13}}>No check history yet</div>
            ) : (<>
              <div style={{display:'flex', gap:3, flexWrap:'wrap'}}>
                {[...checkHistory].reverse().map((c, i) => {
                  const tone = !c.http_status || c.http_status >= 400 ? 'var(--hf-err)' : c.http_status >= 300 ? 'var(--hf-warn)' : 'var(--hf-ok)';
                  return (
                    <div key={i} title={`${c.when}: HTTP ${c.http_status || '?'}`}
                      style={{width:22, height:22, borderRadius:3, background:tone, opacity:0.85, cursor:'default'}}/>
                  );
                })}
              </div>
              <div style={{display:'flex', justifyContent:'space-between', fontSize:11, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)', marginTop:8}}>
                <span>oldest</span>
                <span style={{display:'flex', gap:10}}>
                  <span><span style={{color:'var(--hf-ok)'}}>■</span> 2xx</span>
                  <span><span style={{color:'var(--hf-warn)'}}>■</span> 3xx</span>
                  <span><span style={{color:'var(--hf-err)'}}>■</span> 4xx/5xx</span>
                </span>
                <span>newest</span>
              </div>
            </>)}
          </div>
        </HFCard>

        <HFCard title="URL metadata">
          <div style={{padding:`4px 0`}}>
            {[
              ['Full URL',     fullUrl,                         true],
              ['Shop',         shop,                            false],
              ['Type',         data.url_type || '—',           true],
              ['HTTP status',  httpCode ? String(httpCode) : '—', true],
              ['Fail count',   String(data.fail_count || 0),   true],
              ['Discovered',   data.discovered_ago || '—',     false],
              ['Last checked', data.last_checked_ago || data.last_scraped_ago || '—', false],
            ].map(([k, v, mono], i, arr) => (
              <div key={k} style={{
                display:'flex', padding:`7px var(--hf-card-p)`,
                borderBottom: i<arr.length-1 ? `1px solid ${'var(--hf-border-faint)'}` : 'none',
                fontSize:13, gap:12, alignItems:'center',
              }}>
                <span style={{color:'var(--hf-ink4)', minWidth:100, flexShrink:0}}>{k}</span>
                <span style={{
                  color: v==='—'?'var(--hf-ink4)':'var(--hf-ink)', flex:1, minWidth:0,
                  fontFamily: mono ? 'var(--hf-mono)' : 'var(--hf-sans)',
                  fontSize: mono ? 11 : 12.5,
                  overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
                }}>{v}</span>
              </div>
            ))}
            {data.book_id && (
              <div style={{padding:`7px var(--hf-card-p)`, borderTop:`1px solid ${'var(--hf-border-faint)'}`, display:'flex', alignItems:'center', gap:12, fontSize:13}}>
                <span style={{color:'var(--hf-ink4)', minWidth:100}}>Linked book</span>
                <a onClick={(e)=>{e.preventDefault(); goto('shop-book-detail',{id:data.book_id});}} href="#"
                   style={{color:'var(--hf-accent-ink)', fontWeight:500, textDecoration:'none', cursor:'pointer'}}>
                  {data.book_title || `#${data.book_id}`}
                </a>
              </div>
            )}
          </div>
        </HFCard>
      </div>

      {/* Check history table */}
      <HFCard title="Check history" sub={`${checkHistory.length} most recent checks`}>
        {checkHistory.length === 0
          ? <HFEmptyState title="No check history" sub="This URL has not been scraped yet." onClear={null}/>
          : <HFTable
              onRowClick={r => goto('run-detail', { id: r.run_id })}
              columns={[
                { key:'when', label:'When', w:'1fr', mono:true, muted:true, sortable:true },
                { key:'status', label:'Status', w:'0.7fr', sortable:true, cell:v => (
                  <span style={{display:'inline-flex', alignItems:'center', gap:7}}>
                    <HFDot tone={v==='error'?'err':'ok'}/> <span style={{color:v==='error'?'var(--hf-err-ink)':'var(--hf-ink)'}}>{v}</span>
                  </span>
                )},
                { key:'http_status', label:'HTTP', w:'0.5fr', mono:true, align:'right', sortable:true, sortVal:r=>r.http_status||0, cell:v => v
                  ? <span style={{color:v>=400?'var(--hf-err-ink)':v>=300?'var(--hf-warn-ink)':'var(--hf-ink2)', fontWeight:500, fontVariantNumeric:'tabular-nums'}}>{v}</span>
                  : <span style={{color:'var(--hf-ink4)'}}>—</span> },
                { key:'run_id', label:'Run', w:'0.5fr', mono:true, align:'right', sortable:true, sortVal:r=>r.run_id, cell:v => <span style={{color:'var(--hf-accent-ink)', fontWeight:500}}>#{v}</span> },
                { key:'_', label:'', w:'28px', align:'right', cell:() => <span style={{color:'var(--hf-ink4)', display:'flex', justifyContent:'flex-end'}}>{HF_ICONS.chevron}</span> },
              ]}
              rows={checkHistory}
            />}
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
