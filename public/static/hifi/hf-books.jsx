function HFBooks({ nav, goto }) {
    const HF = getHF();

    const _initialParams = React.useMemo(() => {
        const sp = new URLSearchParams(
            typeof window !== "undefined" ? window.location.search : "",
        );
        return {
            page: Math.max(1, parseInt(sp.get("page") || "1", 10) || 1),
            q: sp.get("q") || "",
            enriched: sp.get("enriched") || "any",
            conflicts: sp.get("conflicts") || "any",
            isbn: sp.get("isbn") || "any",
            shops: sp.get("shops") || "any",
            year: sp.get("year") || "any",
        };
    }, []);

    const [data, setData] = React.useState({ books: [], total: 0, pages: 1 });
    const [loading, setLoading] = React.useState(true);
    const [page, setPage] = React.useState(_initialParams.page);
    const [stats, setStats] = React.useState(null);

    React.useEffect(() => {
        fetch("/api/books/stats")
            .then((r) => (r.ok ? r.json() : null))
            .then((d) => {
                if (d) setStats(d);
            })
            .catch(() => {});
    }, []);

    const [q, setQ] = React.useState(_initialParams.q);
    const [enrichedFilter, setEnrichedFilter] = React.useState(
        _initialParams.enriched,
    );
    const [conflictsFilter, setConflictsFilter] = React.useState(
        _initialParams.conflicts,
    );
    const [isbnFilter, setIsbnFilter] = React.useState(_initialParams.isbn);
    const [shopsFilter, setShopsFilter] = React.useState(_initialParams.shops);
    const [yearFilter, setYearFilter] = React.useState(_initialParams.year);
    const [availableYears, setAvailableYears] = React.useState([]);

    React.useEffect(() => {
        fetch("/api/books/years")
            .then((r) => (r.ok ? r.json() : []))
            .then((ys) => setAvailableYears(ys))
            .catch(() => {});
    }, []);

    React.useEffect(() => {
        const sp = new URLSearchParams();
        if (page > 1) sp.set("page", String(page));
        if (q) sp.set("q", q);
        if (enrichedFilter !== "any") sp.set("enriched", enrichedFilter);
        if (conflictsFilter !== "any") sp.set("conflicts", conflictsFilter);
        if (isbnFilter !== "any") sp.set("isbn", isbnFilter);
        if (shopsFilter !== "any") sp.set("shops", shopsFilter);
        if (yearFilter !== "any") sp.set("year", yearFilter);
        const qs = sp.toString();
        const url = "/books" + (qs ? "?" + qs : "");
        const cur = window.location.pathname + window.location.search;
        if (url !== cur) window.history.replaceState(null, "", url);
    }, [
        page,
        q,
        enrichedFilter,
        conflictsFilter,
        isbnFilter,
        shopsFilter,
        yearFilter,
    ]);

    React.useEffect(() => {
        setLoading(true);
        const params = new URLSearchParams();
        params.set("per_page", "50");
        params.set("page", String(page));
        if (q) params.set("search", q);
        if (enrichedFilter === "enriched")
            params.set("data_source", "ibiblioteka");
        if (enrichedFilter === "not enriched")
            params.set("data_source", "shop_inferred");
        if (shopsFilter === "0 shops") params.set("has_shops", "false");
        if (shopsFilter === "1+ shops") params.set("has_shops", "true");
        if (shopsFilter === "1 shop only") {
            params.set("shop_count_min", "1");
            params.set("shop_count_max", "1");
        }
        if (shopsFilter === "2-3 shops") {
            params.set("shop_count_min", "2");
            params.set("shop_count_max", "3");
        }
        if (shopsFilter === "4+ shops") params.set("shop_count_min", "4");
        if (isbnFilter === "has ISBN") params.set("has_isbn", "true");
        if (isbnFilter === "missing ISBN") params.set("has_isbn", "false");
        if (yearFilter !== "any") params.set("year", yearFilter);
        if (conflictsFilter === "clean") params.set("has_conflicts", "false");
        if (conflictsFilter === "has conflicts")
            params.set("has_conflicts", "true");
        fetch(`/api/books?${params}`)
            .then((r) => r.json())
            .then((d) => {
                setData(d);
                setLoading(false);
            })
            .catch(() => setLoading(false));
    }, [
        q,
        enrichedFilter,
        isbnFilter,
        shopsFilter,
        conflictsFilter,
        yearFilter,
        page,
    ]);

    const onExport = () => {
        const params = new URLSearchParams();
        if (q) params.set("search", q);
        if (enrichedFilter === "enriched")
            params.set("data_source", "ibiblioteka");
        if (enrichedFilter === "not enriched")
            params.set("data_source", "shop_inferred");
        if (shopsFilter === "0 shops") params.set("has_shops", "false");
        if (shopsFilter === "1+ shops") params.set("has_shops", "true");
        if (shopsFilter === "1 shop only") {
            params.set("shop_count_min", "1");
            params.set("shop_count_max", "1");
        }
        if (shopsFilter === "2-3 shops") {
            params.set("shop_count_min", "2");
            params.set("shop_count_max", "3");
        }
        if (shopsFilter === "4+ shops") params.set("shop_count_min", "4");
        if (isbnFilter === "has ISBN") params.set("has_isbn", "true");
        if (isbnFilter === "missing ISBN") params.set("has_isbn", "false");
        if (yearFilter !== "any") params.set("year", yearFilter);
        if (conflictsFilter === "clean") params.set("has_conflicts", "false");
        if (conflictsFilter === "has conflicts")
            params.set("has_conflicts", "true");
        window.location.href = `/api/books/export?${params}`;
    };

    const rows = (data.books || []).map((b) => ({
        id: b.id,
        title: b.title,
        author: (b.authors && b.authors[0]) || "",
        isbn: b.primary_isbn || null,
        year: b.year || null,
        shops: b.shop_count || 0,
        priceMin: b.price_min,
        priceMax: b.price_max,
        enriched: b.data_source !== "shop_inferred",
        conflicts: b.has_conflicts ? 1 : 0,
        updated: "—",
    }));

    const filteredRows = rows.filter((r) => {
        return true;
    });

    return (
        <HFShell
            {...nav}
            activePage="books"
            title="Books"
            subtitle={`Canonical catalog · ${data.total.toLocaleString()} unique titles aggregated from 5 shops + ISBN DB. ↓ Each book maps to N Shop Books.`}
            breadcrumb={
                <>
                    <span>BookScraper</span>
                    <span style={{ color: HF.ink5 }}>/</span>
                    <span style={{ color: HF.ink, fontWeight: 500 }}>
                        Books
                    </span>
                </>
            }
            actions={
                <>
                    <HFButton onClick={onExport}>
                        <span style={{ display: "flex" }}>
                            {HF_ICONS.download}
                        </span>{" "}
                        Export
                    </HFButton>
                    <HFButton>
                        <span style={{ display: "flex" }}>
                            {HF_ICONS.refresh}
                        </span>{" "}
                        Re-aggregate
                    </HFButton>
                    <HFButton
                        variant="primary"
                        onClick={() =>
                            window.HF_APP && window.HF_APP.openAddBook()
                        }
                    >
                        <span style={{ display: "flex" }}>{HF_ICONS.plus}</span>{" "}
                        Add book
                    </HFButton>
                </>
            }
        >
            <HFKpiStrip
                items={[
                    {
                        label: "Total titles",
                        value: stats
                            ? stats.total.toLocaleString()
                            : data.total.toLocaleString(),
                    },
                    {
                        label: "Enriched (ISBN-DB)",
                        value: stats ? stats.enriched.toLocaleString() : "—",
                        delta: stats ? (
                            <span style={{ color: HF.ink3 }}>
                                {stats.enriched_pct}%
                            </span>
                        ) : null,
                    },
                    {
                        label: "Multi-shop",
                        value: stats ? stats.multi_shop.toLocaleString() : "—",
                        delta: stats ? (
                            <span style={{ color: HF.ink3 }}>
                                {stats.avg_shops} shops avg
                            </span>
                        ) : null,
                    },
                    {
                        label: "Single-shop",
                        value: stats ? stats.single_shop.toLocaleString() : "—",
                        delta:
                            stats && stats.total ? (
                                <span style={{ color: HF.ink3 }}>
                                    {Math.round(
                                        (stats.single_shop / stats.total) * 100,
                                    )}
                                    %
                                </span>
                            ) : null,
                    },
                    {
                        label: "Conflicts",
                        value: stats ? stats.conflicts.toLocaleString() : "—",
                        delta: stats ? (
                            <span
                                style={{
                                    color:
                                        stats.conflicts > 0
                                            ? HF.warnInk
                                            : HF.ink3,
                                }}
                            >
                                {stats.conflicts > 0
                                    ? "need review"
                                    : "all clean"}
                            </span>
                        ) : null,
                    },
                ]}
            />

            <HFCard
                style={{ marginBottom: HF.gap, overflow: "visible" }}
                padding={12}
            >
                {(() => {
                    const activeCount = [
                        q !== "",
                        enrichedFilter !== "any",
                        conflictsFilter !== "any",
                        isbnFilter !== "any",
                        shopsFilter !== "any",
                        yearFilter !== "any",
                    ].filter(Boolean).length;
                    const clearAll = () => {
                        setQ("");
                        setEnrichedFilter("any");
                        setConflictsFilter("any");
                        setIsbnFilter("any");
                        setShopsFilter("any");
                        setYearFilter("any");
                        setPage(1);
                    };
                    return (
                        <HFFilterBar
                            right={
                                <>
                                    <span
                                        style={{
                                            fontSize: 11.5,
                                            color: activeCount
                                                ? HF.accentInk
                                                : HF.ink4,
                                            fontFamily: HF.mono,
                                            fontVariantNumeric: "tabular-nums",
                                            fontWeight: activeCount ? 500 : 400,
                                        }}
                                    >
                                        {loading
                                            ? "…"
                                            : `${filteredRows.length} of ${data.total.toLocaleString()}`}
                                    </span>
                                    {activeCount > 0 && (
                                        <HFButton
                                            size="sm"
                                            variant="subtle"
                                            onClick={clearAll}
                                        >
                                            Clear ({activeCount})
                                        </HFButton>
                                    )}
                                </>
                            }
                        >
                            <HFSearch
                                placeholder="Search title, author, ISBN…"
                                width={320}
                                value={q}
                                onChange={(v) => {
                                    setQ(v);
                                    setPage(1);
                                }}
                            />
                            <HFFilter
                                label="Shops"
                                value={shopsFilter}
                                options={[
                                    "any",
                                    "0 shops",
                                    "1+ shops",
                                    "1 shop only",
                                    "2-3 shops",
                                    "4+ shops",
                                ]}
                                onChange={(v) => {
                                    setShopsFilter(v);
                                    setPage(1);
                                }}
                                allLabel="any"
                            />
                            <HFFilter
                                label="Year"
                                value={yearFilter}
                                options={["any", ...availableYears.map(String)]}
                                onChange={(v) => {
                                    setYearFilter(v);
                                    setPage(1);
                                }}
                                allLabel="any"
                            />
                            <HFFilter
                                label="Enriched"
                                value={enrichedFilter}
                                options={["any", "enriched", "not enriched"]}
                                onChange={(v) => {
                                    setEnrichedFilter(v);
                                    setPage(1);
                                }}
                                allLabel="any"
                            />
                            <HFFilter
                                label="ISBN"
                                value={isbnFilter}
                                options={["any", "has ISBN", "missing ISBN"]}
                                onChange={(v) => {
                                    setIsbnFilter(v);
                                    setPage(1);
                                }}
                                allLabel="any"
                            />
                            <HFFilter
                                label="Conflicts"
                                value={conflictsFilter}
                                options={["any", "clean", "has conflicts"]}
                                onChange={(v) => {
                                    setConflictsFilter(v);
                                    setPage(1);
                                }}
                                allLabel="any"
                            />
                        </HFFilterBar>
                    );
                })()}
            </HFCard>

            <HFCard>
                {loading ? (
                    <HFEmptyState
                        title="Loading…"
                        sub="Fetching books from the catalog."
                    />
                ) : filteredRows.length === 0 ? (
                    <HFEmptyState
                        title="No books match these filters"
                        sub="Try clearing filters, or adjusting the search."
                        onClear={() => {
                            setQ("");
                            setEnrichedFilter("any");
                            setConflictsFilter("any");
                            setIsbnFilter("any");
                            setShopsFilter("any");
                            setYearFilter("any");
                            setPage(1);
                        }}
                    />
                ) : (
                    <HFTable
                        onRowClick={(r) => goto("book", { id: r.id })}
                        columns={[
                            {
                                key: "id",
                                label: "ID",
                                w: "0.5fr",
                                mono: true,
                                sortable: true,
                                sortVal: (r) => r.id,
                                cell: (v) => (
                                    <span
                                        style={{
                                            color: HF.accentInk,
                                            fontWeight: 500,
                                        }}
                                    >
                                        #{v}
                                    </span>
                                ),
                            },
                            {
                                key: "title",
                                label: "Title",
                                w: "2.4fr",
                                sortable: true,
                                cell: (v, r) => (
                                    <span
                                        style={{
                                            display: "flex",
                                            flexDirection: "column",
                                            gap: 2,
                                            minWidth: 0,
                                        }}
                                    >
                                        <span
                                            style={{
                                                display: "flex",
                                                alignItems: "center",
                                                gap: 8,
                                                minWidth: 0,
                                            }}
                                        >
                                            <span
                                                style={{
                                                    color: HF.ink,
                                                    fontWeight: 500,
                                                    overflow: "hidden",
                                                    textOverflow: "ellipsis",
                                                    whiteSpace: "nowrap",
                                                }}
                                            >
                                                {v}
                                            </span>
                                            {r.enriched && (
                                                <span
                                                    title="Enriched from ISBN DB"
                                                    style={{
                                                        fontFamily: HF.mono,
                                                        fontSize: 9.5,
                                                        fontWeight: 600,
                                                        letterSpacing: 0.4,
                                                        color: HF.accentInk,
                                                        background:
                                                            HF.accentSoft,
                                                        border: `1px solid ${HF.accentBorder}`,
                                                        borderRadius: 3,
                                                        padding: "0 5px",
                                                        lineHeight: 1.5,
                                                        flexShrink: 0,
                                                    }}
                                                >
                                                    ISBN-DB
                                                </span>
                                            )}
                                        </span>
                                        <span
                                            style={{
                                                color: HF.ink3,
                                                fontSize: 11.5,
                                                overflow: "hidden",
                                                textOverflow: "ellipsis",
                                                whiteSpace: "nowrap",
                                            }}
                                        >
                                            {r.author}
                                        </span>
                                    </span>
                                ),
                            },
                            {
                                key: "isbn",
                                label: "ISBN",
                                w: "1.1fr",
                                mono: true,
                                sortable: true,
                                cell: (v) =>
                                    v ? (
                                        <span style={{ color: HF.ink2 }}>
                                            {v}
                                        </span>
                                    ) : (
                                        <HFPill tone="warn">missing</HFPill>
                                    ),
                            },
                            {
                                key: "year",
                                label: "Year",
                                w: "0.55fr",
                                mono: true,
                                align: "right",
                                sortable: true,
                                cell: (v) =>
                                    v ? (
                                        <span style={{ color: HF.ink2 }}>
                                            {v}
                                        </span>
                                    ) : (
                                        <span style={{ color: HF.ink4 }}>
                                            —
                                        </span>
                                    ),
                            },
                            {
                                key: "shops",
                                label: "Shops",
                                w: "0.7fr",
                                mono: true,
                                align: "right",
                                sortable: true,
                                sortVal: (r) => r.shops,
                                cell: (v) => (
                                    <span
                                        style={{
                                            display: "inline-flex",
                                            alignItems: "center",
                                            gap: 6,
                                            fontVariantNumeric: "tabular-nums",
                                        }}
                                    >
                                        <span
                                            style={{
                                                color:
                                                    v >= 4
                                                        ? HF.okInk
                                                        : v >= 2
                                                          ? HF.ink2
                                                          : HF.warnInk,
                                                fontWeight: 500,
                                            }}
                                        >
                                            {v}
                                        </span>
                                        <span
                                            style={{
                                                color: HF.ink4,
                                                fontSize: 11,
                                            }}
                                        >
                                            shops
                                        </span>
                                    </span>
                                ),
                            },
                            {
                                key: "priceRange",
                                label: "Price range",
                                w: "1.2fr",
                                mono: true,
                                align: "right",
                                sortable: true,
                                sortVal: (r) => r.priceMin,
                                cell: (_, r) =>
                                    r.priceMin == null ? (
                                        <span style={{ color: HF.ink4 }}>
                                            —
                                        </span>
                                    ) : (
                                        <span
                                            style={{
                                                display: "inline-flex",
                                                alignItems: "baseline",
                                                gap: 6,
                                                fontVariantNumeric:
                                                    "tabular-nums",
                                            }}
                                        >
                                            <span
                                                style={{
                                                    color: HF.okInk,
                                                    fontWeight: 600,
                                                }}
                                            >
                                                €{r.priceMin.toFixed(2)}
                                            </span>
                                            <span style={{ color: HF.ink4 }}>
                                                —
                                            </span>
                                            <span style={{ color: HF.ink2 }}>
                                                €{r.priceMax.toFixed(2)}
                                            </span>
                                            {r.priceMax > r.priceMin && (
                                                <span
                                                    style={{
                                                        color: HF.ink4,
                                                        fontSize: 11,
                                                    }}
                                                >
                                                    (
                                                    {Math.round(
                                                        (r.priceMax /
                                                            r.priceMin -
                                                            1) *
                                                            100,
                                                    )}
                                                    %)
                                                </span>
                                            )}
                                        </span>
                                    ),
                            },
                            {
                                key: "conflicts",
                                label: "Conflicts",
                                w: "0.7fr",
                                mono: true,
                                align: "right",
                                sortable: true,
                                sortVal: (r) => r.conflicts,
                                cell: (v) =>
                                    v ? (
                                        <span
                                            style={{
                                                color: HF.errInk,
                                                fontWeight: 500,
                                                fontVariantNumeric:
                                                    "tabular-nums",
                                            }}
                                        >
                                            {v}
                                        </span>
                                    ) : (
                                        <span style={{ color: HF.ink4 }}>
                                            —
                                        </span>
                                    ),
                            },
                            {
                                key: "updated",
                                label: "Updated",
                                w: "0.8fr",
                                muted: true,
                                mono: true,
                                sortable: true,
                            },
                            {
                                key: "_",
                                label: "",
                                w: "28px",
                                align: "right",
                                cell: () => (
                                    <span
                                        style={{
                                            color: HF.ink4,
                                            display: "flex",
                                            justifyContent: "flex-end",
                                        }}
                                    >
                                        {HF_ICONS.chevron}
                                    </span>
                                ),
                            },
                        ]}
                        rows={filteredRows}
                    />
                )}
            </HFCard>

            {(() => {
                const totalPages = data.pages || 1;
                const perPage = 50;
                const start = (page - 1) * perPage + 1;
                const end = Math.min(page * perPage, data.total);
                const pageNums = [];
                const addPage = (n) => {
                    if (n >= 1 && n <= totalPages && !pageNums.includes(n))
                        pageNums.push(n);
                };
                addPage(1);
                addPage(page - 1);
                addPage(page);
                addPage(page + 1);
                addPage(totalPages);
                pageNums.sort((a, b) => a - b);
                const buttons = [];
                pageNums.forEach((n, i) => {
                    if (i > 0 && n > pageNums[i - 1] + 1) buttons.push("…");
                    buttons.push(n);
                });
                return (
                    <div
                        style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            marginTop: 14,
                            fontSize: 12.5,
                            color: HF.ink3,
                        }}
                    >
                        <span>
                            {loading
                                ? "…"
                                : `Showing ${start}–${end} of ${data.total.toLocaleString()}`}
                        </span>
                        <div style={{ display: "flex", gap: 6 }}>
                            <HFButton
                                size="sm"
                                variant="ghost"
                                onClick={() =>
                                    setPage((p) => Math.max(1, p - 1))
                                }
                                disabled={page <= 1}
                            >
                                ‹ Prev
                            </HFButton>
                            {buttons.map((b, i) =>
                                b === "…" ? (
                                    <span
                                        key={`ellipsis-${i}`}
                                        style={{
                                            padding: "6px 4px",
                                            color: HF.ink4,
                                        }}
                                    >
                                        …
                                    </span>
                                ) : (
                                    <HFButton
                                        key={b}
                                        size="sm"
                                        variant={
                                            b === page ? "accent" : undefined
                                        }
                                        onClick={() => setPage(b)}
                                    >
                                        {b}
                                    </HFButton>
                                ),
                            )}
                            <HFButton
                                size="sm"
                                onClick={() =>
                                    setPage((p) => Math.min(totalPages, p + 1))
                                }
                                disabled={page >= totalPages}
                            >
                                Next ›
                            </HFButton>
                        </div>
                    </div>
                );
            })()}
        </HFShell>
    );
}

Object.assign(window, { HFBooks });
