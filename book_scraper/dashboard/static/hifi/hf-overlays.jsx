// Hi-fi global overlays — command palette, avatar menu, settings, add/new dialogs.
// Registers window.HF_APP with openers. Any page can call them.

// ══════════════════════════════ Base Modal ══════════════════════════════
function HFModal({ open, onClose, width = 560, children, align = 'center' }) {
  const HF = getHF();
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onClose && onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, zIndex: 100,
      background: 'rgba(16,24,40,.35)',
      display: 'flex', alignItems: align === 'top' ? 'flex-start' : 'center',
      justifyContent: 'center',
      paddingTop: align === 'top' ? 96 : 0,
      fontFamily: HF.sans,
      backdropFilter: 'blur(2px)',
    }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        width, maxWidth: 'calc(100vw - 32px)', maxHeight: 'calc(100vh - 64px)',
        background: HF.surface, borderRadius: HF.r3,
        border: `1px solid ${HF.border}`,
        boxShadow: '0 24px 48px -12px rgba(16,24,40,.25), 0 0 0 1px rgba(16,24,40,.04)',
        overflow: 'hidden', display: 'flex', flexDirection: 'column',
      }}>
        {children}
      </div>
    </div>
  );
}

// Modal header/footer/body primitives
function HFModalHead({ title, sub, onClose, icon }) {
  const HF = getHF();
  return (
    <div style={{
      padding: '14px 18px', borderBottom: `1px solid ${HF.borderFaint}`,
      display: 'flex', alignItems: 'center', gap: 12,
    }}>
      {icon && (
        <div style={{
          width: 32, height: 32, borderRadius: 7,
          background: HF.accentSoft, border: `1px solid ${HF.accentBorder}`,
          color: HF.accent,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>{icon}</div>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: HF.ink, letterSpacing: -0.1 }}>{title}</div>
        {sub && <div style={{ fontSize: 12, color: HF.ink3, marginTop: 2 }}>{sub}</div>}
      </div>
      {onClose && (
        <button onClick={onClose} className="hf-btn" style={{
          background: 'transparent', border: 'none', color: HF.ink3,
          width: 28, height: 28, borderRadius: 5, cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16,
        }}>✕</button>
      )}
    </div>
  );
}

function HFModalBody({ children, style }) {
  return <div className="hf-scroll" style={{ padding: '16px 18px', overflow: 'auto', ...style }}>{children}</div>;
}

function HFModalFoot({ children }) {
  const HF = getHF();
  return (
    <div style={{
      padding: '12px 18px', borderTop: `1px solid ${HF.borderFaint}`,
      display: 'flex', gap: 8, justifyContent: 'flex-end',
      background: HF.bg,
    }}>{children}</div>
  );
}

// Field — labeled input group
function HFField({ label, hint, children, required }) {
  const HF = getHF();
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 11.5, fontWeight: 600, color: HF.ink2, marginBottom: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
        {label}
        {required && <span style={{ color: HF.errInk }}>*</span>}
      </div>
      {children}
      {hint && <div style={{ fontSize: 11.5, color: HF.ink3, marginTop: 5 }}>{hint}</div>}
    </div>
  );
}

function HFInput({ value, onChange, placeholder, mono, style, autoFocus, ...rest }) {
  const HF = getHF();
  return (
    <input
      autoFocus={autoFocus}
      type="text" value={value || ''} placeholder={placeholder}
      onChange={(e) => onChange && onChange(e.target.value)}
      style={{
        width: '100%', boxSizing: 'border-box',
        padding: '7px 10px', height: 34,
        background: HF.input, border: `1px solid ${HF.borderStrong}`, borderRadius: 6,
        color: HF.ink, fontSize: 12.5,
        fontFamily: mono ? HF.mono : HF.sans,
        outline: 'none',
        ...style,
      }}
      onFocus={(e) => e.currentTarget.style.borderColor = HF.accent}
      onBlur={(e) => e.currentTarget.style.borderColor = HF.borderStrong}
      {...rest}
    />
  );
}

function HFSelect({ value, onChange, options, style }) {
  const HF = getHF();
  return (
    <select value={value} onChange={(e) => onChange && onChange(e.target.value)} style={{
      width: '100%', boxSizing: 'border-box',
      padding: '6px 10px', height: 34,
      background: HF.input, border: `1px solid ${HF.borderStrong}`, borderRadius: 6,
      color: HF.ink, fontSize: 12.5, fontFamily: HF.sans, cursor: 'pointer',
      outline: 'none',
      ...style,
    }}>
      {options.map(o => {
        const v = typeof o === 'string' ? o : o.value;
        const l = typeof o === 'string' ? o : o.label;
        return <option key={v} value={v}>{l}</option>;
      })}
    </select>
  );
}

function HFSegmented({ value, onChange, options }) {
  const HF = getHF();
  return (
    <div style={{
      display: 'inline-flex', background: HF.subtle,
      border: `1px solid ${HF.border}`, borderRadius: 6, padding: 2, gap: 2,
      whiteSpace: 'nowrap',
    }}>
      {options.map(o => {
        const v = typeof o === 'string' ? o : o.value;
        const l = typeof o === 'string' ? o : o.label;
        const sel = v === value;
        return (
          <button key={v} onClick={() => onChange(v)} style={{
            padding: '5px 10px', fontSize: 12, height: 26,
            background: sel ? HF.surface : 'transparent',
            border: sel ? `1px solid ${HF.border}` : '1px solid transparent',
            borderRadius: 4, color: sel ? HF.ink : HF.ink3,
            fontWeight: sel ? 500 : 400, fontFamily: HF.sans, cursor: 'pointer',
            boxShadow: sel ? '0 1px 2px rgba(16,24,40,.04)' : 'none',
            whiteSpace: 'nowrap',
          }}>{l}</button>
        );
      })}
    </div>
  );
}

// ══════════════════════════════ Command palette (⌘K) ══════════════════════════════
function HFCommandK({ open, onClose, goto }) {
  const HF = getHF();
  const [q, setQ] = React.useState('');
  const [idx, setIdx] = React.useState(0);

  const pages = [
    { t:'Go to Overview',     k:'nav', p:'overview',   hint:'dashboard · health' },
    { t:'Go to Runs',         k:'nav', p:'runs',       hint:'scrape history' },
    { t:'Go to Schedules',    k:'nav', p:'cron',       hint:'cron jobs' },
    { t:'Go to Issues',       k:'nav', p:'issues',     hint:'errors · failures' },
    { t:'Go to Shop Books',   k:'nav', p:'shop-books', hint:'catalog' },
    { t:'Go to URLs',         k:'nav', p:'urls',       hint:'source pages' },
    { t:'Go to Shops',        k:'nav', p:'shops',      hint:'targets · parsers' },
    { t:'Go to Prices',       k:'nav', p:'prices',     hint:'price tracking' },
  ];
  const actions = [
    { t:'New run',            k:'act', a:'openNewRun',      hint:'trigger scrape' },
    { t:'New schedule',       k:'act', a:'openNewSchedule', hint:'add cron job' },
    { t:'Add URL',            k:'act', a:'openAddURL',      hint:'enqueue a page' },
    { t:'Add shop',           k:'act', a:'openAddShop',     hint:'new scrape target' },
    { t:'Add book',           k:'act', a:'openAddBook',     hint:'manual entry' },
    { t:'Edit parser…',       k:'act', a:'openParserPick',  hint:'DOM selectors' },
    { t:'Open settings',      k:'act', a:'openSettings',    hint:'preferences' },
  ];
  const quick = [
    { t:'Run vaga.lt now',    k:'jump', p:'shop-detail',      pp:{shop:'vaga'},      hint:'shop · 1,720 URLs' },
    { t:'Run knygos.lt now',  k:'jump', p:'shop-detail',      pp:{shop:'knygos'},    hint:'shop · 980 URLs' },
    { t:'Open Run #4821',     k:'jump', p:'run-detail',       pp:{id:'4821'},        hint:'running · 72%' },
    { t:'Triage 3 issues',    k:'jump', p:'issues',           pp:{},                 hint:'12 open' },
  ];

  const all = [...pages, ...actions, ...quick];
  const filtered = React.useMemo(() => {
    const qq = q.trim().toLowerCase();
    if (!qq) return all;
    return all.filter(x => x.t.toLowerCase().includes(qq) || (x.hint || '').toLowerCase().includes(qq));
  }, [q]);

  React.useEffect(() => { setIdx(0); }, [q]);
  React.useEffect(() => { if (open) setQ(''); }, [open]);

  const run = (item) => {
    onClose();
    if (item.k === 'nav') goto(item.p);
    else if (item.k === 'jump') goto(item.p, item.pp || {});
    else if (item.k === 'act') {
      const fn = window.HF_APP && window.HF_APP[item.a];
      if (fn) fn();
    }
  };

  const onKey = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setIdx(i => Math.min(filtered.length - 1, i + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setIdx(i => Math.max(0, i - 1)); }
    else if (e.key === 'Enter')    { e.preventDefault(); if (filtered[idx]) run(filtered[idx]); }
  };

  const sections = [
    { label: 'Pages',    items: filtered.filter(x => x.k === 'nav') },
    { label: 'Actions',  items: filtered.filter(x => x.k === 'act') },
    { label: 'Jump to',  items: filtered.filter(x => x.k === 'jump') },
  ];

  // global index for highlight
  let running = 0;

  return (
    <HFModal open={open} onClose={onClose} width={620} align="top">
      <div style={{
        padding: '10px 14px', borderBottom: `1px solid ${HF.borderFaint}`,
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <span style={{ color: HF.ink3, display: 'flex' }}>{HF_ICONS.search}</span>
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey}
          placeholder="Search pages, actions, shops…"
          style={{
            flex: 1, border: 'none', outline: 'none', background: 'transparent',
            color: HF.ink, fontSize: 14.5, fontFamily: HF.sans, padding: '4px 0',
          }}
        />
        <span style={{
          fontFamily: HF.mono, fontSize: 10.5,
          padding: '2px 6px', background: HF.subtle,
          border: `1px solid ${HF.border}`, borderRadius: 4, color: HF.ink3,
        }}>esc</span>
      </div>
      <div className="hf-scroll" style={{ maxHeight: 420, overflow: 'auto', padding: 6 }}>
        {filtered.length === 0 && (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: HF.ink3, fontSize: 13 }}>
            No matches for "<span style={{ fontFamily: HF.mono, color: HF.ink2 }}>{q}</span>"
          </div>
        )}
        {sections.map(sec => {
          if (sec.items.length === 0) return null;
          return (
            <div key={sec.label}>
              <div style={{
                fontSize: 10.5, color: HF.ink4, fontWeight: 600,
                textTransform: 'uppercase', letterSpacing: 0.6,
                padding: '8px 10px 4px',
              }}>{sec.label}</div>
              {sec.items.map(it => {
                const myIdx = running++;
                const hl = myIdx === idx;
                return (
                  <div key={sec.label + it.t}
                    onMouseEnter={() => setIdx(myIdx)}
                    onClick={() => run(it)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10,
                      padding: '7px 10px', margin: '1px 0',
                      borderRadius: 5, cursor: 'pointer',
                      background: hl ? HF.accentSoft : 'transparent',
                      color: hl ? HF.accentInk : HF.ink,
                    }}>
                    <span style={{
                      width: 22, height: 22, borderRadius: 4,
                      background: hl ? HF.accentSoft2 : HF.subtle,
                      color: hl ? HF.accent : HF.ink3,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      flexShrink: 0,
                    }}>
                      {it.k === 'nav' ? HF_ICONS.arrow : it.k === 'jump' ? HF_ICONS.play : HF_ICONS.plus}
                    </span>
                    <span style={{ flex: 1, fontSize: 13, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.t}</span>
                    <span style={{ fontSize: 11.5, color: hl ? HF.accentInk : HF.ink3, fontFamily: HF.mono, whiteSpace: 'nowrap', flexShrink: 0, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.hint}</span>
                    {hl && <span style={{ fontSize: 11, color: HF.accentInk, fontFamily: HF.mono }}>↵</span>}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
      <div style={{
        padding: '8px 14px', borderTop: `1px solid ${HF.borderFaint}`,
        background: HF.bg,
        display: 'flex', gap: 14, alignItems: 'center',
        fontSize: 11, color: HF.ink3, fontFamily: HF.mono,
      }}>
        <span>↑↓ navigate</span>
        <span>↵ select</span>
        <span>esc close</span>
        <span style={{ marginLeft: 'auto' }}>{filtered.length} result{filtered.length === 1 ? '' : 's'}</span>
      </div>
    </HFModal>
  );
}

// ══════════════════════════════ New Run dialog ══════════════════════════════
function HFNewRunDialog({ open, onClose, goto }) {
  const HF = getHF();
  const [shop, setShop] = React.useState('');
  const [phase, setPhase] = React.useState('scan');
  const [strategy, setStrategy] = React.useState('sitemap');
  const [mode, setMode] = React.useState('delta');
  const [shops, setShops] = React.useState([]);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState('');

  React.useEffect(() => {
    if (!open) return;
    setError('');
    fetch('/api/shops')
      .then(r => r.json())
      .then(d => {
        const list = d.shops || [];
        setShops(list);
        setShop(prev => prev || (list[0] && list[0].name) || '');
      })
      .catch(() => setError('Could not load shops'));
  }, [open]);

  const selShop = shops.find(s => s.name === shop);
  const urlCount = selShop ? (selShop.discovered_urls || 0) : 0;

  const submit = async () => {
    setSubmitting(true);
    setError('');
    try {
      const resp = await fetch('/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, phase, strategy: phase === 'discover' ? strategy : '', mode }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Request failed (${resp.status})`);
      }
      onClose();
      goto('runs');
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <HFModal open={open} onClose={onClose} width={540}>
      <HFModalHead title="New run" sub="Trigger a scrape manually" onClose={onClose} icon={HF_ICONS.play}/>
      <HFModalBody>
        <HFField label="Shop" required>
          <HFSelect value={shop} onChange={setShop} options={shops.map(s => ({
            value: s.name,
            label: `${s.name}.lt · ${(s.discovered_urls || 0).toLocaleString()} URLs`,
          }))}/>
        </HFField>
        <HFField label="Phase" hint={
          phase === 'scan'
            ? 'Scrape product pages for already-discovered URLs'
            : 'Find new URLs (sitemap / categories / full crawl)'
        }>
          <HFSegmented value={phase} onChange={setPhase} options={[
            { value:'scan',     label:'Scan (products)' },
            { value:'discover', label:'Discover (URLs)' },
          ]}/>
        </HFField>
        {phase === 'scan' && (
          <HFField label="Mode" hint={{
            full:   `Re-scrape every known URL (${urlCount.toLocaleString()} items)`,
            delta:  `Resumable scan — only URLs not yet scraped`,
            sample: `First 10 URLs only (for testing)`,
          }[mode]}>
            <HFSegmented value={mode} onChange={setMode} options={[
              { value:'delta',  label:'Delta' },
              { value:'full',   label:'Full' },
              { value:'sample', label:'Sample (10)' },
            ]}/>
          </HFField>
        )}
        {phase === 'discover' && (
          <HFField label="Strategy" hint={{
            sitemap:    'Read /sitemap.xml — fastest, only URL discovery',
            categories: 'Walk category listing pages — also extracts prices',
            full_crawl: 'Follow every internal link — slowest, most thorough',
          }[strategy]}>
            <HFSegmented value={strategy} onChange={setStrategy} options={[
              { value:'sitemap',    label:'Sitemap' },
              { value:'categories', label:'Categories' },
              { value:'full_crawl', label:'Full crawl' },
            ]}/>
          </HFField>
        )}
        {error && (
          <div style={{
            color: HF.errInk, fontSize: 12.5, padding: '8px 10px',
            background: HF.errSoft, border: `1px solid ${HF.errBorder}`, borderRadius: 6,
          }}>{error}</div>
        )}
      </HFModalBody>
      <HFModalFoot>
        <div style={{ flex: 1, fontSize: 11.5, color: HF.ink3, fontFamily: HF.mono, display: 'flex', alignItems: 'center' }}>
          {selShop ? `${urlCount.toLocaleString()} URLs available` : 'Loading shops…'}
        </div>
        <HFButton onClick={onClose}>Cancel</HFButton>
        <HFButton variant="primary" onClick={submit} disabled={!shop || submitting}>
          <span style={{ display: 'flex' }}>{HF_ICONS.play}</span> {submitting ? 'Starting…' : 'Start run'}
        </HFButton>
      </HFModalFoot>
    </HFModal>
  );
}

// ══════════════════════════════ New Schedule dialog ══════════════════════════════
function HFNewScheduleDialog({ open, onClose }) {
  const HF = getHF();
  const [name, setName] = React.useState('');
  const [shop, setShop] = React.useState('vaga');
  const [cron, setCron] = React.useState('0 */2 * * *');
  const [preset, setPreset] = React.useState('2h');

  const presets = [
    { v:'15m',   lbl:'Every 15 min', cron:'*/15 * * * *' },
    { v:'1h',    lbl:'Hourly',       cron:'0 * * * *' },
    { v:'2h',    lbl:'Every 2 hrs',  cron:'0 */2 * * *' },
    { v:'6h',    lbl:'Every 6 hrs',  cron:'0 */6 * * *' },
    { v:'daily', lbl:'Daily 03:00',  cron:'0 3 * * *' },
    { v:'custom',lbl:'Custom',       cron:'' },
  ];

  const pickPreset = (v) => {
    setPreset(v);
    const p = presets.find(x => x.v === v);
    if (p && p.v !== 'custom') setCron(p.cron);
  };

  return (
    <HFModal open={open} onClose={onClose} width={540}>
      <HFModalHead title="New schedule" sub="Run a shop on a recurring cron" onClose={onClose} icon={HF_ICONS.cron}/>
      <HFModalBody>
        <HFField label="Name" required>
          <HFInput value={name} onChange={setName} placeholder="e.g. vaga-hourly" autoFocus/>
        </HFField>
        <HFField label="Shop" required>
          <HFSelect value={shop} onChange={setShop} options={[
            { value:'vaga', label:'vaga.lt' },
            { value:'knygos', label:'knygos.lt' },
            { value:'patogupirkti', label:'patogupirkti.lt' },
            { value:'humanitas', label:'humanitas.lt' },
          ]}/>
        </HFField>
        <HFField label="Frequency">
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
            {presets.map(p => (
              <button key={p.v} onClick={() => pickPreset(p.v)} style={{
                padding: '4px 9px', fontSize: 11.5, height: 26,
                background: preset === p.v ? HF.accentSoft : HF.surface,
                border: `1px solid ${preset === p.v ? HF.accentBorder : HF.borderStrong}`,
                color: preset === p.v ? HF.accentInk : HF.ink2,
                borderRadius: 5, cursor: 'pointer', fontFamily: HF.sans, fontWeight: 500,
              }}>{p.lbl}</button>
            ))}
          </div>
          <HFInput value={cron} onChange={(v) => { setCron(v); setPreset('custom'); }} mono placeholder="0 */2 * * *"/>
          <div style={{ fontSize: 11.5, color: HF.ink3, marginTop: 6, fontFamily: HF.mono }}>
            min · hr · day · mo · dow
          </div>
        </HFField>
        <HFField label="Mode">
          <HFSegmented value="delta" onChange={() => {}} options={[
            { value:'full', label:'Full' },
            { value:'delta', label:'Delta' },
            { value:'failed', label:'Retry failed' },
          ]}/>
        </HFField>
      </HFModalBody>
      <HFModalFoot>
        <HFButton onClick={onClose}>Cancel</HFButton>
        <HFButton variant="primary" onClick={onClose} disabled={!name}>Create schedule</HFButton>
      </HFModalFoot>
    </HFModal>
  );
}

// ══════════════════════════════ Add URL dialog ══════════════════════════════
function HFAddURLDialog({ open, onClose }) {
  const HF = getHF();
  const [url, setUrl] = React.useState('');
  const [shop, setShop] = React.useState('vaga');
  const [mode, setMode] = React.useState('single');
  const [bulk, setBulk] = React.useState('');

  return (
    <HFModal open={open} onClose={onClose} width={540}>
      <HFModalHead title="Add URL" sub="Enqueue one or more URLs for scraping" onClose={onClose} icon={HF_ICONS.urls}/>
      <HFModalBody>
        <HFField label="Shop" required>
          <HFSelect value={shop} onChange={setShop} options={[
            { value:'vaga', label:'vaga.lt' },
            { value:'knygos', label:'knygos.lt' },
            { value:'patogupirkti', label:'patogupirkti.lt' },
          ]}/>
        </HFField>
        <HFField label="Mode">
          <HFSegmented value={mode} onChange={setMode} options={[
            { value:'single', label:'Single URL' },
            { value:'bulk',   label:'Bulk paste' },
            { value:'file',   label:'Upload CSV' },
          ]}/>
        </HFField>
        {mode === 'single' && (
          <HFField label="URL" required>
            <HFInput value={url} onChange={setUrl} placeholder="https://vaga.lt/knygos/…" mono autoFocus/>
          </HFField>
        )}
        {mode === 'bulk' && (
          <HFField label="URLs — one per line" hint={`${bulk.split('\n').filter(Boolean).length} URL${bulk.split('\n').filter(Boolean).length === 1 ? '' : 's'}`}>
            <textarea value={bulk} onChange={(e) => setBulk(e.target.value)} style={{
              width: '100%', boxSizing: 'border-box', minHeight: 120,
              padding: '8px 10px',
              background: HF.input, border: `1px solid ${HF.borderStrong}`, borderRadius: 6,
              color: HF.ink, fontSize: 12, fontFamily: HF.mono, outline: 'none', resize: 'vertical',
            }} placeholder={'https://vaga.lt/knygos/sapiens\nhttps://vaga.lt/knygos/factfulness\n…'}/>
          </HFField>
        )}
        {mode === 'file' && (
          <div style={{
            padding: 28, textAlign: 'center',
            background: HF.bg, border: `2px dashed ${HF.border}`, borderRadius: 8,
            color: HF.ink3, fontSize: 13,
          }}>
            <div style={{ marginBottom: 8, color: HF.ink4, display: 'flex', justifyContent: 'center' }}>{HF_ICONS.download}</div>
            <div style={{ color: HF.ink2, fontWeight: 500 }}>Drop CSV here</div>
            <div style={{ fontSize: 11.5, marginTop: 4 }}>Column: <span style={{ fontFamily: HF.mono }}>url</span> · optional: <span style={{ fontFamily: HF.mono }}>priority</span></div>
          </div>
        )}
      </HFModalBody>
      <HFModalFoot>
        <HFButton onClick={onClose}>Cancel</HFButton>
        <HFButton variant="primary" onClick={onClose}>Enqueue</HFButton>
      </HFModalFoot>
    </HFModal>
  );
}

// ══════════════════════════════ Add Shop dialog ══════════════════════════════
function HFAddShopDialog({ open, onClose, goto }) {
  const HF = getHF();
  const [name, setName] = React.useState('');
  const [domain, setDomain] = React.useState('');

  return (
    <HFModal open={open} onClose={onClose} width={520}>
      <HFModalHead title="Add shop" sub="A new scrape target. You'll configure the parser next." onClose={onClose} icon={HF_ICONS.shops}/>
      <HFModalBody>
        <HFField label="Shop name" required>
          <HFInput value={name} onChange={setName} placeholder="vaga.lt" autoFocus/>
        </HFField>
        <HFField label="Base URL" required>
          <HFInput value={domain} onChange={setDomain} placeholder="https://vaga.lt" mono/>
        </HFField>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <HFField label="Rate limit" hint="requests / sec">
            <HFInput value="2" onChange={() => {}} mono/>
          </HFField>
          <HFField label="User agent">
            <HFSelect value="default" onChange={() => {}} options={[
              { value:'default', label:'BookScraper/2.14' },
              { value:'browser', label:'Chrome (headless)' },
              { value:'custom',  label:'Custom…' },
            ]}/>
          </HFField>
        </div>
        <div style={{
          padding: 10, background: HF.accentSoft,
          border: `1px solid ${HF.accentBorder}`, borderRadius: 6,
          fontSize: 12, color: HF.accentInk, display: 'flex', gap: 8, alignItems: 'flex-start',
        }}>
          <span style={{ marginTop: 1 }}>{HF_ICONS.bang}</span>
          <span>After creating, you'll be taken to the parser editor to set up selectors.</span>
        </div>
      </HFModalBody>
      <HFModalFoot>
        <HFButton onClick={onClose}>Cancel</HFButton>
        <HFButton variant="primary" onClick={() => { onClose(); goto('parser', { shop: name || 'new-shop' }); }} disabled={!name || !domain}>
          Create & configure parser
        </HFButton>
      </HFModalFoot>
    </HFModal>
  );
}

// ══════════════════════════════ Add Book dialog ══════════════════════════════
function HFAddBookDialog({ open, onClose }) {
  const HF = getHF();
  const [isbn, setIsbn] = React.useState('');
  const [title, setTitle] = React.useState('');
  const [author, setAuthor] = React.useState('');

  return (
    <HFModal open={open} onClose={onClose} width={520}>
      <HFModalHead title="Add book" sub="Manual entry — books are usually added automatically by scrapes" onClose={onClose} icon={HF_ICONS.books}/>
      <HFModalBody>
        <HFField label="ISBN" required hint="ISBN-10 or ISBN-13">
          <HFInput value={isbn} onChange={setIsbn} placeholder="9780062316097" mono autoFocus/>
        </HFField>
        <HFField label="Title" required>
          <HFInput value={title} onChange={setTitle} placeholder="Sapiens: A Brief History of Humankind"/>
        </HFField>
        <HFField label="Author">
          <HFInput value={author} onChange={setAuthor} placeholder="Yuval Noah Harari"/>
        </HFField>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <HFField label="Publisher">
            <HFInput value="" onChange={() => {}}/>
          </HFField>
          <HFField label="Year">
            <HFInput value="" onChange={() => {}} mono placeholder="2014"/>
          </HFField>
        </div>
      </HFModalBody>
      <HFModalFoot>
        <HFButton onClick={onClose}>Cancel</HFButton>
        <HFButton variant="primary" onClick={onClose} disabled={!isbn || !title}>Create book</HFButton>
      </HFModalFoot>
    </HFModal>
  );
}

// ══════════════════════════════ Parser picker (for cmd+K "Edit parser…") ═══════
function HFParserPicker({ open, onClose, goto }) {
  const HF = getHF();
  const shops = [
    { v:'vaga',    lbl:'vaga.lt',        parser:'product.v3', health:99.8 },
    { v:'knygos',  lbl:'knygos.lt',      parser:'product.v2', health:96.4 },
    { v:'patogupirkti', lbl:'patogupirkti.lt', parser:'product.v4', health:82.1 },
    { v:'humanitas', lbl:'humanitas.lt', parser:'product.v1', health:71.2 },
  ];
  return (
    <HFModal open={open} onClose={onClose} width={480}>
      <HFModalHead title="Edit parser — pick a shop" onClose={onClose} icon={HF_ICONS.settings}/>
      <HFModalBody style={{ padding: 8 }}>
        {shops.map(s => {
          const tone = s.health >= 95 ? HF.okInk : s.health >= 85 ? HF.warnInk : HF.errInk;
          return (
            <div key={s.v} onClick={() => { onClose(); goto('parser', { shop: s.v }); }} style={{
              padding: '10px 12px', borderRadius: 6, cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 12,
            }}
            onMouseEnter={(e) => e.currentTarget.style.background = HF.subtle}
            onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: HF.ink }}>{s.lbl}</div>
                <div style={{ fontSize: 11.5, color: HF.ink3, fontFamily: HF.mono, marginTop: 2 }}>{s.parser}</div>
              </div>
              <span style={{ fontFamily: HF.mono, fontSize: 12, color: tone, fontVariantNumeric: 'tabular-nums' }}>{s.health}%</span>
              <span style={{ color: HF.ink4, display: 'flex' }}>{HF_ICONS.arrow}</span>
            </div>
          );
        })}
      </HFModalBody>
    </HFModal>
  );
}

// ══════════════════════════════ Settings modal ══════════════════════════════
function HFSettings({ open, onClose, accent, setAccent, density, setDensity, persist }) {
  const HF = getHF();
  const [tab, setTab] = React.useState('appearance');
  const tabs = [
    ['appearance', 'Appearance'],
    ['notifications', 'Notifications'],
    ['api', 'API'],
    ['account', 'Account'],
  ];

  return (
    <HFModal open={open} onClose={onClose} width={680}>
      <HFModalHead title="Settings" onClose={onClose} icon={HF_ICONS.settings}/>
      <div style={{ display: 'flex', minHeight: 380 }}>
        <div style={{ width: 160, borderRight: `1px solid ${HF.borderFaint}`, padding: 8, background: HF.sidebar }}>
          {tabs.map(([v, l]) => (
            <div key={v} onClick={() => setTab(v)} style={{
              padding: '7px 10px', margin: '1px 0', borderRadius: 5, cursor: 'pointer',
              fontSize: 12.5, fontWeight: tab === v ? 600 : 500,
              color: tab === v ? HF.accentInk : HF.ink2,
              background: tab === v ? HF.accentSoft : 'transparent',
            }}>{l}</div>
          ))}
        </div>
        <div className="hf-scroll" style={{ flex: 1, padding: 18, overflow: 'auto' }}>
          {tab === 'appearance' && (
            <div>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: HF.ink, marginBottom: 10 }}>Accent color</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 20 }}>
                {Object.keys(HF_ACCENTS).map(a => {
                  const c = HF_ACCENTS[a][500];
                  const sel = accent === a;
                  return (
                    <button key={a} onClick={() => { setAccent(a); persist({ accent: a }); }} style={{
                      padding: '5px 11px', fontSize: 12, height: 30,
                      background: sel ? HF_ACCENTS[a][50] : HF.surface,
                      border: `1px solid ${sel ? c : HF.borderStrong}`, borderRadius: 6,
                      color: sel ? HF_ACCENTS[a][700] : HF.ink2,
                      fontFamily: HF.sans, cursor: 'pointer', fontWeight: sel ? 600 : 500,
                      display: 'flex', alignItems: 'center', gap: 6, textTransform: 'capitalize',
                    }}>
                      <span style={{ width: 12, height: 12, borderRadius: 3, background: c }}/>
                      {a}
                    </button>
                  );
                })}
              </div>
              <div style={{ fontSize: 12.5, fontWeight: 600, color: HF.ink, marginBottom: 10 }}>Density</div>
              <HFSegmented value={density} onChange={(v) => { setDensity(v); persist({ density: v }); }} options={[
                { value:'comfortable', label:'Comfortable' },
                { value:'compact', label:'Compact' },
                { value:'ultra', label:'Ultra' },
              ]}/>
              <div style={{ fontSize: 11.5, color: HF.ink3, marginTop: 8 }}>
                Controls row height, card padding, and font size. {density === 'ultra' && 'Ultra is best for power users with 1440p+ displays.'}
              </div>
            </div>
          )}
          {tab === 'notifications' && (
            <div>
              {[
                ['Run failures',     'Any run that exits with errors',     true],
                ['Parser regression', 'Field success rate drops > 10%',    true],
                ['Schedule skipped', 'A cron job was skipped or overran',  true],
                ['Daily digest',     'Summary at 09:00 every morning',     false],
                ['URL stuck > 24h',  'Any URL in queued state for a day',  false],
              ].map(([l, s, on]) => (
                <label key={l} style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '10px 12px', borderBottom: `1px solid ${HF.borderFaint}`, cursor: 'pointer',
                }}>
                  <input type="checkbox" defaultChecked={on} style={{ margin: 0, accentColor: HF.accent }}/>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 12.5, color: HF.ink, fontWeight: 500 }}>{l}</div>
                    <div style={{ fontSize: 11.5, color: HF.ink3, marginTop: 1 }}>{s}</div>
                  </div>
                </label>
              ))}
            </div>
          )}
          {tab === 'api' && (
            <div>
              <HFField label="API key" hint="Use for programmatic access to runs, URLs, and books.">
                <div style={{ display: 'flex', gap: 6 }}>
                  <HFInput value="bs_live_8f3a…k29Q" onChange={() => {}} mono readOnly style={{ fontFamily: HF.mono }}/>
                  <HFButton>Rotate</HFButton>
                </div>
              </HFField>
              <HFField label="Webhook URL" hint="POST run events to this URL">
                <HFInput value="" onChange={() => {}} placeholder="https://hooks.example.com/bookscraper" mono/>
              </HFField>
              <HFField label="Rate limit">
                <HFSelect value="100" onChange={() => {}} options={['50','100','500','1000']}/>
              </HFField>
            </div>
          )}
          {tab === 'account' && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 20 }}>
                <div style={{
                  width: 52, height: 52, borderRadius: '50%',
                  background: `linear-gradient(135deg, ${HF.accent}, ${HF.accentHover})`,
                  color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 20, fontWeight: 600,
                }}>A</div>
                <div>
                  <div style={{ fontSize: 14, color: HF.ink, fontWeight: 600 }}>admin</div>
                  <div style={{ fontSize: 12, color: HF.ink3 }}>admin@bookscraper.local · prod</div>
                </div>
              </div>
              <HFField label="Email">
                <HFInput value="admin@bookscraper.local" onChange={() => {}}/>
              </HFField>
              <HFField label="Timezone">
                <HFSelect value="Europe/Vilnius" onChange={() => {}} options={['Europe/Vilnius','UTC','Europe/London','America/New_York']}/>
              </HFField>
            </div>
          )}
        </div>
      </div>
      <HFModalFoot>
        <HFButton variant="primary" onClick={onClose}>Done</HFButton>
      </HFModalFoot>
    </HFModal>
  );
}

// ══════════════════════════════ Avatar menu (popover) ══════════════════════════════
function HFAvatarMenu({ open, anchorRect, onClose, goto }) {
  const HF = getHF();
  if (!open || !anchorRect) return null;
  const items = [
    { label: 'Signed in as admin', head: true, sub: 'admin@bookscraper.local' },
    { divider: true },
    { label: 'Sign out', icon: null, action: onClose, danger: true },
  ];
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 95 }}>
      <div onClick={(e) => e.stopPropagation()} style={{
        position: 'absolute', top: anchorRect.bottom + 6, right: 24,
        width: 240, background: HF.surface,
        border: `1px solid ${HF.border}`, borderRadius: 8,
        boxShadow: '0 12px 32px rgba(16,24,40,.18), 0 0 0 1px rgba(16,24,40,.03)',
        padding: 4, fontFamily: HF.sans,
      }}>
        {items.map((it, i) => {
          if (it.divider) return <div key={i} style={{ height: 1, background: HF.borderFaint, margin: '4px 0' }}/>;
          if (it.head) return (
            <div key={i} style={{ padding: '8px 10px 6px' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: HF.ink }}>{it.label}</div>
              <div style={{ fontSize: 11, color: HF.ink3, marginTop: 1 }}>{it.sub}</div>
            </div>
          );
          return (
            <div key={i} onClick={it.action} style={{
              padding: '7px 10px', borderRadius: 5, cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 10,
              fontSize: 12.5, color: it.danger ? HF.errInk : HF.ink2,
            }}
            onMouseEnter={(e) => e.currentTarget.style.background = HF.subtle}
            onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
              <span style={{ color: it.danger ? HF.errInk : HF.ink4, display: 'flex', width: 14 }}>{it.icon}</span>
              <span style={{ flex: 1 }}>{it.label}</span>
              {it.kbd && <span style={{
                fontFamily: HF.mono, fontSize: 10.5,
                padding: '1px 5px', background: HF.subtle, color: HF.ink3,
                border: `1px solid ${HF.border}`, borderRadius: 3,
              }}>{it.kbd}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ══════════════════════════════ Rate Settings dialog ══════════════════════════════
function HFRateSettingsDialog({ open, onClose, shopName }) {
  const HF = getHF();
  const [delay, setDelay] = React.useState('');
  const [concurrent, setConcurrent] = React.useState('');
  const [loadingSettings, setLoadingSettings] = React.useState(false);
  const [error, setError] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);

  // Fetch current settings from DB each time the modal opens.
  React.useEffect(() => {
    if (!open || !shopName) return;
    setLoadingSettings(true);
    setError('');
    setSaved(false);
    fetch(`/api/shops/${shopName}`)
      .then(r => r.json())
      .then(d => {
        const s = d.rate_settings || {};
        setDelay(s.download_delay ?? '2.0');
        setConcurrent(s.concurrent_requests_per_domain ?? '1');
        setLoadingSettings(false);
      })
      .catch(() => { setDelay('2.0'); setConcurrent('1'); setLoadingSettings(false); });
  }, [open, shopName]);

  function validate() {
    const d = parseFloat(delay);
    const c = parseInt(concurrent, 10);
    if (isNaN(d) || d < 0.1 || d > 60) return 'Download delay must be 0.1–60 s.';
    if (isNaN(c) || c < 1 || c > 16) return 'Concurrent requests must be 1–16.';
    return null;
  }

  function save() {
    const err = validate();
    if (err) { setError(err); return; }
    setError(''); setSaving(true);
    const body = new URLSearchParams({ download_delay: delay, concurrent_requests_per_domain: concurrent });
    fetch(`/shops/${shopName}/rate-settings`, {
      method: 'POST', body,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
      .then(r => r.text().then(t => ({ ok: r.ok, text: t })))
      .then(({ ok, text }) => {
        setSaving(false);
        if (ok) { setSaved(true); setTimeout(onClose, 900); }
        else setError(text.replace(/<[^>]+>/g, '') || 'Save failed.');
      })
      .catch(e => { setSaving(false); setError(e.message); });
  }

  return (
    <HFModal open={open} onClose={onClose} width={440}>
      <HFModalHead title="Rate settings" sub={`Crawl pacing for ${shopName}`} onClose={onClose} icon={HF_ICONS.settings}/>
      <HFModalBody>
        {loadingSettings
          ? <div style={{color: HF.ink3, fontSize: 13, padding: '8px 0'}}>Loading…</div>
          : <>
          <HFField label="Download delay (seconds)" hint="Minimum pause between requests. Range: 0.1 – 60 s.">
            <HFInput type="number" value={delay} onChange={setDelay} min="0.1" max="60" step="0.1" mono autoFocus/>
          </HFField>
          <HFField label="Concurrent requests per domain" hint="Max in-flight requests at once. Range: 1 – 16.">
            <HFInput type="number" value={concurrent} onChange={setConcurrent} min="1" max="16" step="1" mono/>
          </HFField>
          </>
        }
        {error && (
          <div style={{
            color: HF.errInk, fontSize: 12.5, padding: '8px 10px',
            background: HF.errSoft, border: `1px solid ${HF.errBorder}`, borderRadius: 6,
          }}>{error}</div>
        )}
        {saved && (
          <div style={{
            color: HF.okInk, fontSize: 12.5, padding: '8px 10px',
            background: HF.okSoft, border: `1px solid ${HF.okBorder}`, borderRadius: 6,
          }}>Saved. Changes take effect on the next crawl.</div>
        )}
      </HFModalBody>
      <HFModalFoot>
        <HFButton onClick={onClose}>Cancel</HFButton>
        <HFButton variant="primary" onClick={save} disabled={saving || saved}>
          <span style={{ display: 'flex' }}>{HF_ICONS.settings}</span>
          {saving ? 'Saving…' : saved ? 'Saved ✓' : 'Save'}
        </HFButton>
      </HFModalFoot>
    </HFModal>
  );
}

// ══════════════════════════════ Exports ══════════════════════════════
Object.assign(window, {
  HFModal, HFModalHead, HFModalBody, HFModalFoot,
  HFField, HFInput, HFSelect, HFSegmented,
  HFCommandK, HFNewRunDialog, HFNewScheduleDialog,
  HFAddURLDialog, HFAddShopDialog, HFAddBookDialog,
  HFParserPicker, HFSettings, HFAvatarMenu,
  HFRateSettingsDialog,
});
