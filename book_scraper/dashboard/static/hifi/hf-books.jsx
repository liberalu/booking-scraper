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

  const [debouncedQ, setDebouncedQ] = React.useState(q);
  React.useEffect(() => {
    const id = setTimeout(() => setDebouncedQ(q), 150);
    return () => clearTimeout(id);
  }, [q]);

  React.useEffect(() => {
    const params = new URLSearchParams();
    if (dataSource !== 'all') params.set('data_source', dataSource);
    if (hasIsbn !== 'any')    params.set('has_isbn', hasIsbn === 'yes' ? 'true' : 'false');
    if (hasShops !== 'any')   params.set('has_shops', hasShops === 'linked' ? 'true' : 'false');
    if (year)                 params.set('year', year);
    if (debouncedQ.trim())    params.set('search', debouncedQ.trim());
    params.set('page', String(page));
    params.set('per_page', String(PER_PAGE));
    setLoading(true);
    fetch(`/api/books?${params}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); });
  }, [dataSource, hasIsbn, hasShops, year, debouncedQ, page]);

  const visible = data.books;

  return (
    <HFShell {...nav} goto={goto} activePage="books"
      title="Books"
      subtitle="Canonical catalogue · one record per logical book"
      breadcrumb={<><span>BookScraper</span><span style={{color:'var(--hf-ink5)'}}>/</span><span style={{color:'var(--hf-ink)', fontWeight:500}}>Books</span></>}
      actions={<HFButton variant="primary" onClick={() => window.HF_APP?.openAddBook?.()}><span style={{display:'flex'}}>{HF_ICONS.plus}</span> Add book</HFButton>}
    >
      <HFCard style={{ marginBottom: 'var(--hf-gap)', overflow: 'visible' }} padding={12}>
        <HFFilterBar right={<>
          <span style={{ fontSize: 12, color: 'var(--hf-ink4)', fontFamily: 'var(--hf-mono)' }}>
            {data.total.toLocaleString()} books
          </span>
        </>}>
          <HFSearch placeholder="Title, author, ISBN…" width={260} value={q}
            onChange={v => { setQ(v); setPage(1); }} />
          <HFFilter label="Source"
            value={dataSource}
            options={['all', 'ibiblioteka', 'shop_inferred', 'manual']}
            onChange={v => { setDataSource(v); setPage(1); }} />
          <HFFilter label="ISBN" value={hasIsbn} options={['any', 'yes', 'no']}
            onChange={v => { setHasIsbn(v); setPage(1); }} allLabel="any" />
          <HFFilter label="Shops" value={hasShops} options={['any', 'linked', 'unlinked']}
            onChange={v => { setHasShops(v); setPage(1); }} allLabel="any" />
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

