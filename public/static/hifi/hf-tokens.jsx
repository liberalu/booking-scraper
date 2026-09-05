const HF_ACCENTS = {
    teal: {
        50: "#ecfeff",
        100: "#cffafe",
        200: "#a5f3fc",
        400: "#22d3ee",
        500: "#0ea5a4",
        600: "#0891b2",
        700: "#0e7490",
    },
    violet: {
        50: "#f5f3ff",
        100: "#ede9fe",
        200: "#ddd6fe",
        400: "#a78bfa",
        500: "#7c3aed",
        600: "#6d28d9",
        700: "#5b21b6",
    },
    amber: {
        50: "#fffbeb",
        100: "#fef3c7",
        200: "#fde68a",
        400: "#fbbf24",
        500: "#d97706",
        600: "#b45309",
        700: "#92400e",
    },
    slate: {
        50: "#f8fafc",
        100: "#f1f5f9",
        200: "#e2e8f0",
        400: "#94a3b8",
        500: "#475569",
        600: "#334155",
        700: "#1e293b",
    },
    copper: {
        50: "#fdf4ef",
        100: "#fae6d9",
        200: "#f3c7a8",
        400: "#d97c3f",
        500: "#b45e2b",
        600: "#8f4920",
        700: "#6b3518",
    },
    indigo: {
        50: "#eef2ff",
        100: "#e0e7ff",
        200: "#c7d2fe",
        400: "#818cf8",
        500: "#4f46e5",
        600: "#4338ca",
        700: "#3730a3",
    },
    forest: {
        50: "#f0f7f2",
        100: "#dcebe0",
        200: "#b8d6c1",
        400: "#5a9a72",
        500: "#2f7a4d",
        600: "#256239",
        700: "#1c4a2b",
    },
};

const HF_DENSITIES = {
    comfortable: {
        rowH: 40,
        cellY: 10,
        cardP: 16,
        cardHeadY: 14,
        kpiP: 16,
        gap: 16,
        fsBody: 14,
        fsSmall: 12,
        fsKpi: 26,
        fsMono: 13,
    },
    compact: {
        rowH: 34,
        cellY: 8,
        cardP: 14,
        cardHeadY: 12,
        kpiP: 14,
        gap: 14,
        fsBody: 13,
        fsSmall: 12,
        fsKpi: 24,
        fsMono: 12,
    },
    ultra: {
        rowH: 28,
        cellY: 6,
        cardP: 12,
        cardHeadY: 10,
        kpiP: 12,
        gap: 12,
        fsBody: 12,
        fsSmall: 11,
        fsKpi: 22,
        fsMono: 12,
    },
};

function _hfPublish(a, d) {
    if (typeof document === "undefined" || !document.documentElement) return;
    const r = document.documentElement.style;
    r.setProperty("--hf-bg", "#f7f8fa");
    r.setProperty("--hf-surface", "#ffffff");
    r.setProperty("--hf-sidebar", "#fbfcfd");
    r.setProperty("--hf-raised", "#ffffff");
    r.setProperty("--hf-subtle", "#f3f4f7");
    r.setProperty("--hf-hover", "#f5f6f9");
    r.setProperty("--hf-input", "#ffffff");
    r.setProperty("--hf-border", "#e5e7ec");
    r.setProperty("--hf-border-strong", "#d4d7de");
    r.setProperty("--hf-border-faint", "#eef0f4");
    r.setProperty("--hf-ink", "#111827");
    r.setProperty("--hf-ink2", "#374151");
    r.setProperty("--hf-ink3", "#6b7280");
    r.setProperty("--hf-ink4", "#9ca3af");
    r.setProperty("--hf-ink5", "#c7cbd3");
    r.setProperty("--hf-accent", a[500]);
    r.setProperty("--hf-accent-hover", a[600]);
    r.setProperty("--hf-accent-soft", a[50]);
    r.setProperty("--hf-accent-soft2", a[100]);
    r.setProperty("--hf-accent-border", a[200]);
    r.setProperty("--hf-accent-ink", a[700]);
    r.setProperty("--hf-ok", "#16a34a");
    r.setProperty("--hf-ok-soft", "#f0fdf4");
    r.setProperty("--hf-ok-border", "#bbf7d0");
    r.setProperty("--hf-ok-ink", "#15803d");
    r.setProperty("--hf-warn", "#ca8a04");
    r.setProperty("--hf-warn-soft", "#fefce8");
    r.setProperty("--hf-warn-border", "#fde68a");
    r.setProperty("--hf-warn-ink", "#a16207");
    r.setProperty("--hf-err", "#dc2626");
    r.setProperty("--hf-err-soft", "#fef2f2");
    r.setProperty("--hf-err-border", "#fecaca");
    r.setProperty("--hf-err-ink", "#b91c1c");
    r.setProperty("--hf-shadow-sm", "0 1px 2px rgba(16,24,40,.08)");
    r.setProperty(
        "--hf-shadow",
        "0 1px 2px rgba(16,24,40,.05), 0 1px 3px rgba(16,24,40,.06)",
    );
    r.setProperty(
        "--hf-shadow-md",
        "0 4px 8px -2px rgba(16,24,40,.06), 0 2px 4px -2px rgba(16,24,40,.04)",
    );
    r.setProperty("--hf-shadow-lg", "0 8px 24px rgba(16,24,40,.12)");
    r.setProperty("--hf-row-h", `${d.rowH}px`);
    r.setProperty("--hf-cell-y", `${d.cellY}px`);
    r.setProperty("--hf-card-p", `${d.cardP}px`);
    r.setProperty("--hf-card-head-y", `${d.cardHeadY}px`);
    r.setProperty("--hf-kpi-p", `${d.kpiP}px`);
    r.setProperty("--hf-gap", `${d.gap}px`);
    r.setProperty("--hf-fs-body", `${d.fsBody}px`);
    r.setProperty("--hf-fs-small", `${d.fsSmall}px`);
    r.setProperty("--hf-fs-kpi", `${d.fsKpi}px`);
    r.setProperty("--hf-fs-mono", `${d.fsMono}px`);
    r.setProperty("--hf-content-x", "28px");
    r.setProperty("--hf-chart-primary", a[500]);
    r.setProperty("--hf-chart-fill-from", a[200]);
    r.setProperty("--hf-chart-fill-to", a[50]);
    r.setProperty("--hf-chart-grid", "#eef0f4");
    r.setProperty("--hf-chart-axis", "#9ca3af");
    r.setProperty(
        "--hf-sans",
        '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    );
    r.setProperty(
        "--hf-mono",
        '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace',
    );
    r.setProperty("--hf-r1", "4px");
    r.setProperty("--hf-r2", "6px");
    r.setProperty("--hf-r3", "8px");
    r.setProperty("--hf-r4", "10px");
    r.setProperty("--hf-r5", "12px");
}

function getHF() {
    const accentKey = window.HF_ACCENT || "teal";
    const densityKey = window.HF_DENSITY || "comfortable";
    const a = HF_ACCENTS[accentKey] || HF_ACCENTS.teal;
    const d = HF_DENSITIES[densityKey] || HF_DENSITIES.comfortable;

    _hfPublish(a, d);

    return {
        bg: "#f7f8fa",
        surface: "#ffffff",
        sidebar: "#fbfcfd",
        raised: "#ffffff",
        subtle: "#f3f4f7",
        hover: "#f5f6f9",
        input: "#ffffff",

        border: "#e5e7ec",
        borderStrong: "#d4d7de",
        borderFaint: "#eef0f4",

        ink: "#111827",
        ink2: "#374151",
        ink3: "#6b7280",
        ink4: "#9ca3af",
        ink5: "#c7cbd3",

        accent: a[500],
        accentHover: a[600],
        accentSoft: a[50],
        accentSoft2: a[100],
        accentBorder: a[200],
        accentInk: a[700],

        ok: "#16a34a",
        okSoft: "#f0fdf4",
        okBorder: "#bbf7d0",
        okInk: "#15803d",
        warn: "#ca8a04",
        warnSoft: "#fefce8",
        warnBorder: "#fde68a",
        warnInk: "#a16207",
        err: "#dc2626",
        errSoft: "#fef2f2",
        errBorder: "#fecaca",
        errInk: "#b91c1c",
        info: a[500],
        infoSoft: a[50],

        chartPrimary: a[500],
        chartFillFrom: a[200],
        chartFillTo: a[50],
        chartGrid: "#eef0f4",
        chartAxis: "#9ca3af",

        shadowSm: "0 1px 2px rgba(16,24,40,.08)",
        shadow: "0 1px 2px rgba(16,24,40,.05), 0 1px 3px rgba(16,24,40,.06)",
        shadowMd:
            "0 4px 8px -2px rgba(16,24,40,.06), 0 2px 4px -2px rgba(16,24,40,.04)",
        shadowLg: "0 8px 24px rgba(16,24,40,.12)",

        r1: 4,
        r2: 6,
        r3: 8,
        r4: 10,
        r5: 12,

        contentX: 28,

        sans: '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        mono: '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace',

        rowH: d.rowH,
        cellY: d.cellY,
        cardP: d.cardP,
        cardHeadY: d.cardHeadY,
        kpiP: d.kpiP,
        gap: d.gap,
        fsBody: d.fsBody,
        fsSmall: d.fsSmall,
        fsKpi: d.fsKpi,
        fsMono: d.fsMono,
        density: densityKey,
        accentKey,
    };
}

(function () {
    if (document.getElementById("hf-base")) return;
    const s = document.createElement("style");
    s.id = "hf-base";
    s.textContent = `
    @keyframes hfPulse { 0% { transform: scale(1); opacity: .35 } 100% { transform: scale(2.4); opacity: 0 } }
    @keyframes hfSweep { 0% { transform: translateX(-100%) } 100% { transform: translateX(250%) } }
    @keyframes hfShimmer { 0% { background-position: 200% 0 } 100% { background-position: -200% 0 } }
    .hf-scroll::-webkit-scrollbar { width: 10px; height: 10px }
    .hf-scroll::-webkit-scrollbar-track { background: transparent }
    .hf-scroll::-webkit-scrollbar-thumb { background: #d4d7de; border-radius: 5px; border: 2px solid transparent; background-clip: padding-box }
    .hf-scroll::-webkit-scrollbar-thumb:hover { background: #b8bdc7; background-clip: padding-box; border: 2px solid transparent }
    .hf-row:hover { background: #f5f6f9 !important }
    .hf-navlink:hover { background: #f1f2f5 !important }
    .hf-btn:hover { border-color: #c7cbd3 !important }
    .hf-btn-primary:hover { filter: brightness(0.95) }
    .hf-link { color: inherit; text-decoration: none }
    .hf-link:hover { text-decoration: underline; text-underline-offset: 2px }
    .hf-focus:focus-visible,
    .hf-btn:focus-visible,
    .hf-navlink:focus-visible,
    .hf-row:focus-visible,
    .hf-link:focus-visible,
    [role="menuitem"]:focus-visible,
    [role="menuitemradio"]:focus-visible {
      outline: 2px solid var(--hf-accent, #2f7a4d);
      outline-offset: 2px;
      border-radius: 6px;
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
      }
    }
  `;
    document.head.appendChild(s);
})();

window.getHF = getHF;
window.HF_ACCENTS = HF_ACCENTS;
window.HF_DENSITIES = HF_DENSITIES;
