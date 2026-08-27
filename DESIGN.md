# DESIGN.md — Agent Fleet Control Panel

## Changelog

| Version | Date       | Summary                                                                                         | Author           |
| ------- | ---------- | ----------------------------------------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-08-26 | Initial version. Extracted from high-fidelity prototype at `/docs/prototype/` (Nocturne DS). Documents design system, tokens, component inventory, layout architecture, screen specifications, interaction patterns, and formatting conventions. | product-engineer |

---

## 1. Design System — Nocturne

The panel uses **Nocturne**, a dark, compact design system. The prototype lives at `docs/prototype/` and is the visual source of truth. This document codifies what the prototype shows so a developer can reproduce it in React/Next.js without re-reading raw HTML.

### 1.1 Philosophy

- **Dark ground, low chroma.** The background is near-neutral blue-grey. Color comes from tonal ramps, not saturation. The accent is a blurple used as a line and a glow — never flooded over large areas.
- **Dense on purpose.** The 0.7x spacing scale makes the UI compact. Hierarchy comes from size and whitespace, not bold weight or color floods.
- **Outlined, not filled.** Primary buttons are accent-bordered on transparent, not solid-filled.
- **Rules fade.** Horizontal rules fade to transparent at both ends over 48px (a Nocturne signature).
- **Monospace for data.** Timestamps, IDs, slugs, durations, counts, and code use monospace. UI labels, headings, and descriptions use the body font.

### 1.2 Font Loading

```html
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap">
```

Monospace uses the system stack: `ui-monospace, Menlo, monospace`. No custom monospace font is loaded.

---

## 2. Design Tokens

All values come from CSS custom properties on `:root`. Implementation MUST use these tokens — never hardcode hex values, font names, or pixel spacing.

### 2.1 Colors — Core

| Token | Value | Usage |
|-------|-------|-------|
| `--color-bg` | `#161826` | Page/app background |
| `--color-surface` | `#232532` | Cards, input fields, raised surfaces |
| `--color-text` | `#e9e9ed` | Primary text color |
| `--color-accent` | `#9184d9` | Primary accent (blurple) — buttons, links, active states |
| `--color-divider` | `color-mix(in srgb, #e9e9ed 16%, transparent)` | Borders, rules, separators |

### 2.2 Colors — Neutral Ramp (100-900)

| Token | Value | Usage |
|-------|-------|-------|
| `--color-neutral-100` | `#f3f5fe` | Text on dark tints |
| `--color-neutral-200` | `#e4e7f5` | |
| `--color-neutral-300` | `#cfd3e5` | |
| `--color-neutral-400` | `#b2b6ca` | |
| `--color-neutral-500` | `#9397ab` | |
| `--color-neutral-600` | `#75798c` | |
| `--color-neutral-700` | `#595d6c` | |
| `--color-neutral-800` | `#3f424d` | Tag backgrounds, hovers |
| `--color-neutral-900` | `#292b31` | |

### 2.3 Colors — Accent Ramp (100-900)

| Token | Value | Usage |
|-------|-------|-------|
| `--color-accent-100` | `#f5f4ff` | |
| `--color-accent-200` | `#e7e5fe` | |
| `--color-accent-300` | `#d2cefd` | Running status text, repo names, link hover |
| `--color-accent-400` | `#b5abfc` | Slug text, link hover |
| `--color-accent-500` | `#968ae0` | |
| `--color-accent-600` | `#796cbf` | |
| `--color-accent-700` | `#5d5294` | |
| `--color-accent-800` | `#423a6a` | Tag fills |
| `--color-accent-900` | `#2b2741` | |

### 2.4 Colors — Status (App-Level Tokens)

These are NOT in the Nocturne DS stylesheet — defined per-page in the prototype, must be added to the app's global CSS.

| Token | Value | Maps to |
|-------|-------|---------|
| `--st-ok` | `#74b58f` | `succeeded` |
| `--st-fail` | `#d1706b` | `failed` |
| `--st-timeout` | `#d1a45e` | `timed_out` |
| (accent) | `#9184d9` | `running` |
| (muted) | 38% text | `failed_to_start` |

### 2.5 Colors — Utility Aliases

| Token | Value | Usage |
|-------|-------|-------|
| `--rule` | `var(--color-divider)` | Shorthand for borders |
| `--muted` | `color-mix(in srgb, var(--color-text) 55%, transparent)` | Secondary text |
| `--faint` | `color-mix(in srgb, var(--color-text) 38%, transparent)` | Tertiary/disabled text |

### 2.6 Typography

| Token | Value |
|-------|-------|
| `--font-heading` | `"Inter", system-ui, sans-serif` |
| `--font-heading-weight` | `500` |
| `--font-body` | `"Inter", system-ui, sans-serif` |
| `--mono` | `ui-monospace, Menlo, monospace` |

**Type scale (from DS):**

| Element | Size | Weight | Line-height | Letter-spacing |
|---------|------|--------|-------------|----------------|
| h1 | 42px | 500 | 1.12 | -0.015em |
| h2 | 32px | 500 | 1.12 | -0.015em |
| h3 | 25px | 500 | 1.12 | -0.015em |
| h4 | 20px | 500 | 1.12 | -0.015em |
| h5 | 16px | 500 | 1.12 | -0.015em |
| h6 | 13px | 500 | 1.12 | 0.08em, uppercase |
| body | 15px | 400 | 1.55 | — |

**Prototype overrides (smaller scale for the dense UI):**

| Context | Font shorthand |
|---------|---------------|
| Page title | `500 19-21px/1.2 var(--font-heading)` |
| Card/agent name | `500 13.5-15px var(--font-heading)` |
| Nav items | `400 12.5px var(--font-body)` |
| Descriptions | `400 11.5-12.5px/1.45-1.55 var(--font-body)` |
| Section labels (`.klabel`) | `500 10px var(--font-body); letter-spacing:.08em; text-transform:uppercase` |
| Monospace data | `400 11-12px var(--mono)` |
| Log lines | `400 12px/1.65 var(--mono)` |
| Status pills | `500 11px var(--mono); letter-spacing:.02em` |
| Table headers | `500 10px var(--font-body); letter-spacing:.08em; text-transform:uppercase` |

### 2.7 Spacing

| Token | Value | Note |
|-------|-------|------|
| `--space-1` | `2.8px` | Tight gaps |
| `--space-2` | `5.6px` | Button padding, small gaps |
| `--space-3` | `8.4px` | Card padding, component gaps |
| `--space-4` | `11.2px` | Section padding |
| `--space-6` | `16.8px` | Larger gaps |
| `--space-8` | `22.4px` | Major section spacing |

**Common paddings observed in prototype:**

| Context | Padding |
|---------|---------|
| Sidebar nav items | `6px 9px` |
| Top bar | `0 14px` (height 38px) |
| Page header | `18px 14px 14px` |
| Content area | `0 14px 20px` |
| Table rows | `9-11px 16px` |
| Cards | `14px` |
| Dialog | `12-20px` |
| Log lines | `1.5px 16px` |

### 2.8 Border Radius

| Token | Value | Usage |
|-------|-------|-------|
| `--radius-sm` | `4px` | Small badges, brand icon |
| `--radius-md` | `8px` | Buttons, inputs, cards, nav items |
| `--radius-lg` | `14px` | Dialogs, outer containers |

**Additional radii in prototype:**

| Value | Usage |
|-------|-------|
| `7px` | Nav items |
| `6px` | Tags, step items |
| `999px` | Pills (status, live tail, artifact links) |
| `3px` | Status bar segments |
| `2px` | Mini progress bars |
| `1px` | Run strip bars |
| `12px` | Invoke dialog outer |
| `10px` | Content region border |

### 2.9 Shadows / Elevation

| Token | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 0 0 1px #3f424d` | Cards, subtle elevation |
| `--shadow-md` | `0 0 0 1px #595d6c, 0 6px 18px rgba(0,0,0,0.55)` | Dropdowns |
| `--shadow-lg` | `0 0 0 1px #9397ab, 0 16px 40px rgba(0,0,0,0.65)` | Dialogs, prototype cards |

---

## 3. Component Inventory

### 3.1 Buttons

| Variant | Border | Text color | Hover BG | Active BG | Notes |
|---------|--------|------------|----------|-----------|-------|
| `.btn-primary` | `1px solid var(--color-accent)` | `var(--color-accent)` | 12% accent tint | 22% accent tint | Outlined, never filled |
| `.btn-secondary` | `1px solid var(--color-divider)` | `var(--color-text)` | 7% text tint | 14% text tint | Subtle |
| `.btn-ghost` | none | `var(--color-accent)` | 10% accent tint | 18% accent tint | Minimal |

**Size variants observed:**

| Size | min-height | padding | font-size |
|------|------------|---------|-----------|
| Default | 36px | `5.6px 10.08px` | 14px |
| Small | 28-30px | `0 11-13px` | 12px |
| Medium | 32px | `0 16-20px` | 12.5-13px |

Disabled: `opacity:0.45; cursor:not-allowed`

### 3.2 Inputs

- Background: `var(--color-surface)`
- Border: `1px solid var(--color-divider)` → hover: 45% text → focus: accent
- Border-radius: `var(--radius-md)` (8px)
- Caret: `var(--color-accent)`
- Prototype uses small variants: `min-height:26-32px; font-size:11.5-12.5px`

### 3.3 Tags

| Variant | Background | Text | Border |
|---------|------------|------|--------|
| `.tag-accent` | `var(--color-accent-800)` | `var(--color-accent-100)` | none |
| `.tag-neutral` | `var(--color-neutral-800)` | `var(--color-neutral-100)` | none |
| `.tag-outline` | transparent | `var(--color-accent)` | `1px solid var(--color-accent)` |

Prototype uses small variants: `font-size:9.5px; padding:1px 5-6px; letter-spacing:.06em`

### 3.4 Status Pill

Custom component (not in DS, prototype-defined):

```css
.st {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font: 500 11px var(--mono);
  letter-spacing: 0.02em;
  padding: 2px 8px 2px 6px;
  border-radius: 999px;
  background: color-mix(in srgb, <status-color> 14%, transparent);
}
.st .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: <status-color>;
}
```

Running variant: dot has `animation: pulse 1.6s ease-in-out infinite`

### 3.5 Nav Item

```css
.navitem {
  display: grid;
  align-items: center;
  gap: 10px;
  padding: 6px 9px;
  border-radius: 7px;
  cursor: pointer;
  font: 400 12.5px var(--font-body);
}
/* Expanded columns: 15px minmax(0,1fr) auto */
/* Collapsed columns: 15px */
```

Active state: `background: color-mix(in srgb, var(--color-accent) 12%, transparent); border-left: 2px solid var(--color-accent)`

### 3.6 Log Line

```css
.logline {
  display: grid;
  grid-template-columns: 82px 46px 108px minmax(0,1fr);
  gap: 12px;
  padding: 1.5px 16px;
  font: 400 12px/1.65 var(--mono);
  white-space: pre-wrap;
  word-break: break-word;
}
.logline:hover {
  background: color-mix(in srgb, var(--color-text) 4%, transparent);
}
```

Columns: `timestamp | level | step | message`

### 3.7 Section Label (`.klabel`)

```css
.klabel {
  font: 500 10px var(--font-body);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--faint);
}
```

### 3.8 Status Bar (stacked)

```css
/* Container */
height: 5px;
border-radius: 3px;
overflow: hidden;
background: var(--rule);
display: flex;

/* Segments: percentage widths, colored by status */
```

### 3.9 Run Strip (24-bar sparkline)

```css
/* Container */
height: 22px;
display: flex;
gap: 2px;
align-items: flex-end;

/* Each bar */
flex: 1;
height: 100%; /* or 33% for empty */
border-radius: 1px;
background: <status-color>;

/* Running bar: animation: pulse 1.6s ease-in-out infinite */
/* Empty/future: height:33%; background: color-mix(in srgb, var(--color-text) 13%, transparent) */
```

### 3.10 Toggle Switch (Invoke form)

```css
/* Track */
width: 38px;
height: 21px;
border-radius: 999px;
padding: 2px;
transition: all 0.14s ease;

/* Off: transparent bg, rule border, justify flex-start */
/* On: accent-tinted bg, accent border, justify flex-end */

/* Knob */
width: 15px;
height: 15px;
border-radius: 50%;
/* Off: muted color */
/* On: accent color */
```

---

## 4. Layout Architecture

### 4.1 App Shell

```
┌──────────────────────────────────────────────────────────┐
│ height: 100dvh; overflow: hidden; display: flex          │
├──────────────┬───────────────────────────────────────────┤
│ Sidebar      │ Content Area                              │
│ width: 212px │ flex: 1; min-width: 0; flex-direction: col│
│ (52px coll.) │ ┌───────────────────────────────────────┐ │
│ flex: none   │ │ Top Bar — height: 38px                │ │
│              │ ├───────────────────────────────────────┤ │
│              │ │ Page Content — flex:1; overflow-y:auto │ │
│              │ └───────────────────────────────────────┘ │
└──────────────┴───────────────────────────────────────────┘
```

- Sidebar transition: `width 0.14s ease`
- Sidebar bg: `color-mix(in srgb, var(--color-bg) 92%, #000)`
- Body bg: `color-mix(in srgb, var(--color-bg) 88%, #000)`
- Border between sidebar and content: `1px solid var(--rule)`

### 4.2 Run Detail (full-height, no outer scroll)

```
flex-direction: column; (fills content area)
├── Breadcrumb + actions (flex: none)
├── [Optional banner] (flex: none)
├── Summary panel (flex: none, 2-column grid)
│   grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr)
│   gap: 28px
├── Log toolbar (flex: none)
├── Log viewer (flex: 1; overflow-y: auto)
└── Log footer (flex: none)
```

### 4.3 Dashboard Table Grid

```css
grid-template-columns: 26px minmax(0,1fr) 128px 300px 132px 92px;
```

### 4.4 Run History Table Grid

```css
grid-template-columns: 118px 122px minmax(0,1fr) 96px 78px 104px 30px;
```

### 4.5 Dashboard Cards

```css
grid-template-columns: repeat(2, minmax(0, 1fr));
gap: 14px;
```

---

## 5. Screen Specifications

### 5.1 Agents Dashboard

Three density variants to choose from (or offer as a view toggle):

| Variant | ID | Description | Best for |
|---------|-----|-------------|----------|
| Dense rows | 1a | Table with status bar + legend per row | Many agents, data comparison |
| Cards | 1b | 2-col card grid with 24-bar run strip | Visual overview, fewer agents |
| Ledger | 1c | Maximum density, keyboard-first | Power users, keyboard nav |

**Common elements:**
- Page header: "Agents" + summary stats + time range filter (7d/30d/all) + filter input
- Per-agent: status dot, name (heading weight), slug (mono, accent-400), description (muted, truncated), run count, status breakdown, last run time + outcome tag, action button

### 5.2 Agent Run History

- Agent header with breadcrumb, name, description, metadata (params count, p50 duration, success rate)
- Filter bar: status segmented control (with colored dots + counts), repo chips, search input, live indicator
- Table with columns: Status pill | Outcome tag | Repository + branch + PR | Duration | Steps (n/m) | Started (relative) | Chevron
- Pagination: "X of Y" + "Load more" button
- Empty state: message + CTA buttons

### 5.3 Run Detail

- Full-height layout (log viewer owns the scroll)
- Summary: status pill, outcome tag, title (Run ID), repository (accent-300), metadata grid (queued/started/finished/duration/branch), artifact links (pill-shaped)
- Steps panel: vertical list with colored dot, name (mono 500), duration, event count; click filters log
- Log viewer: 4-column grid (time/level/step/message), level coloring, hover highlight, live cursor block
- State banners for terminal states (timed_out, failed_to_start) with colored border and background tint

### 5.4 Invoke Agent

- Centered dialog (max-width 760px) with `--shadow-lg`
- Header: title + agent slug + close button
- Schema-driven form: field rows with label+type+required on left, input on right (2-column grid: `minmax(0,1fr) 292px`)
- Toggle switches for booleans
- Select dropdowns for enums
- Repository field rendered separately (first, outside params)
- Schema preview toggle
- Footer: API hint + Cancel + Run button
- Success state: animated confirmation with run ID and link to detail

---

## 6. Interaction Patterns

### 6.1 Animations

| Name | Keyframes | Duration | Easing | Usage |
|------|-----------|----------|--------|-------|
| `pulse` | `0%,100%{opacity:1} 50%{opacity:.3}` | 1.6s | ease-in-out, infinite | Running dots, live indicators |
| `pulse` (slow) | same | 2s | ease-in-out, infinite | Realtime indicator |
| `spin` | `to{transform:rotate(360deg)}` | 0.9s | linear, infinite | Loading spinner (queued) |
| `rise` | `from{opacity:0;translateY(6px)}` | 0.18s | ease, fill both | Success state appear |

### 6.2 Transitions

| Element | Property | Duration | Easing |
|---------|----------|----------|--------|
| Sidebar width | width | 0.14s | ease |
| Toggle switch | all | 0.14s | ease |
| Button hover/active | background | instant (no transition) | — |

### 6.3 Hover States

| Element | Effect |
|---------|--------|
| Nav items | `background: color-mix(in srgb, var(--color-text) 5%, transparent)` |
| Log lines | `background: color-mix(in srgb, var(--color-text) 4%, transparent)` |
| Table rows | 4% text tint overlay |
| Links | color shifts to `var(--color-accent-400)` |
| Buttons | Per-variant tints (see §3.1) |

### 6.4 Focus States

```css
:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: 2px;
}
```

Never use browser default focus ring.

### 6.5 Keyboard Shortcuts (shown in UI)

| Shortcut | Action |
|----------|--------|
| `Cmd+\` | Toggle sidebar collapse |
| `Cmd+K` | Open command palette |
| `Up/Down` | Navigate list (ledger view) |
| `Enter` | Run selected (ledger view) |
| `/` | Focus filter input (ledger view) |

### 6.6 Live Tail Behavior

- Auto-scrolls log when user is within 24px of bottom
- Scrolling up pauses auto-scroll; shows "paused" state on live tail button
- Click "live tail" re-scrolls to bottom and resumes
- Active: green dot + green text + pulsing animation
- Paused: transparent bg + muted text

---

## 7. Data Formatting Conventions

### 7.1 Timestamps

| Context | Format | Example |
|---------|--------|---------|
| Log viewer | `HH:MM:SS` (24h, monospace) | `14:02:13` |
| Run metadata | `HH:MM:SS` (24h, monospace) | `14:02:07` |
| Run history table | Relative time | `2 min ago`, `14m ago`, `yesterday` |
| Dashboard last run | Short relative | `14m ago`, `6h ago`, `23d ago` |

### 7.2 Durations

| Context | Format | Example |
|---------|--------|---------|
| Run detail | `Xm XXs` | `3m 04s` |
| Step list | Short | `4s`, `1m 12s` |
| Run history | `Xm XXs` | `1m 48s` |
| Running in-progress | `running · Xm` | `running · 2m` |

### 7.3 Counts and IDs

| Content | Format |
|---------|--------|
| Run ID | Short ULID-style, uppercase monospace: `01J8XQ2F` |
| Run count | Plain number: `82` |
| With label | `82 runs` |
| Step progress | `2/4` |
| Event count | `12 ev` |
| Pagination | `8 of 82` |
| Status legend | `65 ok · 11 fail · 6 timeout` |
| Cards compact | `65 ✓ · 11 ✕ · 6 ⧗` |

### 7.4 Typography Usage Rules

| Content type | Font stack |
|-------------|------------|
| Headings, button labels, nav labels | `var(--font-heading)` weight 500 |
| Body text, descriptions | `var(--font-body)` weight 400 |
| Slugs, IDs, timestamps, durations, counts, code, branches, commit SHAs | `var(--mono)` |
| Section headers | `.klabel` pattern (10px uppercase) |
| Repository names | Monospace at 12.5px |
| Status labels in pills | Monospace 500 11px |

### 7.5 Truncation

| Pattern | Usage |
|---------|-------|
| Single-line ellipsis | Agent descriptions in table, sidebar labels, step names |
| 2-line clamp | Agent descriptions in cards |
| Word-wrap | Log messages (never truncate log content) |

---

## 8. Status Visualization

### 8.1 Status → Visual Mapping

| Status | Color | Dot | Animation | Pill BG |
|--------|-------|-----|-----------|---------|
| `running` | `var(--color-accent)` | 7px solid + `box-shadow: 0 0 7px` | `pulse 1.6s` | 16% accent |
| `succeeded` | `var(--st-ok)` | 7px solid | none | 14% green |
| `failed` | `var(--st-fail)` | 7px solid | none | 14% red |
| `timed_out` | `var(--st-timeout)` | 7px solid | none | 14% amber |
| `failed_to_start` | `var(--faint)` | 7px hollow (border only) | none | `var(--rule)` |
| `queued` | `var(--color-accent)` | pulsing | `pulse 1.4s` | 16% accent |

### 8.2 Outcome Tags

Always `.tag-outline` style. Uppercase text. Known values: `FIXED`, `NO VULNS`, `PARTIAL`, `NEEDS REVIEW`, `—` (pending/none, with opacity 0.45).

### 8.3 Terminal-State Banners (Run Detail)

Shown above the log viewer for `timed_out` and `failed_to_start`:

```css
padding: 12px 16px;
border-bottom: 1px solid color-mix(in srgb, <status-color> 35%, transparent);
background: color-mix(in srgb, <status-color> 10%, transparent);
```

Contains: status dot + title (bold, colored) + explanation text + action buttons + metadata.

---

## 9. Responsive Behavior

The prototype targets **1180-1440px width** and does not define responsive breakpoints. For Phase 2 implementation:

- **Minimum supported width:** 1024px (sidebar always visible)
- **Below 1024px:** behavior undefined — acceptable for a single-operator internal tool
- **Sidebar collapse** at 52px provides some flexibility but is a user preference, not a breakpoint response

---

## 10. Icons

Use **Phosphor Icons** (https://phosphoricons.com) throughout, rendered as inline SVG on `currentColor`. The prototype uses Unicode glyphs as stand-ins:

| Glyph | Meaning | Phosphor equivalent |
|-------|---------|-------------------|
| ▦ | Agents | `GridFour` or `Robot` |
| ≡ | All runs | `List` |
| ⑃ | Repositories | `GitBranch` |
| ⚙ | Settings | `GearSix` |
| ◈ | System health | `Heartbeat` |
| « / » | Collapse/expand | `CaretLeft` / `CaretRight` |
| › | Row chevron | `CaretRight` |
| ✕ | Close | `X` |

---

## 11. Implementation Notes

### 11.1 CSS Architecture

- Use CSS custom properties for all tokens (not Tailwind utility classes alone — the tokens must be the source of truth)
- `color-mix()` is used extensively — requires Chrome 111+, Safari 16.2+, Firefox 113+
- Consider a Tailwind plugin that maps to these tokens, or use CSS Modules with the token sheet

### 11.2 Component Library

The prototype maps cleanly to a small component set:

| Component | Props |
|-----------|-------|
| `Button` | variant (primary/secondary/ghost), size (sm/md/default), disabled, icon |
| `Tag` | variant (accent/neutral/outline), size (sm/default) |
| `StatusPill` | status (running/succeeded/failed/timed_out/failed_to_start/queued) |
| `StatusDot` | status, size (5px/6px/7px) |
| `NavItem` | active, icon, label, badge, collapsed |
| `Input` | size (sm/default), placeholder |
| `LogLine` | timestamp, level, step, message |
| `StatusBar` | segments: {color, percent}[] |
| `RunStrip` | runs: {status}[], max (24) |
| `Toggle` | checked, onChange |
| `KLabel` | children |
| `Breadcrumb` | items: {label, href, active}[] |

### 11.3 Key Behavioral Contracts

1. **Log auto-scroll:** If `scrollHeight - scrollTop - clientHeight < 24`, auto-scroll on new events
2. **Sidebar state:** Persisted in localStorage; animated with CSS transition
3. **Realtime:** Supabase Realtime subscription on `run_events` and `runs`; green indicator reflects connection state
4. **Schema-driven form:** Generated from `agents.params_schema` JSON Schema (requirement from parent PRD D2)
5. **No authentication UI:** Single-user system, no login screen, no user avatar, no roles

---

## 12. Do / Don't

### Do

- Use tokens for every color, spacing, radius, and font value
- Keep chroma low — lean on neutral ramp for surfaces and borders
- Use monospace for all data values (timestamps, IDs, counts, slugs)
- Use the compact spacing scale — this UI is intentionally dense
- Outline buttons; let `:focus-visible` carry the accent
- Fade rules at both ends (the `linear-gradient` to transparent pattern)

### Don't

- Do not flood large areas with the accent color
- Do not use pure black or pure white — every value comes from the ramps
- Do not bolden headings past weight 500
- Do not stack heavy shadows — on a dark ground elevation is an edge + ambient darkness
- Do not use browser default focus rings
- Do not add decorative elements (badges, illustrations, gradients) — this is a utility panel
