# Research: High-Fidelity UI Prototype Analysis

## Changelog
| Date | Change |
|------|--------|
| 2025-01-27 | Initial research artifact |

## Provenance
- **Repository:** current workspace
- **Base branch:** main
- **Commit SHA:** 33e5c6474221982ab9c8f57ece8f42d44339002c
- **Invoking agent:** user (direct)
- **Research question:** Comprehensive analysis of the Agent Fleet UI prototype for implementation-ready specifications
- **Date:** 2025-01-27
- **Multi-repo source:** N/A (single repo, direct scanning)

## Answer First

The prototype defines a 6-screen agent fleet management UI built on the "Nocturne" dark design system. The app uses a collapsible sidebar (212px/52px) + top breadcrumb bar + scrollable content area shell. Core screens are: agents dashboard (3 density variants), per-agent run history table, run detail with live log viewer (4 states: queued/running/timed_out/failed_to_start), and an invoke agent form/dialog. The design system provides tokens via CSS custom properties for colors (`#161826` bg, `#e9e9ed` text, `#9184d9` accent), Inter font family, 0.7x density spacing scale, and 8px radius. Status colors are hardcoded in page-level `:root`: `--st-ok: #74b58f`, `--st-fail: #d1706b`, `--st-timeout: #d1a45e`. The prototype uses monospace for data/timestamps (`ui-monospace, Menlo, monospace`) and Inter for UI labels/headings.

## Relevance-Ranked File Map

| # | File | Purpose |
|---|------|---------|
| 1 | `docs/prototype/_ds/nocturne-a98c260f-d03a-4bc8-ac61-7b143a751c04/styles.css` | Design system tokens + component classes |
| 2 | `docs/prototype/App Shell.dc.html` | Application shell (sidebar + topbar + content) |
| 3 | `docs/prototype/Agents Dashboard.dc.html` | Agent list in 3 densities (table, cards, ledger) |
| 4 | `docs/prototype/Agent Run History.dc.html` | Per-agent run history table |
| 5 | `docs/prototype/Run Detail.dc.html` | Live run detail with streaming log |
| 6 | `docs/prototype/Run Detail States.dc.html` | Run detail in 4 terminal states |
| 7 | `docs/prototype/Invoke Agent.dc.html` | Schema-driven invocation form |
| 8 | `docs/prototype/_ds/nocturne-a98c260f-d03a-4bc8-ac61-7b143a751c04/readme.md` | DS usage guide |
| 9 | `docs/prototype/_ds/nocturne-a98c260f-d03a-4bc8-ac61-7b143a751c04/_ds_manifest.json` | Token manifest |

## S1 — Components/Modules (Screen Inventory)

### Screen 1: App Shell (`App Shell.dc.html`)
**Purpose:** Application frame containing sidebar navigation, top breadcrumb bar, page header with actions, and content region. Preview: 1440×820.

**Layout:**
- Root: `height:100dvh; overflow:hidden; display:flex`
- Sidebar: `width:212px` (expanded) / `52px` (collapsed); `flex:none; flex-direction:column; border-right:1px solid var(--rule)`
- Content: `flex:1; min-width:0; flex-direction:column`
- Transition: `width .14s ease`

**Sidebar sections:**
1. Brand header: logo icon (16×16px square, 4px radius, accent border with 5px dot inside) + "Agent Fleet" text
2. Primary nav (scrollable): Agents (▦), All runs (≡), Repositories (⑃)
3. Agent list: colored dots per agent with slug in mono, run count
4. Footer: Settings (⚙), System health (◈), Collapse toggle (⌘\)

**Nav item spec (`.navitem`):**
- `display:grid; align-items:center; gap:10px; padding:6px 9px; border-radius:7px`
- `font:400 12.5px var(--font-body)`
- Grid columns expanded: `15px minmax(0,1fr) auto`
- Grid columns collapsed: `15px`
- Active state: `background:color-mix(in srgb, var(--color-accent) 12%, transparent); border-left:2px solid var(--color-accent)`

**Top bar:**
- `height:38px; padding:0 14px; border-bottom:1px solid var(--rule)`
- Left: breadcrumbs (mono 12px, `/` separator) + optional running pill
- Right: realtime indicator (green dot + "realtime"), region ("us-east-1"), command palette shortcut ("⌘K")

**Page header:**
- `padding:18px 14px 14px`
- Title: `font:500 19px/1.2 var(--font-heading)`
- Subtitle: `font:400 12px/1.55 var(--font-body); color:var(--muted)`
- Actions: ghost button (secondary) + primary button (accent)

**Navigation targets (from JS):**
- Agents, Runs, Repositories, Settings, System health
- Per-agent detail pages
- Run detail pages

---

### Screen 2: Agents Dashboard (`Agents Dashboard.dc.html`)
**Purpose:** List all configured agents with status, run counts, and status breakdown. Three density variants. Preview: within 1180px card.

#### Variant 1a: Dense Rows (table-first)
**Grid columns:** `26px minmax(0,1fr) 128px 300px 132px 92px`

**Header row:**
- Column labels (`.hhd`): `font:500 10px var(--font-body); letter-spacing:.08em; text-transform:uppercase; color:var(--faint)`
- Columns: [status dot] Agent | Runs·7d | Status breakdown | Last run | Action

**Agent row spec:**
- Padding: `11px 16px`
- Status dot: `width:7px; height:7px; border-radius:50%`
  - Enabled: `background:var(--st-ok)` (solid green)
  - Running: `background:var(--color-accent); box-shadow:0 0 7px var(--color-accent); animation:pulse 1.6s`
  - Disabled: `border:1px solid var(--faint)` (hollow)
- Agent name: `font:500 13.5px var(--font-heading)`
- Agent slug: `font:400 11.5px ui-monospace; color:var(--color-accent-400)`
- Description: `font:400 11.5px var(--font-body); color:var(--muted); text-overflow:ellipsis`
- Run count: `font:500 16px ui-monospace` + "runs" label at `10.5px`
- Status bar: `height:5px; border-radius:3px; overflow:hidden; background:var(--rule)` with colored segments
- Status legend: `font:400 11px ui-monospace` with colored text per status
- Last run: `font:400 11.5px ui-monospace; color:var(--muted)` (relative time)
- Outcome tag: `.tag.tag-outline` at `font-size:9.5px; padding:1px 5px; letter-spacing:.06em`
- Action button: `.btn.btn-primary; min-height:28px; padding:0 12px; font-size:12px`
- Disabled row: `opacity:.5`

**Toolbar:**
- Time range segmented control: `7d | 30d | all` with border group
- Filter input: `width:180px; min-height:30px; font-size:12px`

#### Variant 1b: Cards
**Grid:** `grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px`

**Card spec:**
- Uses `.card` class + `padding:14px; flex-direction:column; gap:11px`
- Header: name (15px heading) + ENABLED/DISABLED tag + Run button
- Slug: `font:400 11.5px ui-monospace; color:var(--color-accent-400)`
- Description: `font:400 12px/1.45; -webkit-line-clamp:2`
- Run strip: `height:22px; display:flex; gap:2px` — 24 bars, each `flex:1; border-radius:1px`
  - Colored by status (ok/fail/timeout)
  - Running bar: `animation:pulse 1.6s ease-in-out infinite`
  - Empty/future bars: `height:33%; background:color-mix(in srgb, var(--color-text) 13%, transparent)`
- Footer: `padding-top:9px; border-top:1px solid var(--rule)` with stats and "last X ago"
- Disabled card: `opacity:.55`

#### Variant 1c: Ledger (maximum density)
**Layout:** Flex rows, no grid. Full-width list.
- Header: `Agents · 4` + keyboard hints `↑↓ select · ⏎ run · / filter`
- Row: `display:flex; align-items:center; gap:12px; padding:9px 14px`
- Active row: `border-left:2px solid var(--color-accent); background:color-mix(in srgb, var(--color-accent) 8%, transparent)`
- Mini progress bar: `width:70px; height:4px; border-radius:2px`
- Last run time: `width:52px; text-align:right`
- Run button: `min-height:24px; padding:0 9px; font-size:11px`

---

### Screen 3: Agent Run History (`Agent Run History.dc.html`)
**Purpose:** Per-agent run list with filters, showing status, outcome, repo, duration, steps, and start time.

**Header section:**
- Breadcrumb: `agents / dependency-update`
- Agent title: `font:500 21px/1.2 var(--font-heading)` + ENABLED tag
- Description: `font:400 12.5px/1.5 var(--font-body); color:var(--muted)`
- Meta line: `font:400 11.5px var(--mono); color:var(--faint)` — "4 params · p50 3m 12s · 79% success · 7d"
- Actions: "Edit config" ghost button + "Invoke ▸" primary button (min-height:32px)

**Filter bar:**
- Status segmented control: All | Running (1) | Succeeded (65) | Failed (11) | Timed out (6)
  - Each option has a colored dot
- Repository chip: `.chip` class — `padding:4px 9px; border:1px solid var(--rule); border-radius:var(--radius-md)`
- Active filter chip: accent border + accent text color
- Search input: `width:170px; min-height:30px; font-size:12px`
- Live indicator: green pulsing dot + "live"

**Table (`.hrow`):**
- Grid: `grid-template-columns:118px 122px minmax(0,1fr) 96px 78px 104px 30px`
- Row gap: `14px`
- Row padding: `9px 16px`
- Border: `border-bottom:1px solid var(--rule)`

**Status pill (`.st`):**
- `display:inline-flex; align-items:center; gap:6px; font:500 11px var(--mono); letter-spacing:.02em; padding:2px 8px 2px 6px; border-radius:999px`
- Background: `color-mix(in srgb, <status-color> 14-16%, transparent)`
- Dot inside: `width:6px; height:6px; border-radius:50%`
- Running dot: `animation:pulse 1.6s ease-in-out infinite`

**Statuses observed:**
- `running` — accent color, pulsing dot
- `succeeded` — st-ok green
- `failed` — st-fail red
- `timed_out` — st-timeout amber
- `failed_to_start` — neutral (muted text, outline dot `border:1px solid var(--muted)`)

**Row data fields:**
- Outcome: `.tag.tag-outline` (FIXED, NO VULNS, NEEDS REVIEW, PARTIAL, —)
- Repository: `font-size:12.5px; color:var(--color-text)` + branch in faint + optional PR link
- Error inline: `color:var(--st-fail); font-size:11px`
- Duration: `font:400 11.5px var(--mono)` — colored by status for timeout
- Steps: `2/4` format in mono
- Started: relative time, right-aligned
- Chevron: `›` in faint, right-aligned

**Pagination:** "8 of 82 · sorted by started_at desc" + "Load 50 more" button

**Empty state (2b):**
- "No runs yet" label (uppercase mono)
- Description paragraph
- Two action buttons: "Invoke on one repo" (primary) + "Enable agent" (secondary)

---

### Screen 4: Run Detail (`Run Detail.dc.html`)
**Purpose:** Single run view with live-streaming log viewer. Preview: 1240×860.

**Layout:** Full-height flex column, no outer scroll.
- Breadcrumb bar (flex:none)
- Summary panel (flex:none, border-bottom)
- Log viewer (flex:1, own scroll)

**Breadcrumb bar:**
- `padding:9px 16px`
- Path: `agents / dependency-update / run_01J8XQ2F`
- Actions: "Copy run id" (ghost) + "Re-run" (secondary) + "Cancel" (secondary, red-tinted border)

**Summary panel (2-column grid):**
- Grid: `grid-template-columns:minmax(0,1.35fr) minmax(0,1fr); gap:28px`

**Left column:**
- Status pill: `font:500 12px var(--mono); padding:3px 10px 3px 8px; border-radius:999px`
- Outcome: `.tag.tag-outline` with opacity 0.5 for "pending"
- Title: `font:500 20px/1.2 var(--font-heading)` + repo in `font-size:16px; color:var(--color-accent-300)`
- Metadata grid (flex, gap:22px):
  - Labels (`.klabel`): `font:500 10px var(--font-body); letter-spacing:.08em; text-transform:uppercase; color:var(--faint)`
  - Values: `.mono; font-size:13px` (Duration), normal 11.5px for others
  - Fields: Duration, Queued, Started, Finished, Branch
- Artifacts: pill-shaped links with `padding:4px 10px; border-radius:999px`
  - PR artifact: accent border + accent text
  - Report artifact: rule border + text color
  - Note: `font:400 11px var(--mono); color:var(--faint)`

**Right column (Steps panel):**
- Header: "Steps" klabel + "Show all events" ghost button
- Step list: vertical stack, gap:1px
- Step item: `grid-template-columns:16px minmax(0,1fr) 62px 54px; gap:10px; padding:6px 9px; border-radius:6px`
  - Dot: `7px×7px` circle (colored by step status)
  - Name: `font:500 12px var(--mono)`
  - Duration: `font:400 11px var(--mono); text-align:right`
  - Event count: same font, right-aligned
  - Selected state: `background:color-mix(in srgb, var(--color-accent) 12%, transparent); border-left:2px solid var(--color-accent)`

**Log viewer:**
- Toolbar: filter chip + level filter (all/warn/error/debug) + grep input + live tail toggle
- Log area: `background:color-mix(in srgb, var(--color-bg) 94%, #000); padding:8px 0 14px; overflow-y:auto`
- Log line (`.logline`): `grid-template-columns:82px 46px 108px minmax(0,1fr); gap:12px; padding:1.5px 16px; font:400 12px/1.65 var(--mono); white-space:pre-wrap; word-break:break-word`
  - Columns: timestamp | level | step | message
  - Hover: `background:color-mix(in srgb, var(--color-text) 4%, transparent)`
- Cursor (live): `width:7px; height:14px; background:var(--color-accent); animation:pulse 1s steps(2,end) infinite`
- Live tail toggle: pill button `padding:4px 10px; border-radius:999px`
  - Active: green bg tint + green text + pulsing dot
  - Paused: transparent bg + muted text
- Footer: `padding:6px 16px; font:400 11px var(--mono); color:var(--faint)` — event count + channel name

---

### Screen 5: Run Detail States (`Run Detail States.dc.html`)
**Purpose:** The same run detail page in 4 states: queued, running, timed_out, failed_to_start. Preview: 1240×880.

**State-specific behaviors:**

**Queued:**
- Empty log area with spinner: `22px circle, border:2px solid var(--rule); border-top-color:var(--color-accent); animation:spin .9s linear infinite`
- Info: "Waiting for agent to start…" + description + queue metadata (position, cold start, timeout)
- Cancel button visible

**Running:**
- Log streams in real-time (1.5s interval in prototype)
- Live tail button visible and active
- Cursor block visible
- Cancel button visible

**Timed_out:**
- Banner: `padding:12px 16px; border-bottom colored; background tinted`
  - Status dot (7px) + title (12.5px bold, status color) + body (12px, muted) + action buttons + meta text
  - Banner bg: `color-mix(in srgb, <status-color> 10%, transparent)`
  - Banner border: `color-mix(in srgb, <status-color> 35%, transparent)`
- Last log line highlighted: `background:color-mix(in srgb, var(--st-timeout) 12%, transparent)`
- No live tail, no cancel

**Failed_to_start:**
- Same banner pattern but with fail color
- Minimal log (system events only)
- Steps show "never ran" for all
- No artifacts produced

---

### Screen 6: Invoke Agent (`Invoke Agent.dc.html`)
**Purpose:** Schema-driven form to invoke an agent against a repository. Preview: 900×880.

**Layout:** Centered dialog, `max-width:760px; border-radius:12px; box-shadow:var(--shadow-lg)`
- Background: radial gradient with 7% accent tint
- Container: `background:var(--color-bg); border:1px solid var(--rule)`

**Header:**
- `padding:12px 20px; border-bottom:1px solid var(--rule)`
- Title: `font:500 14px var(--font-heading)` + slug in accent mono
- Close: `✕` at `font:400 16px var(--mono); color:var(--faint)`

**Form structure:**
- Intro text: explains schema-driven fields
- Schema toggle: "View schema" / "Hide schema" ghost button
- Schema display: `<pre>` in `font:400 11px/1.6 var(--mono)` with dark bg and rule border

**Field rows (`.fieldrow`):**
- Grid: `grid-template-columns:minmax(0,1fr) 292px; gap:24px; padding:15px 0; border-top:1px solid var(--rule)`
- Label side: field name (`font:500 13px var(--mono)`) + type badge (`.ftype`: `font:400 10px var(--mono); padding:1px 6px; border:1px solid var(--rule); border-radius:4px`) + required asterisk (red)
- Description: `font:400 11.5px/1.5 var(--font-body); color:var(--muted)`
- Input side: select/toggle controls at `min-height:32px; font-size:12.5px`
- Default value hint: `font:400 11.5px var(--mono); color:var(--faint)`

**Toggle switch:**
- `width:38px; height:21px; border-radius:999px; padding:2px`
- Knob: `width:15px; height:15px; border-radius:50%`
- Off: transparent bg, rule border, muted knob, justify flex-start
- On: accent-tinted bg, accent border, accent knob, justify flex-end
- Transition: `all .14s ease`

**Footer:**
- `padding:14px 20px; border-top:1px solid var(--rule); background:color-mix(in srgb, var(--color-bg) 96%, #000)`
- Left: API hint in mono faint
- Right: Cancel (ghost) + Run (primary, `min-height:32px; padding:0 20px; font-size:13px`)
- Disabled state: `opacity:0.5` when no repo selected

**Success state (queued):**
- `animation:rise .18s ease both` (translateY 6px fade in)
- Status pill: "queued" with pulsing accent dot
- Title: "Run accepted"
- Details grid: `grid-template-columns:auto minmax(0,1fr); gap:6px 18px`
- Progress bar: `height:3px; border-radius:2px` with animated width
- Actions: "Open run detail ▸" (primary) + "Invoke another" (secondary)

---

## S2 — APIs/Contracts

**Navigation routes (from App Shell JS):**
- `/agents` — Agents list
- `/runs` — All runs (cross-agent)
- `/repos` — Repositories
- `/agents/:slug` — Agent detail
- `/agents/:slug/runs/:id` — Run detail
- `/settings` — Settings
- `/health` — System health

**Data models implied:**
- Agent: `{ slug, name, description, runs_count, enabled, live_running }`
- Run: `{ id, status, outcome, repository, branch, duration, steps_completed, steps_total, started_at }`
- Run statuses: `running`, `succeeded`, `failed`, `timed_out`, `failed_to_start`
- Run outcomes: `FIXED`, `NO VULNS`, `NEEDS REVIEW`, `PARTIAL`, `pending`, `none`
- Log event: `{ timestamp, level, step_name, message }`
- Log levels: `info`, `warn`, `error`, `debug`
- Step: `{ name, status, duration, event_count }`
- Step statuses: `succeeded`, `running`, `timed_out`, `pending`, `skipped`, `never_ran`

---

## S3 — UI Surfaces

Covered in S1 above (all 6 screens documented).

---

## S4 — Tests

N/A — prototype only, no test files present.

---

## S5 — Data Model

See S2 for implied data structures. Additional observations:
- Run IDs use ULID-like format: `01J8XQ2F` (Crockford base32)
- Repositories: `org/repo` format
- Timestamps: `HH:MM:SS` format in logs, relative time ("14m ago", "6h ago", "yesterday") in tables
- Duration: `Xm XXs` format
- Step progress: `completed/total` fraction

---

## S6 — Config/Env/CI

**Design system loaded via:**
- `<link rel="stylesheet" href="_ds/nocturne-.../styles.css">`
- `<script src="_ds/nocturne-.../_ds_bundle.js">`
- Google Fonts: `Inter:wght@400;500;600` (some pages also load `JetBrains+Mono:wght@400;500`)

**Font loading:** `<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>`

---

## S7 — Relationships

**Screen flow:**
1. App Shell → contains all other screens in content region
2. Agents Dashboard → click agent → Agent Run History
3. Agent Run History → click row → Run Detail
4. Any screen → "Invoke" button → Invoke Agent dialog
5. Invoke Agent → success → Run Detail (live)

**Component reuse across screens:**
- Status pill (`.st`) — used in run history rows, run detail header
- Status dot (7px circle) — sidebar, dashboard rows, run history, steps panel
- Outcome tag (`.tag.tag-outline`) — dashboard rows, run history rows, run detail
- Run strip (24-bar visualization) — dashboard cards
- Stacked bar chart — dashboard table rows, ledger rows
- Log viewer — run detail, run detail states
- Breadcrumbs — top bar (all screens)
- klabel — used everywhere for section headers
- mono class — data values everywhere

---

## S8 — Prior History

N/A — no git history relevant to the prototype analysis.

---

## Relationships

```
App Shell
├── Sidebar (persistent)
│   ├── Brand + nav items
│   ├── Agent list (with live indicators)
│   └── Footer (settings, health, collapse)
├── Top Bar (persistent)
│   ├── Breadcrumbs
│   └── Realtime + region + ⌘K
└── Content (routed)
    ├── Agents Dashboard (3 variants)
    ├── Agent Run History
    ├── Run Detail (4 states)
    └── Invoke Agent (overlay/dialog)
```

---

## Risks and Gotchas

1. **Monospace font inconsistency:** Most pages use `ui-monospace, Menlo, monospace` via `--mono` custom property; the dashboard page also loads JetBrains Mono but references are mixed. Implementation should standardize on one.

2. **No responsive breakpoints:** The prototype is fixed-width (1180–1440px). No media queries or responsive indicators exist. Mobile/tablet behavior is undefined.

3. **Inline styles everywhere:** The prototype uses almost exclusively inline styles rather than CSS classes. Implementation must extract these into a component system.

4. **Page-level tokens override DS:** Each page re-declares `--st-ok`, `--st-fail`, `--st-timeout`, `--rule`, `--muted`, `--faint`, `--mono` in its own `:root`. These are NOT in the Nocturne DS stylesheet — they must be added to the app's global CSS.

5. **Animation perf:** The `pulse` keyframe runs on multiple dots simultaneously. On screens with many agents running, this could impact paint performance.

6. **Log viewer scroll behavior:** Auto-scroll-to-bottom logic uses `scrollHeight - scrollTop - clientHeight < 24` threshold. Implementation must match this for consistent UX.

7. **Color-mix usage:** Heavy use of `color-mix(in srgb, ...)` requires modern browser support (Chrome 111+, Safari 16.2+, Firefox 113+).

8. **No explicit font-size for body:** The DS sets `font-size:15px` on body, but the prototype pages override with specific sizes everywhere (11–13px for most UI text).

---

## Not Investigated

- The `support.js` file referenced by all pages (framework runtime)
- The `_ds_bundle.js` file (DS JavaScript behavior)
- Accessibility audit (focus order, ARIA attributes, screen reader behavior)
- Dark/light mode toggling (prototype is dark-only)
- Actual data fetching patterns or API response shapes
- Animation timing preferences beyond what's declared in CSS

---

## Confidence

**High** — All 9 source files were read in their entirety. The analysis is based on direct inspection of HTML structure, inline CSS, and component logic scripts. Token values are extracted verbatim from the design system stylesheet.

---

## Appendix A: Design Tokens (Complete)

### From Nocturne DS (`styles.css` `:root`)

#### Colors — Core
| Token | Value | Usage |
|-------|-------|-------|
| `--color-bg` | `#161826` | Page background |
| `--color-surface` | `#232532` | Card/input backgrounds |
| `--color-text` | `#e9e9ed` | Primary text |
| `--color-accent` | `#9184d9` | Primary accent (blurple) |
| `--color-accent-2` | `#a7a1db` | Secondary accent (treat as same role) |
| `--color-divider` | `color-mix(in srgb, #e9e9ed 16%, transparent)` | Borders/rules |

#### Colors — Neutral Ramp
| Token | Value |
|-------|-------|
| `--color-neutral-100` | `#f3f5fe` |
| `--color-neutral-200` | `#e4e7f5` |
| `--color-neutral-300` | `#cfd3e5` |
| `--color-neutral-400` | `#b2b6ca` |
| `--color-neutral-500` | `#9397ab` |
| `--color-neutral-600` | `#75798c` |
| `--color-neutral-700` | `#595d6c` |
| `--color-neutral-800` | `#3f424d` |
| `--color-neutral-900` | `#292b31` |

#### Colors — Accent Ramp
| Token | Value |
|-------|-------|
| `--color-accent-100` | `#f5f4ff` |
| `--color-accent-200` | `#e7e5fe` |
| `--color-accent-300` | `#d2cefd` |
| `--color-accent-400` | `#b5abfc` |
| `--color-accent-500` | `#968ae0` |
| `--color-accent-600` | `#796cbf` |
| `--color-accent-700` | `#5d5294` |
| `--color-accent-800` | `#423a6a` |
| `--color-accent-900` | `#2b2741` |

#### Typography
| Token | Value |
|-------|-------|
| `--font-heading` | `"Inter", system-ui, sans-serif` |
| `--font-heading-weight` | `500` |
| `--font-body` | `"Inter", system-ui, sans-serif` |

#### Spacing (0.7× density)
| Token | Value |
|-------|-------|
| `--space-1` | `2.8px` |
| `--space-2` | `5.6px` |
| `--space-3` | `8.4px` |
| `--space-4` | `11.2px` |
| `--space-6` | `16.8px` |
| `--space-8` | `22.4px` |

#### Border Radius
| Token | Value |
|-------|-------|
| `--radius-sm` | `4px` |
| `--radius-md` | `8px` |
| `--radius-lg` | `14px` |

#### Shadows/Elevation
| Token | Value |
|-------|-------|
| `--shadow-sm` | `0 0 0 1px #3f424d` |
| `--shadow-md` | `0 0 0 1px #595d6c, 0 6px 18px rgba(0,0,0,0.55)` |
| `--shadow-lg` | `0 0 0 1px #9397ab, 0 16px 40px rgba(0,0,0,0.65)` |

### From Prototype Pages (App-Level Tokens)

| Token | Value | Usage |
|-------|-------|-------|
| `--st-ok` | `#74b58f` | Succeeded status |
| `--st-fail` | `#d1706b` | Failed status |
| `--st-timeout` | `#d1a45e` | Timed out status |
| `--rule` | `var(--color-divider)` | Alias for borders |
| `--muted` | `color-mix(in srgb, var(--color-text) 55%, transparent)` | Secondary text |
| `--faint` | `color-mix(in srgb, var(--color-text) 38%, transparent)` | Tertiary/disabled text |
| `--mono` | `ui-monospace, Menlo, monospace` | Monospace font stack |

---

## Appendix B: Component Specifications

### Button (`.btn`)
- Base: `display:inline-flex; align-items:center; justify-content:center; gap:6px; font-family:var(--font-heading); font-weight:500; font-size:14px; padding:5.6px 10.08px; border-radius:8px; border:1px solid transparent`
- **Primary** (`.btn-primary`): `color:var(--color-accent); border-color:var(--color-accent)`
  - Hover: `background:color-mix(in srgb, var(--color-accent) 12%, transparent)`
  - Active: `background:color-mix(in srgb, var(--color-accent) 22%, transparent)`
- **Secondary** (`.btn-secondary`): `border-color:var(--color-divider)`
  - Hover: `background:color-mix(in srgb, var(--color-text) 7%, transparent)`
  - Active: `background:color-mix(in srgb, var(--color-text) 14%, transparent)`
- **Ghost** (`.btn-ghost`): `color:var(--color-accent); padding-inline:2.8px`
  - Hover: `background:color-mix(in srgb, var(--color-accent) 10%, transparent)`
  - Active: `background:color-mix(in srgb, var(--color-accent) 18%, transparent)`
- **Disabled**: `opacity:0.45; cursor:not-allowed`
- **Prototype overrides (small)**: `min-height:28-32px; padding:0 11-20px; font-size:12-13px`

### Input (`.input`)
- `width:100%; min-height:36px; padding:6px 10px; font-size:14px; color:var(--color-text); caret-color:var(--color-accent); background:var(--color-surface); border:1px solid var(--color-divider); border-radius:8px`
- Hover: `border-color:color-mix(in srgb, var(--color-text) 45%, transparent)`
- Focus: `border-color:var(--color-accent); outline-offset:0`
- **Prototype overrides**: `min-height:26-32px; font-size:11.5-12.5px; width:150-180px`

### Tag (`.tag`)
- Base: `display:inline-flex; align-items:center; font-size:11px; letter-spacing:0.02em; padding:3px 10px; border-radius:6px`
- **Accent** (`.tag-accent`): `background:var(--color-accent-800); color:var(--color-accent-100)`
- **Neutral** (`.tag-neutral`): `background:var(--color-neutral-800); color:var(--color-neutral-100)`
- **Outline** (`.tag-outline`): `border:1px solid var(--color-accent); color:var(--color-accent)`
- **Prototype overrides**: `font-size:9.5px; padding:1px 5-6px; letter-spacing:.06em`

### Card (`.card`)
- `display:flex; flex-direction:column; gap:5.6px; padding:8.4px; border-radius:8px; background:var(--color-surface)`

### Status Pill (`.st` — prototype only)
- `display:inline-flex; align-items:center; gap:6px; font:500 11px var(--mono); letter-spacing:.02em; padding:2px 8px 2px 6px; border-radius:999px`
- Background: 14-16% tint of status color
- Dot: 6px circle in status color

### Log Line (`.logline` — prototype only)
- `display:grid; grid-template-columns:82px 46px 108px minmax(0,1fr); gap:12px; padding:1.5px 16px; font:400 12px/1.65 var(--mono); white-space:pre-wrap; word-break:break-word`
- Hover: 4% text color tint background

### Nav Item (`.navitem` — prototype only)
- `display:grid; align-items:center; gap:10px; padding:6px 9px; border-radius:7px; font:400 12.5px var(--font-body)`

### klabel (`.klabel` — prototype only)
- `font:500 10px var(--font-body); letter-spacing:.08em; text-transform:uppercase; color:var(--faint)`

### mono (`.mono` — prototype only)
- `font:400 11.5px var(--mono)`

---

## Appendix C: Layout Architecture

### App Shell
```
┌─────────────────────────────────────────────────┐
│ Sidebar (212px / 52px)  │  Content Area (flex:1) │
│ ┌─────────────────────┐ │ ┌───────────────────┐ │
│ │ Brand (38px high)   │ │ │ Top Bar (38px)    │ │
│ ├─────────────────────┤ │ ├───────────────────┤ │
│ │ Nav Items           │ │ │ Page Header       │ │
│ │ (scrollable)        │ │ │ (18px top pad)    │ │
│ │                     │ │ ├───────────────────┤ │
│ │ ─── Agents ───      │ │ │ Content Region    │ │
│ │ agent-1             │ │ │ (scrollable)      │ │
│ │ agent-2             │ │ │                   │ │
│ │ ...                 │ │ │                   │ │
│ ├─────────────────────┤ │ │                   │ │
│ │ Footer (fixed)      │ │ │                   │ │
│ │ Settings/Health     │ │ │                   │ │
│ │ Collapse ⌘\        │ │ │                   │ │
│ └─────────────────────┘ │ └───────────────────┘ │
└─────────────────────────────────────────────────┘
```

**Sidebar backgrounds:**
- Expanded: `background:color-mix(in srgb, var(--color-bg) 92%, #000)`
- Body: `background:color-mix(in srgb, var(--color-bg) 88%, #000)`

### Run Detail Layout
```
┌─────────────────────────────────────────────┐
│ Breadcrumb Bar (flex:none, 38px)            │
├─────────────────────────────────────────────┤
│ [Optional: State Banner]                     │
├────────────────────────┬────────────────────┤
│ Summary (1.35fr)       │ Steps (1fr)        │
│ - Status pill          │ - Step list        │
│ - Title + repo         │ - Select to filter │
│ - Metadata grid        │                    │
│ - Artifacts            │                    │
├────────────────────────┴────────────────────┤
│ Log Toolbar (flex:none)                      │
├─────────────────────────────────────────────┤
│ Log Viewer (flex:1, own scroll)              │
│ ┌─────────────────────────────────────────┐ │
│ │ 14:02:13  info  checkout  resolving...  │ │
│ │ 14:02:15  debug checkout  git clone...  │ │
│ │ ...                                     │ │
│ │ █ (cursor)                              │ │
│ └─────────────────────────────────────────┘ │
├─────────────────────────────────────────────┤
│ Log Footer (flex:none, 28px)                 │
└─────────────────────────────────────────────┘
```

---

## Appendix D: Interaction Patterns

### Animations
| Name | Keyframes | Usage |
|------|-----------|-------|
| `pulse` | `0%,100%{opacity:1} 50%{opacity:.3-.35}` | Running status dots, live indicators, cursor |
| `spin` | `to{transform:rotate(360deg)}` | Loading spinner (queued state) |
| `rise` | `from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:none}` | Success confirmation appear |

### Timing
| Animation | Duration | Easing |
|-----------|----------|--------|
| Running dot pulse | 1.6s | ease-in-out, infinite |
| Realtime indicator pulse | 2s | ease-in-out, infinite |
| Live tail dot pulse | 2s | ease-in-out, infinite |
| Queued pulse | 1.4s | ease-in-out, infinite |
| Cursor blink | 1s | steps(2,end), infinite |
| Spinner | 0.9s | linear, infinite |
| Sidebar collapse | 0.14s | ease |
| Toggle switch | 0.14s | ease |
| Rise animation | 0.18s | ease, both (fill-mode) |

### Hover States
- Nav items: `background:color-mix(in srgb, var(--color-text) 5%, transparent)`
- Log lines: `background:color-mix(in srgb, var(--color-text) 4%, transparent)`
- Links: `color:var(--color-accent-400)` (from accent base)
- Buttons: per-variant tints (see Component Specs)

### Keyboard Shortcuts (shown in UI)
| Shortcut | Action |
|----------|--------|
| `⌘\` | Toggle sidebar collapse |
| `⌘K` | Command palette |
| `↑↓` | Navigate list (ledger view) |
| `⏎` | Run selected (ledger view) |
| `/` | Filter (ledger view) |

### Realtime Behavior
- Green pulsing dot + "realtime" / "live" label in top bar and filter bar
- Live tail auto-scrolls log; scrolling up pauses
- Threshold: within 24px of bottom = "at end"
- Resume: click "live tail" button re-scrolls to end
- Event streaming interval: ~1.4-1.5s per event (prototype simulation)

---

## Appendix E: Status Visualization System

### Status → Color Mapping
| Status | Color Token | Hex | Dot | Pill BG |
|--------|-------------|-----|-----|---------|
| running | `var(--color-accent)` | `#9184d9` | Pulsing, with box-shadow glow `0 0 7px` | 16% accent tint |
| succeeded | `var(--st-ok)` | `#74b58f` | Solid | 14% green tint |
| failed | `var(--st-fail)` | `#d1706b` | Solid | 14% red tint |
| timed_out | `var(--st-timeout)` | `#d1a45e` | Solid | 14% amber tint |
| failed_to_start | `var(--muted)` | (38% text) | Hollow (border only) | `var(--rule)` solid |

### Stacked Bar Chart (Dashboard Table)
- Container: `height:5px; border-radius:3px; overflow:hidden; background:var(--rule)`
- Segments: percentage widths, colored by status (ok/fail/timeout)
- Legend below: `font:400 11px ui-monospace` with colored text per count

### Run Strip (Dashboard Cards)
- Container: `height:22px; display:flex; gap:2px; align-items:flex-end`
- Each bar: `flex:1; height:100%; border-radius:1px; background:<status-color>`
- Running bar: `animation:pulse 1.6s ease-in-out infinite`
- No-data bars: `height:33%; background:color-mix(in srgb, var(--color-text) 13%, transparent)`
- Disabled/empty bars: `height:33%; background:var(--rule)`

### Mini Progress Bar (Ledger)
- `width:70px; height:4px; border-radius:2px; overflow:hidden; background:var(--rule); display:flex`
- Same percentage segments as stacked bar

---

## Appendix F: Data Formatting Conventions

### Timestamps
| Context | Format | Example |
|---------|--------|---------|
| Log events | `HH:MM:SS` (24h) | `14:02:13` |
| Run metadata | `HH:MM:SS` (24h) | `14:02:07` |
| Table "started" | Relative | `2 min ago`, `14 min ago`, `38 min ago`, `1 hr ago`, `3 hr ago`, `5 hr ago`, `6 hr ago`, `yesterday` |
| Dashboard "last run" | Relative | `14m ago`, `6h ago`, `23d ago` |
| Running duration | Relative | `running · 2m` |

### Durations
| Context | Format | Example |
|---------|--------|---------|
| Run detail | `Xm XXs` | `1m 48s`, `3m 04s`, `0m 41s` |
| Step duration | Short | `4s`, `22s`, `1m 12s` |
| Timed out | Max format | `15m 00s` |
| Table | `Xm XXs` | same |

### Counts
| Context | Format |
|---------|--------|
| Run count (large) | Plain number: `82` |
| Run count with label | `82 runs` |
| Step progress | `2/4` |
| Event count | `12 ev` (abbreviated) |
| Total display | `8 of 82` |
| Status breakdown | `65 ok · 11 fail · 6 timeout` (ledger: just numbers `65 11 6 /82`) |
| Cards | `82 runs · 65 ✓ · 11 ✕ · 6 ⧗` |

### Typography Usage Rules
| Content Type | Font |
|-------------|------|
| Headings, button labels, nav labels | `var(--font-heading)` (Inter 500) |
| Body text, descriptions | `var(--font-body)` (Inter 400) |
| Slugs, IDs, timestamps, durations, counts, code | `var(--mono)` (ui-monospace, Menlo, monospace) |
| Section labels | `.klabel` (Inter 500 10px uppercase) |
| Run IDs, commit SHAs, branch names | Monospace |
| Repository names | Monospace at 12.5px |
| Status labels | Monospace 500 11-12px |

### Truncation
| Pattern | Usage |
|---------|-------|
| `text-overflow:ellipsis; white-space:nowrap; overflow:hidden` | Agent descriptions in table, sidebar labels, step names |
| `-webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden` | Agent descriptions in cards |
| `word-break:break-word; white-space:pre-wrap` | Log messages (wrap, don't truncate) |
