// Canonical Book detail page.
// Used in the design prototype (HFBook fetches the first available book when no params.id).
// In the production dashboard, HFBookDetail (hf-books.jsx) handles the routed case with params.id.

function DataSourceBadge({ value }) {
  const map = {
    ibiblioteka:   { label: 'National Library', tone: 'ok' },
    shop_inferred: { label: 'From shops',       tone: 'neutral' },
    manual:        { label: 'Manual',           tone: 'accent' },
  };
  const cfg = map[value] || { label: value || '—', tone: 'neutral' };
  return <HFPill tone={cfg.tone} soft>{cfg.label}</HFPill>;
}

function HFBook({ nav, goto, params }) {
  const HF = getHF();
  const [book, setBook] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);

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

  const meta = [
    book.year,
    book.publisher,
    book.format,
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
              style={{
                width: 108, height: 'auto', objectFit: 'contain',
                flexShrink: 0, borderRadius: 6,
                border: '1px solid var(--hf-border)',
                boxShadow: '0 2px 8px rgba(16,24,40,.08)',
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
                  <span key={i.isbn} style={{
                    fontFamily: 'var(--hf-mono)', fontSize: 11,
                    padding: '2px 7px', borderRadius: 4,
                    background: 'var(--hf-subtle)', border: '1px solid var(--hf-border)',
                    color: 'var(--hf-ink2)',
                  }}>{i.isbn}</span>
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

        {/* Subjects */}
        {(book.subjects || []).length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--hf-border-faint)' }}>
            {book.subjects.map(s => <HFPill key={s} tone="neutral" soft>{s}</HFPill>)}
          </div>
        )}

        {/* Description */}
        {book.description && (
          <div style={{
            marginTop: 14, paddingTop: 14,
            borderTop: (book.subjects || []).length > 0 ? 'none' : '1px solid var(--hf-border-faint)',
            lineHeight: 1.65, fontSize: 13, color: 'var(--hf-ink2)',
          }}>
            {book.description}
          </div>
        )}
      </HFCard>

      {/* Shop listings */}
      <HFCard
        title="Available at"
        sub={(book.shops || []).length > 0 ? `${book.shops.length} shop${book.shops.length !== 1 ? 's' : ''}` : undefined}
      >
        {(book.shops || []).length === 0
          ? <div style={{ padding: 20 }}>
              <HFEmptyState
                title="Not listed anywhere we track"
                sub="No shop listings have been linked to this canonical book yet."
              />
            </div>
          : <HFTable
              columns={[
                { key: 'shop',         label: 'Shop',      w: '120px' },
                { key: 'price',        label: 'Price',     w: '90px' },
                { key: 'in_stock',     label: 'Stock',     w: '80px' },
                { key: 'last_seen_at', label: 'Last seen', w: '1fr' },
                { key: 'url',          label: 'URL',       w: '60px' },
              ]}
              rows={(book.shops || []).map(s => ({
                ...s,
                price: s.price ? `€${Number(s.price).toFixed(2)}` : '—',
                in_stock: s.in_stock
                  ? <HFPill tone="ok" soft>In stock</HFPill>
                  : <HFPill tone="warn" soft>Out</HFPill>,
                url: s.url
                  ? <a href={s.url} target="_blank" rel="noopener noreferrer"
                       style={{ color: 'var(--hf-accent-ink)', fontFamily: 'var(--hf-mono)', fontSize: 11 }}>↗</a>
                  : '—',
              }))}
            />
        }
      </HFCard>
    </HFShell>
  );
}
