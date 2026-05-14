# Schedules Chain Visualization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat "Chain" column in HFCron with a tree-sorted table where chain children appear indented under their parent, with a "Trigger" column showing clock icon + cron for time-based jobs vs chain icon for chained jobs.

**Architecture:** Pure frontend change to `hf-other.jsx`. Pre-sort the `jobs` array by building a `byParent` map keyed on `chain_to_name`, then walk the tree recursively adding a `depth` field. The Name column renderer reads `depth` to prepend an SVG L-connector. A new Trigger column replaces the old Chain column. No API changes.

**Tech Stack:** React 18 (Babel CDN), existing HFTable/HFPill/HFDot/HFButton components, inline SVG path for connector.

**Spec:** `docs/superpowers/specs/2026-05-14-schedules-chain-visualization-design.md`

---

## File Structure

| File | Change |
|---|---|
| `book_scraper/dashboard/static/hifi/hf-other.jsx` | Modify HFCron: tree-sort, SVG connector in Name col, new Trigger col, Next run fix, subtitle update |

No new files. No backend changes.

---

## Task 1: Tree-sort `jobs` array with `depth` field

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-other.jsx` (inside `HFCron`, replace the current `jobs` mapping)

Current code (around line 37 in hf-other.jsx):
```js
const jobs = jobsRaw.map(j => ({
  ...j,
  state: j.enabled ? 'active' : 'disabled',
  lastStatus: j.last_status || 'ok',
  next: j.next || '—',
  avgDur: j.avg_dur || '—',
}));
```

- [ ] **Step 1: Replace the `jobs` mapping with tree-sort**

Replace the above block entirely with:

```jsx
const jobsFlat = (() => {
  // Build parent → children map.
  // A job is a child of another if its chain_to_name matches the parent's name.
  const byParent = {};
  jobsRaw.forEach(j => {
    const parentKey = j.chain_to_id ? (j.chain_to_name || '__orphan__') : '__root__';
    (byParent[parentKey] = byParent[parentKey] || []).push(j);
  });
  const out = [];
  // Recursive DFS: root jobs first, then their children, depth-capped at 1.
  const visit = (parent, depth) => {
    (byParent[parent] || []).forEach(j => {
      out.push({ ...j, depth: Math.min(depth, 1) });
      visit(j.name, depth + 1);
    });
  };
  visit('__root__', 0);
  // Orphaned chain rows (parent name not found) appended flat.
  jobsRaw.forEach(j => {
    if (!out.find(o => o.name === j.name)) out.push({ ...j, depth: 0 });
  });
  return out;
})();

const jobs = jobsFlat.map(j => ({
  ...j,
  state: j.enabled ? 'active' : 'disabled',
  lastStatus: j.last_status || 'ok',
  next: j.next || '—',
  avgDur: j.avg_dur || '—',
}));
```

- [ ] **Step 2: Rebuild and verify tree order in browser**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

Open `http://localhost:8000/cron`. Check:
- patogupirkti.discover.sitemap renders first (depth 0)
- patogupirkti.discover.categories appears directly below it (depth 1)
- patogupirkti.scan.delta appears below that (depth 1, capped from 2)
- vaga/pegasas/humanitas jobs remain in their original relative order

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-other.jsx
git commit -m "feat(dashboard): tree-sort cron jobs by chain depth"
```

---

## Task 2: SVG L-connector in Name column for depth > 0

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-other.jsx` (Name column `cell` function inside HFTable columns)

Current Name column definition:
```jsx
{ key:'name', label:'Name', w:'1.8fr', mono:true, sortable:true,
  cell:(v,r) => <span style={{color: r.enabled? 'var(--hf-ink)' : 'var(--hf-ink4)', fontWeight:500}}>{v}</span>
},
```

- [ ] **Step 1: Update Name column cell to show connector**

Replace the Name column `cell` function with:

```jsx
{ key:'name', label:'Name', w:'1.8fr', mono:true, sortable:true,
  cell:(v, r) => {
    const depth = r.depth || 0;
    return (
      <span style={{display:'inline-flex', alignItems:'center', minWidth:0}}>
        {depth > 0 && (
          <span style={{
            display:'inline-flex', alignItems:'center',
            marginRight:6, flexShrink:0, color:'var(--hf-ink5)',
          }}>
            <svg width="18" height="16" viewBox="0 0 18 16" fill="none" style={{flexShrink:0}}>
              <path d="M5 0 V8 Q5 11 8 11 H16"
                    stroke="var(--hf-ink5)"
                    strokeWidth="1.25"
                    strokeLinecap="round"
                    fill="none"/>
            </svg>
          </span>
        )}
        <span style={{
          color: r.enabled ? 'var(--hf-ink)' : 'var(--hf-ink4)',
          fontWeight:500,
          overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
        }}>{v}</span>
      </span>
    );
  }
},
```

- [ ] **Step 2: Rebuild and verify connector renders**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

Open `http://localhost:8000/cron`. Check:
- Chain children (patogupirkti.discover.categories, patogupirkti.scan.delta) have an L-shaped connector to their left.
- Standalone jobs (vaga, humanitas, etc.) have no connector.

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-other.jsx
git commit -m "feat(dashboard): SVG L-connector for chained schedule rows"
```

---

## Task 3: Replace Chain column with Trigger column + update subtitle

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-other.jsx` (HFTable columns + HFShell subtitle)

Current Chain column (remove this):
```jsx
{ key:'chain_to_name', label:'Chain', w:'1fr', cell:(v) =>
  v ? (
    <span style={{...}}>
      <span style={{opacity:0.5}}>→</span> {v}
    </span>
  ) : (
    <span style={{color:'var(--hf-ink5)', fontSize:12}}>—</span>
  )
},
```

- [ ] **Step 1: Delete Chain column, insert Trigger column in its place**

Remove the entire `chain_to_name` column object from the columns array.

Insert the following column at the same position (after the `shop` column, before `lastStatus`):

```jsx
{ key:'_trigger', label:'Trigger', w:'1.4fr',
  cell:(_, r) => {
    if (r.chain_to_id) {
      // Chain-triggered job: chain icon badge + "chain" label
      return (
        <span style={{display:'inline-flex', alignItems:'center', gap:6, minWidth:0}}>
          <span style={{
            display:'inline-flex', alignItems:'center', justifyContent:'center',
            width:18, height:18, borderRadius:4,
            background:'var(--hf-accent-soft)',
            border:'1px solid var(--hf-accent-border)',
            color:'var(--hf-accent-ink)', flexShrink:0,
          }}>
            {/* Link/chain SVG icon */}
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
              <path d="M6.5 9.5 L9.5 6.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
              <path d="M6 6 L4 8 Q2 10 4 12 Q6 14 8 12 L10 10"
                    stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
              <path d="M10 10 L12 8 Q14 6 12 4 Q10 2 8 4 L6 6"
                    stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" fill="none"/>
            </svg>
          </span>
          <span style={{fontSize:12, color:'var(--hf-ink3)'}}>chain</span>
        </span>
      );
    }
    // Time-triggered job: clock icon badge + cron expression
    return (
      <span style={{display:'inline-flex', alignItems:'center', gap:6, minWidth:0}}>
        <span style={{
          display:'inline-flex', alignItems:'center', justifyContent:'center',
          width:18, height:18, borderRadius:4,
          background:'var(--hf-bg)',
          border:'1px solid var(--hf-border-faint)',
          color:'var(--hf-ink3)', flexShrink:0,
        }}>
          {/* Clock SVG icon */}
          <svg width="11" height="11" viewBox="0 0 16 16" fill="none">
            <circle cx="8" cy="8" r="5.5" stroke="currentColor" strokeWidth="1.6"/>
            <path d="M8 5.5 V8 L10 9.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
          </svg>
        </span>
        <span style={{
          fontFamily:'var(--hf-mono)', color:'var(--hf-ink2)',
          fontSize:12, fontVariantNumeric:'tabular-nums',
          overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap',
        }}>{r.cron || '—'}</span>
      </span>
    );
  }
},
```

- [ ] **Step 2: Update HFShell subtitle**

Find the current subtitle in `HFCron`:
```jsx
subtitle="Cron-driven scrape jobs. Disable, edit, or trigger manually."
```

Replace with:
```jsx
subtitle="Time-driven and chain-triggered scrape jobs. Disable, edit, or trigger manually."
```

- [ ] **Step 3: Update search fields to include chain_to_name**

Find the `search` entry in the `useHFFilters` call:
```js
search: { fields: j => `${j.name} ${j.cron} ${j.shop}` },
```

Replace with:
```js
search: { fields: j => `${j.name} ${j.cron || ''} ${j.shop} ${j.chain_to_name || ''}` },
```

- [ ] **Step 4: Rebuild and verify**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

Open `http://localhost:8000/cron`. Check:
- Time-based jobs: clock icon badge + monospace cron expression in Trigger column.
- Chain children: chain icon badge + "chain" label in Trigger column.
- Old Chain column with `→ name` is gone.
- Subtitle updated.
- Searching "patogupirkti" finds all 3 chain members.

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-other.jsx
git commit -m "feat(dashboard): Trigger column + subtitle — chain visualization complete"
```

---

## Task 4: Fix Next run column for chain-triggered jobs

**Files:**
- Modify: `book_scraper/dashboard/static/hifi/hf-other.jsx` (Next run column cell)

Current Next run column:
```jsx
{ key:'next', label:'Next run', w:'0.8fr', mono:true, sortable:true,
  cell:(v,r) => <span style={{color: r.enabled? 'var(--hf-accent-ink)' : 'var(--hf-ink4)', fontWeight:500}}>
    {r.enabled? v : 'disabled'}
  </span>
},
```

- [ ] **Step 1: Update Next run cell**

Replace with:
```jsx
{ key:'next', label:'Next run', w:'0.8fr', mono:true, sortable:true,
  cell:(v, r) => {
    if (!r.enabled) return <span style={{color:'var(--hf-ink4)', fontWeight:500}}>disabled</span>;
    if (r.chain_to_id) return <span style={{color:'var(--hf-ink5)'}}>—</span>;
    return <span style={{color:'var(--hf-accent-ink)', fontWeight:500}}>{v}</span>;
  }
},
```

- [ ] **Step 2: Rebuild and verify**

```bash
docker compose build dashboard && docker compose up -d dashboard
```

Open `http://localhost:8000/cron`. Check:
- patogupirkti.discover.categories and patogupirkti.scan.delta show "—" in Next run (they have no cron).
- patogupirkti.discover.sitemap still shows its next run time.

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/static/hifi/hf-other.jsx
git commit -m "fix(dashboard): chain jobs show — in Next run (no cron schedule)"
```

---

## Notes for the implementer

- **Docker BuildKit cache gotcha:** if changes don't appear after rebuild, confirm with `docker exec book-scraper-dashboard-1 grep -c 'chain_to_id' /app/book_scraper/dashboard/static/hifi/hf-other.jsx`. If 0, rebuild with `--no-cache`.
- **Real data shape:** `/api/cron` returns `{ id, name, cron, shop, chain_to_id, chain_to_name, ... }` per job. `chain_to_id` is `null` for time-based jobs, integer for chain-triggered.
- **No backend changes needed** — all data already in the API response.
- **Depth cap:** depth is capped at 1 (`Math.min(depth, 1)`). If patogupirkti ever adds a 4th job chaining off scan.delta, it will still render indented at depth 1 (same visual level as categories and scan).
