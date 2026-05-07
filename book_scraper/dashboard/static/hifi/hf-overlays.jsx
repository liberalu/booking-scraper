// Hi-fi global overlays — command palette, avatar menu, settings, add/new dialogs.
// Registers window.HF_APP with openers. Any page can call them.

// Module-level scroll-lock counter so stacked modals don't unlock the body
// before the topmost one closes.
let _hfOpenModalCount = 0;

// Focusable selector — used by the focus trap and the initial focus pass.
const _HF_FOCUSABLE_SEL = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'textarea:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

const _hfModalCtx = React.createContext(null);

// ══════════════════════════════ Discover strategy catalog ══════════════════════════════
// Single source of truth for strategy button labels + hint copy. The backend
// (/api/shops) tells us which keys are configured for each shop; we filter
// this catalog by that list when rendering the segmented picker.
const HF_DISCOVER_STRATEGIES = {
  sitemap:    { label: 'Sitemap',    hint: 'Read /sitemap.xml — fastest, only URL discovery' },
  categories: { label: 'Categories', hint: 'Walk category listing pages — also extracts prices' },
  graphql:    { label: 'GraphQL',    hint: 'Magento GraphQL — full metadata (ISBN, year, pages) in one pass' },
  lupasearch: { label: 'LupaSearch', hint: 'Fast price + stock + new-arrival pass (no ISBN/year/pages)' },
  full_crawl: { label: 'Full crawl', hint: 'Follow every internal link — slowest, most thorough' },
};

// Build segmented options from the strategy keys a shop has configured.
function _hfStrategyOptions(keys) {
  const list = Array.isArray(keys) && keys.length ? keys : Object.keys(HF_DISCOVER_STRATEGIES);
  return list
    .filter(k => HF_DISCOVER_STRATEGIES[k])
    .map(k => ({ value: k, label: HF_DISCOVER_STRATEGIES[k].label }));
}
function _hfStrategyHint(key) {
  return HF_DISCOVER_STRATEGIES[key]?.hint || '';
}

// ══════════════════════════════ Base Modal ══════════════════════════════
function HFModal({ open, onClose, width = 560, children, align = 'center', label }) {
  const HF = getHF();
  const panelRef = React.useRef(null);
  const lastFocusedRef = React.useRef(null);
  const titleId = React.useId();

  // Save trigger focus on open; restore it on close so keyboard users return
  // to the button that launched the dialog instead of falling back to <body>.
  // Initial-focus pass moves focus to the first interactive element inside
  // the panel (or the panel itself if none), so the dialog is announced
  // and immediately operable by keyboard.
  React.useEffect(() => {
    if (!open) return;
    lastFocusedRef.current = document.activeElement;
    const id = requestAnimationFrame(() => {
      const panel = panelRef.current;
      if (!panel) return;
      const els = panel.querySelectorAll(_HF_FOCUSABLE_SEL);
      const first = Array.from(els).find(el => el.offsetParent !== null);
      (first || panel).focus({ preventScroll: true });
    });
    return () => {
      cancelAnimationFrame(id);
      const el = lastFocusedRef.current;
      if (el && typeof el.focus === 'function') {
        try { el.focus({ preventScroll: true }); } catch (_) { /* node detached */ }
      }
    };
  }, [open]);

  // Body scroll lock. Counter pattern handles nested modals correctly.
  React.useEffect(() => {
    if (!open) return;
    _hfOpenModalCount += 1;
    if (_hfOpenModalCount === 1) {
      document.body.style.overflow = 'hidden';
    }
    return () => {
      _hfOpenModalCount = Math.max(0, _hfOpenModalCount - 1);
      if (_hfOpenModalCount === 0) {
        document.body.style.overflow = '';
      }
    };
  }, [open]);

  // Escape closes; Tab/Shift+Tab cycles inside the panel (focus trap).
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === 'Escape') {
        if (onClose) { e.stopPropagation(); onClose(); }
        return;
      }
      if (e.key !== 'Tab') return;
      const panel = panelRef.current;
      if (!panel) return;
      const els = Array.from(panel.querySelectorAll(_HF_FOCUSABLE_SEL))
        .filter(el => el.offsetParent !== null);
      if (els.length === 0) {
        e.preventDefault();
        panel.focus({ preventScroll: true });
        return;
      }
      const first = els[0];
      const last = els[els.length - 1];
      const active = document.activeElement;
      if (e.shiftKey && (active === first || !panel.contains(active))) {
        e.preventDefault();
        last.focus({ preventScroll: true });
      } else if (!e.shiftKey && (active === last || !panel.contains(active))) {
        e.preventDefault();
        first.focus({ preventScroll: true });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <_hfModalCtx.Provider value={{ titleId }}>
      <div onClick={onClose} style={{
        position: 'fixed', inset: 0, zIndex: 100,
        background: 'rgba(16,24,40,.35)',
        display: 'flex', alignItems: align === 'top' ? 'flex-start' : 'center',
        justifyContent: 'center',
        paddingTop: align === 'top' ? 96 : 0,
        fontFamily: 'var(--hf-sans)',
        backdropFilter: 'blur(2px)',
      }}>
        <div
          ref={panelRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby={label ? undefined : titleId}
          aria-label={label}
          tabIndex={-1}
          onClick={(e) => e.stopPropagation()}
          style={{
            width, maxWidth: 'calc(100vw - 32px)', maxHeight: 'calc(100vh - 64px)',
            background: 'var(--hf-surface)', borderRadius: 'var(--hf-r3)',
            border: `1px solid ${'var(--hf-border)'}`,
            boxShadow: '0 24px 48px -12px rgba(16,24,40,.25), 0 0 0 1px rgba(16,24,40,.04)',
            overflow: 'hidden', display: 'flex', flexDirection: 'column',
            outline: 'none',
          }}>
          {children}
        </div>
      </div>
    </_hfModalCtx.Provider>
  );
}

// Modal header/footer/body primitives
function HFModalHead({ title, sub, onClose, icon }) {
  const HF = getHF();
  const ctx = React.useContext(_hfModalCtx);
  return (
    <div style={{
      padding: '14px 18px', borderBottom: `1px solid ${'var(--hf-border-faint)'}`,
      display: 'flex', alignItems: 'center', gap: 12,
    }}>
      {icon && (
        <div aria-hidden="true" style={{
          width: 32, height: 32, borderRadius: 7,
          background: 'var(--hf-accent-soft)', border: `1px solid ${'var(--hf-accent-border)'}`,
          color: 'var(--hf-accent)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>{icon}</div>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div id={ctx?.titleId} style={{ fontSize: 14, fontWeight: 600, color: 'var(--hf-ink)', letterSpacing: -0.1 }}>{title}</div>
        {sub && <div style={{ fontSize: 12, color: 'var(--hf-ink3)', marginTop: 2 }}>{sub}</div>}
      </div>
      {onClose && (
        <button onClick={onClose} aria-label="Close dialog" className="hf-btn" style={{
          background: 'transparent', border: 'none', color: 'var(--hf-ink3)',
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
      padding: '12px 18px', borderTop: `1px solid ${'var(--hf-border-faint)'}`,
      display: 'flex', gap: 8, justifyContent: 'flex-end',
      background: 'var(--hf-bg)',
    }}>{children}</div>
  );
}

// Field — labeled input group
function HFField({ label, hint, children, required }) {
  const HF = getHF();
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--hf-ink2)', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 4 }}>
        {label}
        {required && <span style={{ color: 'var(--hf-err-ink)' }}>*</span>}
      </div>
      {children}
      {hint && <div style={{ fontSize: 12, color: 'var(--hf-ink3)', marginTop: 5 }}>{hint}</div>}
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
        background: 'var(--hf-input)', border: `1px solid ${'var(--hf-border-strong)'}`, borderRadius: 6,
        color: 'var(--hf-ink)', fontSize: 13,
        fontFamily: mono ? 'var(--hf-mono)' : 'var(--hf-sans)',
        outline: 'none',
        ...style,
      }}
      onFocus={(e) => e.currentTarget.style.borderColor = 'var(--hf-accent)'}
      onBlur={(e) => e.currentTarget.style.borderColor = 'var(--hf-border-strong)'}
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
      background: 'var(--hf-input)', border: `1px solid ${'var(--hf-border-strong)'}`, borderRadius: 6,
      color: 'var(--hf-ink)', fontSize: 13, fontFamily: 'var(--hf-sans)', cursor: 'pointer',
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
      display: 'inline-flex', background: 'var(--hf-subtle)',
      border: `1px solid ${'var(--hf-border)'}`, borderRadius: 6, padding: 2, gap: 2,
      whiteSpace: 'nowrap',
    }}>
      {options.map(o => {
        const v = typeof o === 'string' ? o : o.value;
        const l = typeof o === 'string' ? o : o.label;
        const sel = v === value;
        return (
          <button key={v} onClick={() => onChange(v)} style={{
            padding: '5px 10px', fontSize: 12, height: 26,
            background: sel ? 'var(--hf-surface)' : 'transparent',
            border: sel ? `1px solid ${'var(--hf-border)'}` : '1px solid transparent',
            borderRadius: 4, color: sel ? 'var(--hf-ink)' : 'var(--hf-ink3)',
            fontWeight: sel ? 500 : 400, fontFamily: 'var(--hf-sans)', cursor: 'pointer',
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
        padding: '10px 14px', borderBottom: `1px solid ${'var(--hf-border-faint)'}`,
        display: 'flex', alignItems: 'center', gap: 10,
      }}>
        <span style={{ color: 'var(--hf-ink3)', display: 'flex' }}>{HF_ICONS.search}</span>
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKey}
          placeholder="Search pages, actions, shops…"
          style={{
            flex: 1, border: 'none', outline: 'none', background: 'transparent',
            color: 'var(--hf-ink)', fontSize: 15, fontFamily: 'var(--hf-sans)', padding: '4px 0',
          }}
        />
        <span style={{
          fontFamily: 'var(--hf-mono)', fontSize: 11,
          padding: '2px 6px', background: 'var(--hf-subtle)',
          border: `1px solid ${'var(--hf-border)'}`, borderRadius: 4, color: 'var(--hf-ink3)',
        }}>esc</span>
      </div>
      <div className="hf-scroll" style={{ maxHeight: 420, overflow: 'auto', padding: 6 }}>
        {filtered.length === 0 && (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--hf-ink3)', fontSize: 13 }}>
            No matches for "<span style={{ fontFamily: 'var(--hf-mono)', color: 'var(--hf-ink2)' }}>{q}</span>"
          </div>
        )}
        {sections.map(sec => {
          if (sec.items.length === 0) return null;
          return (
            <div key={sec.label}>
              <div style={{
                fontSize: 11, color: 'var(--hf-ink4)', fontWeight: 600,
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
                      background: hl ? 'var(--hf-accent-soft)' : 'transparent',
                      color: hl ? 'var(--hf-accent-ink)' : 'var(--hf-ink)',
                    }}>
                    <span style={{
                      width: 22, height: 22, borderRadius: 4,
                      background: hl ? 'var(--hf-accent-soft2)' : 'var(--hf-subtle)',
                      color: hl ? 'var(--hf-accent)' : 'var(--hf-ink3)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      flexShrink: 0,
                    }}>
                      {it.k === 'nav' ? HF_ICONS.arrow : it.k === 'jump' ? HF_ICONS.play : HF_ICONS.plus}
                    </span>
                    <span style={{ flex: 1, fontSize: 13, fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.t}</span>
                    <span style={{ fontSize: 12, color: hl ? 'var(--hf-accent-ink)' : 'var(--hf-ink3)', fontFamily: 'var(--hf-mono)', whiteSpace: 'nowrap', flexShrink: 0, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>{it.hint}</span>
                    {hl && <span style={{ fontSize: 11, color: 'var(--hf-accent-ink)', fontFamily: 'var(--hf-mono)' }}>↵</span>}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
      <div style={{
        padding: '8px 14px', borderTop: `1px solid ${'var(--hf-border-faint)'}`,
        background: 'var(--hf-bg)',
        display: 'flex', gap: 14, alignItems: 'center',
        fontSize: 11, color: 'var(--hf-ink3)', fontFamily: 'var(--hf-mono)',
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
  const shopStrategies = selShop?.discover_strategies || [];

  // Snap strategy to the first one the selected shop actually exposes
  // whenever the shop or phase changes — otherwise switching from vaga
  // to pegasas leaves "sitemap" selected (which pegasas doesn't have).
  React.useEffect(() => {
    if (phase !== 'discover' || !shopStrategies.length) return;
    if (!shopStrategies.includes(strategy)) setStrategy(shopStrategies[0]);
  }, [phase, shop, shopStrategies.join(',')]);

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
          <HFField label="Strategy" hint={_hfStrategyHint(strategy)}>
            {shopStrategies.length ? (
              <HFSegmented value={strategy} onChange={setStrategy}
                options={_hfStrategyOptions(shopStrategies)}/>
            ) : (
              <div style={{ fontSize:13, color:'var(--hf-ink3)' }}>
                No discover strategies configured for {shop || 'this shop'}.
              </div>
            )}
          </HFField>
        )}
        {error && (
          <div style={{
            color: 'var(--hf-err-ink)', fontSize: 13, padding: '8px 10px',
            background: 'var(--hf-err-soft)', border: `1px solid ${'var(--hf-err-border)'}`, borderRadius: 6,
          }}>{error}</div>
        )}
      </HFModalBody>
      <HFModalFoot>
        <div style={{ flex: 1, fontSize: 12, color: 'var(--hf-ink3)', fontFamily: 'var(--hf-mono)', display: 'flex', alignItems: 'center' }}>
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
const CRON_PRESETS = [
  { v:'15m',   lbl:'Every 15 min', cron:'*/15 * * * *' },
  { v:'1h',    lbl:'Hourly',       cron:'0 * * * *' },
  { v:'2h',    lbl:'Every 2 hrs',  cron:'0 */2 * * *' },
  { v:'6h',    lbl:'Every 6 hrs',  cron:'0 */6 * * *' },
  { v:'daily', lbl:'Daily 03:00',  cron:'0 3 * * *' },
  { v:'custom',lbl:'Custom',       cron:'' },
];

function HFCronFrequencyPicker({ value, onChange }) {
  const [preset, setPreset] = React.useState('custom');

  const pickPreset = (v) => {
    setPreset(v);
    const p = CRON_PRESETS.find(x => x.v === v);
    if (p && p.v !== 'custom') onChange(p.cron);
  };

  const handleManual = (v) => { onChange(v); setPreset('custom'); };

  return (
    <>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
        {CRON_PRESETS.map(p => (
          <button key={p.v} onClick={() => pickPreset(p.v)} style={{
            padding: '4px 9px', fontSize: 12, height: 26,
            background: preset === p.v ? 'var(--hf-accent-soft)' : 'var(--hf-surface)',
            border: `1px solid ${preset === p.v ? 'var(--hf-accent-border)' : 'var(--hf-border-strong)'}`,
            color: preset === p.v ? 'var(--hf-accent-ink)' : 'var(--hf-ink2)',
            borderRadius: 5, cursor: 'pointer', fontFamily: 'var(--hf-sans)', fontWeight: 500,
          }}>{p.lbl}</button>
        ))}
      </div>
      <HFInput value={value} onChange={handleManual} mono placeholder="0 */2 * * *"/>
      <div style={{ fontSize: 12, color: 'var(--hf-ink3)', marginTop: 6, fontFamily: 'var(--hf-mono)' }}>
        min · hr · day · mo · dow
      </div>
    </>
  );
}

function HFNewScheduleDialog({ open, onClose }) {
  const HF = getHF();
  const [shop, setShop] = React.useState('');
  const [phase, setPhase] = React.useState('scan');
  const [strategy, setStrategy] = React.useState('');
  const [cron, setCron] = React.useState('0 */2 * * *');
  const [chainToId, setChainToId] = React.useState(null);
  const [shops, setShops] = React.useState([]);
  const [allJobs, setAllJobs] = React.useState([]);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');

  React.useEffect(() => {
    if (!open) { setChainToId(null); setError(''); return; }
    fetch('/api/shops')
      .then(r => r.json())
      .then(d => {
        const list = d.shops || [];
        setShops(list);
        setShop(prev => prev || (list[0] && list[0].name) || '');
      })
      .catch(() => setError('Could not load shops'));
    fetch('/api/cron')
      .then(r => r.json())
      .then(d => setAllJobs(d.jobs || []))
      .catch(() => setAllJobs([]));
  }, [open]);

  const selShop = shops.find(s => s.name === shop);
  const shopStrategies = selShop?.discover_strategies || [];
  const chainOptions = allJobs.filter(j => j.shop === shop);

  React.useEffect(() => {
    if (phase === 'scan') {
      if (!['delta', 'full'].includes(strategy)) setStrategy('delta');
      return;
    }
    if (!shopStrategies.length) { setStrategy(''); return; }
    if (!shopStrategies.includes(strategy)) setStrategy(shopStrategies[0]);
  }, [phase, shop, shopStrategies.join(',')]);

  const handleCreate = async () => {
    if (!cron.trim()) return;
    setSaving(true); setError('');
    try {
      const resp = await fetch('/api/cron', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ shop, phase, strategy, cron_expression: cron, chain_to_id: chainToId || null }),
      });
      if (!resp.ok) {
        const d = await resp.json().catch(() => ({}));
        setError(d.detail || `Error ${resp.status}`);
        return;
      }
      onClose(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const canCreate = cron.trim().length > 0;

  return (
    <HFModal open={open} onClose={() => onClose(false)} width={540}>
      <HFModalHead title="New schedule" sub="Run a shop on a recurring cron" onClose={() => onClose(false)} icon={HF_ICONS.cron}/>
      <HFModalBody>
        <HFField label="Shop" required>
          <HFSelect value={shop} onChange={setShop} options={shops.map(s => ({
            value: s.name,
            label: `${s.name}.lt`,
          }))}/>
        </HFField>
        <HFField label="Phase" required>
          <HFSegmented value={phase} onChange={setPhase} options={[
            { value:'scan',     label:'Scan' },
            { value:'discover', label:'Discover' },
          ]}/>
        </HFField>
        <HFField label="Mode" hint={phase === 'scan' ? {
            delta: 'Resumable scan — only URLs not yet scraped',
            full:  'Re-scrape every known URL',
          }[strategy] : _hfStrategyHint(strategy)}>
          {phase === 'scan' ? (
            <HFSegmented value={strategy} onChange={setStrategy} options={[
              { value:'delta', label:'Delta' },
              { value:'full',  label:'Full' },
            ]}/>
          ) : (
            shopStrategies.length ? (
              <HFSegmented value={strategy} onChange={setStrategy}
                options={_hfStrategyOptions(shopStrategies)}/>
            ) : (
              <div style={{ fontSize:13, color:'var(--hf-ink3)' }}>
                No discover strategies configured for {shop || 'this shop'}.
              </div>
            )
          )}
        </HFField>
        <HFField label="Frequency" required>
          <HFCronFrequencyPicker value={cron} onChange={setCron}/>
        </HFField>
        <HFField label="Chain to" hint="Spawn this job automatically after the selected job finishes">
          <HFSelect
            value={chainToId ? String(chainToId) : ''}
            onChange={v => setChainToId(v ? parseInt(v, 10) : null)}
            options={[
              { value: '', label: 'None — run independently' },
              ...chainOptions.map(j => ({ value: String(j.id), label: j.name })),
            ]}
          />
        </HFField>
        {error && <div style={{color:'var(--hf-err-ink)', fontSize:13, marginTop:4}}>{error}</div>}
      </HFModalBody>
      <HFModalFoot>
        <HFButton onClick={() => onClose(false)}>Cancel</HFButton>
        <HFButton variant="primary" onClick={handleCreate} disabled={!canCreate || saving}>
          {saving ? 'Creating…' : 'Create schedule'}
        </HFButton>
      </HFModalFoot>
    </HFModal>
  );
}

function HFEditScheduleDialog({ open, job, onClose }) {
  const HF = getHF();
  const [phase, setPhase] = React.useState(job?.phase || 'scan');
  const [strategy, setStrategy] = React.useState(job?.strategy || '');
  const [cron, setCron] = React.useState(job?.cron || '');
  const [chainToId, setChainToId] = React.useState(job?.chain_to_id || null);
  const [shopStrategies, setShopStrategies] = React.useState([]);
  const [allJobs, setAllJobs] = React.useState([]);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState('');

  React.useEffect(() => {
    if (job) {
      setPhase(job.phase || 'scan');
      setStrategy(job.strategy || '');
      setCron(job.cron || '');
      setChainToId(job.chain_to_id || null);
      setError('');
    }
  }, [job]);

  React.useEffect(() => {
    if (!open || !job?.shop) { setShopStrategies([]); setAllJobs([]); return; }
    fetch(`/api/shops/${encodeURIComponent(job.shop)}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => setShopStrategies(d?.discover_strategies || []))
      .catch(() => setShopStrategies([]));
    fetch('/api/cron')
      .then(r => r.json())
      .then(d => setAllJobs(d.jobs || []))
      .catch(() => setAllJobs([]));
  }, [open, job?.shop]);

  React.useEffect(() => {
    if (phase === 'scan') {
      if (!['delta', 'full'].includes(strategy)) setStrategy('delta');
      return;
    }
    if (!shopStrategies.length) return;
    if (!shopStrategies.includes(strategy)) setStrategy(shopStrategies[0]);
  }, [phase, shopStrategies.join(',')]);

  const chainOptions = allJobs.filter(j => j.shop === job?.shop && j.id !== job?.id);

  const handleSave = async () => {
    if (!cron.trim() || !job?.id) return;
    setSaving(true); setError('');
    try {
      const resp = await fetch(`/api/cron/${job.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          phase,
          strategy,
          cron_expression: cron,
          chain_to_id: chainToId || null,
          clear_chain: chainToId === null,
        }),
      });
      if (!resp.ok) {
        const d = await resp.json().catch(() => ({}));
        setError(d.detail || `Error ${resp.status}`);
        return;
      }
      onClose(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <HFModal open={open} onClose={() => onClose(false)} width={540}>
      <HFModalHead title="Edit schedule" sub={job?.name || ''} onClose={() => onClose(false)} icon={HF_ICONS.settings}/>
      <HFModalBody>
        <HFField label="Phase" required>
          <HFSegmented value={phase} onChange={setPhase} options={[
            { value:'scan',     label:'Scan' },
            { value:'discover', label:'Discover' },
          ]}/>
        </HFField>
        <HFField label="Mode" hint={phase === 'scan' ? {
            delta: 'Resumable scan — only URLs not yet scraped',
            full:  'Re-scrape every known URL',
          }[strategy] : _hfStrategyHint(strategy)}>
          {phase === 'scan' ? (
            <HFSegmented value={strategy} onChange={setStrategy} options={[
              { value:'delta', label:'Delta' },
              { value:'full',  label:'Full' },
            ]}/>
          ) : (
            shopStrategies.length ? (
              <HFSegmented value={strategy} onChange={setStrategy}
                options={_hfStrategyOptions(shopStrategies)}/>
            ) : (
              <div style={{ fontSize:13, color:'var(--hf-ink3)' }}>
                No discover strategies configured for this shop.
              </div>
            )
          )}
        </HFField>
        <HFField label="Frequency" required>
          <HFCronFrequencyPicker value={cron} onChange={setCron}/>
        </HFField>
        <HFField label="Chain to" hint="Spawn this job automatically after the selected job finishes">
          <HFSelect
            value={chainToId ? String(chainToId) : ''}
            onChange={v => setChainToId(v ? parseInt(v, 10) : null)}
            options={[
              { value: '', label: 'None — run independently' },
              ...chainOptions.map(j => ({ value: String(j.id), label: j.name })),
            ]}
          />
        </HFField>
        {error && <div style={{color:'var(--hf-err-ink)', fontSize:13, marginTop:4}}>{error}</div>}
      </HFModalBody>
      <HFModalFoot>
        <HFButton onClick={() => onClose(false)}>Cancel</HFButton>
        <HFButton variant="primary" onClick={handleSave} disabled={!cron.trim() || saving}>
          {saving ? 'Saving…' : 'Save changes'}
        </HFButton>
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
            { value:'pegasas', label:'pegasas.lt' },
            { value:'humanitas', label:'humanitas.lt' },
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
              background: 'var(--hf-input)', border: `1px solid ${'var(--hf-border-strong)'}`, borderRadius: 6,
              color: 'var(--hf-ink)', fontSize: 12, fontFamily: 'var(--hf-mono)', outline: 'none', resize: 'vertical',
            }} placeholder={'https://vaga.lt/knygos/sapiens\nhttps://vaga.lt/knygos/factfulness\n…'}/>
          </HFField>
        )}
        {mode === 'file' && (
          <div style={{
            padding: 28, textAlign: 'center',
            background: 'var(--hf-bg)', border: `2px dashed ${'var(--hf-border)'}`, borderRadius: 8,
            color: 'var(--hf-ink3)', fontSize: 13,
          }}>
            <div style={{ marginBottom: 8, color: 'var(--hf-ink4)', display: 'flex', justifyContent: 'center' }}>{HF_ICONS.download}</div>
            <div style={{ color: 'var(--hf-ink2)', fontWeight: 500 }}>Drop CSV here</div>
            <div style={{ fontSize: 12, marginTop: 4 }}>Column: <span style={{ fontFamily: 'var(--hf-mono)' }}>url</span> · optional: <span style={{ fontFamily: 'var(--hf-mono)' }}>priority</span></div>
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
          padding: 10, background: 'var(--hf-accent-soft)',
          border: `1px solid ${'var(--hf-accent-border)'}`, borderRadius: 6,
          fontSize: 12, color: 'var(--hf-accent-ink)', display: 'flex', gap: 8, alignItems: 'flex-start',
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
          const tone = s.health >= 95 ? 'var(--hf-ok-ink)' : s.health >= 85 ? 'var(--hf-warn-ink)' : 'var(--hf-err-ink)';
          return (
            <div key={s.v} onClick={() => { onClose(); goto('parser', { shop: s.v }); }} style={{
              padding: '10px 12px', borderRadius: 6, cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: 12,
            }}
            onMouseEnter={(e) => e.currentTarget.style.background = 'var(--hf-subtle)'}
            onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--hf-ink)' }}>{s.lbl}</div>
                <div style={{ fontSize: 12, color: 'var(--hf-ink3)', fontFamily: 'var(--hf-mono)', marginTop: 2 }}>{s.parser}</div>
              </div>
              <span style={{ fontFamily: 'var(--hf-mono)', fontSize: 12, color: tone, fontVariantNumeric: 'tabular-nums' }}>{s.health}%</span>
              <span style={{ color: 'var(--hf-ink4)', display: 'flex' }}>{HF_ICONS.arrow}</span>
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
        <div style={{ width: 160, borderRight: `1px solid ${'var(--hf-border-faint)'}`, padding: 8, background: 'var(--hf-sidebar)' }}>
          {tabs.map(([v, l]) => (
            <div key={v} onClick={() => setTab(v)} style={{
              padding: '7px 10px', margin: '1px 0', borderRadius: 5, cursor: 'pointer',
              fontSize: 13, fontWeight: tab === v ? 600 : 500,
              color: tab === v ? 'var(--hf-accent-ink)' : 'var(--hf-ink2)',
              background: tab === v ? 'var(--hf-accent-soft)' : 'transparent',
            }}>{l}</div>
          ))}
        </div>
        <div className="hf-scroll" style={{ flex: 1, padding: 18, overflow: 'auto' }}>
          {tab === 'appearance' && (
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--hf-ink)', marginBottom: 10 }}>Accent color</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 20 }}>
                {Object.keys(HF_ACCENTS).map(a => {
                  const c = HF_ACCENTS[a][500];
                  const sel = accent === a;
                  return (
                    <button key={a} onClick={() => { setAccent(a); persist({ accent: a }); }} style={{
                      padding: '5px 11px', fontSize: 12, height: 30,
                      background: sel ? HF_ACCENTS[a][50] : 'var(--hf-surface)',
                      border: `1px solid ${sel ? c : 'var(--hf-border-strong)'}`, borderRadius: 6,
                      color: sel ? HF_ACCENTS[a][700] : 'var(--hf-ink2)',
                      fontFamily: 'var(--hf-sans)', cursor: 'pointer', fontWeight: sel ? 600 : 500,
                      display: 'flex', alignItems: 'center', gap: 6, textTransform: 'capitalize',
                    }}>
                      <span style={{ width: 12, height: 12, borderRadius: 3, background: c }}/>
                      {a}
                    </button>
                  );
                })}
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--hf-ink)', marginBottom: 10 }}>Density</div>
              <HFSegmented value={density} onChange={(v) => { setDensity(v); persist({ density: v }); }} options={[
                { value:'comfortable', label:'Comfortable' },
                { value:'compact', label:'Compact' },
                { value:'ultra', label:'Ultra' },
              ]}/>
              <div style={{ fontSize: 12, color: 'var(--hf-ink3)', marginTop: 8 }}>
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
                  padding: '10px 12px', borderBottom: `1px solid ${'var(--hf-border-faint)'}`, cursor: 'pointer',
                }}>
                  <input type="checkbox" defaultChecked={on} style={{ margin: 0, accentColor: 'var(--hf-accent)' }}/>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, color: 'var(--hf-ink)', fontWeight: 500 }}>{l}</div>
                    <div style={{ fontSize: 12, color: 'var(--hf-ink3)', marginTop: 1 }}>{s}</div>
                  </div>
                </label>
              ))}
            </div>
          )}
          {tab === 'api' && (
            <div>
              <HFField label="API key" hint="Use for programmatic access to runs, URLs, and books.">
                <div style={{ display: 'flex', gap: 6 }}>
                  <HFInput value="bs_live_8f3a…k29Q" onChange={() => {}} mono readOnly style={{ fontFamily: 'var(--hf-mono)' }}/>
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
                  background: `linear-gradient(135deg, ${'var(--hf-accent)'}, ${'var(--hf-accent-hover)'})`,
                  color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 20, fontWeight: 600,
                }}>A</div>
                <div>
                  <div style={{ fontSize: 14, color: 'var(--hf-ink)', fontWeight: 600 }}>admin</div>
                  <div style={{ fontSize: 12, color: 'var(--hf-ink3)' }}>admin@bookscraper.local · prod</div>
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
  const lastFocusedRef = React.useRef(null);
  const menuRef = React.useRef(null);

  React.useEffect(() => {
    if (!open) return;
    lastFocusedRef.current = document.activeElement;
    const id = requestAnimationFrame(() => {
      const first = menuRef.current?.querySelector('[role="menuitem"]');
      first?.focus({ preventScroll: true });
    });
    return () => {
      cancelAnimationFrame(id);
      const el = lastFocusedRef.current;
      if (el && typeof el.focus === 'function') {
        try { el.focus({ preventScroll: true }); } catch (_) { /* node detached */ }
      }
    };
  }, [open]);

  React.useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); onClose && onClose(); return; }
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Tab') return;
      const items = Array.from(menuRef.current?.querySelectorAll('[role="menuitem"]') || []);
      if (items.length === 0) return;
      const i = items.indexOf(document.activeElement);
      let next = i;
      if (e.key === 'ArrowDown' || (e.key === 'Tab' && !e.shiftKey)) next = (i + 1) % items.length;
      else next = (i - 1 + items.length) % items.length;
      e.preventDefault();
      items[next]?.focus({ preventScroll: true });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open || !anchorRect) return null;
  const items = [
    { label: 'Signed in as admin', head: true, sub: 'admin@bookscraper.local' },
    { divider: true },
    { label: 'Sign out', icon: null, action: onClose, danger: true },
  ];
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 95 }}>
      <div
        ref={menuRef}
        role="menu"
        aria-label="Account menu"
        onClick={(e) => e.stopPropagation()}
        style={{
          position: 'absolute', top: anchorRect.bottom + 6, right: 24,
          width: 240, background: 'var(--hf-surface)',
          border: `1px solid ${'var(--hf-border)'}`, borderRadius: 8,
          boxShadow: '0 12px 32px rgba(16,24,40,.18), 0 0 0 1px rgba(16,24,40,.03)',
          padding: 4, fontFamily: 'var(--hf-sans)',
        }}>
        {items.map((it, i) => {
          if (it.divider) return <div key={i} role="separator" style={{ height: 1, background: 'var(--hf-border-faint)', margin: '4px 0' }}/>;
          if (it.head) return (
            <div key={i} style={{ padding: '8px 10px 6px' }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--hf-ink)' }}>{it.label}</div>
              <div style={{ fontSize: 11, color: 'var(--hf-ink3)', marginTop: 1 }}>{it.sub}</div>
            </div>
          );
          return (
            <button
              key={i}
              role="menuitem"
              onClick={it.action}
              className="hf-focus"
              style={{
                width: '100%', textAlign: 'left',
                background: 'transparent', border: 'none', cursor: 'pointer',
                padding: '7px 10px', borderRadius: 5,
                display: 'flex', alignItems: 'center', gap: 10,
                fontSize: 13, fontFamily: 'var(--hf-sans)',
                color: it.danger ? 'var(--hf-err-ink)' : 'var(--hf-ink2)',
              }}
              onMouseEnter={(e) => e.currentTarget.style.background = 'var(--hf-subtle)'}
              onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
              <span aria-hidden="true" style={{ color: it.danger ? 'var(--hf-err-ink)' : 'var(--hf-ink4)', display: 'flex', width: 14 }}>{it.icon}</span>
              <span style={{ flex: 1 }}>{it.label}</span>
              {it.kbd && <span style={{
                fontFamily: 'var(--hf-mono)', fontSize: 11,
                padding: '1px 5px', background: 'var(--hf-subtle)', color: 'var(--hf-ink3)',
                border: `1px solid ${'var(--hf-border)'}`, borderRadius: 3,
              }}>{it.kbd}</span>}
            </button>
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
          ? <div style={{color: 'var(--hf-ink3)', fontSize: 13, padding: '8px 0'}}>Loading…</div>
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
            color: 'var(--hf-err-ink)', fontSize: 13, padding: '8px 10px',
            background: 'var(--hf-err-soft)', border: `1px solid ${'var(--hf-err-border)'}`, borderRadius: 6,
          }}>{error}</div>
        )}
        {saved && (
          <div style={{
            color: 'var(--hf-ok-ink)', fontSize: 13, padding: '8px 10px',
            background: 'var(--hf-ok-soft)', border: `1px solid ${'var(--hf-ok-border)'}`, borderRadius: 6,
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

// ══════════════════════════════ Confirm dialog ══════════════════════════════
// Drop-in replacement for window.confirm(): renders a styled modal so action
// flows match the rest of the dashboard. `danger` swaps the primary button to
// the danger variant for destructive actions (Stop run, Re-run, etc.).
function HFConfirmDialog({ open, title, body, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger, busy, onConfirm, onCancel }) {
  const HF = getHF();
  return (
    <HFModal open={open} onClose={busy ? undefined : onCancel} width={460}>
      <HFModalHead title={title} onClose={busy ? undefined : onCancel}/>
      <HFModalBody>
        <div style={{ fontSize: 13, color: 'var(--hf-ink2)', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{body}</div>
      </HFModalBody>
      <HFModalFoot>
        <HFButton onClick={onCancel} disabled={busy}>{cancelLabel}</HFButton>
        <HFButton variant={danger ? 'danger' : 'primary'} onClick={onConfirm} disabled={busy}>
          {busy ? 'Working…' : confirmLabel}
        </HFButton>
      </HFModalFoot>
    </HFModal>
  );
}

// ══════════════════════════════ Acknowledge failure-group dialog ══════════════════════════════
// Replaces a multi-line window.prompt() — operators come back to acked buckets
// months later, so a labelled textarea with a real placeholder is much better
// UX than the OS prompt with `\n`-padded body text.
function HFAckGroupDialog({ open, group, runId, busy, onConfirm, onCancel }) {
  const HF = getHF();
  const [note, setNote] = React.useState('');
  React.useEffect(() => { if (open) setNote(''); }, [open, group]);
  if (!group) return null;
  const label = `${group.reason_display ?? group.reason ?? 'unknown'}${group.http != null ? ` · HTTP ${group.http}` : ''}`;
  return (
    <HFModal open={open} onClose={busy ? undefined : onCancel} width={520}>
      <HFModalHead title="Mark group as known" sub={`Run #${runId} · ${label}`} onClose={busy ? undefined : onCancel}/>
      <HFModalBody>
        <div style={{ fontSize: 13, color: 'var(--hf-ink2)', lineHeight: 1.5, marginBottom: 14 }}>
          The bucket will stop appearing on the Failures card. You can still find acknowledged groups via <strong>Show acknowledged</strong>.
        </div>
        <HFField label="Note" hint='Optional. e.g. "vendor outage 2026-04-28", "URL deleted upstream".'>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            placeholder="Why is this safe to ignore?"
            style={{
              width: '100%', boxSizing: 'border-box',
              padding: '8px 10px', resize: 'vertical', minHeight: 64,
              background: 'var(--hf-input)', border: `1px solid ${'var(--hf-border-strong)'}`, borderRadius: 6,
              color: 'var(--hf-ink)', fontSize: 13, fontFamily: 'var(--hf-sans)', outline: 'none',
            }}
            onFocus={(e) => e.currentTarget.style.borderColor = 'var(--hf-accent)'}
            onBlur={(e) => e.currentTarget.style.borderColor = 'var(--hf-border-strong)'}
          />
        </HFField>
      </HFModalBody>
      <HFModalFoot>
        <HFButton onClick={onCancel} disabled={busy}>Cancel</HFButton>
        <HFButton variant="primary" onClick={() => onConfirm(note.trim())} disabled={busy}>
          {busy ? 'Acknowledging…' : 'Mark as known'}
        </HFButton>
      </HFModalFoot>
    </HFModal>
  );
}

// ══════════════════════════════ Toasts ══════════════════════════════
// Pub/sub bus + global push/dismiss. HFToastHost subscribes once and renders
// the stack at bottom-right. Any code can call window.HF_APP.toast({...}).
const _hfToastListeners = new Set();
let _hfToastSeq = 0;
function _hfPushToast(t) {
  const id = ++_hfToastSeq;
  // Tone-based default TTL: errors stay longer so operators can read them.
  const ttlByTone = { ok: 3500, accent: 3500, warn: 5500, err: 7000, neutral: 4000 };
  const toast = {
    id,
    tone: t.tone || 'neutral',
    message: t.message || '',
    detail: t.detail || '',
    ttl: t.ttl != null ? t.ttl : (ttlByTone[t.tone] ?? 4000),
  };
  _hfToastListeners.forEach(l => l({ kind: 'add', toast }));
  return id;
}
function _hfDismissToast(id) {
  _hfToastListeners.forEach(l => l({ kind: 'remove', id }));
}

function HFToast({ toast, onDismiss }) {
  const HF = getHF();
  React.useEffect(() => {
    if (!toast.ttl || toast.ttl <= 0) return;
    const t = setTimeout(() => onDismiss(toast.id), toast.ttl);
    return () => clearTimeout(t);
  }, [toast.id, toast.ttl, onDismiss]);

  const tones = {
    ok:      { bg: 'var(--hf-ok-soft)',     bd: 'var(--hf-ok-border)',     fg: 'var(--hf-ok-ink)',     icon: HF_ICONS.check },
    err:     { bg: 'var(--hf-err-soft)',    bd: 'var(--hf-err-border)',    fg: 'var(--hf-err-ink)',    icon: HF_ICONS.bang },
    warn:    { bg: 'var(--hf-warn-soft)',   bd: 'var(--hf-warn-border)',   fg: 'var(--hf-warn-ink)',   icon: HF_ICONS.bang },
    accent:  { bg: 'var(--hf-accent-soft)', bd: 'var(--hf-accent-border)', fg: 'var(--hf-accent-ink)', icon: HF_ICONS.bang },
    neutral: { bg: 'var(--hf-surface)',    bd: 'var(--hf-border-strong)', fg: 'var(--hf-ink2)',      icon: null },
  };
  const t = tones[toast.tone] || tones.neutral;

  return (
    <div role="status" style={{
      display: 'flex', alignItems: 'flex-start', gap: 10,
      minWidth: 280, maxWidth: 420,
      padding: '10px 12px',
      background: 'var(--hf-surface)',
      border: `1px solid ${t.bd}`,
      borderLeft: `3px solid ${t.fg}`,
      borderRadius: 'var(--hf-r3)',
      boxShadow: 'var(--hf-shadow-lg)',
      fontFamily: 'var(--hf-sans)', fontSize: 13, color: 'var(--hf-ink)',
      pointerEvents: 'auto',
    }}>
      {t.icon && (
        <span aria-hidden="true" style={{
          color: t.fg, display: 'flex', flexShrink: 0,
          marginTop: 1,
        }}>{t.icon}</span>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 500, color: 'var(--hf-ink)', lineHeight: 1.35 }}>{toast.message}</div>
        {toast.detail && (
          <div style={{ fontSize: 12, color: 'var(--hf-ink3)', marginTop: 3, lineHeight: 1.4, wordBreak: 'break-word' }}>
            {toast.detail}
          </div>
        )}
      </div>
      <button
        onClick={() => onDismiss(toast.id)}
        aria-label="Dismiss"
        className="hf-focus"
        style={{
          background: 'transparent', border: 'none', cursor: 'pointer',
          color: 'var(--hf-ink4)', fontSize: 16, lineHeight: 1, padding: '2px 4px',
          borderRadius: 4, flexShrink: 0,
          fontFamily: 'var(--hf-sans)',
        }}
      >×</button>
    </div>
  );
}

function HFToastHost() {
  const [toasts, setToasts] = React.useState([]);
  React.useEffect(() => {
    const handler = (ev) => {
      if (ev.kind === 'add')    setToasts(prev => [...prev, ev.toast]);
      if (ev.kind === 'remove') setToasts(prev => prev.filter(x => x.id !== ev.id));
    };
    _hfToastListeners.add(handler);
    return () => _hfToastListeners.delete(handler);
  }, []);
  const onDismiss = React.useCallback((id) => _hfDismissToast(id), []);

  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      style={{
        position: 'fixed', right: 20, bottom: 20, zIndex: 200,
        display: 'flex', flexDirection: 'column-reverse', gap: 8,
        pointerEvents: 'none',
      }}
    >
      {toasts.map(t => <HFToast key={t.id} toast={t} onDismiss={onDismiss}/>)}
    </div>
  );
}

// ══════════════════════════════ Exports ══════════════════════════════
Object.assign(window, {
  HFModal, HFModalHead, HFModalBody, HFModalFoot,
  HFField, HFInput, HFSelect, HFSegmented,
  HFCommandK, HFNewRunDialog, HFNewScheduleDialog, HFEditScheduleDialog,
  HFAddURLDialog, HFAddShopDialog, HFAddBookDialog,
  HFParserPicker, HFSettings, HFAvatarMenu,
  HFRateSettingsDialog,
  HFConfirmDialog, HFAckGroupDialog,
  HFToast, HFToastHost,
  _hfPushToast, _hfDismissToast,
});
