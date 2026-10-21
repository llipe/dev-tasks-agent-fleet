# Claude Design prompt — Agent Scheduler UI (Nocturne)

> Paste the section below into Claude Design to generate the scheduler prototype.
> It is grounded in the existing **Nocturne** design system (`/DESIGN.md`) and the
> scheduler PRD (`docs/requirements/prd-agent-scheduler.md`). When the prototype is
> ready, export the screens (HTML/CSS and/or rendered images) back to this repo so
> `product-engineer` can fold them into `DESIGN.md` §5 and pin each UI story to a
> pixel-accurate reference.
>
> **Screens to produce:** (1) Schedules list `/schedules`, (2) Create/Edit schedule
> dialog with the cadence picker, (3) Notifications feed, (4) the agent-page
> "scheduled" indicator, (5) the sidebar nav-state change.

---

## Prompt

Design a feature for an existing dark, dense, utility control-panel called **Agent Fleet Control Plane**. It uses a design system named **Nocturne**. Match the existing system exactly — do not introduce a new look, new colors, new fonts, or decorative elements. This is an internal single-operator tool; it is deliberately compact and data-dense, outlined rather than filled, low-chroma on a near-neutral blue-grey dark ground.

### Design system to reuse (Nocturne)

**Fonts:** Inter (weights 400/500/600) for all UI text; system monospace (`ui-monospace, Menlo, monospace`) for ALL data values — timestamps, IDs, slugs, durations, counts, cron expressions, cadence summaries, branches.

**Core colors (CSS custom properties — use these, never raw hex):**
- `--color-bg: #161826` (page background)
- `--color-surface: #232532` (cards, inputs, raised surfaces)
- `--color-text: #e9e9ed` (primary text)
- `--color-accent: #9184d9` (blurple — buttons, links, active states; used as a line/glow, never flooded)
- `--color-divider: color-mix(in srgb, #e9e9ed 16%, transparent)` (borders/rules)
- Accent ramp for data: `--color-accent-400: #b5abfc` (slugs), `--color-accent-300: #d2cefd` (repo names/running text)
- Muted text `--muted` = 55% text; faint/disabled `--faint` = 38% text.

**Status colors (for run/schedule states):** `--st-ok: #74b58f` (succeeded/active), `--st-fail: #d1706b` (failed), `--st-timeout: #d1a45e` (timed_out/warning), accent `#9184d9` (running), faint 38% (failed_to_start / paused-muted).

**Spacing (0.7x compact scale):** `--space-1: 2.8px`, `--space-2: 5.6px`, `--space-3: 8.4px`, `--space-4: 11.2px`, `--space-6: 16.8px`, `--space-8: 22.4px`.

**Radius:** small badges 4px, buttons/inputs/cards/nav 8px, dialogs 14px, pills 999px, tags 6px.

**Shadows (elevation = edge + ambient darkness, never heavy stacks):** cards `0 0 0 1px #3f424d`; dialogs `0 0 0 1px #9397ab, 0 16px 40px rgba(0,0,0,0.65)`.

**Typography scale (compact overrides):** page title `500 19–21px`; card/row name `500 13.5–15px`; nav items `400 12.5px`; descriptions `400 11.5–12.5px`; section labels (`.klabel`) `500 10px uppercase, letter-spacing .08em, color faint`; monospace data `400 11–12px`; status pills `500 11px mono`; table headers `500 10px uppercase`.

**Existing components to reuse (do not reinvent):**
- **Button** — outlined, never filled. `primary` = 1px accent border on transparent, accent text; `secondary` = divider border; `ghost` = no border, accent text. Disabled = opacity 0.45.
- **Input** — surface bg, divider border → accent border on focus, 8px radius, accent caret, compact 26–32px height.
- **Tag** — `accent` (accent-800 bg, accent-100 text), `neutral` (neutral-800 bg), `outline` (transparent, accent border). Small: 9.5px, padding 1px 6px, uppercase-ish.
- **StatusPill / StatusDot** — pill: `font 500 11px mono`, 999px radius, background = 14% of the status color; dot = 6–7px, `running` pulses (`pulse 1.6s`), `queued` spins (`spin 0.9s`), `failed_to_start`/paused = hollow dot (border only).
- **KLabel** — 10px uppercase faint eyebrow label above sections.
- **Toggle switch** — 38×21px track, 15px knob; off = transparent bg + divider border; on = accent-tinted bg + accent border + accent knob.
- **Semantic table on CSS grid** — tables are real `<table>` markup laid out via a CSS grid per row (columns like `118px 122px minmax(0,1fr) 96px …`), uppercase 10px headers, rows ~9–11px vertical padding, hover = 4% text tint. Empty state = KLabel + one body line in a `role="status"` region, never a blank area.
- **Confirm dialog** — minimal accessible overlay (`role="dialog"`, `aria-modal`), used for destructive actions; names the target, states the consequence in plain language, Cancel + Confirm.

**App shell:** 212px sidebar (collapses to 52px) on the left (bg = bg mixed 92% with black), 1px divider, then a content area with a 38px top bar (breadcrumb slot + optional right-aligned actions slot) and a scrolling page region under `100dvh; overflow:hidden`. The sidebar has a nav list and a footer (Log out + Collapse). Minimum width 1024px; no responsive breakpoints below that.

**Interaction/formatting conventions:** `:focus-visible` = 2px accent outline, offset 2px (never browser default). Relative times: `just now` / `14 min ago` / `6h ago` / `yesterday` / `23d ago`. Durations: `3m 04s`, running = `running · 2m`. Horizontal rules fade to transparent at both ends. Icons = Phosphor, inline SVG on `currentColor`.

---

### The feature to design: Agent Scheduler

The panel invokes autonomous agents (e.g. `dependency-update`, `security-analyst`) against GitHub repositories. Today invocation is manual. This feature adds **scheduled, unattended invocation on a configurable cadence**, with firing guardrails and a notification system. Design these surfaces:

#### Screen 1 — Schedules list (`/schedules`)

A new primary nav destination (a sidebar item that was previously disabled becomes live — use the Phosphor `CalendarDots` or `Clock` icon). Fleet-wide list of all schedules across all agents.

- Page header: title "Schedules" + a short summary stat line (e.g. `7 schedules · 2 paused · 1 blocked`) + a primary "New schedule" button (opens Screen 2).
- A **semantic table on the Nocturne CSS-grid pattern**, newest-or-name-ordered, with columns:
  - **State** — a StatusPill-style indicator: `active` (st-ok dot), `paused` (hollow/faint dot), `blocked` (st-timeout dot). "Blocked" means a guardrail is currently holding firing (overlap or an unresolved open PR).
  - **Agent** — name (heading weight) + slug (mono, accent-400).
  - **Repository** — `owner/repo` (mono, accent-300) + branch (mono, muted).
  - **Cadence** — a human summary in mono/body, e.g. `Daily · 07:00` or `Weekly · Mon 04:00` or `Every 6h` or `Cron · 0 4 * * 1`, plus the timezone in faint (`America/Santiago`).
  - **Next run** — relative time (`in 3h`, `tomorrow 07:00`) in mono; shows `—` when paused.
  - **Last run** — a small StatusPill of the last produced run's outcome + relative time, linking to that run's detail.
  - **Actions** — Pause/Resume (toggle), Edit, and a Delete that opens the confirm dialog.
- A **"blocked" / "skipped — why" affordance:** when State is `blocked` or a schedule was recently skipped, show a small inline reason chip or tooltip (e.g. "Blocked: open PR awaiting review" or "Skipped last tick: concurrency cap"). When blocked by an open PR, include a **"Resume anyway / PR handled"** small ghost button that clears the manual block.
- Empty state: KLabel + one line ("No schedules yet.") + the New schedule CTA.

#### Screen 2 — Create / Edit schedule (dialog)

A centered dialog (like the existing Invoke dialog, max-width ~760px, dialog shadow + 14px radius). Reuses the schema-driven invoke form and adds a cadence picker.

- Header: "New schedule" (or "Edit schedule") + close (X).
- **Agent select** (dropdown of enabled agents) — selecting an agent drives the rest of the form.
- **Repository select** (dropdown of enabled repos) — rendered separately, first, like the invoke form; only when the agent requires a repository.
- **Params section** — the existing **schema-driven form**: field rows with a left column (label + type + required marker) and a right column control (Toggle for booleans, Select for enums, Input for text/number), 2-column grid. This is generated from the agent's params schema; render a representative example (e.g. a `fix_mode` enum select, a `fail_on_findings` toggle, a `max_fix_attempts` number).
- **Cadence picker** — the centerpiece. A segmented control or radio-row to choose the cadence KIND:
  - **Hourly**
  - **Daily** → a time field (`HH:MM`).
  - **Weekly** → a weekday select (Mon–Sun) + a time field (`HH:MM`).
  - **Every N hours** → a number field (N).
  - **Advanced (cron)** → a monospace cron-expression Input (`0 4 * * 1`) with an inline-validated hint.
  - Below the picker, show a **live human summary** of the resulting cadence (mono/body: "Runs daily at 07:00 America/Santiago") and the **next 3 computed run times** (mono, faint) as a preview.
- **Timezone select** — IANA zones, defaulting to `America/Santiago`.
- **Guardrail settings** (compact, collapsible "Advanced" section): consecutive-failure auto-pause threshold (number, default 3), and a per-schedule "email me when a run succeeds" opt-in toggle (off by default). Overlap suppression and open-PR backoff are always-on and shown as read-only informational lines ("Won't fire while a prior run is still active" / "Won't fire while a prior run's PR is open").
- Footer: a small hint line + Cancel + a primary "Create schedule" (or "Save") button with a pending/disabled state.

#### Screen 3 — Notifications feed

A new surface (could be its own route `/notifications` and/or a top-bar bell affordance with an unread badge — design both the bell indicator and the full feed). Reads a notifications table (the system of record).

- Top-bar **bell icon** (Phosphor `Bell`) with a small accent unread-count badge.
- **Feed** (full view): a vertical list, newest-first, each item a compact row/card:
  - a leading status/kind dot (st-fail for a failed run, st-timeout for an auto-pause, accent for a PR-opened, st-ok for a success),
  - a one-line title (e.g. "security-analyst run failed on owner/repo", "Schedule auto-paused after 3 failures", "dependency-update opened a PR on owner/repo"),
  - a faint relative timestamp (mono),
  - a muted detail line (reason / error code / PR link),
  - a link to the related run detail where applicable,
  - a read/unread treatment (unread = slightly brighter + an accent left-edge; read = muted).
- A "mark all read" ghost action in the header.
- A faint footer note: "A daily email digest of these is sent at 08:00 America/Santiago."
- Empty state: KLabel + "No notifications."

#### Screen 4 — Agent-page scheduled indicator

On the existing agent run-history screen (`/agents/[slug]`), add a small **read-only indicator** in the agent header area showing the agent has schedule(s) attached — e.g. a `Tag` or a small line "`2 schedules`" (mono) that links to `/schedules` filtered to that agent. Do not add CRUD here; it is a pointer only.

#### Screen 5 — Sidebar nav state

Show the sidebar with the **Schedules** item now a live nav link (and, if you design the `/notifications` route, Notifications too), keeping the existing live items (Agents, All runs, Repositories) and the still-disabled items (Settings, System health). Match the existing nav-item active/hover styling (active = 12% accent tint bg + 2px accent left border).

---

### Output guidance

- Produce the five surfaces above as high-fidelity screens at ~1280px content width.
- Reuse ONLY the Nocturne tokens/components described. No new palette, no gradients, no illustrations, no filled primary buttons, no pure black/white.
- Keep everything dense and monospace-for-data.
- The cadence picker's live summary + next-3-run preview is the most important novel element — make it clear and legible.
- Favor the existing semantic-table-on-grid and confirm-dialog patterns so the result drops into the existing panel without visual drift.
