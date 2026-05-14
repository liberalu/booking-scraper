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
