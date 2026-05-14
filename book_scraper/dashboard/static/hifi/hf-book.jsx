// Canonical Book detail page — the routed component for /books/:id.
// The fallback "fetch the first book when no params.id" path remains for the
// design prototype's pager, which renders this component without a route.

// Locale-correct EUR formatting for Lithuanian price display.
const _eurFormatter = new Intl.NumberFormat('lt-LT', {
  style: 'currency', currency: 'EUR',
});
function formatEur(value) {
  if (value == null || value === '') return '—';
  const n = Number(value);
  return Number.isFinite(n) ? _eurFormatter.format(n) : '—';
}

// "Last seen" relative formatting. Falls back to the raw ISO if input is unusable.
function formatRelative(iso) {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return iso;
  const diffSec = Math.round((Date.now() - t) / 1000);
  if (diffSec < 60) return 'just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 86400 * 30) return `${Math.floor(diffSec / 86400)}d ago`;
  return new Date(iso).toLocaleDateString('lt-LT');
}

function DataSourceBadge({ value }) {
  const map = {
    ibiblioteka:   { label: 'National Library', tone: 'ok' },
    shop_inferred: { label: 'From shops',       tone: 'neutral' },
    manual:        { label: 'Manual',           tone: 'accent' },
  };
  const cfg = map[value] || { label: 'Unknown', tone: 'neutral' };
  return <HFPill tone={cfg.tone} soft>{cfg.label}</HFPill>;
}

const SHOP_COLORS = ['var(--hf-accent)', '#0e7490', '#b45309', '#7c3aed', '#16a34a', '#6b7280'];

function ShopMark({ name, allShops }) {
  const idx = allShops ? allShops.indexOf(name) : 0;
  const color = SHOP_COLORS[Math.max(0, idx) % SHOP_COLORS.length];
  return (
    <span style={{
      display: 'inline-block',
      width: 10, height: 10,
      borderRadius: '50%',
      background: color,
      flexShrink: 0,
    }} aria-hidden="true" />
  );
}

function HFBookListings({ book, shopNames, lowestPrice, goto }) {
  const shops = book.shops || [];

  if (shops.length === 0) {
    return (
      <HFCard>
        <div style={{ padding: 20 }}>
          <HFEmptyState
            title="Not listed anywhere we track"
            sub="No shop listings have been linked to this canonical book yet."
          />
        </div>
      </HFCard>
    );
  }

  return (
    <HFCard
      title="Listings across shops"
      sub={`${shops.length} shop${shops.length !== 1 ? 's' : ''} · price, stock, last scrape`}
    >
      <HFTable
        columns={[
          { key: 'shop', label: 'Shop', w: '1.1fr', cell: (v) => (
            <span style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
              <ShopMark name={v} allShops={shopNames} />
              <span style={{ color: 'var(--hf-ink)', fontWeight: 500 }}>{v}</span>
            </span>
          )},
          { key: 'price', label: 'Price', w: '0.9fr', align: 'right', cell: (_, r) => {
            if (r.price == null) return <span style={{ color: 'var(--hf-ink4)' }}>—</span>;
            const n = Number(r.price);
            const isBest = lowestPrice != null && Math.abs(n - lowestPrice) < 0.001;
            return (
              <span style={{ display: 'inline-flex', alignItems: 'baseline', gap: 6, justifyContent: 'flex-end' }}>
                <span style={{
                  fontFamily: 'var(--hf-mono)',
                  color: isBest ? 'var(--hf-ok-ink)' : 'var(--hf-ink)',
                  fontWeight: isBest ? 600 : 500,
                }}>
                  {new Intl.NumberFormat('lt-LT', { style: 'currency', currency: 'EUR' }).format(n)}
                </span>
                {isBest && (
                  <span style={{
                    fontSize: 10, color: 'var(--hf-ok-ink)',
                    fontWeight: 600, letterSpacing: 0.4,
                  }}>BEST</span>
                )}
              </span>
            );
          }},
          { key: 'delta', label: 'Δ 30d', w: '0.55fr', align: 'right',
            cell: () => <span style={{ color: 'var(--hf-ink4)', fontFamily: 'var(--hf-mono)' }}>—</span>
          },
          { key: 'in_stock', label: 'Stock', w: '0.7fr', cell: (v) => (
            v
              ? <HFPill tone="ok" soft>In stock</HFPill>
              : <HFPill tone="warn" soft>Out</HFPill>
          )},
          { key: 'last_seen_at', label: 'Last scrape', w: '0.85fr', cell: (v) =>
            v
              ? <time dateTime={v}>{formatRelative(v)}</time>
              : <span style={{ color: 'var(--hf-ink4)' }}>—</span>
          },
          { key: 'url', label: '', w: '90px', align: 'right', cell: (v, r) =>
            v
              ? <a
                  href={v}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`Open at ${r.shop} (new tab)`}
                  title={`Open at ${r.shop}`}
                  style={{
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    minWidth: 32, minHeight: 32, padding: '0 8px',
                    color: 'var(--hf-accent-ink)',
                    fontFamily: 'var(--hf-mono)', fontSize: 11,
                    textDecoration: 'none',
                  }}
                >Visit ↗</a>
              : '—'
          },
        ]}
        rows={shops}
      />
    </HFCard>
  );
}

function HFBookMetadata({ book, authorsByRole }) {
  const ROLE_LABELS = {
    author:       'Author',
    translator:   'Translated by',
    narrator:     'Narrated by',
    editor:       'Edited by',
    illustrator:  'Illustrated by',
    cover_artist: 'Cover by',
    producer:     'Produced by',
  };

  const roleOrder = ['author', 'translator', 'narrator', 'editor',
                     'illustrator', 'cover_artist', 'producer'];
  const extraRoles = Object.keys(authorsByRole).filter(r => !roleOrder.includes(r));
  const allRoles = [...roleOrder, ...extraRoles].filter(r => (authorsByRole[r] || []).length > 0);

  const fields = [
    ['Year',           book.year],
    ['Publisher',      book.publisher],
    ['Format',         book.format],
    ['Language',       book.language],
    ['Pages',          book.pages ? `${book.pages} p.` : null],
    ['Duration',       book.duration],
    ['Type',           book.type],
    ['Audience',       book.audience],
    ['Series',         book.series],
    ['Release place',  book.release_place],
    ['UDC codes',      (book.udc_codes || []).join(', ') || null],
    ['Translated from',book.translated_from],
    ['Dimensions',     book.dimensions],
    ['LIBIS code',     book.libis_code],
    ['Data source',    book.data_source],
    ['Subjects',       (book.subjects || []).join(' · ') || null],
    ['Description',    book.description],
  ].filter(([, v]) => v != null && v !== '');

  return (
    <>
      <HFCard
        title="Contributors"
        sub="author, translator, narrator, editor, and other credited roles"
        style={{ marginBottom: 'var(--hf-gap)' }}
      >
        {allRoles.length === 0 ? (
          <div style={{ padding: '16px 20px', fontSize: 13, color: 'var(--hf-ink3)' }}>
            No contributor data.
          </div>
        ) : (
          <div style={{ padding: '4px 0' }}>
            {allRoles.map((role, i) => (
              <div key={role} style={{
                display: 'grid',
                gridTemplateColumns: '160px 1fr',
                padding: '10px 20px',
                borderBottom: i < allRoles.length - 1
                  ? '1px solid var(--hf-border-faint)' : 'none',
                fontSize: 13,
                alignItems: 'baseline',
              }}>
                <span style={{ color: 'var(--hf-ink3)', fontWeight: 500 }}>
                  {ROLE_LABELS[role] || role.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                </span>
                <span style={{ color: 'var(--hf-ink)' }}>
                  {authorsByRole[role].join(', ')}
                </span>
              </div>
            ))}
          </div>
        )}
      </HFCard>

      <HFCard title="Metadata" sub="fields from the canonical record">
        {fields.length === 0 ? (
          <div style={{ padding: '16px 20px', fontSize: 13, color: 'var(--hf-ink3)' }}>
            No metadata.
          </div>
        ) : (
          <div style={{ padding: '4px 0' }}>
            {fields.map(([label, value], i) => (
              <div key={label} style={{
                display: 'grid',
                gridTemplateColumns: '160px 1fr',
                padding: '10px 20px',
                borderBottom: i < fields.length - 1
                  ? '1px solid var(--hf-border-faint)' : 'none',
                fontSize: 13,
                alignItems: 'baseline',
                background: i % 2 === 0 ? 'transparent' : 'var(--hf-subtle)',
              }}>
                <span style={{ color: 'var(--hf-ink3)', fontWeight: 500 }}>{label}</span>
                <span style={{ color: 'var(--hf-ink)', lineHeight: 1.5 }}>
                  {label === 'LIBIS code'
                    ? <span style={{
                        fontFamily: 'var(--hf-mono)', fontSize: 11,
                        padding: '2px 7px', borderRadius: 4,
                        background: 'var(--hf-subtle)',
                        border: '1px solid var(--hf-border)',
                        color: 'var(--hf-ink3)',
                      }}>{value}</span>
                    : label === 'Data source'
                      ? <DataSourceBadge value={book.data_source} />
                      : String(value)
                  }
                </span>
              </div>
            ))}
          </div>
        )}
      </HFCard>
    </>
  );
}

function HFBookPricesStub() {
  return (
    <HFCard title="Price history" sub="Coming in a future release">
      <div style={{ padding: 32 }}>
        <HFEmptyState
          title="Price history not yet available"
          sub="Once the price history endpoint is added, this tab will show per-shop price trends over time."
        />
      </div>
    </HFCard>
  );
}

function HFBookConflictsStub() {
  return (
    <HFCard title="Conflicts" sub="Coming in a future release">
      <div style={{ padding: 32 }}>
        <HFEmptyState
          title="Conflict detection not yet available"
          sub="This tab will highlight fields that differ between the canonical record and individual shop listings."
        />
      </div>
    </HFCard>
  );
}

function HFBook({ nav, goto, params }) {
  const HF = getHF();
  const [book, setBook] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);
  const [tab, setTab] = React.useState('listings');

  const bookId = params && params.id;

  React.useEffect(() => {
    setLoading(true);
    setError(null);

    const load = bookId
      ? fetch(`/api/books/${bookId}`).then(r => r.ok ? r.json() : Promise.reject(r.status))
      : fetch('/api/books?per_page=1&has_isbn=true')
          .then(r => r.json())
          .then(d => {
            const first = d.books && d.books[0];
            if (!first) return fetch('/api/books?per_page=1').then(r => r.json()).then(dd => {
              const f2 = dd.books && dd.books[0];
              if (!f2) throw new Error('no-books');
              return fetch(`/api/books/${f2.id}`).then(r => r.ok ? r.json() : Promise.reject(r.status));
            });
            return fetch(`/api/books/${first.id}`).then(r => r.ok ? r.json() : Promise.reject(r.status));
          });

    load
      .then(d => { setBook(d); setLoading(false); })
      .catch(e => { setError(String(e)); setLoading(false); });
  }, [bookId]);

  if (loading) {
    return (
      <HFShell {...nav} goto={goto} activePage="books" title="Book">
        <HFCard padding={20} style={{ marginBottom: 'var(--hf-gap)' }}>
          <div style={{ display: 'flex', gap: 20 }}>
            <HFSkeleton w={100} h={140} br={6} style={{ flexShrink: 0 }} />
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <HFSkeleton w="60%" h={24} />
              <HFSkeleton w="40%" h={14} />
              <HFSkeleton w="30%" h={13} />
              <HFSkeleton w="50%" h={13} />
            </div>
          </div>
        </HFCard>
        <HFCard><HFSkeleton h={160} /></HFCard>
      </HFShell>
    );
  }

  if (error || !book) {
    return (
      <HFShell {...nav} goto={goto} activePage="books" title="Book">
        <HFCard padding={32}>
          <HFEmptyState
            title={error === 'no-books' ? 'No books yet' : 'Book not found'}
            sub={error === 'no-books'
              ? 'Run an ibiblioteka discovery to populate the canonical catalogue.'
              : `Could not load book (${error}).`}
          />
        </HFCard>
      </HFShell>
    );
  }

  const authorsByRole = {};
  for (const a of (book.authors || [])) {
    (authorsByRole[a.role] = authorsByRole[a.role] || []).push(a.name);
  }

  const shopNames = (book.shops || []).map(s => s.shop);
  const prices = (book.shops || []).map(s => s.price).filter(p => p != null).map(Number);
  const lowestPrice = prices.length ? Math.min(...prices) : null;

  const meta = [
    book.year,
    book.publisher,
    book.format,
    book.language,
    book.pages && `${book.pages} p.`,
    book.duration,
  ].filter(Boolean).join(' · ');

  const isbns = book.isbns || [];

  return (
    <HFShell
      {...nav}
      goto={goto}
      activePage="books"
      title={book.title}
      subtitle={meta || undefined}
      breadcrumb={
        <>
          <HFBreadcrumbLink page="books" goto={goto}>Books</HFBreadcrumbLink>
          <span>/</span>
          <span>{book.title}</span>
        </>
      }
    >
      {/* Hero card */}
      <HFCard padding={20} style={{ marginBottom: 'var(--hf-gap)' }}>
        <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
          {book.cover_url && (
            <img
              src={book.cover_url}
              alt={book.title}
              loading="lazy"
              style={{
                width: 108, aspectRatio: '2 / 3', objectFit: 'contain',
                flexShrink: 0, borderRadius: 6,
                border: '1px solid var(--hf-border)',
                boxShadow: '0 2px 8px rgba(16,24,40,.08)',
                background: 'var(--hf-subtle)',
              }}
            />
          )}

          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, marginBottom: 8 }}>
              <div style={{ minWidth: 0 }}>
                <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, lineHeight: 1.3, color: 'var(--hf-ink)', letterSpacing: -0.3 }}>
                  {book.title}
                </h2>
                {book.title_full && book.title_full !== book.title && (
                  <div style={{ color: 'var(--hf-ink3)', fontSize: 13, marginTop: 3 }}>{book.title_full}</div>
                )}
              </div>
              <DataSourceBadge value={book.data_source} />
            </div>

            {(authorsByRole.author || []).length > 0 && (
              <div style={{ fontSize: 14, color: 'var(--hf-ink)', marginBottom: 3 }}>
                {authorsByRole.author.join(', ')}
              </div>
            )}
            {(authorsByRole.translator || []).length > 0 && (
              <div style={{ fontSize: 13, color: 'var(--hf-ink3)', marginBottom: 3 }}>
                Translated by {authorsByRole.translator.join(', ')}
              </div>
            )}
            {(authorsByRole.narrator || []).length > 0 && (
              <div style={{ fontSize: 13, color: 'var(--hf-ink3)', marginBottom: 3 }}>
                Narrated by {authorsByRole.narrator.join(', ')}
              </div>
            )}

            {meta && (
              <div style={{ fontSize: 13, color: 'var(--hf-ink3)', marginTop: 6 }}>{meta}</div>
            )}

            {/* ISBNs + LIBIS */}
            {(isbns.length > 0 || book.libis_code) && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
                {isbns.map(i => (
                  <button
                    key={i.isbn}
                    type="button"
                    aria-label={`Copy ISBN ${i.isbn}`}
                    onClick={() => {
                      navigator.clipboard.writeText(i.isbn).then(
                        () => window.HF_APP?.toast?.({ tone: 'ok', message: `Copied ${i.isbn}` }),
                        () => window.HF_APP?.toast?.({ tone: 'err', message: 'Copy failed' }),
                      );
                    }}
                    style={{
                      fontFamily: 'var(--hf-mono)', fontSize: 11,
                      padding: '3px 8px', borderRadius: 4,
                      background: 'var(--hf-subtle)', border: '1px solid var(--hf-border)',
                      color: 'var(--hf-ink2)', cursor: 'pointer',
                    }}
                  >{i.isbn}</button>
                ))}
                {book.libis_code && (
                  <span style={{
                    fontFamily: 'var(--hf-mono)', fontSize: 11,
                    padding: '2px 7px', borderRadius: 4,
                    background: 'var(--hf-subtle)', border: '1px solid var(--hf-border)',
                    color: 'var(--hf-ink3)',
                  }}>LIBIS {book.libis_code}</span>
                )}
              </div>
            )}
          </div>
        </div>

      </HFCard>

      <HFCard style={{ marginBottom: 'var(--hf-gap)' }} padding={0}>
        <div style={{ padding: `0 var(--hf-card-p, 16px)` }}>
          <HFTabs
            active={tab}
            onChange={setTab}
            tabs={[
              { id: 'listings',  label: 'Listings',  count: (book.shops || []).length },
              { id: 'metadata',  label: 'Metadata' },
              { id: 'prices',    label: 'Prices' },
              { id: 'conflicts', label: 'Conflicts' },
            ]}
          />
        </div>
      </HFCard>

      {tab === 'listings'  && <HFBookListings  book={book} shopNames={shopNames} lowestPrice={lowestPrice} goto={goto} />}
      {tab === 'metadata'  && <HFBookMetadata  book={book} authorsByRole={authorsByRole} />}
      {tab === 'prices'    && <HFBookPricesStub />}
      {tab === 'conflicts' && <HFBookConflictsStub />}
    </HFShell>
  );
}
