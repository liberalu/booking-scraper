// Hi-fi UI primitives — light-mode, density-aware.

// Generic filter hook. Pass rows + filter spec; returns {filtered, filterBar state, clearAll, activeCount, empty}.
// Each filter: { id, label, options (array), match: (row, value) => bool }
// `search` spec: { placeholder, width, fields: (row) => string to match against }
function useHFFilters(rows, spec) {
  const initial = {};
  spec.filters.forEach(f => { initial[f.id] = f.default || 'all'; });
  const [q, setQ] = React.useState('');
  const [vals, setVals] = React.useState(initial);

  const setVal = (id, v) => setVals(prev => ({ ...prev, [id]: v }));

  const filtered = React.useMemo(() => {
    const qq = q.trim().toLowerCase();
    return rows.filter(r => {
      for (const f of spec.filters) {
        const v = vals[f.id];
        if (v && v !== (f.default || 'all') && !f.match(r, v)) return false;
      }
      if (qq && spec.search) {
        const hay = (spec.search.fields(r) || '').toLowerCase();
        if (!hay.includes(qq)) return false;
      }
      return true;
    });
  }, [rows, vals, q]);

  const activeCount = (q.trim() ? 1 : 0) +
    spec.filters.reduce((n, f) => n + (vals[f.id] !== (f.default || 'all') ? 1 : 0), 0);

  const clearAll = () => {
    setQ('');
    setVals(initial);
  };

  return { q, setQ, vals, setVal, filtered, activeCount, clearAll };
}

// Standard empty-state card body (wrap in HFCard)
function HFEmptyState({ title, sub, onClear, actionLabel = 'Clear filters' }) {
  const HF = getHF();
  return (
    <div style={{padding:'60px 20px', textAlign:'center', color:HF.ink3}}>
      <div style={{fontSize:28, marginBottom:8, color:HF.ink5, display:'flex', justifyContent:'center'}}>{HF_ICONS.search}</div>
      <div style={{fontSize:14, color:HF.ink, fontWeight:500, marginBottom:4}}>{title}</div>
      {sub && <div style={{fontSize:12.5, color:HF.ink3, marginBottom:14, maxWidth:360, margin:'0 auto 14px', lineHeight:1.5}}>{sub}</div>}
      {onClear && <HFButton size="sm" onClick={onClear}>{actionLabel}</HFButton>}
    </div>
  );
}

function HFButton({ children, variant = 'default', size = 'md', style, ...rest }) {
  const HF = getHF();
  const sizes = {
    sm: { padding: '4px 9px', fontSize: 12, height: 26 },
    md: { padding: '6px 12px', fontSize: 13, height: 32 },
    lg: { padding: '8px 16px', fontSize: 13.5, height: 36 },
  };
  const variants = {
    default: { background: HF.surface, border: `1px solid ${HF.borderStrong}`, color: HF.ink, boxShadow: '0 1px 2px rgba(16,24,40,.04)' },
    primary: { background: HF.accent, border: `1px solid ${HF.accent}`, color: '#fff', fontWeight: 500, boxShadow: '0 1px 2px rgba(16,24,40,.06)' },
    subtle:  { background: 'transparent', border: `1px solid transparent`, color: HF.ink2 },
    ghost:   { background: HF.bg, border: `1px solid ${HF.border}`, color: HF.ink2 },
    danger:  { background: HF.surface, border: `1px solid ${HF.errBorder}`, color: HF.err },
    accent:  { background: HF.accentSoft, border: `1px solid ${HF.accentBorder}`, color: HF.accentInk, fontWeight: 500 },
  };
  const cls = variant === 'primary' ? 'hf-btn hf-btn-primary' : 'hf-btn';
  return (
    <button {...rest} className={cls} style={{
      ...sizes[size],
      ...variants[variant],
      borderRadius: 6,
      cursor: 'pointer',
      fontFamily: HF.sans,
      display: 'inline-flex', alignItems: 'center', gap: 6,
      whiteSpace: 'nowrap',
      transition: 'border-color 120ms, background 120ms, filter 120ms',
      ...style,
    }}>{children}</button>
  );
}

function HFPill({ children, tone = 'neutral', soft = true, style }) {
  const HF = getHF();
  const tones = {
    neutral: { bg: HF.subtle, fg: HF.ink2, bd: HF.border },
    ok:      { bg: HF.okSoft, fg: HF.okInk, bd: HF.okBorder },
    warn:    { bg: HF.warnSoft, fg: HF.warnInk, bd: HF.warnBorder },
    err:     { bg: HF.errSoft, fg: HF.errInk, bd: HF.errBorder },
    accent:  { bg: HF.accentSoft, fg: HF.accentInk, bd: HF.accentBorder },
    muted:   { bg: HF.bg, fg: HF.ink3, bd: HF.border },
  };
  const t = tones[tone] || tones.neutral;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '1px 8px', height: 20,
      background: t.bg, color: t.fg, border: `1px solid ${t.bd}`,
      borderRadius: 4, fontSize: 11.5, fontWeight: 500,
      fontFamily: HF.sans, whiteSpace: 'nowrap', lineHeight: '18px',
      ...style,
    }}>{children}</span>
  );
}

function HFDot({ tone = 'ok', pulse = false, size = 8 }) {
  const HF = getHF();
  const c = { ok: HF.ok, warn: HF.warn, err: HF.err, neutral: HF.ink4, accent: HF.accent }[tone] || HF.ink4;
  return (
    <span style={{ position: 'relative', display: 'inline-flex', width: size, height: size }}>
      {pulse && <span style={{
        position: 'absolute', inset: -2,
        borderRadius: '50%', background: c, opacity: 0.3,
        animation: 'hfPulse 1.6s ease-out infinite',
      }}/>}
      <span style={{ width: size, height: size, borderRadius: '50%', background: c, boxShadow: `0 0 0 2px ${HF.surface}` }}/>
    </span>
  );
}

function HFFilterBar({ children, right }) {
  return (
    <div style={{ display: 'flex', gap: 6, marginBottom: 12, alignItems: 'center', flexWrap: 'wrap' }}>
      {children}
      {right && <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>{right}</div>}
    </div>
  );
}

function HFFilter({ label, value, options, onChange, active, allLabel = 'all' }) {
  const HF = getHF();
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef(null);
  const isActive = active !== undefined ? active : (value != null && value !== '' && value !== allLabel);

  React.useEffect(() => {
    if (!open) return;
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  const handlePick = (v) => { onChange && onChange(v); setOpen(false); };

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <button className="hf-btn" onClick={() => options && setOpen(!open)} style={{
        padding: '5px 10px', height: 30,
        background: isActive ? HF.accentSoft : HF.surface,
        border: `1px solid ${isActive ? HF.accentBorder : HF.borderStrong}`,
        borderRadius: 6,
        color: HF.ink,
        fontSize: 12.5, fontFamily: HF.sans,
        cursor: options ? 'pointer' : 'default', display: 'inline-flex', alignItems: 'center', gap: 6,
        boxShadow: '0 1px 2px rgba(16,24,40,.03)',
      }}>
        <span style={{ color: HF.ink3 }}>{label}:</span>
        <span style={{ color: isActive ? HF.accentInk : HF.ink, fontWeight: 500 }}>{value}</span>
        <span style={{ color: HF.ink4, display: 'flex', transform: open?'rotate(180deg)':'none', transition:'transform 120ms' }}>{HF_ICONS.chevronD}</span>
      </button>
      {open && options && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 4px)', left: 0, zIndex: 40,
          minWidth: 160, maxHeight: 280, overflow: 'auto',
          background: HF.surface, border: `1px solid ${HF.border}`, borderRadius: 6,
          boxShadow: '0 8px 24px rgba(16,24,40,.12)', padding: 4,
        }}>
          {options.map(opt => {
            const v = typeof opt === 'string' ? opt : opt.value;
            const lbl = typeof opt === 'string' ? opt : (opt.label || opt.value);
            const sel = v === value;
            return (
              <div key={v} onClick={() => handlePick(v)} style={{
                padding: '6px 10px', fontSize: 12.5,
                borderRadius: 4, cursor: 'pointer',
                color: sel ? HF.accentInk : HF.ink2,
                background: sel ? HF.accentSoft : 'transparent',
                fontWeight: sel ? 500 : 400,
                display: 'flex', alignItems: 'center', gap: 8,
              }}
              onMouseEnter={(e) => { if (!sel) e.currentTarget.style.background = HF.subtle; }}
              onMouseLeave={(e) => { if (!sel) e.currentTarget.style.background = 'transparent'; }}>
                <span style={{ flex: 1 }}>{lbl}</span>
                {sel && <span style={{ color: HF.accent, display: 'flex' }}>{HF_ICONS.check}</span>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function HFSearch({ placeholder = 'Search…', width = 260, value, onChange }) {
  const HF = getHF();
  const controlled = value !== undefined;
  return (
    <label style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '0 10px', height: 32,
      background: HF.surface, border: `1px solid ${HF.borderStrong}`, borderRadius: 6,
      color: HF.ink4, fontSize: 12.5, width,
      boxShadow: '0 1px 2px rgba(16,24,40,.03)',
      cursor: 'text',
    }}>
      <span style={{ color: HF.ink4, display: 'flex' }}>{HF_ICONS.search}</span>
      <input
        type="text"
        placeholder={placeholder}
        value={controlled ? value : undefined}
        onChange={(e) => onChange && onChange(e.target.value)}
        style={{
          flex: 1, border: 'none', outline: 'none', background: 'transparent',
          color: HF.ink, fontSize: 12.5, fontFamily: HF.sans, padding: 0,
          minWidth: 0,
        }}
      />
      {controlled && value && (
        <span onClick={(e) => { e.preventDefault(); onChange(''); }} style={{
          color: HF.ink4, fontSize: 14, cursor: 'pointer', padding: '0 2px',
        }}>×</span>
      )}
    </label>
  );
}

// Card — elevated white surface with optional header
function HFCard({ title, sub, action, children, style, padding, flush }) {
  const HF = getHF();
  return (
    <div style={{
      background: HF.surface, border: `1px solid ${HF.border}`,
      borderRadius: HF.r3, overflow: 'hidden',
      boxShadow: HF.shadow,
      ...style,
    }}>
      {(title || action) && (
        <div style={{
          padding: `${HF.cardHeadY}px ${HF.cardP}px`,
          borderBottom: `1px solid ${HF.borderFaint}`,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12,
        }}>
          <div style={{ minWidth: 0, flex: 1, overflow: 'hidden' }}>
            {title && <div style={{ fontSize: 13.5, fontWeight: 600, color: HF.ink, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', letterSpacing: -0.1 }}>{title}</div>}
            {sub && <div style={{ fontSize: 12, color: HF.ink3, marginTop: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{sub}</div>}
          </div>
          {action && <div style={{ flexShrink: 0, display:'flex', gap:8 }}>{action}</div>}
        </div>
      )}
      <div style={{ padding: padding == null ? 0 : padding }}>{children}</div>
    </div>
  );
}

// Table — density aware, hover rows, optional striping, sortable headers
// Columns can declare `sortable: true` and the table displays an arrow affordance.
// Pass `sortBy` + `sortDir` ('asc'|'desc') + `onSort(key)` to make it controlled,
// or leave uncontrolled and it self-manages sort state (client-side sort).
function HFTable({ columns, rows, stripe = false, onRowClick, sortBy: extSortBy, sortDir: extSortDir, onSort }) {
  const HF = getHF();
  const gridCols = columns.map(c => c.w || '1fr').join(' ');

  // uncontrolled sort state
  const [uSortBy, setUSortBy] = React.useState(null);
  const [uSortDir, setUSortDir] = React.useState('asc');
  const sortBy  = extSortBy  !== undefined ? extSortBy  : uSortBy;
  const sortDir = extSortDir !== undefined ? extSortDir : uSortDir;

  const handleSort = (key) => {
    if (onSort) { onSort(key); return; }
    if (uSortBy === key) setUSortDir(uSortDir === 'asc' ? 'desc' : 'asc');
    else { setUSortBy(key); setUSortDir('asc'); }
  };

  const displayRows = React.useMemo(() => {
    if (!sortBy) return rows;
    const col = columns.find(c => c.key === sortBy);
    if (!col || !col.sortable) return rows;
    const sortVal = col.sortVal || ((r) => r[sortBy]);
    const copy = rows.slice();
    copy.sort((a,b) => {
      const va = sortVal(a), vb = sortVal(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === 'number' && typeof vb === 'number') return sortDir==='asc'? va - vb : vb - va;
      return sortDir==='asc' ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
    });
    return copy;
  }, [rows, sortBy, sortDir, columns]);

  const SortIcon = ({ active, dir }) => (
    <svg width="9" height="11" viewBox="0 0 9 11" style={{flexShrink:0, marginLeft:4, verticalAlign:'middle'}}>
      <path d="M4.5 0.5 L8 4 L1 4 Z" fill={active && dir==='asc' ? HF.ink : HF.ink5}/>
      <path d="M4.5 10.5 L1 7 L8 7 Z" fill={active && dir==='desc' ? HF.ink : HF.ink5}/>
    </svg>
  );

  return (
    <div>
      <div style={{
        display: 'grid', gridTemplateColumns: gridCols,
        padding: `8px ${HF.cardP}px`,
        borderBottom: `1px solid ${HF.border}`,
        background: HF.subtle,
        fontSize: 11, color: HF.ink3, fontWeight: 600,
        textTransform: 'uppercase', letterSpacing: 0.5,
      }}>
        {columns.map((c, i) => {
          const isActive = sortBy === c.key;
          const clickable = !!c.sortable;
          return (
            <div key={i}
              onClick={clickable ? (e) => { e.stopPropagation(); handleSort(c.key); } : undefined}
              style={{
                textAlign: c.align || 'left',
                paddingRight: i < columns.length - 1 ? 12 : 0,
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                cursor: clickable ? 'pointer' : 'default',
                userSelect: 'none',
                color: isActive ? HF.ink : HF.ink3,
                display: 'inline-flex',
                alignItems: 'center',
                gap: 0,
                justifyContent: c.align === 'right' ? 'flex-end' : 'flex-start',
                transition: 'color 100ms',
              }}
              onMouseEnter={(e) => { if (clickable) e.currentTarget.style.color = HF.ink; }}
              onMouseLeave={(e) => { if (clickable && !isActive) e.currentTarget.style.color = HF.ink3; }}
            >
              <span>{c.label}</span>
              {clickable && <SortIcon active={isActive} dir={sortDir}/>}
            </div>
          );
        })}
      </div>
      {displayRows.map((r, i) => (
        <div key={i} className="hf-row" onClick={onRowClick ? () => onRowClick(r, i) : undefined} style={{
          display: 'grid', gridTemplateColumns: gridCols,
          padding: `${HF.cellY}px ${HF.cardP}px`,
          minHeight: HF.rowH,
          borderBottom: i < displayRows.length - 1 ? `1px solid ${HF.borderFaint}` : 'none',
          fontSize: HF.fsBody, color: HF.ink, alignItems: 'center',
          background: stripe && i % 2 === 1 ? HF.subtle : HF.surface,
          cursor: onRowClick ? 'pointer' : 'default',
          transition: 'background 80ms',
        }}>
          {columns.map((c, j) => (
            <div key={j} style={{
              textAlign: c.align || 'left',
              color: c.muted ? HF.ink3 : HF.ink,
              fontFamily: c.mono ? HF.mono : HF.sans,
              fontSize: c.mono ? HF.fsMono : HF.fsBody,
              paddingRight: j < columns.length - 1 ? 12 : 0,
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              minWidth: 0,
              fontVariantNumeric: c.mono ? 'tabular-nums' : undefined,
            }}>
              {c.cell ? c.cell(r[c.key], r, i) : r[c.key]}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function HFTabs({ tabs, active, onChange }) {
  const HF = getHF();
  return (
    <div style={{
      display: 'flex', gap: 2, borderBottom: `1px solid ${HF.border}`,
      marginBottom: 14,
    }}>
      {tabs.map(t => {
        const a = t.id === active;
        return (
          <button key={t.id} onClick={() => onChange && onChange(t.id)} style={{
            padding: '9px 14px',
            background: 'transparent', border: 'none',
            borderBottom: a ? `2px solid ${HF.accent}` : '2px solid transparent',
            color: a ? HF.ink : HF.ink3,
            fontSize: 13, fontWeight: a ? 600 : 500,
            cursor: 'pointer', fontFamily: HF.sans,
            display: 'inline-flex', alignItems: 'center', gap: 6,
            marginBottom: -1,
          }}>
            {t.label}
            {t.count != null && (
              <span style={{
                fontFamily: HF.mono, fontSize: 11,
                padding: '1px 6px', borderRadius: 4,
                background: a ? HF.accentSoft : HF.subtle,
                color: a ? HF.accentInk : HF.ink3,
              }}>{t.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// Sparkline / area chart
function HFAreaChart({ data, h = 140, w = 900, strokeW = 1.8 }) {
  const HF = getHF();
  const max = Math.max(...data), min = Math.min(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 14) - 7;
    return [x, y];
  });
  const path = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const areaPath = `${path} L${w},${h} L0,${h} Z`;
  const gid = 'hfA_' + Math.random().toString(36).slice(2, 8);
  // gridlines
  const lines = [0.25, 0.5, 0.75].map(p => h * p);
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={HF.chartFillFrom} stopOpacity="0.9"/>
          <stop offset="100%" stopColor={HF.chartFillTo} stopOpacity="0.15"/>
        </linearGradient>
      </defs>
      {lines.map((y, i) => (
        <line key={i} x1="0" y1={y} x2={w} y2={y} stroke={HF.chartGrid} strokeWidth="1" strokeDasharray="2 4" vectorEffect="non-scaling-stroke"/>
      ))}
      <path d={areaPath} fill={`url(#${gid})`}/>
      <path d={path} stroke={HF.chartPrimary} strokeWidth={strokeW} fill="none" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke"/>
    </svg>
  );
}

function HFBarChart({ data, h = 140, colorFn }) {
  const HF = getHF();
  const max = Math.max(...data.map(d => Math.abs(d)));
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: h }}>
      {data.map((v, i) => {
        const c = colorFn ? colorFn(v, i, HF) : (v >= 0 ? HF.accent : HF.err);
        return (
          <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%' }}>
            <div style={{
              height: `${(Math.abs(v) / max) * 100}%`,
              background: c, opacity: i === data.length - 1 ? 1 : 0.75,
              borderRadius: '3px 3px 0 0', minHeight: 2,
            }}/>
          </div>
        );
      })}
    </div>
  );
}

function HFSparkBars({ data, h = 80 }) {
  const HF = getHF();
  const max = Math.max(...data);
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: h }}>
      {data.map((v, i) => (
        <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%' }}>
          <div style={{
            height: `${(v / max) * 100}%`,
            background: i === data.length - 1 ? HF.accent : HF.accentBorder,
            borderRadius: '3px 3px 0 0',
            minHeight: 2,
          }}/>
        </div>
      ))}
    </div>
  );
}

function HFKpiTile({ label, value, delta, tone, href = '#', last, icon, onClick }) {
  const HF = getHF();
  const toneColor = tone === 'ok' ? HF.okInk : tone === 'warn' ? HF.warnInk : tone === 'err' ? HF.errInk : tone === 'accent' ? HF.accentInk : HF.ink3;
  const clickable = !!onClick;
  return (
    <a href={href}
       onClick={clickable ? (e) => { e.preventDefault(); onClick(); } : undefined}
       className="hf-link" style={{
      display: 'block', textDecoration: 'none', color: HF.ink,
      padding: `${HF.kpiP}px ${HF.kpiP + 2}px`,
      borderRight: last ? 'none' : `1px solid ${HF.border}`,
      background: HF.surface,
      cursor: clickable ? 'pointer' : 'default',
      transition: 'background 100ms',
    }}
    onMouseEnter={clickable ? (e) => { e.currentTarget.style.background = HF.subtle; } : undefined}
    onMouseLeave={clickable ? (e) => { e.currentTarget.style.background = HF.surface; } : undefined}>
      <div style={{
        fontSize: 11.5, color: HF.ink3, fontWeight: 500,
        textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6,
      }}>{label}</div>
      <div style={{
        fontFamily: HF.mono, fontSize: HF.fsKpi, fontWeight: 500,
        letterSpacing: -0.5, lineHeight: 1, color: HF.ink,
        fontVariantNumeric: 'tabular-nums',
      }}>{value}</div>
      {delta && (
        <div style={{ fontSize: 12, color: toneColor, marginTop: 6, display:'flex', alignItems:'center', gap:4 }}>{delta}</div>
      )}
    </a>
  );
}

function HFKpiStrip({ items }) {
  const HF = getHF();
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: `repeat(${items.length}, 1fr)`,
      border: `1px solid ${HF.border}`, borderRadius: HF.r3,
      background: HF.surface, boxShadow: HF.shadow,
      overflow: 'hidden', marginBottom: HF.gap,
    }}>
      {items.map((k, i) => <HFKpiTile key={i} {...k} last={i === items.length - 1}/>)}
    </div>
  );
}

const hfLink = (HF) => ({
  fontSize: 12.5, color: HF.accentInk,
  textDecoration: 'none', fontFamily: HF.sans, fontWeight: 500,
  display: 'inline-flex', alignItems: 'center', gap: 4,
});

Object.assign(window, {
  HFButton, HFPill, HFDot, HFFilterBar, HFFilter, HFSearch,
  HFTable, HFTabs, HFAreaChart, HFBarChart, HFSparkBars,
  HFKpiTile, HFKpiStrip, HFCard, hfLink,
});
