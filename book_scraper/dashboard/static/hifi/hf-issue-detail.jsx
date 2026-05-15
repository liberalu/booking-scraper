// Hi-fi Issue detail — rebuilt to match prod /issues/:id + scale features.
// Loaded after hf-details.jsx; overrides the legacy HFIssueDetail.
//
// Adds versus the prod screenshot:
//   • Wave context callout — "this is 1 of 36,242 issues from run #407"
//   • "Fix this" action panel — type-specific buttons (Open parser / Re-scrape / Bulk ack)
//   • Raw extraction snippet — show what the parser saw so you can diagnose without leaving

function HFIssueDetail({ nav, goto, params }) {
  const HF = getHF();

  // Fetch from API when params.id is a numeric issue ID; fall back to mock
  // params for hifi-preview mode (where params carry display fields directly).
  const issueId = params?.id && /^\d+$/.test(String(params.id)) ? params.id : null;
  const [apiData, setApiData] = React.useState(null);
  const [apiLoading, setApiLoading] = React.useState(!!issueId);
  const [apiNotFound, setApiNotFound] = React.useState(false);
  const [waveTotal, setWaveTotal] = React.useState(1);
  const [otherIssues, setOtherIssues] = React.useState([]);

  // Fetch real wave total from /api/issues/groups whenever the issue's type changes.
  // Depends on `apiData?.issue || params?.type` directly so the hook stays above
  // the early-return guards (Rules of Hooks).
  React.useEffect(() => {
    const t = apiData?.issue || params?.type;
    if (!t) return;
    fetch(`/api/issues/groups?group_by=type&state=new`)
      .then(r => r.json())
      .then(d => {
        const groups = Array.isArray(d) ? d : (d.groups || []);
        const row = groups.find(g => g.issue_type === t);
        if (row && row.total) setWaveTotal(row.total);
      })
      .catch(() => {});
  }, [apiData?.issue, params?.type]);

  React.useEffect(() => {
    if (!issueId) { setApiLoading(false); return; }
    setApiLoading(true);
    setApiNotFound(false);
    fetch(`/api/issues/${issueId}`)
      .then(r => {
        if (r.status === 404) { setApiNotFound(true); setApiLoading(false); return null; }
        return r.json();
      })
      .then(d => { if (d) { setApiData(d); setApiLoading(false); } })
      .catch(() => setApiLoading(false));
  }, [issueId]);

  React.useEffect(() => {
    const t = apiData?.issue || params?.type;
    const s = apiData?.shop_name || params?.shop;
    if (!t) return;
    const p = new URLSearchParams({ issue_type: t, per_page: 6, state: 'all' });
    if (s) p.set('shop', s);
    fetch(`/api/issues?${p}`)
      .then(r => r.json())
      .then(d => {
        const rows = Array.isArray(d) ? d : (d.issues || d.items || []);
        const filtered = issueId ? rows.filter(row => String(row.id) !== String(issueId)) : rows;
        setOtherIssues(filtered.slice(0, 5).map(row => ({
          id: row.id,
          book: row.shop_book_title || '—',
          issue: row.issue,
          age: row.added_ago || '—',
        })));
      })
      .catch(() => {});
  }, [apiData?.issue, apiData?.shop_name, params?.type, params?.shop, issueId]);

  if (apiLoading) return <div style={{padding:40, color: getHF().ink3, fontFamily: getHF().sans}}>Loading…</div>;
  if (apiNotFound) return <div style={{padding:40, color: getHF().errInk, fontFamily: getHF().sans}}>Issue not found.</div>;

  // Resolve display fields: prefer live API data, fall back to params (hifi preview).
  const id        = apiData ? `ISS-${apiData.id}` : (params?.id        || 'ISS-266206');
  const type      = apiData?.issue             || params?.type      || 'missing_price';
  const sev       = apiData?.severity          || params?.sev       || 'critical';
  const lifecycle = apiData?.lifecycle_state   || params?.lifecycle || 'new';
  const shop      = apiData?.shop_name         || params?.shop      || 'patogupirkti';
  const book      = apiData?.shop_book_title   || params?.book      || 'Arturas ir Maltazaro kerštas (DVD)';
  const url       = apiData?.url               || params?.url       || 'https://patogupirkti.lt/knyga/arturas-ir-maltazaro-kerstas-dvd';
  const age       = apiData?.added_ago         || params?.age       || '4d ago';
  const runId     = apiData?.scrape_run_id     || params?.runId     || 407;

  const FIELD_BY_TYPE = {
    missing_price:         'price',
    match_isbn_drift:      'isbn',
    invalid_isbn:          'isbn',
    non_product_active:    'classification',
    price_spike:           'price',
    discover_fetch_failed: 'url',
    unmatched_has_isbn:    'book_id',
    scrape_run_failed:     'run.status',
    product_url_non_book:  'classification',
  };
  const DESC_BY_TYPE = {
    missing_price:         'No price scraped. Parser likely hit a broken or restructured product page.',
    match_isbn_drift:      'Shop reports an ISBN that disagrees with the canonical book matched by other shops.',
    invalid_isbn:          'ISBN failed check-digit / length validation. Value cannot be reliably matched.',
    non_product_active:    'A URL classified as non-product is still being scraped as if it were a book listing.',
    price_spike:           'Price moved by more than the configured threshold in a single run, with no promo marker.',
    discover_fetch_failed: 'Sitemap or discovery URL returned 4xx or 5xx — likely permanent removal.',
    unmatched_has_isbn:    'Shop book carries a valid ISBN but did not link to any canonical book.',
    scrape_run_failed:     'A scrape run ended with status=failed before completing its phase.',
    product_url_non_book:  'A URL classified as a product page resolved to something that is not a book (DVD, stationery, gift card, etc.).',
  };
  // (waveTotal fetched above, before the early-return guards)

  // Type-specific actions for the Fix-this panel.
  const fixActions = (() => {
    const open = (page, p) => () => goto(page, p);
    switch (type) {
      case 'missing_price':
      case 'invalid_isbn':
      case 'price_spike':
        return [
          { label:'Open parser', primary:true, action:open('parser', { shop }), desc:`Edit selectors for ${shop}` },
          { label:'Re-scrape URL',   action:() => {}, desc:'Re-fetch this URL only' },
          { label:'Bulk-ack wave',   action:() => {}, desc:`Acknowledge all ${waveTotal.toLocaleString()} ${type} issues in this wave` },
        ];
      case 'match_isbn_drift':
      case 'unmatched_has_isbn':
        return [
          { label:'Open book', primary:true, action:open('book', {}), desc:'Inspect the canonical book record' },
          { label:'Re-run matcher',  action:() => {}, desc:'Re-evaluate this shop book against the matcher' },
          { label:'Bulk-ack wave',   action:() => {}, desc:`Acknowledge all ${waveTotal.toLocaleString()} ${type} issues in this wave` },
        ];
      case 'discover_fetch_failed':
        return [
          { label:'Edit sitemap', primary:true, action:open('shop-detail', { name: shop }), desc:'Manage discovery URLs for this shop' },
          { label:'Remove URL',   action:() => {}, desc:'Stop scraping this URL' },
        ];
      case 'scrape_run_failed':
        return [
          { label:'Open run', primary:true, action:open('run-detail', { id: runId }), desc:`Inspect run #${runId}` },
          { label:'Re-run',   action:() => {}, desc:'Re-trigger with the same parameters' },
        ];
      case 'non_product_active':
      case 'product_url_non_book':
        return [
          { label:'Open classifier', primary:true, action:open('parser', { shop }), desc:'Update URL classification rules' },
          { label:'Mark URL non-book', action:() => {}, desc:'Add to skip list' },
          { label:'Bulk-ack wave', action:() => {}, desc:`Acknowledge all ${waveTotal.toLocaleString()} similar` },
        ];
      default:
        return [
          { label:'Open parser', primary:true, action:open('parser', {}), desc:'Edit selectors' },
          { label:'Re-scrape',   action:() => {}, desc:'Re-fetch this URL only' },
        ];
    }
  })();

  const field = FIELD_BY_TYPE[type] || 'unknown';
  const desc  = DESC_BY_TYPE[type] || '—';

  const sevTone = { critical:'err', high:'warn', medium:'warn', low:'neutral' };
  const lifecycleTone = { new:'err', acknowledged:'accent', snoozed:'warn', resolved:'ok' };

  const rawSnippet = apiData?.raw_value || '(no raw value recorded)';


  const trimUrl = url ? url.replace(/^https?:\/\//, '') : null;
  const trimmedShown = trimUrl && trimUrl.length > 48 ? trimUrl.slice(0, 48) + '…' : trimUrl;

  return (
    <HFShell {...nav} activePage="issues"
      title={
        <span style={{display:'flex', alignItems:'center', gap:12, flexWrap:'wrap'}}>
          <span style={{color: sev==='critical'?HF.errInk:sev==='high'?HF.warnInk:HF.ink3, display:'flex'}}>{HF_ICONS.bang}</span>
          <span>{type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</span>
          <HFPill tone={sevTone[sev]}>{sev}</HFPill>
          <HFPill tone={lifecycleTone[lifecycle]}>{lifecycle}</HFPill>
        </span>
      }
      subtitle={
        <span style={{fontFamily:HF.mono, fontSize:12.5, color:HF.ink3, display:'flex', flexWrap:'wrap', gap:8, alignItems:'center'}}>
          <span>{id}</span><span style={{color:HF.ink5}}>·</span>
          <span>field={field}</span><span style={{color:HF.ink5}}>·</span>
          <span>{age}</span><span style={{color:HF.ink5}}>·</span>
          {book && <span style={{color:HF.ink2, fontFamily:HF.sans, fontWeight:500}}>"{book}"</span>}
        </span>
      }
      breadcrumb={<>
        <a href="#" onClick={(e)=>{e.preventDefault(); goto('issues');}} style={{color:HF.ink3, textDecoration:'none'}}>Issues</a>
        <span style={{color:HF.ink5}}>/</span>
        <span style={{color:HF.ink, fontWeight:500, fontFamily:HF.mono}}>{id}</span>
      </>}
      actions={<>
        {lifecycle === 'new'
          ? <HFButton><span style={{display:'flex'}}>{HF_ICONS.check}</span> Mark acknowledged</HFButton>
          : <HFButton>Move to New</HFButton>}
        <HFButton variant="primary" onClick={() => goto('issues')}>Back to issues</HFButton>
      </>}
    >
      {/* 4-tile KPI strip: SEVERITY / LIFECYCLE / DETECTED / FIELD */}
      <div style={{
        display:'grid', gridTemplateColumns:'repeat(4, 1fr)',
        border:`1px solid ${HF.border}`, borderRadius: HF.r3,
        background: HF.surface, boxShadow: HF.shadow,
        overflow:'hidden', marginBottom: HF.gap,
      }}>
        {[
          { label:'SEVERITY',  value:sev,       tone: sev==='critical'?'err':sev==='high'?'warn':'neutral' },
          { label:'LIFECYCLE', value:lifecycle, tone: lifecycle==='new'?'err':lifecycle==='resolved'?'ok':'neutral' },
          { label:'DETECTED',  value:age,       sub:`from run #${runId}` },
          { label:'FIELD',     value:field,     sub:'affected' },
        ].map((k, i, arr) => (
          <div key={i} style={{
            padding:'18px 22px',
            borderRight: i < arr.length - 1 ? `1px solid ${HF.border}` : 'none',
            display:'flex', flexDirection:'column', gap:6,
          }}>
            <div style={{fontSize: 11, color: HF.ink3, fontWeight: 600, textTransform:'uppercase', letterSpacing: 0.6}}>{k.label}</div>
            <div style={{
              fontFamily: HF.mono, fontSize: 24, fontWeight: 600, lineHeight: 1.1,
              letterSpacing: -0.4,
              color: k.tone === 'err' ? HF.errInk : k.tone === 'warn' ? HF.warnInk : k.tone === 'ok' ? HF.okInk : HF.ink,
            }}>{k.value}</div>
            {k.sub && (
              <div style={{fontSize: 12, color: HF.ink3, fontFamily: HF.mono, fontVariantNumeric:'tabular-nums'}}>{k.sub}</div>
            )}
          </div>
        ))}
      </div>

      {/* Wave context callout — only show when wave is meaningful (> 1 issue) */}
      {waveTotal > 1 && (
        <div style={{
          marginBottom: HF.gap, padding: '12px 14px',
          background: HF.warnSoft, border: `1px solid ${HF.warnBorder}`,
          borderRadius: 6,
          display:'flex', alignItems:'center', gap:14,
        }}>
          <span style={{
            display:'inline-flex', alignItems:'center', justifyContent:'center',
            width:28, height:28, borderRadius:6,
            background: HF.warnInk, color: '#fff',
            fontFamily: HF.mono, fontSize: 13, fontWeight: 700, flexShrink:0,
          }}>⚠</span>
          <div style={{flex:1, minWidth:0}}>
            <div style={{fontSize:13, color: HF.ink, fontWeight:600, marginBottom:2}}>
              This is 1 of <span style={{fontFamily:HF.mono}}>{waveTotal.toLocaleString()}</span> issues from run <a href="#" onClick={(e)=>{e.preventDefault(); goto('run-detail', {id:runId});}} style={{color:HF.warnInk, fontFamily:HF.mono, textDecoration:'underline', textUnderlineOffset:2}}>#{runId}</a>
            </div>
            <div style={{fontSize:12, color: HF.ink2, lineHeight:1.5}}>
              Likely a single parser regression, not {waveTotal.toLocaleString()} separate problems. Ack the entire wave in one action — see "Fix this" below.
            </div>
          </div>
          <HFButton size="md" variant="primary">View wave →</HFButton>
        </div>
      )}

      {/* What this means + Failure details */}
      <div style={{display:'grid', gridTemplateColumns:'1.4fr 1fr', gap:HF.gap, marginBottom:HF.gap, alignItems:'start'}}>
        <HFCard
          title="What this means"
          sub={`issue type: ${type}`}
        >
          <div style={{padding:`14px ${HF.cardP}px`, fontSize:13.5, color:HF.ink, lineHeight:1.6, textWrap:'pretty'}}>
            {desc}
          </div>
          <div style={{padding:`0 ${HF.cardP}px ${HF.cardP}px`}}>
            <div style={{fontSize:10.5, color:HF.ink4, textTransform:'uppercase', letterSpacing:0.5, fontWeight:600, marginBottom:6}}>Raw extraction snippet</div>
            <pre style={{
              margin:0, padding:'10px 12px',
              background:'#0F1419', color:'#D9E0E6', borderRadius:6,
              fontFamily:HF.mono, fontSize:11.5, lineHeight:1.55,
              overflow:'auto', whiteSpace:'pre',
            }}>{rawSnippet}</pre>
          </div>
        </HFCard>

        <HFCard title="Failure details">
          <div style={{padding:`4px 0 8px`}}>
            {[
              { k:'Field',     v:field,   mono:true },
              { k:'Issue',     v:type,    mono:true },
              { k:'Severity',  v:sev,     mono:true, tone:sevTone[sev] },
              { k:'Lifecycle', v:lifecycle, mono:true, tone:lifecycleTone[lifecycle] },
              { k:'Detected',  v:age },
              { k:'Run',       v:`#${runId}`, mono:true, link:() => goto('run-detail', { id:runId }) },
              { k:'Shop',      v:shop || '—', mono:true, link: shop ? () => goto('shop-detail', { name:shop }) : null },
              ...(url ? [{ k:'URL', v:trimmedShown, mono:true, urlLink: url, extra: <a href="#" onClick={(e)=>{e.preventDefault(); goto('urls');}} style={{color:HF.accentInk, fontFamily:HF.sans, fontSize:11.5, textDecoration:'none', whiteSpace:'nowrap'}}>View in URLs →</a> }] : []),
            ].map((row, i, arr) => (
              <div key={row.k} style={{
                display:'grid', gridTemplateColumns:'90px 1fr',
                padding:`8px ${HF.cardP}px`, alignItems:'center',
                borderBottom: i < arr.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
                fontSize:12.5,
              }}>
                <span style={{color:HF.ink3, fontSize:11.5}}>{row.k}</span>
                <span style={{display:'flex', alignItems:'center', gap:10, justifyContent:'space-between', minWidth:0}}>
                  {row.urlLink ? (
                    <a href={row.urlLink} target="_blank" rel="noopener noreferrer" style={{color:HF.ink, fontFamily:HF.mono, textDecoration:'underline', textUnderlineOffset:2, textDecorationColor:HF.ink4, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap', minWidth:0, flex:1}}>{row.v}</a>
                  ) : row.link ? (
                    <a href="#" onClick={(e)=>{e.preventDefault(); row.link();}} style={{color:HF.accentInk, fontFamily: row.mono?HF.mono:HF.sans, fontWeight:500, textDecoration:'none'}}>{row.v}</a>
                  ) : (
                    <span style={{
                      color: row.tone==='err'?HF.errInk:row.tone==='warn'?HF.warnInk:row.tone==='ok'?HF.okInk:HF.ink,
                      fontWeight: row.tone ? 600 : 500,
                      fontFamily: row.mono ? HF.mono : HF.sans,
                    }}>{row.v}</span>
                  )}
                  {row.extra}
                </span>
              </div>
            ))}
          </div>
        </HFCard>
      </div>

      {/* Fix this — type-specific action panel */}
      <HFCard
        title="Fix this"
        sub="Type-aware actions for this issue. Bulk actions apply to the entire wave."
        style={{marginBottom:HF.gap}}
        flush
      >
        {fixActions.map((a, i, arr) => (
          <div key={a.label} style={{
            padding:`12px ${HF.cardP}px`,
            borderBottom: i < arr.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
            display:'grid', gridTemplateColumns:'1fr auto', gap:14, alignItems:'center',
          }}>
            <div style={{display:'flex', flexDirection:'column', gap:2, minWidth:0}}>
              <span style={{fontSize:13, color:HF.ink, fontWeight:500}}>{a.label}</span>
              <span style={{fontSize:12, color:HF.ink3}}>{a.desc}</span>
            </div>
            <HFButton size="sm" variant={a.primary?'primary':'default'} onClick={a.action}>{a.label}</HFButton>
          </div>
        ))}
      </HFCard>

      {/* Affected book */}
      {book && (
        <HFCard
          title="Affected book"
          sub="book where this issue was detected"
          style={{marginBottom:HF.gap}}
        >
          <div style={{padding:`14px ${HF.cardP}px`, display:'flex', alignItems:'center', gap:14}}>
            <span style={{
              width:48, height:48, borderRadius:8,
              background:HF.accentSoft, border:`1px solid ${HF.accentBorder}`,
              display:'flex', alignItems:'center', justifyContent:'center',
              color:HF.accentInk, flexShrink:0,
            }}>{HF_ICONS.books}</span>
            <div style={{flex:1, minWidth:0, display:'flex', flexDirection:'column', gap:3}}>
              <a href="#" onClick={(e)=>{e.preventDefault(); goto('shop-book-detail', { id: apiData?.shop_book_id });}} style={{
                color:HF.ink, fontWeight:600, fontSize:14, textDecoration:'none', overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
              }}>{book}</a>
              <span style={{fontFamily:HF.mono, fontSize:11.5, color:HF.ink3}}>
                #{apiData?.shop_book_id || '—'} <span style={{color:HF.ink5, margin:'0 6px'}}>·</span> {shop}
              </span>
            </div>
            {url && (
              <HFButton onClick={() => window.open(url, '_blank')}>
                <span style={{display:'flex'}}>{HF_ICONS.external}</span> Open book
              </HFButton>
            )}
          </div>
        </HFCard>
      )}

      {/* Other issues of same type in same shop */}
      <HFCard
        title={`Other ${type} issues${shop ? ' in ' + shop : ''}`}
        sub={`${otherIssues.length} of ${(waveTotal - 1).toLocaleString()} other issues in this wave`}
        flush
      >
        {otherIssues.length === 0 && (
          <div style={{padding:`14px ${HF.cardP}px`, color:HF.ink3, fontSize:13}}>No other issues of this type found.</div>
        )}
        {otherIssues.map((o, i, arr) => (
          <div key={o.id} style={{
            padding:`12px ${HF.cardP}px`,
            borderBottom: i < arr.length-1 ? `1px solid ${HF.borderFaint}` : 'none',
            display:'grid', gridTemplateColumns:'14px 1fr auto auto', gap:14, alignItems:'center',
            cursor:'pointer',
          }}
          onClick={() => goto('issue-detail', { id: o.id })}
          className="hf-row"
          >
            <span style={{
              width:8, height:8, borderRadius:'50%',
              background: sev === 'critical' ? HF.err : sev === 'high' ? HF.warn : HF.ink4,
            }}/>
            <div style={{display:'flex', flexDirection:'column', gap:2, minWidth:0}}>
              <span style={{color:HF.ink, fontSize:13, fontWeight:500, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>{o.book}</span>
              <span style={{fontFamily:HF.mono, fontSize:11.5, color:HF.ink3}}>
                ISS-{o.id} <span style={{color:HF.ink5, margin:'0 6px'}}>·</span> {o.issue}
              </span>
            </div>
            <span style={{fontFamily:HF.mono, fontSize:11.5, color:HF.ink3, whiteSpace:'nowrap'}}>{o.age}</span>
            <span style={{color:HF.ink4, display:'flex'}}>{HF_ICONS.chevron}</span>
          </div>
        ))}
      </HFCard>
    </HFShell>
  );
}

Object.assign(window, { HFIssueDetail });
