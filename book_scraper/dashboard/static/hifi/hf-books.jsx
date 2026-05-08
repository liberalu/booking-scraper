// Books page — canonical book list + detail.

function DataSourceBadge({ value }) {
  const map = {
    ibiblioteka:   { label: 'National Library', tone: 'ok' },
    shop_inferred: { label: 'From shops',       tone: 'neutral' },
    manual:        { label: 'Manual',           tone: 'accent' },
  };
  const cfg = map[value] || { label: value, tone: 'neutral' };
  return <HFPill tone={cfg.tone} soft>{cfg.label}</HFPill>;
}


function HFBooks({ nav, goto }) {
  const _sp = new URLSearchParams(window.location.search);
  const [q, setQ]                   = React.useState(_sp.get('q') || '');
  const [dataSource, setDataSource] = React.useState(_sp.get('data_source') || 'all');
  const [hasIsbn, setHasIsbn]       = React.useState(_sp.get('has_isbn') || 'any');
  const [hasShops, setHasShops]     = React.useState(_sp.get('has_shops') || 'any');
  const [year, setYear]             = React.useState(_sp.get('year') || '');
  const [page, setPage]             = React.useState(1);
  const PER_PAGE = 50;

  const [data, setData] = React.useState({ books: [], total: 0, pages: 1 });
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    const params = new URLSearchParams();
    if (dataSource !== 'all') params.set('data_source', dataSource);
    if (hasIsbn !== 'any')    params.set('has_isbn', hasIsbn === 'yes' ? 'true' : 'false');
    if (hasShops !== 'any')   params.set('has_shops', hasShops === 'linked' ? 'true' : 'false');
    if (year)                 params.set('year', year);
    params.set('page', String(page));
    params.set('per_page', String(PER_PAGE));
    setLoading(true);
    fetch(`/api/books?${params}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); });
  }, [dataSource, hasIsbn, hasShops, year, page]);

  const visible = q
    ? data.books.filter(b => (b.title || '').toLowerCase().includes(q.toLowerCase()))
    : data.books;

  return (
    <HFShell {...nav} goto={goto}>
      <HFCard style={{ marginBottom: 'var(--hf-gap)', overflow: 'visible' }} padding={12}>
        <HFFilterBar right={<>
          <span style={{ fontSize: 12, color: 'var(--hf-ink4)', fontFamily: 'var(--hf-mono)' }}>
            {data.total.toLocaleString()} books
          </span>
        </>}>
          <HFSearch placeholder="Title, ISBN…" width={260} value={q} onChange={setQ} />
          <HFFilter label="Source"
            value={dataSource}
            options={['all', 'ibiblioteka', 'shop_inferred', 'manual']}
            onChange={setDataSource} />
          <HFFilter label="ISBN" value={hasIsbn} options={['any', 'yes', 'no']}
            onChange={setHasIsbn} allLabel="any" />
          <HFFilter label="Shops" value={hasShops} options={['any', 'linked', 'unlinked']}
            onChange={setHasShops} allLabel="any" />
        </HFFilterBar>
      </HFCard>

      <HFCard>
        {loading
          ? <HFTableSkeleton columns={['Title','Authors','Year','Publisher','ISBN','Source','Shops']} rows={6} />
          : visible.length === 0
            ? <HFEmptyState
                title="No books"
                sub={data.total === 0
                  ? "No canonical books yet. Run an ibiblioteka discovery + scan to populate the catalogue."
                  : "No books match the current filters."} />
            : <HFTable
                columns={[
                  { key: 'title',        label: 'Title' },
                  { key: 'authors',      label: 'Authors' },
                  { key: 'year',         label: 'Year' },
                  { key: 'publisher',    label: 'Publisher' },
                  { key: 'primary_isbn', label: 'ISBN' },
                  { key: 'data_source',  label: 'Source' },
                  { key: 'shop_count',   label: 'Shops' },
                ]}
                rows={visible.map(b => ({
                  ...b,
                  authors: (b.authors || []).join('; '),
                  data_source: <DataSourceBadge value={b.data_source} />,
                  shop_count: b.shop_count > 0
                    ? <HFPill tone="ok">{b.shop_count}</HFPill>
                    : <span style={{ color: 'var(--hf-ink4)' }}>—</span>,
                }))}
                onRowClick={r => goto('book-detail', { id: r.id })} />
        }
      </HFCard>

      {data.pages > 1 && !loading &&
        <div style={{ display: 'flex', gap: 8, marginTop: 12, justifyContent: 'center' }}>
          <HFButton size="sm" variant="subtle" disabled={page <= 1}
            onClick={() => setPage(page - 1)}>Prev</HFButton>
          <span style={{ fontSize: 12, alignSelf: 'center', color: 'var(--hf-ink4)' }}>
            Page {data.page} of {data.pages}
          </span>
          <HFButton size="sm" variant="subtle" disabled={page >= data.pages}
            onClick={() => setPage(page + 1)}>Next</HFButton>
        </div>}
    </HFShell>
  );
}


function HFBookDetail({ nav, goto, params }) {
  const [book, setBook] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);

  React.useEffect(() => {
    fetch(`/api/books/${params.id}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => { setBook(d); setLoading(false); })
      .catch(s => { setError(s); setLoading(false); });
  }, [params.id]);

  if (loading) return <HFShell {...nav} goto={goto}><HFCard><HFSkeleton h={200} /></HFCard></HFShell>;
  if (error) return <HFShell {...nav} goto={goto}><HFCard><HFEmptyState title="Book not found" sub={`HTTP ${error}`} /></HFCard></HFShell>;

  const authorsByRole = {};
  for (const a of book.authors || []) {
    (authorsByRole[a.role] = authorsByRole[a.role] || []).push(a.name);
  }

  return (
    <HFShell {...nav} goto={goto}>
      <HFCard padding={20}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <button onClick={() => goto('books')}
              style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--hf-accent-ink)' }}>
              ← Books
            </button>
            <h2 style={{ margin: '8px 0', fontSize: 24 }}>{book.title}</h2>
            {book.title_full && book.title_full !== book.title &&
              <div style={{ color: 'var(--hf-ink3)', marginBottom: 8 }}>{book.title_full}</div>}
            {(authorsByRole.author || []).length > 0 &&
              <div>By {(authorsByRole.author).join(', ')}</div>}
            {(authorsByRole.translator || []).length > 0 &&
              <div style={{ color: 'var(--hf-ink3)' }}>Translated by {(authorsByRole.translator).join(', ')}</div>}
            {(authorsByRole.narrator || []).length > 0 &&
              <div style={{ color: 'var(--hf-ink3)' }}>Narrated by {(authorsByRole.narrator).join(', ')}</div>}
            <div style={{ color: 'var(--hf-ink3)', fontSize: 13, marginTop: 8 }}>
              {[book.year, book.publisher, book.format,
                book.pages && `${book.pages} p.`, book.duration]
                .filter(Boolean).join(' · ')}
            </div>
          </div>
          <DataSourceBadge value={book.data_source} />
        </div>

        {book.cover_url &&
          <div style={{ marginTop: 16 }}>
            <img src={book.cover_url} alt={book.title} style={{ maxHeight: 240 }} />
          </div>}

        <div style={{ marginTop: 16, fontSize: 13, color: 'var(--hf-ink3)' }}>
          {book.isbns?.length > 0 && <div>ISBN: {book.isbns.map(i => i.isbn).join(', ')}</div>}
          {book.libis_code && <div>LIBIS: {book.libis_code}</div>}
          {book.subjects?.length > 0 && <div>Subjects: {book.subjects.join(' · ')}</div>}
        </div>

        {book.description &&
          <div style={{ marginTop: 16, lineHeight: 1.6 }}>{book.description}</div>}
      </HFCard>

      <HFCard style={{ marginTop: 'var(--hf-gap)' }}>
        <h3 style={{ margin: '12px 16px', fontSize: 14, color: 'var(--hf-ink3)' }}>Available at</h3>
        {(book.shops || []).length === 0
          ? <HFEmptyState title="Not sold anywhere we track"
              sub="No shop listings linked to this canonical book yet." />
          : <HFTable
              columns={[
                { key: 'shop',         label: 'Shop' },
                { key: 'price',        label: 'Price' },
                { key: 'in_stock',     label: 'Stock' },
                { key: 'url',          label: 'URL' },
                { key: 'last_seen_at', label: 'Last seen' },
              ]}
              rows={book.shops.map(s => ({
                ...s,
                price: s.price ? `€${s.price}` : '—',
                in_stock: s.in_stock
                  ? <HFPill tone="ok" soft>ok</HFPill>
                  : <HFPill tone="warn" soft>out</HFPill>,
              }))} />
        }
      </HFCard>
    </HFShell>
  );
}
