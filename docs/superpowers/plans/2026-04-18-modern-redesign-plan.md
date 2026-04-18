# Dashboard Modern Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine the existing dashboard with DM Sans font, indigo-shifted accent tokens, slimmer nav, crisper card radii, color-coded progress bars, and rounded validation chips.

**Architecture:** Pure CSS + one `<link>` tag + one Jinja template tweak. No new routes, no JS, no schema changes. Three files touched total.

**Tech Stack:** Pico CSS v2 (override via `--pico-font-family`), DM Sans (Google Fonts CDN), Jinja2 templates, FastAPI dashboard served via Docker.

---

## Task 1: Add DM Sans font

**Files:**
- Modify: `book_scraper/dashboard/templates/base.html`
- Modify: `book_scraper/dashboard/static/dashboard.css`

- [ ] **Step 1: Add font preconnect and stylesheet link to base.html**

In `book_scraper/dashboard/templates/base.html`, add these two lines immediately before the existing `<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">` line:

```html
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800;1,9..40,400&display=swap" rel="stylesheet">
```

- [ ] **Step 2: Override Pico's font-family in dashboard.css**

In `book_scraper/dashboard/static/dashboard.css`, add a new block after the closing `}` of the `[data-theme="dark"]` block (around line 118, before the `html, body` rule):

```css
:root {
    --pico-font-family: 'DM Sans', system-ui, sans-serif;
}
```

- [ ] **Step 3: Set font-family on body**

In `dashboard.css`, find the `body {` rule (around line 124) and add `font-family: 'DM Sans', system-ui, sans-serif;` inside it:

```css
body {
    margin: 0;
    font-family: 'DM Sans', system-ui, sans-serif;
    color: var(--text-primary);
    background:
        radial-gradient(circle at top left, var(--page-bg-accent), transparent 34%),
        radial-gradient(circle at top right, var(--page-bg-accent-2), transparent 28%),
        var(--page-bg);
}
```

- [ ] **Step 4: Commit**

```bash
git add book_scraper/dashboard/templates/base.html book_scraper/dashboard/static/dashboard.css
git commit -m "style: add DM Sans font via Google Fonts CDN"
```

---

## Task 2: Slim the navigation bar

**Files:**
- Modify: `book_scraper/dashboard/static/dashboard.css`

- [ ] **Step 1: Reduce nav height to 60px**

Find `.top-nav-inner {` in `dashboard.css` (around line 207). Change `min-height: 72px` → `min-height: 60px`:

```css
.top-nav-inner {
    max-width: min(1320px, calc(100vw - 2rem));
    margin: 0 auto;
    min-height: 60px;
    display: flex;
    align-items: center;
    gap: 1rem;
}
```

- [ ] **Step 2: Scale down brand mark**

Find `.brand-mark {` (around line 229). Change `width: 42px`, `height: 42px`, and `border-radius: 14px` to:

```css
.brand-mark {
    width: 30px;
    height: 30px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 8px;
    background: linear-gradient(135deg, var(--accent-soft-strong), rgba(20, 184, 166, 0.16));
    color: var(--accent);
    font-size: 0.9rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    border: 1px solid var(--border);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
}
```

- [ ] **Step 3: Switch nav link active state to rounded rectangle**

Find `.nav-links li a {` (around line 279). Change `border-radius: 999px` → `border-radius: 8px` and `padding: 0 0.9rem` → `padding: 0 0.8rem`:

```css
.nav-links li a {
    display: inline-flex;
    align-items: center;
    min-height: 42px;
    padding: 0 0.8rem;
    border-radius: 8px;
    color: var(--text-secondary);
    font-size: 0.86rem;
    font-weight: 600;
    white-space: nowrap;
    transition: background 0.16s ease, color 0.16s ease, box-shadow 0.16s ease;
}
```

Also update `.nav-links li a:hover {` to match the new radius — it only sets `background` and `color` so no radius change needed there.

- [ ] **Step 4: Update mobile breakpoint for nav height**

Find the `@media (max-width: 1024px)` block (around line 1177). Change `min-height: 64px` → `min-height: 56px`:

```css
@media (max-width: 1024px) {
    .top-nav-inner {
        min-height: 56px;
    }
    /* rest unchanged */
}
```

- [ ] **Step 5: Commit**

```bash
git add book_scraper/dashboard/static/dashboard.css
git commit -m "style: slim nav to 60px, switch link active state to rounded rect"
```

---

## Task 3: Update accent color tokens

**Files:**
- Modify: `book_scraper/dashboard/static/dashboard.css`

- [ ] **Step 1: Update light theme accent tokens**

In the `[data-theme="light"]` block, replace the accent/link/badge-running tokens. Find each line and update:

| Find | Replace |
|------|---------|
| `--link: #215ec9;` | `--link: #3b5fe3;` |
| `--link-hover: #173f88;` | `--link-hover: #2442b0;` |
| `--accent: #215ec9;` | `--accent: #3b5fe3;` |
| `--accent-soft: rgba(33, 94, 201, 0.12);` | `--accent-soft: rgba(59, 95, 227, 0.12);` |
| `--accent-soft-strong: rgba(33, 94, 201, 0.18);` | `--accent-soft-strong: rgba(59, 95, 227, 0.18);` |
| `--input-focus: rgba(33, 94, 201, 0.45);` | `--input-focus: rgba(59, 95, 227, 0.45);` |
| `--badge-running-bg: rgba(59, 130, 246, 0.14);` | `--badge-running-bg: rgba(59, 95, 227, 0.14);` |
| `--badge-running-fg: #215ec9;` | `--badge-running-fg: #3b5fe3;` |

- [ ] **Step 2: Update dark theme accent tokens**

In the `[data-theme="dark"]` block, update:

| Find | Replace |
|------|---------|
| `--accent: #7ea7ff;` | `--accent: #6e8fef;` |
| `--accent-soft: rgba(126, 167, 255, 0.16);` | `--accent-soft: rgba(110, 143, 239, 0.16);` |
| `--accent-soft-strong: rgba(126, 167, 255, 0.25);` | `--accent-soft-strong: rgba(110, 143, 239, 0.25);` |
| `--input-focus: rgba(138, 180, 255, 0.48);` | `--input-focus: rgba(110, 143, 239, 0.48);` |
| `--badge-running-bg: rgba(96, 165, 250, 0.14);` | `--badge-running-bg: rgba(110, 143, 239, 0.14);` |
| `--badge-running-fg: #8ab4ff;` | `--badge-running-fg: #6e8fef;` |

- [ ] **Step 3: Commit**

```bash
git add book_scraper/dashboard/static/dashboard.css
git commit -m "style: shift accent color to indigo (#3b5fe3 light, #6e8fef dark)"
```

---

## Task 4: Refine card border-radius and shadow

**Files:**
- Modify: `book_scraper/dashboard/static/dashboard.css`

- [ ] **Step 1: Update stat-card and insight-card**

Find `.stat-card, .insight-card {` (around line 397). Change `border-radius: 20px` → `border-radius: 16px` and add inset highlight to the `box-shadow`. The full rule should be:

```css
.stat-card,
.insight-card {
    display: block;
    position: relative;
    overflow: hidden;
    padding: 1.2rem 1.1rem;
    border-radius: 16px;
    border: 1px solid var(--border);
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.06), transparent), var(--card-bg);
    box-shadow: var(--shadow-sm), inset 0 1px 0 rgba(255, 255, 255, 0.05);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
}
```

- [ ] **Step 2: Update .card**

Find `.card {` (around line 458). Change `border-radius: 24px` → `border-radius: 18px` and add the same inset highlight:

```css
.card {
    background: linear-gradient(180deg, rgba(255, 255, 255, 0.04), transparent), var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 18px;
    padding: 1.35rem;
    margin-bottom: 1.5rem;
    box-shadow: var(--shadow-sm), inset 0 1px 0 rgba(255, 255, 255, 0.04);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
}
```

- [ ] **Step 3: Update .field-filter-card**

Find `.field-filter-card {` (around line 662). Change `border-radius: 18px` → `border-radius: 14px`:

```css
.field-filter-card {
    padding: 0.9rem;
    border-radius: 14px;
    border: 1px solid var(--border);
    background: var(--card-muted);
}
```

- [ ] **Step 4: Commit**

```bash
git add book_scraper/dashboard/static/dashboard.css
git commit -m "style: reduce card border-radius, add inset edge highlight"
```

---

## Task 5: Progress bars — slim height and color-coded variants

**Files:**
- Modify: `book_scraper/dashboard/static/dashboard.css`
- Modify: `book_scraper/dashboard/templates/overview.html`

- [ ] **Step 1: Slim progress track to 6px**

Find `.progress-track {` (around line 933). Change `height: 8px` → `height: 6px`:

```css
.progress-track {
    position: relative;
    flex: 1;
    height: 6px;
    border-radius: 999px;
    overflow: hidden;
    background: var(--neutral-soft);
}
```

- [ ] **Step 2: Add .high and .medium progress fill variants**

After the existing `.progress-fill.success`, `.progress-fill.warning`, `.progress-fill.error` rules (around line 948–959), add:

```css
.progress-fill.high {
    background: linear-gradient(90deg, var(--success), #22d3ee);
}

.progress-fill.medium {
    background: linear-gradient(90deg, var(--warning), #f97316);
}
```

- [ ] **Step 3: Apply color-coded classes in the overview template**

In `book_scraper/dashboard/templates/overview.html`, find the progress fill line inside the `{% for item in completeness %}` loop:

```html
                <div class="progress-fill" style="width: {{ item.pct }}%"></div>
```

Replace it with:

```html
                <div class="progress-fill{% if item.pct >= 80 %} high{% elif item.pct >= 40 %} medium{% endif %}" style="width: {{ item.pct }}%"></div>
```

- [ ] **Step 4: Commit**

```bash
git add book_scraper/dashboard/static/dashboard.css book_scraper/dashboard/templates/overview.html
git commit -m "style: slim progress bars to 6px, add color-coded high/medium variants"
```

---

## Task 6: Validation chips — rounded rectangle

**Files:**
- Modify: `book_scraper/dashboard/static/dashboard.css`

- [ ] **Step 1: Change chip border-radius to 10px**

Find `.validation-inline-item {` (around line 968). Change `border-radius: 999px` → `border-radius: 10px`:

```css
.validation-inline-item {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.45rem 0.7rem;
    border-radius: 10px;
    background: var(--card-muted);
    color: var(--text-primary);
    font-size: 0.82rem;
}
```

- [ ] **Step 2: Commit**

```bash
git add book_scraper/dashboard/static/dashboard.css
git commit -m "style: switch validation chips from pill to rounded rect (10px)"
```

---

## Task 7: Deploy and smoke test

- [ ] **Step 1: Rebuild dashboard Docker image**

```bash
docker compose build dashboard
```

Expected: build completes with no errors.

- [ ] **Step 2: Restart dashboard container**

```bash
docker compose up -d dashboard
```

Expected: container starts, no errors in `docker compose logs dashboard`.

- [ ] **Step 3: Run smoke tests**

```bash
uv run pytest tests/integration/test_dashboard_routes.py -v
```

Expected: all tests pass (green).

- [ ] **Step 4: Visual check in browser**

Open `http://localhost:8000` in a browser. Verify:
- DM Sans font is loading (check Network tab — should see fonts.googleapis.com request)
- Nav is visibly slimmer, nav link active state is a rounded rectangle not a pill
- Stat cards have slightly smaller radius and a subtle top-edge highlight
- Overview progress bars are thinner (6px) with green/amber/blue color coding
- Validation chips (if any issues exist) are rounded rectangles, not pills
- Light/dark toggle still works

---

## File Summary

| File | Changes |
|------|---------|
| `book_scraper/dashboard/templates/base.html` | Add 2 font `<link>` tags |
| `book_scraper/dashboard/static/dashboard.css` | Font override, nav dims, accent tokens, card radii + shadows, progress height + variants, chip radius |
| `book_scraper/dashboard/templates/overview.html` | Add conditional class to progress fill |
