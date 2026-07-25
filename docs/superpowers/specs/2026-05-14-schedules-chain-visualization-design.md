# Schedules Chain Visualization — Design Spec

**Status:** Implemented
## Goal

Make chained cron jobs visually obvious in `HFCron`. Replace the flat "Chain" column with a tree-sorted table where chain children appear indented under their parent, a "Trigger" column distinguishes time-based vs chain-triggered jobs, and chain-triggered jobs show no "Next run" (they have no cron schedule of their own).

## Scope

- One file changed: `book_scraper/dashboard/static/hifi/hf-other.jsx`
- Frontend only — no backend, no API, no DB changes
- No new components — existing `HFTable`, `HFIcon`, `HFDot`, `HFButton`, tokens, etc.
- Design reference: `hifi/hf-other.jsx` in `Test design (1)/` folder (adapted for `chain_to_id` model)

## Non-Goals

- Chain-level bulk actions (enable/disable/run entire chain) — too much scope for this phase
- "on: success | any" trigger condition — not in DB schema
- Depth > 1 visual indentation — cap at 1 level (matches reference design)
- Backend/API changes

---

## Changes to `HFCron` in `hf-other.jsx`

### 1. Tree sort (replaces flat `jobs` array)

Build a `byParent` map: key = `chain_to_name` of children (i.e., name of the job whose completion triggers them), value = array of child jobs. Root jobs (no `chain_to_id`) key to `'__root__'`.

Recursive `visit('__root__', 0)` produces a flat ordered array with a `depth` field. Depth is capped at 1 visually. Orphaned chain rows (parent not in list) are appended at depth 0.

```js
const jobsFlat = (() => {
  const byParent = {};
  jobsRaw.forEach(j => {
    const parentKey = j.chain_to_id ? j.chain_to_name : '__root__';
    (byParent[parentKey] = byParent[parentKey] || []).push(j);
  });
  const out = [];
  const visit = (parent, depth) => {
    (byParent[parent] || []).forEach(j => {
      out.push({ ...j, depth: Math.min(depth, 1) });
      visit(j.name, depth + 1);
    });
  };
  visit('__root__', 0);
  jobsRaw.forEach(j => {
    if (!out.find(o => o.name === j.name)) out.push({ ...j, depth: 0 });
  });
  return out;
})();
```

### 2. Name column — SVG L-connector for depth > 0

When `r.depth > 0`, prepend an SVG curved L-connector (18×16px, `var(--hf-ink5)`) before the name text:

```jsx
{depth > 0 && (
  <span style={{ display:'inline-flex', alignItems:'center', marginRight:6, color:'var(--hf-ink5)', flexShrink:0 }}>
    <svg width="18" height="16" viewBox="0 0 18 16" fill="none">
      <path d="M5 0 V8 Q5 11 8 11 H16"
            stroke="var(--hf-ink5)" strokeWidth="1.25"
            strokeLinecap="round" fill="none"/>
    </svg>
  </span>
)}
```

### 3. Trigger column (replaces Chain column)

Two variants:

**Time-based** (`!j.chain_to_id`): small square badge with clock icon + monospace cron expression.

**Chain-triggered** (`j.chain_to_id`): small square badge with link/chain icon + "chain" label in `var(--hf-ink3)`.

Badge style: `18×18px`, `border-radius: 4px`. Time badge: `var(--hf-bg)` bg, `var(--hf-border-faint)` border. Chain badge: `var(--hf-accent-soft)` bg, `var(--hf-accent-border)` border, `var(--hf-accent-ink)` icon color.

Column definition:
```
{ key:'trigger', label:'Trigger', w:'1.4fr' }
```

### 4. Next run column

Chain-triggered jobs (`r.chain_to_id`): render `—` in `var(--hf-ink5)` (they have no cron, fire after parent).  
Time-based + disabled: render "disabled" in `var(--hf-ink4)`.  
Time-based + enabled: render value in `var(--hf-accent-ink)` bold.

### 5. Subtitle update

```
"Time-driven and chain-triggered scrape jobs. Disable, edit, or trigger manually."
```

### 6. Remove old Chain column

Delete `{ key:'chain_to_name', label:'Chain', ... }` column definition — superseded by tree sort + Trigger column.

### 7. Search field

Include `chain_to_name` in search fields so operators can search for "patogupirkti" and see the whole chain:

```js
search: { fields: j => `${j.name} ${j.cron || ''} ${j.shop} ${j.chain_to_name || ''}` }
```

---

## Result with real data (8 jobs, 1 chain)

```
Name                                Trigger               Shop          Last    Next
─────────────────────────────────────────────────────────────────────────────────────
vaga.discover.sitemap               🕐 0 2 * * *          vaga          ●ok     2h
vaga.scan.delta                     🕐 0 4 * * *          vaga          ●ok     4h
pegasas.discover.lupasearch         🕐 0 */6 * * *        pegasas       ●ok     1h
humanitas.discover.categories       🕐 0 2 * * 0          humanitas     ●ok     Sun
humanitas.scan.delta                🕐 0 4 * * 0          humanitas     ●ok     Sun
patogupirkti.discover.sitemap       🕐 0 2 * * *          patogupirkti  ●ok     2h
└─ patogupirkti.discover.categories  ⛓ chain             patogupirkti  ●ok     —
   └─ patogupirkti.scan.delta         ⛓ chain             patogupirkti  ●ok     —
```

---

## Testing

No new integration tests needed (no API change). Manual verification:
- Open `/cron` — patogupirkti jobs render indented under their parent in correct order
- Search "patogupirkti" — all 3 chain members appear
- Filter by shop → chain structure maintained within filtered set
- Sort by "Trigger" — time-based jobs sort before chain-triggered
- Standalone jobs unaffected
- Rebuild dashboard: `docker compose build dashboard && docker compose up -d dashboard`
