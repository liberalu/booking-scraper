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

// Human-readable labels for issue type keys
const ISSUE_TITLES = {
  missing_price:             'Missing price',
  zero_price:                'Zero price',
  price_higher_than_original:'Price exceeds original',
  invalid_price:             'Invalid price',
  invalid_price_original:    'Invalid original price',
  missing_title:             'Missing title',
  suspicious_title:          'Suspicious title',
  html_in_text:              'HTML in text field',
  format_mismatch:           'Format mismatch',
  attribute_unknown_key:     'Unknown attribute key',
  attribute_invalid_value:   'Invalid attribute value',
  field_cleared:             'Field cleared',
  scrape_run_failed:         'Scrape run failed',
  invalid_isbn:              'Invalid ISBN',
  invalid_year:              'Invalid year',
  year_pages_swap:           'Year / pages swapped',
  discover_fetch_failed:     'Discovery fetch failed',
};

function HFIssueDetail({ nav, goto, params }) {
  const HF = getHF();
  const rawId = params?.id || '';
  const numericId = parseInt(rawId.replace(/^ISS-/i, ''), 10);

  const [data, setData]     = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [acting, setActing]   = React.useState(false);

  React.useEffect(() => {
    if (!numericId) { setLoading(false); return; }
    fetch(`/api/issues/${numericId}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [numericId]);

  const lifecycle = async (state) => {
    if (acting) return;
    setActing(true);
    try {
      const r = await fetch(`/api/issues/${numericId}/lifecycle?state=${state}`, { method: 'PATCH' });
      if (r.ok) {
        const updated = await r.json();
        setData(prev => ({ ...prev, lifecycle_state: updated.lifecycle_state }));
        window.HF_APP?.toast({ tone: 'ok', message: `Issue marked as ${state.replace('_', ' ')}` });
      }
    } finally { setActing(false); }
  };

  if (loading) {
    return (
      <HFShell {...nav} activePage="issues" title="Issue detail" subtitle="Loading…"
        breadcrumb={<><HFBreadcrumbLink page="issues" goto={goto}>Issues</HFBreadcrumbLink><span>/</span><span>…</span></>}>
        <div style={{padding:40, color:'var(--hf-ink3)'}}>Loading…</div>
      </HFShell>
    );
  }
  if (!data) {
    return (
      <HFShell {...nav} activePage="issues" title="Issue not found" subtitle={rawId}
        breadcrumb={<><HFBreadcrumbLink page="issues" goto={goto}>Issues</HFBreadcrumbLink><span>/</span><span>{rawId}</span></>}>
        <HFEmptyState title="Issue not found" sub={`No issue with ID ${rawId} exists.`} onClear={() => goto('issues')}/>
      </HFShell>
    );
  }

  const sevTone  = data.severity === 'critical' ? 'err' : data.severity === 'warning' ? 'warn' : 'neutral';
  const sevInk   = data.severity === 'critical' ? 'var(--hf-err-ink)' : data.severity === 'warning' ? 'var(--hf-warn-ink)' : 'var(--hf-ink3)';
  const lcTone   = { new:'err', recurring:'warn', already_seen:'ok' };
  const lcLabel  = { new:'new', recurring:'recurring', already_seen:'known' };
  const issueTitle = ISSUE_TITLES[data.issue] || data.issue;
  const isKnown = data.lifecycle_state === 'already_seen';

  const shortUrl = data.url
    ? data.url.replace(/^https?:\/\//, '').replace(/\/$/, '')
    : '—';

  return (
    <HFShell {...nav} activePage="issues"
      title={
        <span style={{display:'flex', alignItems:'center', gap:10, minWidth:0, flexWrap:'wrap'}}>
          <span style={{color:sevInk, display:'flex', flexShrink:0}}>{HF_ICONS.bang}</span>
          <span style={{fontWeight:600}}>{issueTitle}</span>
          <HFPill tone={sevTone}>{data.severity}</HFPill>
          <HFPill tone={lcTone[data.lifecycle_state] || 'neutral'}>{lcLabel[data.lifecycle_state] || data.lifecycle_state}</HFPill>
        </span>
      }
      subtitle={
        <span style={{fontFamily:'var(--hf-mono)', fontSize:13, color:'var(--hf-ink3)'}}>
          {rawId} · field={data.field} · {data.added_ago}
          {data.shop_book_title ? ` · "${data.shop_book_title}"` : ''}
        </span>
      }
      breadcrumb={<>
        <HFBreadcrumbLink page="issues" goto={goto}>Issues</HFBreadcrumbLink>
        <span style={{color:'var(--hf-ink5)'}}>/</span>
        <span style={{color:'var(--hf-ink)', fontWeight:500, fontFamily:'var(--hf-mono)'}}>{rawId}</span>
      </>}
      actions={<>
        {!isKnown
          ? <HFButton onClick={() => lifecycle('already_seen')} disabled={acting}>
              <span style={{display:'flex'}}>{HF_ICONS.check}</span> Mark known
            </HFButton>
          : <HFButton onClick={() => lifecycle('open')} disabled={acting}>Reopen</HFButton>
        }
        <HFButton variant="primary" onClick={() => goto('issues')}>
          Back to issues
        </HFButton>
      </>}
    >
      {/* KPI strip */}
      <HFKpiStrip items={[
        { label:'Severity',  value: data.severity,  tone: sevTone },
        { label:'Lifecycle', value: lcLabel[data.lifecycle_state] || data.lifecycle_state, tone: lcTone[data.lifecycle_state] || 'neutral' },
        { label:'Detected',  value: data.added_ago, delta: <span style={{color:'var(--hf-ink3)'}}>from run #{data.scrape_run_id}</span> },
        { label:'Field',     value: data.field, delta: <span style={{color:'var(--hf-ink3)'}}>affected</span> },
      ]}/>

      {/* Main 2-col: description left, failure details right */}
      <div style={{display:'grid', gridTemplateColumns:'3fr 2fr', gap:'var(--hf-gap)', marginBottom:'var(--hf-gap)'}}>

        {/* What this means */}
        <HFCard title="What this means" sub={`issue type: ${data.issue}`}>
          <div style={{padding:`var(--hf-card-p)`}}>
            {data.description ? (
              <p style={{margin:'0 0 14px', fontSize:13, color:'var(--hf-ink)', lineHeight:1.6}}>
                {data.description}
              </p>
            ) : (
              <p style={{margin:'0 0 14px', fontSize:13, color:'var(--hf-ink3)', fontStyle:'italic'}}>
                No description available for this issue type.
              </p>
            )}
            {data.raw_value && (
              <div style={{marginTop:6}}>
                <div style={{fontSize:11, color:'var(--hf-ink4)', textTransform:'uppercase', letterSpacing:0.5, fontWeight:600, marginBottom:6}}>
                  Raw scraped value
                </div>
                <div style={{
                  padding:'9px 12px',
                  background:'var(--hf-subtle)', border:`1px solid ${'var(--hf-border-faint)'}`, borderRadius:5,
                  fontFamily:'var(--hf-mono)', fontSize:13, color:'var(--hf-ink2)',
                  wordBreak:'break-all',
                }}>
                  {data.raw_value}
                </div>
              </div>
            )}
          </div>
        </HFCard>

        {/* Failure details */}
        <HFCard title="Failure details">
          <div style={{padding:`4px 0`}}>
            {[
              ['Field',     data.field,                    true],
              ['Issue',     data.issue,                    true],
              ['Severity',  data.severity,                 false],
              ['Lifecycle', lcLabel[data.lifecycle_state] || data.lifecycle_state, false],
              ['Detected',  data.added_ago,                true],
              ['Run',       `#${data.scrape_run_id}`,      true, data.scrape_run_id],
              ['Shop',      data.shop_name || '—',         false],
            ].map(([k, v, mono, runLink], i, arr) => (
              <div key={k} style={{
                display:'flex', padding:`8px var(--hf-card-p)`,
                borderBottom: i < arr.length-1 ? `1px solid ${'var(--hf-border-faint)'}` : 'none',
                fontSize:13, gap:10, alignItems:'center',
              }}>
                <span style={{color:'var(--hf-ink4)', minWidth:80, flexShrink:0, fontSize:12}}>{k}</span>
                {runLink
                  ? <a onClick={(e)=>{e.preventDefault(); goto('run-detail',{id:runLink});}} href="#"
                       style={{color:'var(--hf-accent-ink)', fontWeight:500, fontFamily:'var(--hf-mono)', fontSize:12, textDecoration:'none', cursor:'pointer'}}>
                      {v}
                    </a>
                  : <span style={{
                      color: v==='—'?'var(--hf-ink4)':'var(--hf-ink)',
                      fontFamily: mono ? 'var(--hf-mono)' : 'inherit',
                      fontSize: mono ? 12 : 13, fontWeight: 500,
                    }}>{v}</span>
                }
              </div>
            ))}
            {data.url && (
              <div style={{padding:`8px var(--hf-card-p)`, borderTop:`1px solid ${'var(--hf-border-faint)'}`, display:'flex', gap:10, alignItems:'center', fontSize:13}}>
                <span style={{color:'var(--hf-ink4)', minWidth:80, flexShrink:0, fontSize:12}}>URL</span>
                <a href={data.url} target="_blank" rel="noopener noreferrer"
                   style={{color:'var(--hf-accent-ink)', fontFamily:'var(--hf-mono)', fontSize:11, wordBreak:'break-all', textDecoration:'none'}}>
                  {shortUrl}
                </a>
              </div>
            )}
          </div>
        </HFCard>
      </div>

      {/* Affected book */}
      {data.shop_book_id && (
        <HFCard title="Affected book" sub="book where this issue was detected">
          <div style={{
            padding:`14px var(--hf-card-p)`,
            display:'flex', alignItems:'center', gap:16,
          }}>
            <div style={{
              width:42, height:42, borderRadius:8, flexShrink:0,
              background:`linear-gradient(135deg, ${'var(--hf-accent)'} 0%, ${'var(--hf-accent-hover)'} 100%)`,
              display:'flex', alignItems:'center', justifyContent:'center',
              color:'#fff', fontSize:18, opacity:0.85,
            }}>
              {HF_ICONS.books}
            </div>
            <div style={{flex:1, minWidth:0}}>
              <div style={{fontSize:14, fontWeight:600, color:'var(--hf-ink)', lineHeight:1.3}}>
                {data.shop_book_title || `Shop book #${data.shop_book_id}`}
              </div>
              <div style={{fontSize:12, color:'var(--hf-ink4)', fontFamily:'var(--hf-mono)', marginTop:3}}>
                #{data.shop_book_id}{data.shop_name ? ` · ${data.shop_name}` : ''}
              </div>
            </div>
            <HFButton onClick={() => goto('shop-book-detail', { id: data.shop_book_id })}>
              <span style={{display:'flex'}}>{HF_ICONS.external}</span> Open book
            </HFButton>
          </div>
        </HFCard>
      )}
    </HFShell>
  );
}

Object.assign(window, { HFUrlDetail, HFIssueDetail });
