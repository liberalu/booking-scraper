# Dashboard Modern Redesign — Design Spec

## Overview

Refine the existing dark/glass admin dashboard without changing its layout structure or adding new features. The goal is sharper typography, tighter component polish, and a more premium feel — achieved through three targeted changes: a custom font, refined CSS design tokens, and component-level tweaks.

**Decisions made:**
- Layout: keep existing top nav (no sidebar migration)
- Style: refined glassmorphism — sharper, not replaced
- Font: DM Sans (Google Fonts)

---

## 1. Typography

Replace the system font stack (currently inherited from Pico CSS) with **DM Sans** loaded from Google Fonts.

**`base.html` changes:**
- Add `<link rel="preconnect" href="https://fonts.googleapis.com">` before the existing stylesheet links
- Add `<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800;1,9..40,400&display=swap" rel="stylesheet">`

**`dashboard.css` changes:**
- Add `font-family: 'DM Sans', system-ui, sans-serif;` to the `body` rule (Pico CSS sets its own font-family on `:root`; we override on `body`)
- Override Pico's `:root` font-family to use DM Sans as well so headings pick it up

---

## 2. Navigation

Slim the nav from 72px → 60px tall, and switch nav link active state from full pill (border-radius 999px) to a subtle rounded rectangle (border-radius 8px). This makes the nav feel modern and less chunky.

**Changes to `dashboard.css`:**
- `.top-nav-inner`: `min-height: 60px` (was 72px)
- `.nav-links li a`: `border-radius: 8px` (was 999px), `padding: 0 0.8rem`
- `.brand-mark`: `width: 30px; height: 30px; border-radius: 8px` (was 42px/14px) — scale down to match slimmer nav
- `.brand-name` font-size stays, `.brand-subtitle` stays

---

## 3. Accent Color

Shift the blue accent slightly toward indigo to feel more premium and less generic. This is a token-only change — all components that reference `--accent` update automatically.

| Token | Old value | New value |
|---|---|---|
| `--accent` (light) | `#215ec9` | `#3b5fe3` |
| `--accent` (dark) | `#7ea7ff` | `#6e8fef` |
| `--link` (light) | `#215ec9` | `#3b5fe3` |
| `--link-hover` (light) | `#173f88` | `#2442b0` |

All `--accent-soft`, `--accent-soft-strong`, `--badge-running-*`, `--input-focus` tokens derive their hue from the accent — update their rgba values to match the new hue.

---

## 4. Cards

Reduce border-radius slightly for a crisper look, and strengthen the inset highlight on the top edge.

**Changes to `dashboard.css`:**
- `.stat-card`, `.insight-card`: `border-radius: 16px` (was 20px); add `box-shadow: 0 4px 24px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.05)` in light and `0 4px 24px rgba(0,0,0,0.32), inset 0 1px 0 rgba(255,255,255,0.04)` in dark
- `.card`: `border-radius: 18px` (was 24px); same inset highlight tweak
- `.field-filter-card`: `border-radius: 14px` (was 18px)

---

## 5. Progress Bars

Slim from 8px → 6px height for a more refined look. Add color variants to indicate coverage quality:

| Variant | Class | Gradient | When to use |
|---|---|---|---|
| Default (accent) | `.progress-fill` | `--accent` → teal | general / medium |
| High | `.progress-fill.high` | green → cyan | ≥ 80% coverage |
| Medium | `.progress-fill.medium` | amber → orange | 40–79% |

Update the overview template to apply the correct class based on coverage:
- `high` when `item.pct >= 80`
- `medium` when `item.pct >= 40` and `item.pct < 80`
- default (no extra class) when `item.pct < 40`

**Changes to `dashboard.css`:**
- `.progress-track`: `height: 6px` (was 8px)
- Add `.progress-fill.high { background: linear-gradient(90deg, var(--success), #22d3ee); }`
- Add `.progress-fill.medium { background: linear-gradient(90deg, var(--warning), #f97316); }`

---

## 6. Validation Chips (Overview)

Change the `.validation-inline-item` chips from pill (border-radius 999px) to a softer rounded rectangle (border-radius 10px) to match the card style direction.

**Changes to `dashboard.css`:**
- `.validation-inline-item`: `border-radius: 10px` (was 999px)

---

## 7. Pico CSS Override

Pico CSS sets aggressive font-family and some color variables on `:root`. We need to ensure DM Sans wins everywhere — including inside Pico-managed form elements and tables.

Add to `dashboard.css` after the theme blocks:
```css
:root {
  --pico-font-family: 'DM Sans', system-ui, sans-serif;
}
```

This is the Pico v2 variable for overriding the font globally without fighting specificity.

---

## Scope

Changes are **CSS + one font `<link>` + one template tweak** (progress bar class logic in `overview.html`). No new routes, no JS changes, no database changes, no template restructuring. The existing dark/light theme toggle continues to work unchanged.

Files touched:
- `book_scraper/dashboard/templates/base.html` — add font links
- `book_scraper/dashboard/static/dashboard.css` — all style changes
- `book_scraper/dashboard/templates/overview.html` — progress fill class logic

---

## Out of Scope

- Sidebar navigation
- New pages or routes
- Chart.js visual changes
- Mobile layout changes beyond what the above tokens affect
