// Hi-fi shell — sidebar + topbar + page head. Light mode.

function HFShell({ collapsed, setCollapsed, setPage, activePage, children, title, subtitle, actions, breadcrumb }) {
  const HF = getHF();
  const avatarRef = React.useRef(null);
  const openAvatar = () => {
    const r = avatarRef.current && avatarRef.current.getBoundingClientRect();
    if (window.HF_APP && window.HF_APP.openAvatarMenu) window.HF_APP.openAvatarMenu(r);
  };
  const openCmdK = () => window.HF_APP && window.HF_APP.openCmdK && window.HF_APP.openCmdK();
  const openNewRun = () => window.HF_APP && window.HF_APP.openNewRun && window.HF_APP.openNewRun();

  const [runningCount, setRunningCount] = React.useState(0);
  React.useEffect(() => {
    const load = () => fetch('/api/runs?status=running&per_page=1')
      .then(r => r.json())
      .then(d => setRunningCount(d.kpis?.running_now || 0))
      .catch(() => {});
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, []);

  const navGroups = [
    { group: 'Operations', items: [
      ['overview', 'Overview', HF_ICONS.overview],
      ['runs', 'Runs', HF_ICONS.runs, runningCount > 0 ? String(runningCount) : null],
      ['cron', 'Schedules', HF_ICONS.cron],
      ['issues', 'Issues', HF_ICONS.issues],
    ]},
    { group: 'Catalog', items: [
      ['books', 'Books', HF_ICONS.books],
      ['shop-books', 'Shop Books', HF_ICONS.books],
      ['urls', 'URLs', HF_ICONS.urls],
      ['shops', 'Shops', HF_ICONS.shops],
    ]},
    { group: 'Data', items: [
      ['prices', 'Prices', HF_ICONS.prices],
    ]},
  ];

  const sidebarW = collapsed ? 56 : 232;

  return (
    <div style={{ display: 'flex', height: '100%', background: 'var(--hf-bg)', color: 'var(--hf-ink)', fontFamily: 'var(--hf-sans)', fontSize: 13, fontFeatureSettings: '"cv11","ss01"' }}>
      {/* Sidebar */}
      <aside style={{
        width: sidebarW, flexShrink: 0,
        background: 'var(--hf-sidebar)',
        borderRight: `1px solid ${'var(--hf-border)'}`,
        display: 'flex', flexDirection: 'column',
        transition: 'width 160ms ease',
      }}>
        {/* Brand */}
        <div style={{
          height: 56, padding: collapsed ? 0 : '0 14px',
          display: 'flex', alignItems: 'center', gap: 10,
          justifyContent: collapsed ? 'center' : 'flex-start',
          borderBottom: `1px solid ${'var(--hf-border-faint)'}`,
        }}>
          <div style={{
            width: 28, height: 28, borderRadius: 7,
            background: `linear-gradient(135deg, ${'var(--hf-accent)'}, ${'var(--hf-accent-hover)'})`,
            color: '#fff',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 12, fontWeight: 700, letterSpacing: -0.3,
            boxShadow: 'var(--hf-shadow-sm)',
          }}>BS</div>
          {!collapsed && (
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 600, lineHeight: 1.1, color: 'var(--hf-ink)' }}>BookScraper</div>
              <div style={{ fontSize: 11, color: 'var(--hf-ink3)', lineHeight: 1.2, marginTop: 2 }}>admin · prod</div>
            </div>
          )}
        </div>

        {/* Search */}
        {!collapsed && (
          <div style={{ padding: '12px 10px 6px' }}>
            <button onClick={openCmdK} aria-label="Open command palette" className="hf-btn" style={{
              width: '100%',
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '7px 10px', background: 'var(--hf-surface)',
              border: `1px solid ${'var(--hf-border-strong)'}`, borderRadius: 6,
              color: 'var(--hf-ink4)', fontSize: 13, fontFamily: 'var(--hf-sans)',
              boxShadow: '0 1px 2px rgba(16,24,40,.03)',
              cursor: 'pointer', textAlign: 'left',
            }}>
              <span style={{ color: 'var(--hf-ink4)', display: 'flex' }}>{HF_ICONS.search}</span>
              <span style={{ flex: 1 }}>Search…</span>
              <span style={{
                fontFamily: 'var(--hf-mono)', fontSize: 11,
                padding: '1px 5px', background: 'var(--hf-subtle)',
                border: `1px solid ${'var(--hf-border)'}`, borderRadius: 3, color: 'var(--hf-ink3)',
              }}>⌘K</span>
            </button>
          </div>
        )}

        {/* Nav */}
        <div className="hf-scroll" style={{ flex: 1, overflow: 'auto', padding: collapsed ? '8px 4px' : '8px 10px' }}>
          {navGroups.map(g => (
            <div key={g.group} style={{ marginBottom: 14 }}>
              {!collapsed && (
                <div style={{
                  fontSize: 11, color: 'var(--hf-ink4)', fontWeight: 600,
                  textTransform: 'uppercase', letterSpacing: 0.7,
                  padding: '4px 8px 6px',
                }}>{g.group}</div>
              )}
              {g.items.map(([id, label, icon, badge]) => {
                const a = id === activePage;
                const href = (window.HF_BUILD_PATH && window.HF_BUILD_PATH(id)) || '#';
                const onNavClick = (e) => {
                  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
                  e.preventDefault();
                  setPage && setPage(id);
                };
                return (
                  <a key={id} href={href} onClick={onNavClick}
                     aria-current={a ? 'page' : undefined}
                     aria-label={collapsed ? label : undefined}
                     title={collapsed ? label : undefined}
                     className="hf-navlink" style={{
                    display: 'flex', alignItems: 'center',
                    gap: collapsed ? 0 : 10,
                    justifyContent: collapsed ? 'center' : 'flex-start',
                    padding: collapsed ? '8px 0' : '7px 9px',
                    margin: '1px 0',
                    borderRadius: 6,
                    color: a ? 'var(--hf-accent-ink)' : 'var(--hf-ink2)',
                    background: a ? 'var(--hf-accent-soft)' : 'transparent',
                    fontSize: 13, fontWeight: a ? 600 : 500,
                    textDecoration: 'none',
                    position: 'relative',
                    transition: 'background 100ms',
                  }}>
                    {a && !collapsed && <span style={{position:'absolute', left:-10, top:6, bottom:6, width:3, background:'var(--hf-accent)', borderRadius:'0 2px 2px 0'}}/>}
                    <span style={{ color: a ? 'var(--hf-accent)' : 'var(--hf-ink3)', display: 'flex' }}>{icon}</span>
                    {!collapsed && (
                      <>
                        <span style={{ flex: 1 }}>{label}</span>
                        {badge && (
                          <span style={{
                            fontFamily: 'var(--hf-mono)', fontSize: 11, fontWeight: 500,
                            padding: '1px 6px',
                            background: a ? 'var(--hf-surface)' : 'var(--hf-subtle)',
                            color: a ? 'var(--hf-accent-ink)' : 'var(--hf-ink2)',
                            border: `1px solid ${a ? 'var(--hf-accent-border)' : 'var(--hf-border)'}`,
                            borderRadius: 4,
                          }}>{badge}</span>
                        )}
                      </>
                    )}
                  </a>
                );
              })}
            </div>
          ))}
        </div>

        {/* Footer: status + collapse */}
        <div style={{
          borderTop: `1px solid ${'var(--hf-border-faint)'}`,
          padding: collapsed ? '10px 0' : '12px 12px',
          display: 'flex', flexDirection: collapsed ? 'column' : 'row', alignItems: 'center', gap: 10,
        }}>
          {!collapsed && (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 7, fontSize: 12, color: 'var(--hf-ink2)' }}>
              <HFDot tone="ok" size={7}/>
              <span>all systems ok</span>
            </div>
          )}
          <button onClick={() => setCollapsed(!collapsed)} className="hf-btn"
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-expanded={!collapsed}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            style={{
            background: 'var(--hf-surface)', border: `1px solid ${'var(--hf-border-strong)'}`, borderRadius: 6,
            color: 'var(--hf-ink3)', cursor: 'pointer', padding: '5px 7px',
            display: 'flex', alignItems: 'center',
          }}>
            <span style={{ display: 'inline-block', transform: collapsed ? 'rotate(0deg)' : 'rotate(180deg)', transition: 'transform 160ms' }}>
              {HF_ICONS.chevron}
            </span>
          </button>
        </div>
      </aside>

      {/* Main */}
      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {/* Topbar */}
        <div style={{
          height: 56, flexShrink: 0,
          padding: `0 var(--hf-content-x)`,
          borderBottom: `1px solid ${'var(--hf-border)'}`,
          display: 'flex', alignItems: 'center', gap: 14,
          background: 'var(--hf-surface)',
        }}>
          <div style={{ fontSize: 13, color: 'var(--hf-ink3)', display: 'flex', alignItems: 'center', gap: 6 }}>
            {breadcrumb}
          </div>
          <div style={{ flex: 1 }}/>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12, color: 'var(--hf-ink3)' }}>
            <span style={{ fontFamily: 'var(--hf-mono)', fontSize: 11, color: 'var(--hf-ink4)' }}>v2.14.0</span>
            <span style={{ width: 1, height: 18, background: 'var(--hf-border)' }}/>
            <HFButton size="md" variant="primary" onClick={openNewRun}>
              <span style={{ display: 'flex' }}>{HF_ICONS.plus}</span> New run
            </HFButton>
            <button ref={avatarRef} onClick={openAvatar}
              aria-label="Open account menu"
              aria-haspopup="menu"
              className="hf-focus" style={{
              width: 30, height: 30, borderRadius: '50%',
              background: `linear-gradient(135deg, ${'var(--hf-accent)'}, ${'var(--hf-accent-hover)'})`,
              border: 'none', padding: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 12, color: '#fff', fontWeight: 600,
              boxShadow: 'var(--hf-shadow-sm)', cursor: 'pointer',
              fontFamily: 'var(--hf-sans)',
            }}>A</button>
          </div>
        </div>

        {/* Page head */}
        <div style={{
          padding: `24px var(--hf-content-x) 18px`,
          borderBottom: `1px solid ${'var(--hf-border)'}`,
          display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16,
          background: 'var(--hf-surface)',
        }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 24, fontWeight: 700, letterSpacing: -0.5, lineHeight: 1.15, color: 'var(--hf-ink)' }}>{title}</div>
            {subtitle && <div style={{ fontSize: 14, color: 'var(--hf-ink3)', marginTop: 6 }}>{subtitle}</div>}
          </div>
          {actions && <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>{actions}</div>}
        </div>

        {/* Content */}
        <div className="hf-scroll" style={{ flex: 1, overflow: 'auto', padding: `20px var(--hf-content-x) 48px`, background: 'var(--hf-bg)' }}>
          <div style={{ minWidth: 1100 }}>
            {children}
          </div>
        </div>
      </main>
    </div>
  );
}

window.HFShell = HFShell;
