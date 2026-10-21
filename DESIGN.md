# DESIGN.md — Agent Fleet Control Panel

## Changelog

| Version | Date       | Summary                                                                                         | Author           |
| ------- | ---------- | ----------------------------------------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-08-26 | Initial version. Extracted from high-fidelity prototype at `/docs/prototype/` (Nocturne DS). Documents design system, tokens, component inventory, layout architecture, screen specifications, interaction patterns, and formatting conventions. | product-engineer |
| 1.1     | 2026-09-04 | Resolved the three self-contradictions the S-105 audit found in this document ([`workstream/archive/fidelity-report-S-105.md`](workstream/archive/fidelity-report-S-105.md) drift D1–D3), each in favor of the single consistent reading. **D1 — status-pill tint is a uniform 14%** for every status; §8.1 previously gave `running`/`queued` 16% while §3.4 specified 14% for all, with no rationale for the exception. **D2 — pulse cadence is 1.6s everywhere**, including `queued`, which §8.1 alone put at 1.4s. **D3 — §7.1 now defines one relative-time form, not two**; the "Dashboard last run — short relative" row (`14m ago`) is removed, so the run history table and the dashboard share `formatRelative`, and a screen never formats a relative time itself. All three now match the implementation shipped in S-105, so no code changes: this is the document catching up to a codebase that had already resolved the ambiguity the only way it could. Decided before Wave 3 started, because D3 was S-107 scope. | product-engineer |
| 1.2     | 2026-09-09 | Added **§5.5 Login (`/login`)** to the screen specifications (Story S-119 / issue #158). Documents the panel's only public, shell-free screen: the centered Nocturne card, the brand row reusing the §4.1 sidebar mark + wordmark, the "Sign in" heading + invitation-only subtitle, the faded rule, the `EMAIL`/`PASSWORD` fields with the keyboard-operable `SHOW`/`HIDE` toggle (`aria-pressed`, defaults masked), the full-width primary Sign in button with its pending/disabled state, the `role="alert"` region carrying the single generic anti-enumeration credential message, the footer row with the **dead** `aria-disabled` "Forgot password?" non-link and the monospace region tag, and the 12-hour session fine print. Token-only CSS Modules, label-associated fields, `:focus-visible` rings. Documentation catching up to the screen shipped in S-119 — no new visual token or component introduced (reuses `Input`/`Button`/`KLabel` and the §4.1 brand pattern). | developer |
| 1.3     | 2026-09-09 | Added the **sidebar footer Log out affordance** to **§4.1 App Shell** (Story S-120 / issue #159). Documents the footer's two stacked controls and their order — **Log out below "System health" and above "Collapse"** — sharing the footer-control grid (icon + label, icon-only when collapsed). Log out uses the Phosphor `Power` icon (§10) and is a **POST-only** `<form action="/api/auth/logout">` submit button (a GET logout is CSRF-triggerable); the accessible name "Log out" is preserved in the collapsed icon-only state; token-only CSS, global `:focus-visible` ring. **Visibility gate:** the item renders only when the request is authenticated and is absent when unauthenticated, with auth state passed into the shell as a server-provided prop (the authenticated route-group layout computes it) — the shell performs no auth I/O (SD2 preserved). Documentation catching up to the affordance shipped in S-120 — no new visual token or component introduced (reuses the §4.1 footer `.toggle` grid pattern and the `Power` icon already in §10). | developer |
| 1.4     | 2026-09-11 | Drift-reconciliation write-back (auth go-public pass, issue #162). Two documentation-only corrections catching the design contract up to shipped reality; no visual token or component change. **§5.1 Agents Dashboard** — annotated the "time range filter (7d/30d/all)" common-element line: the chips were **deliberately not built** (S-107 scope decision), the dashboard ships the name+slug filter input only over "all" runs, because a client-side window misreports the loaded-set counts and a server-side window reintroduces the refetch the density toggle avoids. **§8.2 Outcome Tags** — added **`N/A`** (the `not_applicable` outcome) to the known-values list, which the run-history screen (S-108) already renders via `outcomeLabel`; it was omitted here and is distinct from `—` (pending/none). Source: `workstream/drift-reconciliation-2026-09-11-auth-go-public.md`; companion write-backs in PRD v2.5 and spec v1.7. | product-engineer |
| 1.5     | 2026-09-15 | Fixed a self-contradiction in **§8.1 Status → Visual Mapping**: the `queued` row said `pulse 1.6s`, contradicting §6.1's own animation table, which already listed `spin` as "Loading spinner (queued)". §6.1 is the authority (it is the more specific animation-catalog source); the §8.1 row now reads `spin 0.9s`. This documentation fix accompanies the corresponding code fix (Story S-142 / issue #202) that flipped `queued`'s `StatusMeta` entry from `pulse:true` to `spin:true`, matching this table. No new visual token or component introduced — `spin` was already defined and unused in `styles/globals.css`. | developer |
| 1.6     | 2026-09-15 | **§5.2 Agent Run History**'s filter bar/pagination/empty-state contract shipped as written (Story S-143 / issue #203) — documentation catching up to the built screen, no visual-contract change. One clarification: the search input's placeholder reads "repository or run id", but the shipped free-text match is a `repository_full_name` substring plus an **exact** `id` match only (a run-id *substring* match is not reachable through the read layer without a schema change — a query-shape constraint, see `docs/technical-guidelines.md` row 1.36); §5.2's "search input" bullet is otherwise unchanged. No new visual token or component introduced — reuses `Input`, `Button`, `StatusDot`, and the existing token set. | developer |
| 1.7     | 2026-09-15 | Added **§5.6 Repositories (`/repositories`)** (Story S-147 / issue #207, FR15/FR16/FR18). Documents the list + Add-repository form as a **first-pass layout, not a dedicated `ux-engineer` design pass** (spec Open Question #4 was unresolved when this story started — explicitly flagged rather than improvised silently): the list reuses the `RunHistoryTable` semantic-table-on-CSS-grid pattern with a `Tag`-based enabled/disabled state; the form reuses `LoginForm`'s field-row + `role="alert"` + pending/disabled double-submit pattern. No Archive action yet (Story S-148 scope). Sidebar "Repositories" flips from `DisabledNavItem` to a live `NavItem`. No new visual token or component variant introduced — every primitive used (`Tag`, `Input`, `Button`, `KLabel`) already existed. | developer |
| 1.8     | 2026-09-15 | Extended **§5.6 Repositories** with the **Archive action** (Story S-148 / issue #208, FR17). Documents the new Actions column + per-row "Archive" button and the panel's **first destructive-action confirm dialog** (a minimal, accessible `role="dialog"`/`aria-modal="true"` overlay — not a reusable primitive, since no other screen has one yet): names the repository, states the consequence in plain language (stops appearing as an invocation target; existing runs keep their history/name unchanged; not undoable from the UI, AC6), Cancel/Confirm actions, and a `router.refresh()`-driven re-fetch on success rather than client-side row removal. No new visual token — reuses `Button` (`variant="ghost"`/`"secondary"`/`"primary"`), the existing `--space-*`/`--rule`/`--st-fail` tokens, and the `role="alert"` error pattern already established by `AddRepositoryForm`. | developer |
| 1.9     | 2026-09-15 | Planner-level drift pass (`integration/panel-v3-ui-depth` pre-merge check): added **§5.2a All Runs (`/runs`)** — Story S-146 / issue #206 shipped this cross-agent feed screen with no corresponding §5 section; it was documented in the changelog (row 1.39 there is none — see `docs/technical-guidelines.md` row 1.39) but never given its own screen-spec entry here. §5.2a documents it as a pure composition of the existing §5.2 filter bar + table plus one Agent column, matching the shipped code. Also added a **"Sidebar nav item state (current)"** note to **§4.1** stating plainly which of the five nav items are live (Agents, All runs, Repositories) versus still disabled (Settings, System health) — this fact was previously only recoverable by reading each screen section's closing sentence individually. Current-state, documentation-only additions; no visual token, component, or behavior change. | technical-writer |
| 1.11    | 2026-10-13 | Added the **Agent Scheduler** screen specs (Phase 4, [`prd-agent-scheduler.md`](requirements/prd-agent-scheduler.md) / [`specification-prd-agent-scheduler.md`](../workstream/specification-prd-agent-scheduler.md)), pinned to the delivered Nocturne prototype (`docs/prototype/Agent Scheduler.dc.html`, same `_ds` bundle hash as the existing screens — zero DS divergence). New **§5.7 Schedules (`/schedules`)** (the fleet-wide list: State/Agent/Repository/Cadence/Next run/Last run/Actions semantic-table-on-grid, the unified blocked/skipped reason chip + "PR handled · resume anyway" ghost action, the New/Edit dialog with the schema-driven param form + cadence picker + live summary + next-3-runs preview + collapsible guardrails, and the delete `alertdialog`) and **§5.8 Notifications (`/notifications` + top-bar bell)** (the bell + unread badge + popover, and the full grouped feed). **§4.1** nav-state note updated: **Schedules** and **Notifications** are now live nav destinations (four of six items live; Settings + System health remain disabled). **§10** gains the scheduler icons (`CalendarDots` Schedules, `Bell` Notifications, plus the row-action `Pencil`/`Trash`/`Play`/`Pause` and reason `GitPullRequest`/`Warning`/`SkipForward`/`LockSimple`). No new visual token or component variant introduced — every surface reuses existing primitives (semantic table, `Button` ghost/primary/secondary, `Tag`/status-pill pattern, segmented control `.seg`, toggle switch, the dialog shell, `KLabel`). Documentation locking the design contract to the reviewed prototype ahead of story generation. | product-engineer |
| 1.10    | 2026-09-17 | Added the **audit-report findings block** to **§5.3 Run Detail** (issue #241). `audit_report` artifacts carry their content in `metadata` and have no URL by design, so the pill link alone showed nothing reviewable. The summary now renders, under the artifact pills, one findings block per `audit_report`: a summary line (total, per-tool and per-severity counts, before→after bucket counts for fix-mode reports) and a semantic `<table>` on the §4.4 CSS-grid pattern (tool · severity · bucket · `path:line` · rule · message), with a generic key/value `<dl>` fallback for unrecognized metadata shapes and an explicit "No findings." empty state. Severity text is tinted with the existing §2.4 status tokens (`--st-fail` for critical/high, `--st-timeout` for medium, `--faint` for low) via a per-row custom property, mirroring `StatusPill`'s `--st-color` mechanism. Metadata is untrusted and renders as text only (no markup, no links) — the same posture as §5.3's artifact-link guard. No new token or component variant introduced; header/row typography reuses the §2 table tokens. | developer |
| 1.11    | 2026-10-13 | Added the **findings disclosure** to the **§5.3 Run Detail** audit-report block (issue #245). A large `audit_report` previously pushed the steps panel, log toolbar, and log viewer off screen, breaking §4.2's "no outer scroll" contract. The findings table is now wrapped in a native `<details>`/`<summary>`: the summary line is the always-visible `<summary>`, the table is the collapsible body. Default state is server-rendered via the `open` attribute — open at **10 rendered rows or fewer** (counting `view.rows.length`, not the agent-reported `total_findings`), closed above. When open, the body is a scroll container capped at `max-height: 40vh; overflow-y: auto` (the cap sits on the body container, not on `<details>`, so the summary stays visible). Paired with a **`min-height: 240px` log-section floor** on `RunDetailLogSection`'s `.section`, so the steps panel/toolbar/viewer never collapse to zero; the 40vh cap yields first on short viewports. The empty state and the key/value fallback have no table and therefore no disclosure. The `<summary>` keeps a visible `:focus-visible` ring. The component stays server-safe (no `"use client"`) and metadata stays escaped text. No new token or component variant — reuses §2 typography and the existing `--space-*`/`--radius-md`/`--color-accent-400` tokens. | developer |
| 1.12    | 2026-10-20 | Added **§5.9 Webhooks (`/webhooks`)** (Webhook Triggers Phase 1, Story S-176 / issue #321, D-W13). Documents the endpoint list (Status / Endpoint / Events / Rules / Payload URL / Actions on the §5.7 semantic-table-on-grid), the New/Edit endpoint dialog (source segmented control fixed after creation; generic-only header fields; event checkboxes + an "Other events" field; bot-author and enabled toggles), the **show-once signing-secret dialog** (closes only on an explicit "I've stored it", no Escape/backdrop close, secret never re-displayed), and the delete and rotate `alertdialog`s. **§4.1** nav-state note: **Webhooks** is live after Schedules (six of eight items live); this also corrects the previous note, which said "four of six" while listing five. **§10** gains `WebhooksLogo`, `Copy` and `ArrowsClockwise`. No new visual token or component variant: every surface reuses the §5.7 table, the §3.4 pill mechanism, `Tag`, `Toggle`, `Button`, `KLabel` and the §5.7.2 dialog shell. First-pass layout without a dedicated `ux-engineer` prototype, flagged as with §5.6. | developer |
| 1.13    | 2026-10-20 | Added **§5.9.4 Endpoint page** (`/webhooks/[id]`) and **§5.9.5 Rule dialog** (Story S-177 / issue #322, D-W7/D-W13): the numbered rule list in match order with the first-match note, the default rule in its own section, per-row text summary (events, conditions, agent, repository source) with ↑/↓ reorder, enable/disable, edit and delete; and the rule dialog's When / Run / Guardrails groups (event checkboxes from the endpoint allowlist, AND-ed condition rows, agent select, repository from a payload path or fixed, the reused `FieldRow` param grid, "fill from the payload" rows, threshold and toggles). Validation runs on the server before anything is stored; errors render inline and a summary sits next to Save. Endpoint names in the §5.9 list now link to the endpoint page. No new token or component variant. | developer |
| 1.14    | 2026-10-20 | Added **§5.9.6 Delivery log** (Story S-178 / issue #323, D-W11/D-W13, FR23) on the endpoint page: a newest-first semantic table (Received relative + absolute UTC · Event · Delivery ID · Signature · Rule · Outcome pill + plain-language reason + `Open run ▸` for `fired`), keyset-paged with **Older ▸ / ◂ Newest** links, the configured retention stated in the header, and the dashed empty state. Untrusted header and reason values render as text only. No new token or component variant: the §5.7 table grid, the §3.4 pill mechanism and the §5.8 muted reason line. | developer |

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

#### Sidebar footer — Log out (authenticated only)

The sidebar footer holds two controls, stacked in this order, sharing the footer-control grid pattern (icon + label, icon-only when collapsed):

1. **Log out** — the session-ending affordance, shown **below "System health" and above "Collapse"**. It uses the Phosphor `Power` icon (§10) and is a plain `<form method="post" action="/api/auth/logout">` submit button (POST-only: a GET logout is CSRF-triggerable and can be fired by a prefetcher). The accessible name stays "Log out" in both expanded and collapsed states, so the icon-only collapsed control remains labeled. It reuses the footer `.toggle` grid + hover tint, token-only, and the global `:focus-visible` accent ring.
2. **Collapse / Expand** — the existing sidebar toggle (`«`/`»`, `Cmd/Ctrl+\`).

Visibility: **Log out renders only when the request is authenticated, and is absent entirely when unauthenticated.** Authentication state is passed into the shell as a server-provided prop (the authenticated route-group layout computes it via the auth-server client) — the shell performs no auth I/O itself (SD2 preserved).

#### Sidebar nav item state (current)

As of Webhook Triggers Phase 1 (§5.9), **six of the eight primary nav items are
live links**: Agents (since S-101), **All runs** (S-146, §5.2a), **Repositories**
(S-147, §5.6), **Schedules** (§5.7, `CalendarDots`), **Webhooks** (S-176, §5.9,
`WebhooksLogo`, right after Schedules) and **Notifications** (§5.8, `Bell`,
carrying the unread badge). **Two remain
`DisabledNavItem`** — Settings and System health (`aria-disabled`, "not
available in this phase", not focusable, per PRD §10). (Before Phase 4 only the
first three were live; Schedules and Notifications were disabled placeholders.)

### 4.2 Run Detail (full-height, no outer scroll)

```
flex-direction: column; (fills content area)
├── Breadcrumb + actions (flex: none)
├── [Optional banner] (flex: none)
├── Summary panel (flex: none, 2-column grid)
│   grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr)
│   gap: 28px
├── Steps panel (flex: none, vertical list — §5.3, Story S-145)
├── Log toolbar (flex: none — hosts the log-level filter, §5.3, Story S-145)
├── Log viewer (flex: 1; overflow-y: auto)
└── Log footer (flex: none)
```

**Story S-145 note:** the Steps panel and the Log toolbar's level-filter control
are owned by a single `"use client"` filter-state wrapper
(`components/run-detail/RunDetailLogSection.tsx`) sitting between the Summary
panel and whichever log viewer mounts (terminal `LogViewer` or live
`LiveLogViewer`) — clicking a step row or changing the level select narrows
the SAME already-loaded log window client-side (no new server read); neither
control affects the log viewer's own pagination/live-tail state.

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
  - **Not built (S-107 scope decision, 2026-09-04).** The dashboard ships the **name+slug filter input only**, over "all" runs — the **7d/30d/all time-range chips were deliberately not implemented**: a client-side window would misreport the status-breakdown counts (they are derived from the loaded set), and a server-side window needs a `searchParams` write that reintroduces a refetch the density toggle is specifically designed to avoid. If a time window is wanted later it belongs to the v3 UI-depth run-history filtering work, not the dashboard header. See `technical-guidelines.md` row 1.18.
- Per-agent: status dot, name (heading weight), slug (mono, accent-400), description (muted, truncated), run count, status breakdown, last run time + outcome tag, action button

### 5.2 Agent Run History

- Agent header with breadcrumb, name, description, metadata (params count, p50 duration, success rate)
- Filter bar: status segmented control (with colored dots + counts), repo chips, search input, live indicator
- Table with columns: Status pill | Outcome tag | Repository + branch + PR | Duration | Steps (n/m) | Started (relative) | Chevron
- Pagination: "X of Y" + "Load more" button
- Empty state: message + CTA buttons

### 5.2a All Runs (`/runs`)

The cross-agent run feed (Story S-146 / issue #206, FR13/FR14), reversing the
v2.1 non-goal that deferred "All runs" out of Phase 2 scope. Visually and
structurally **identical to §5.2's filter bar + table**, composed rather than
redesigned: the same `RunFilterBar` (status counts, repo chips, debounced
search, connection indicator) and the same table, unscoped to any agent
(`agentSlug: null`) — so it reads across the whole fleet, newest-first — plus
one addition: a leading **Agent** column (name + slug, monospace,
`--color-accent-400`, the same agent-identity treatment `AgentCards` already
uses on the dashboard, §5.1). There is no agent header block here (no
metadata to show without an agent scope) and no disabled-agent 404 guard —
a disabled agent's historical runs still appear. Sidebar: the "All runs" item
(§4.1) flips from a `DisabledNavItem` to a live `NavItem` linking to `/runs`,
active on both `/runs` and `/runs/[id]`.

### 5.3 Run Detail

- Full-height layout (log viewer owns the scroll)
- Summary: status pill, outcome tag, title (Run ID), repository (accent-300), metadata grid (queued/started/finished/duration/branch), artifact links (pill-shaped)
- Audit-report findings (issue #241): for each `audit_report` artifact, directly under the artifact pills — summary line (`N findings`, per-tool and per-severity counts; fix-mode reports add `before → after` bucket counts), then a semantic `<table>` on the §4.4 grid pattern with columns tool · severity · bucket · location (`path:line`, mono) · rule (mono) · message (muted). Severity tinted via §2.4 status tokens (critical/high `--st-fail`, medium `--st-timeout`, low `--faint`). Unrecognized metadata shapes render a key/value `<dl>` fallback; zero findings render "No findings."; more than 500 rows render a "N more not shown." note. Renders on every run status (same rule as the artifact pills). All metadata is untrusted and rendered as text only — never markup, never a link.
  - **Findings disclosure (issue #245).** The findings table is wrapped in a native `<details>`/`<summary>` so a large report cannot push the steps panel, log toolbar, and log viewer off screen (§4.2 "no outer scroll"). The summary line (and the fix-mode `before → after` row) is the `<summary>` content and is **always visible**; the table is the collapsible body. **Default state** is server-rendered via the `open` attribute: open when the report has **10 rendered rows or fewer**, closed when it has more. The threshold counts **rendered rows** (`view.rows.length`, ≤ 500 `MAX_ROWS`) — not the agent-reported `total_findings` — because the rendered rows are what take up space. When open, the body is a scroll container capped at `max-height: 40vh` with `overflow-y: auto` (the cap sits on the body container, not on `<details>`, so the summary line stays visible). The empty state and the generic key/value fallback have no table and therefore no disclosure. The `<summary>` keeps a visible keyboard focus ring (`:focus-visible`, `--color-accent-400`). The component stays presentational and server-safe — no `"use client"`. Paired with it, `RunDetailLogSection`'s `.section` carries a `min-height: 240px` **log-section floor** so the steps panel, toolbar, and viewer never collapse to zero; on short viewports the 40vh table cap yields before the floor does. No new token or component variant — the summary reuses §2 typography and the existing `--space-*`/`--radius-md`/`--color-accent-400` tokens.
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

### 5.5 Login (`/login`)

The only public screen — rendered **outside** the app shell (no sidebar, no top bar), on the page background, as a single centered card (`--color-surface`, `--radius-lg`, `--shadow-lg`, max-width ~360px). Reached when the auth gate (S-117) redirects an unauthenticated request; an already-authenticated visit redirects to `/`.

- **Brand row:** reuses the sidebar brand markup pattern — the accent-bordered mark with its glowing dot + the "Agent Fleet" wordmark (§4.1).
- **"Sign in" heading:** h-scale heading, weight 500 (§2.6).
- **Invitation subtitle:** `--muted`, ~12.5px body — invitation-only, contact an administrator.
- **Faded rule:** the Nocturne fade-to-transparent divider (§1.1).
- **`EMAIL` field:** `KLabel` + `Input` (`type="email"`, `autoComplete="email"`, placeholder `you@company.com`).
- **`PASSWORD` field:** `KLabel` + `Input` (`autoComplete="current-password"`) with a **`SHOW`/`HIDE` toggle** right-aligned on the label row — a text button (accent, klabel-scale), keyboard-operable, `aria-pressed` reflecting the revealed state; the field **defaults to masked**.
- **Sign in button:** `Button` `variant="primary"`, **full width**; disabled and showing a pending label while submitting (prevents double submit).
- **Error region:** a `role="alert"` panel above the fields, tinted with `--st-fail`, carrying the **single generic** "Invalid email or password." message — unknown-email and wrong-password are indistinguishable (anti-enumeration).
- **Footer row:** a **dead "Forgot password?"** control — a styled non-link `<span>` with `aria-disabled`, `--faint`, `not-allowed` cursor (never an `<a href="#">`, never activatable) — and a monospace `· <region>` tag (`--faint`, non-secret display value).
- **Fine print:** "Sessions expire after 12 hours of inactivity." (`--faint`).

Styling is token-only CSS Modules (Nocturne token discipline). Fields are label-associated, the form is semantic, and focus rings use the global `:focus-visible` accent ring.

### 5.6 Repositories (`/repositories`)

> **First-pass layout, not a dedicated `ux-engineer` design pass.** Spec §10 assumed a `ux-engineer` pass would produce this section before Story S-147 started implementation (spec Open Question #4); that pass had not landed by the time S-147 was executed. Per the story's explicit fallback instruction, this section documents a first-pass layout composed entirely from EXISTING Nocturne primitives and established screen patterns — no new visual token, no new component variant — so the screen ships legibly rather than blocking on an unavailable design pass. **This is flagged here deliberately so a future design review can revisit it on purpose, rather than the gap going unnoticed.**

A single server-rendered screen (`app/(panel)/repositories/page.tsx`) composed of two stacked sections, each headed by a `KLabel` eyebrow (§3.7):

- **"Registered repositories"** — the list, rendered by `RepositoryTable`. Reuses the `RunHistoryTable` pattern exactly: a semantic `<table>` laid out on a CSS grid per `<tr>` (repository / default branch / state / actions), so it reads as a table to assistive tech rather than a div grid (§4.4 precedent). Columns: `full_name` (monospace, `--color-text`), `default_branch` (monospace, `--muted`), enabled state via a `Tag` (`variant="accent"` "Enabled" / `variant="neutral"` "Disabled", §3.3 — state conveyed by both color and text, never color alone), and (as of Story S-148, issue #208) an **Actions** column with a per-row "Archive" button. An empty list renders a `KLabel` + one line of body copy in a `role="status"` region (mirrors `RunHistoryTable`'s empty state), never a blank area or an error.
- **Archive (Story S-148).** Clicking "Archive" opens the panel's **first destructive-action confirm dialog** — no other screen has one, so this is a simple, minimal, accessible overlay (`role="dialog"`, `aria-modal="true"`, `aria-label="Archive repository"`), not a reusable dialog primitive. The dialog names the repository, explains the consequence in plain language (stops appearing as an invocation target; existing runs keep their history and repository name unchanged; not undoable from the UI — no restore affordance exists, AC6), and offers Cancel / Confirm. Confirming submits the `archiveRepository` Server Action; on success the dialog closes and `router.refresh()` re-runs the server component's read, so the archived row disappears from the default list on the next render (no client-side row removal — matches `AddRepositoryForm`'s "server re-fetch is the source of truth" posture). A server-returned failure keeps the dialog open with an inline `role="alert"` error, never a silent failure. Each row owns an independent action/pending/error state (one row's in-flight archive never affects another row's).
- **"Add repository"** — `AddRepositoryForm`, reusing the `LoginForm` field-row pattern exactly: a `KLabel` + `<label>` above each `Input` (`REPOSITORY` — placeholder `owner/repo`; `DEFAULT BRANCH` — placeholder `main`, optional), a `role="alert"` region above the fields for a server-returned error (duplicate / malformed), an inline per-field error under `REPOSITORY` for the client-side shape check, and a full-width-equivalent `Button variant="primary"` with the same pending/disabled double-submit guard as `LoginForm` (`useFormStatus`, "Adding…" label while pending). On success the fields clear (remounted under a fresh key, same technique `LoginForm` uses to reset its password field after a failure, applied here on the opposite branch) and a `role="status"` line names the added repository.

Sidebar: the "Repositories" item (§4.1) flips from a `DisabledNavItem` to a live `NavItem` linking to `/repositories`, using the same `GitBranch` icon it already had while disabled.

Styling is token-only CSS Modules, following the established grid/spacing/color-token set (`--space-*`, `--rule`, `--faint`, `--muted`, `--color-text`, `--st-fail`, `--st-ok`) — no new token introduced. No new component was built either: `RepositoryTable` and `AddRepositoryForm` are new FILES, but every visual primitive inside them (`Tag`, `Input`, `Button`, `KLabel`) already existed.

### 5.7 Schedules (`/schedules`)

Phase 4 — the Agent Scheduler (PRD/spec Phase 4). Pinned to the reviewed prototype
`docs/prototype/Agent Scheduler.dc.html` (Nocturne, same `_ds` bundle as every other
screen). A new authenticated fleet-wide surface; the sidebar **Schedules** item flips
from `DisabledNavItem` to a live `NavItem` (icon `CalendarDots`, §10). No new visual
token or component variant — every element below reuses an existing primitive.

**Page header.** Flush-left `h1` "Schedules" (`500 21px/1.2 var(--font-heading)`); when
scoped to one agent (arriving from the §5.2 agent-page indicator, §5.7.1), an inline
filter chip `agent: <slug>` (`--color-accent-300`, 999px, 1px rule border) with an `✕`
clear control, and a mirrored breadcrumb `Schedules / <slug>` in the top bar. A summary
stat line in mono/`--faint`: `N schedules · M paused · K blocked` (the blocked count
tints `--st-timeout` when non-zero), plus the standing note `all times
America/Santiago unless noted`. Right-aligned primary **New schedule** button
(`btn-primary`, `Plus` icon) opening the §5.7.2 dialog.

**Table (semantic `<table>` on the §4.4 CSS-grid pattern).** `role="table"`, min-width
1080px (horizontal scroll below that — this is a wide table on a 1024px floor, §9),
grid columns `100px minmax(150px,1.1fr) minmax(170px,1.25fr) minmax(150px,1.1fr) 120px
136px 184px`. Uppercase 10px `.klabel` headers; the header rule and each row's bottom
rule use the Nocturne **fade-to-transparent-at-48px** gradient (§1.1), not a flat
border. Row hover = 4% text tint. Columns:

- **State** — a status-pill (§3.4 pattern, `500 10.5px mono`, 999px, 14%/13%/6% tint):
  `active` (`--st-ok` solid dot), `blocked` (`--st-timeout` solid dot), `paused`
  (`--muted` text, **hollow** dot — border only, mirroring `failed_to_start` §8.1).
- **Agent** — name (`500 13px heading`) over slug (`mono 11px --color-accent-400`).
- **Repository** — `owner/repo` (`mono --color-accent-300`, ellipsis) over a branch row
  (`mono 11px --muted` with a `GitBranch` glyph).
- **Cadence** — the human summary (`mono --color-text`): `Daily · 07:00`, `Weekly · Mon
  04:00`, `Every 6h`, `Hourly`, or `Cron · 0 4 * * 1`; the IANA timezone below in
  `mono 10.5px --faint`.
- **Next run** — relative (`in 3h 40m`, `tomorrow 07:00`, `Thu 05:00`) in mono over the
  absolute `Wed 14 Oct · 07:00` sub-line; `—` when paused, `held` (`--faint`) when
  blocked with a `tick … skipped` sub-line.
- **Last run** — a compact outcome pill (`success`/`failed`/`timed_out`, §8 colors)
  over `<ago> ↗`, the whole cell linking to that run's `/runs/[id]`.
- **Actions** — right-aligned ghost buttons: **Pause/Resume** (toggle, `Pause`/`Play`
  icon + label), **Edit** (`Pencil`, icon-only 28px), **Delete** (`Trash`, icon-only;
  hover tints `--st-fail` + a `--st-fail` 50% border).

**Blocked / skipped reason row (unified, spec SD-G6).** When a row is `blocked` or was
recently `skipped`, a second row spanning columns 2→end shows one reason chip
(`mono 10.5px`, 6px radius, 1px tinted border, a leading glyph): `open_pr` →
`GitPullRequest` + `--st-timeout` ("Blocked: PR #214 awaiting review"); `auto_paused`
→ `Warning` + `--st-timeout`; manual pause → `Pause` + `--muted`; `concurrency_cap` /
`missed_tick` → `SkipForward` + `--faint`. An `open_pr` block additionally renders a
ghost **"PR handled · resume anyway"** button (the G5-c manual clear).

**Empty state.** A dashed-border panel (`KLabel` "Schedules" + one muted line — "No
schedules yet." or "No schedules for `<slug>` yet." when filtered — + the New schedule
CTA), never a blank area.

**On create/edit success**, the affected row flashes a 2px `--color-accent` left inset
(`rise`-adjacent, transient ~2.4s) — the server-refetch-is-truth posture (§5.6), the
flash is purely a confirmation cue.

#### 5.7.1 Agent-page scheduled indicator (`/agents/[slug]`)

A read-only pointer in the agent run-history header (§5.2): a small `mono`/`Tag` count
`N schedules` linking to `/schedules?agent=<slug>` (which renders the header filter
chip above). No CRUD on the agent page — the indicator is a link only.

#### 5.7.2 New / Edit schedule dialog

A centered modal over a `--color-neutral-900` 62% backdrop, max-width 760px,
`--color-bg` panel, `--radius-lg` (14px), `--shadow-lg`, `rise` entrance — the same
dialog shell family as §5.4 Invoke. Header: title ("New schedule" / "Edit schedule") +
the selected agent slug (`mono --color-accent-300`) + an `X` close. Scrolls within the
viewport; sticky-feel footer band.

- **Agent select** — `select.input` (mono), enabled agents only; a disabled agent shows
  `(disabled)` and is non-selectable. Changing the agent reloads the param rows from
  that agent's schema and resets param values to the schema defaults.
- **Repository select** — rendered **separately, first** (same rule as §5.4), only when
  the agent `requires_repository`. A hint line shows `branch: <default> (default)` once
  picked, `20 repos connected` before, or a `--st-fail` "required — pick a repository"
  when the form was submitted invalid.
- **Parameters** — a `KLabel` "Parameters" + `from parameters_schema` note, then the
  **schema-driven `fieldrow` grid** (`minmax(0,1fr) minmax(200px,268px)`, 22px gap,
  top-ruled rows), identical in shape to §5.4: left column = the param key (`mono 500`),
  a `.ftype` chip (`string · enum`, `integer · 1–5`, `boolean`, …), a `*` required
  marker, and the description; right column = the control (`select` for enums, the §3.10
  **toggle switch** for booleans with an `on`/`off` mono label, `number`/`text` input
  otherwise) + a `default: <x>` hint.
- **Cadence** — a `KLabel` "Cadence" + `when this schedule fires`, then a **segmented
  control** (`.seg`/`.seg-opt`, §forms) over `Hourly · Daily · Weekly · Every N hours ·
  Advanced (cron)` (the selected option reads `--color-accent`). Below, a two-column
  grid: **left** = the kind-specific fields — `Hourly` shows an explanatory line; `Daily`
  a `time` input (`HH:MM`); `Weekly` a weekday `select` + the `time` input; `Every N
  hours` a bounded number input (1–23) with an inline `--st-fail` range error; `Advanced
  (cron)` a `mono` cron Input (placeholder `0 4 * * 1`, border tints `--st-fail` on an
  invalid expression) with a live hint (`✓ valid · first fire …` in `--st-ok`, or the
  parse error in `--st-fail`) and the field legend `minute · hour · day-of-month · month
  · day-of-week`; and in every kind a **Timezone** `select` defaulting
  `America/Santiago`. **Right** = a bordered **Preview** card (`KLabel` "Preview", a
  `500 13px` human summary e.g. "Runs daily at 07:00 America/Santiago", the derived
  `cron …` line in `mono --faint`, and a ruled **Next 3 runs** list of absolute+relative
  times in mono). The summary/preview recompute live from the cadence fields (spec SD-T6
  — the real panel sources these from the authoritative DB RPC, not a TS reimpl).
- **Advanced · guardrails** — a collapsible disclosure (`CaretRight`/`CaretDown`, a
  one-line `pause after N · success email on/off` summary when collapsed): an
  **Auto-pause after failures** number input (default 3) and an **Email me when a run
  succeeds** toggle (default off, with the note that failures/auto-pauses always notify
  and successes otherwise only appear in the daily digest). Two read-only always-on
  guardrail lines (`LockSimple` glyph, `--muted`): "Won't fire while a prior run is still
  active" (G1) and "Won't fire while a prior run's PR is open" (G5).
- **Footer** — a left hint (`POST /schedules · first fire <rel>`, or a `--st-fail` "Fix
  the highlighted fields to continue" when invalid) + **Cancel** (ghost) + a primary
  **Create schedule** / **Save** button carrying a pending dot + "Creating…"/"Saving…"
  label and a disabled state while submitting or while the cadence is invalid.

#### 5.7.3 Delete confirm dialog

The §5.6/§3-pattern destructive confirm, as an `alertdialog` (`role="alertdialog"`,
`aria-modal`): "Delete schedule?", a plain-language body naming the agent + repo +
cadence (`mono --color-accent-300`) and stating "will stop firing. Past runs and their
logs are kept.", Cancel (ghost) + a `btn-secondary` **Delete schedule** tinted
`--st-fail` (hover fills a 12% `--st-fail` tint). Deleting a schedule never deletes its
produced runs (the `on delete set null` FK, spec §2).

### 5.8 Notifications (`/notifications` + top-bar bell)

Phase 4. The channel-agnostic `notifications` table surfaced in-panel (spec SD-N5). Two
entry points share one data source:

**Top-bar bell.** A `btn-ghost` icon button (`Bell`, §10) in the top bar's right cluster
(beside the realtime/region indicators and the user email). An **unread badge** —
`min-width 15px`, 999px, `--color-accent` fill, `--color-bg` text, a 2px `--color-bg`
ring so it reads over the bar — shows the unread count; absent at zero. Clicking opens a
**popover** (384px, `--color-surface`, `--radius 12px`, `--shadow-lg`, `rise` entrance,
closed by an invisible full-viewport scrim): a header ("Notifications" + a "Mark all
read" ghost shown only when unread > 0), up to 5 newest items (the §5.8 item row), an
empty state (`KLabel` "Inbox" + "No notifications."), and a footer (`<unread> unread ·
<total> total` + a "View all ▸" link to `/notifications`).

**Feed (`/notifications`).** A single-column surface, max-width 780px. Header `h1`
"Notifications" + a `mono --faint` stat (`<unread> unread · <total> total · newest
first`) + a "Mark all read" ghost (dimmed to 0.45 when nothing is unread). The list is
grouped by day with `.klabel` group headers ("Today" / "Earlier"). Each **item row** is
a `8px minmax(0,1fr) auto` grid:

- a leading **kind dot** (7px) colored by kind — `run_succeeded` `--st-ok`,
  `run_failed` `--st-fail`, `schedule_auto_paused` `--st-timeout`, `pr_opened`
  `--color-accent` — with a `box-shadow` glow when unread;
- a title (`13px body`; **unread** = `--color-text` weight 500 + a 2px `--color-accent`
  left edge + a 5% accent background; **read** = `--muted` weight 400, transparent edge),
  e.g. "security-analyst run failed on llipe/ripley-ingest", "Schedule auto-paused after
  3 failures", "dependency-update opened a PR on llipe/thinkfirst-web";
- a `mono --muted` detail line (reason / `error_code` / PR note — **untrusted, rendered
  as text only**, never markup or a metadata-built link, same posture as §5.3);
- optional `mono` links ("Open run ▸" → `/runs/[id]`, "View schedule ▸" → `/schedules`,
  "PR #214 ↗");
- a `mono 10.5px --faint` relative timestamp, right-aligned.

Clicking an item marks it read (clears the unread treatment). An empty feed shows the
dashed `KLabel` "Inbox" + "No notifications." panel. A persistent `mono --faint` footer
states: **"A daily email digest of these is sent at 08:00 America/Santiago."** (the SES
digest, spec SD-N6 — the panel feed and the digest are two consumers of the same table).

Server-read (SD2, RLS deny-all); mark-(all)-read is a Server Action; routes declare
inline route-segment config. No new visual token or component variant — the bell reuses
`btn-ghost`, the badge/dots reuse the status-pill color mechanism, the rows reuse the
`KLabel` + mono/body type set.

### 5.9 Webhooks (`/webhooks`)

Webhook Triggers Phase 1 (S-176, D-W13). An authenticated fleet-wide surface for the
inbound endpoints GitHub (or another HMAC-signing sender) posts to. The sidebar
**Webhooks** item (`WebhooksLogo`, §10) sits right after Schedules. First-pass layout
with no dedicated prototype; it reuses the §5.7 primitives, and no token is new.

**Page header.** `h1` "Webhooks" (the §5.7 heading), then the mono/`--faint` stat line
`N endpoints · M enabled · K rules · every delivery is signature-checked`. A right-
aligned primary **New endpoint** button (`Plus`).

**Table (semantic `<table aria-label="Webhook endpoints">` on the §4.4 grid).** Min-width
1080px with horizontal scroll below; columns `100px minmax(170px,1.1fr)
minmax(200px,1.3fr) 80px minmax(260px,1.6fr) 176px`; header and row rules, hover tint
and the create/edit accent left inset exactly as §5.7.

- **Status**: §3.4 pill, `enabled` (`--st-ok` solid dot) or `disabled` (`--muted`,
  hollow dot).
- **Endpoint**: name (`500 13px heading`) over the source (`github` / `generic`, mono
  11px `--color-accent-400`).
- **Events**: the first 3 allowlisted events as small `Tag`s, then an outline `+N` tag
  whose `title` lists the rest.
- **Rules**: `N rules` (mono).
- **Payload URL**: `<origin>/api/webhooks/<token>` in mono `--color-accent-300`,
  ellipsized with the full value in `title`, plus an icon-only **Copy URL for
  <name>** button (`Copy`) and a polite live `Copied` confirmation (`--st-ok`).
  The origin is the host the operator is using (display only).
- **Actions**: right-aligned ghost **Enable/Disable** text toggle, then icon-only
  **Edit** (`Pencil`), **Rotate secret** (`ArrowsClockwise`) and **Delete** (`Trash`,
  `--st-fail` hover as §5.7). Every control has an accessible name that includes the
  endpoint name.

**Empty state.** The §5.7 dashed panel: `KLabel` "Webhooks", "No webhook endpoints
yet. Create one to get a URL and secret for GitHub.", and the New endpoint CTA.

**Errors.** A failed toggle, delete or rotate shows a `role="alert"` banner above the
table (the §5.7.2 banner tint). A failed rotate says the old secret is still active.

#### 5.9.1 New / Edit endpoint dialog

The §5.7.2 dialog shell at max-width 640px; Escape and ✕ close it; focus starts on Name.

- **Name**: text input, required, ≤100 characters.
- **Source** (create only): the `.seg` segmented control over **GitHub · Generic**
  (radio inputs), with a one-line hint on the signature scheme. On edit the source
  is shown as fixed text. GitHub's header names are fixed; **Generic** reveals
  **Signature header** (default `x-signature-256`) and **Delivery ID header**
  (default `x-delivery-id`, hint: without one, duplicates are detected by body hash).
- **Events**: a checkbox grid of common GitHub events plus a free-text **Other
  events** input (comma or space separated). At least one is required: deliveries for
  any other event are recorded as `ignored`.
- **Ignore events from the fleet's bot**: §3.10 toggle, default on.
- **Enabled** (edit only): §3.10 toggle; hint "A disabled endpoint answers 404 and
  records nothing."
- **Footer**: Cancel (ghost) and a primary **Create endpoint** / **Save** with a
  `Creating…` / `Saving…` pending state. Server field errors render inline under
  their field (`--st-fail`, `aria-invalid`), and a summary banner sits at the top.

#### 5.9.2 Show-once signing secret

After **create** or **rotate**, a small dialog (`aria-label="Copy the signing
secret"`, max-width 480px) shows a `--st-timeout`-tinted warning ("Copy the secret now.
It won't be shown again."), a one-line setup instruction (GitHub: payload URL, secret,
`application/json`; on rotate, update the sender now or deliveries return 401), and two
read-only mono inputs, **Signing secret** (focused and selected on open) and **Payload
URL**, each with a **Copy** button. It closes **only** on the primary **I've stored
it**: no Escape, no backdrop click. Closing discards the secret; it is never fetched
again, so the only way to get a new one is to rotate.

#### 5.9.3 Delete and rotate confirms

The §5.7.3 `alertdialog` pattern, focus on Cancel, Escape cancels.
- **Delete endpoint?** The endpoint and its N rules are deleted along with its delivery
  log and secret, and its URL stops working. Runs it already started are kept.
- **Rotate the signing secret?** The old secret stops working immediately. Update the
  sender right away or its deliveries return 401.

#### 5.9.4 Endpoint page (`/webhooks/[id]`)

A mono breadcrumb `Webhooks / <name>` (link in `--color-accent-300`), the endpoint name
as `h1`, a `--faint` stat line (`source · enabled · events …`), and the full payload URL
in mono. Below it, **Rules** (`500 16px heading`) with the standing note "The first
matching rule wins, top to bottom. The default rule runs only when nothing else
matches." and a primary **Add rule** button. S-178 adds the delivery log under it.

- **Rule list**: an `<ol aria-label="Rules in match order">`; each row is a
  `32px 1fr auto` grid with the 1-based position (mono `--color-accent-300`), the name
  (`500 13px heading`) plus the §3.4 enabled/disabled pill and, once a rule has
  failed, `N/T failed starts` in `--st-timeout`; a summary line (`on` + event `Tag`s +
  one bordered mono chip per condition, e.g. `comment.body contains /audit`) and a
  target line (`→ <agent> · <repo>` or `repo from <path>`, mono `--muted`). Row rules
  and hover tint as §5.7.
- **Row actions** (right): icon-only **↑ / ↓** (disabled at the edges), the ghost
  **Enable/Disable** text toggle, **Edit** (`Pencil`) and **Delete** (`Trash`). Every
  accessible name includes the rule name. A move sends the whole new order; the
  server renumbers in one statement.
- **Default rule**: a separate `KLabel` "Default rule" section after the list, with
  the summary "when no other rule matches" and no move buttons, because its position
  never matters.
- **Empty state**: the dashed panel, "No rules yet. Every delivery to this endpoint is
  recorded as no match until you add one."
- **Delete confirm**: the §5.7.3 `alertdialog`: the rule stops matching; runs it started
  are kept.

#### 5.9.5 Rule dialog

The §5.7.2 shell at max-width 820px; Escape and ✕ close it; focus starts on the name.
Three groups separated by a top rule, each with an uppercase 10px `--faint` legend:

- **Rule name**, then a **Default rule** §3.10 toggle (hint: one per endpoint). When
  on, the **When** group is hidden.
- **When**: event checkboxes from the endpoint's allowlist only, then condition rows
  (`minmax(0,1.2fr) 140px minmax(0,1fr) 28px`): field path input, operator select
  (`equals · not equals · contains · prefix · suffix · in · exists`), value input
  (`in` takes a comma list; `exists` has no value), and a remove button. Conditions are
  AND-ed. A ghost **+ Add condition** button.
- **Run**: the agent select (a disabled agent is listed but not selectable; changing
  the agent resets the parameters to that agent's defaults), the repository `.seg`
  (**From the payload** with a path input defaulting to `repository.full_name`, or
  **Fixed repository** with a select of enabled repositories), the reused §5.7.2
  `FieldRow` parameter grid, then **Fill from the payload** rows (parameter select +
  path input + remove) with a ghost **+ Add payload value** button.
- **Guardrails**: **Disable after consecutive failed starts** (number, 1–100, default
  3), **Notify me when a run succeeds** and **Enabled** toggles, and a `--faint` line
  naming the always-on guardrails (no overlap, open-PR backoff, fleet-wide cap).
- **Footer**: the server's summary ("Fix the highlighted fields.") in `--st-fail` on
  the left, so it stays visible however far the form is scrolled; Cancel; and the
  primary **Save rule** / `Saving…`. Field errors render under their group.


#### 5.9.6 Delivery log

On the endpoint page, below the rules. A `Deliveries` heading (`500 16px heading`)
with the note "Every request to this URL, newest first. Kept for N days." (N is the
configured retention, `webhook.config`). A semantic `<table aria-label="Deliveries">`
on the §5.7 grid (`150px 150px minmax(160px,1fr) 110px minmax(140px,0.8fr)
minmax(260px,1.4fr)`, rows top-aligned):

- **Received**: §7.1 relative time (mono) over the absolute `YYYY-MM-DD HH:MM:SS UTC`
  (`--faint`).
- **Event** and **Delivery ID**: the sender's header values in mono, ellipsized, `—`
  when absent. They are untrusted and always rendered as text, never markup or links.
- **Signature**: `verified` (`--faint`) or `signature failed` (`--st-fail`).
- **Rule**: the matched rule's name, `deleted rule` when it is gone, `—` when none.
- **Outcome**: a §3.4 pill (`fired` `--st-ok`; `skipped` / `rejected` `--st-timeout`;
  `unauthorized` `--st-fail`; `ignored` / `no match` `--faint`; `duplicate` /
  `received` `--muted`), plus `Open run ▸` (mono `--color-accent-300`) for `fired`
  only. Below it, a plain-language reason in 12px `--muted`: known codes are
  translated (e.g. "A run is already running for this agent and repository.",
  "Signature doesn't match this endpoint's secret."); unknown text is shown as-is,
  capped at 200 characters.

Paging is keyset (`created_at, id`), 50 per page: a right-aligned `Older ▸` link
carries an opaque `?before=` cursor, and `◂ Newest` returns to the first page. A
malformed cursor silently shows the first page. Empty state: the dashed panel, "No
deliveries yet. Every request to this endpoint lands here, including rejected ones."

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
| Relative time — **one form**, used by both the run history table and the dashboard "last run" | `just now` under a minute, `N min ago` under an hour, `Nh ago` under a day, `yesterday` at one day, `Nd ago` beyond | `just now`, `14 min ago`, `6h ago`, `yesterday`, `23d ago` |

**There is one relative-time form, not two** (v1.1 correction). Earlier revisions listed a separate "Dashboard last run — short relative" row with a compact `14m ago`, which produced two forms for the same value and was never implemented. The single form above is what `panel/lib/format.ts` `formatRelative` emits, and both screens use it. If a compact form is ever wanted, it belongs here first as a second named formatter — a screen must never format a relative time itself.

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
| `running` | `var(--color-accent)` | 7px solid + `box-shadow: 0 0 7px` | `pulse 1.6s` | 14% accent |
| `succeeded` | `var(--st-ok)` | 7px solid | none | 14% green |
| `failed` | `var(--st-fail)` | 7px solid | none | 14% red |
| `timed_out` | `var(--st-timeout)` | 7px solid | none | 14% amber |
| `failed_to_start` | `var(--faint)` | 7px hollow (border only) | none | `var(--rule)` |
| `queued` | `var(--color-accent)` | spinning | `spin 0.9s` | 14% accent |

**Pill tint is a uniform 14% for every status** (v1.1 correction). Earlier revisions of this table gave `running` and `queued` 16% while §3.4 specified 14% for all — a self-contradiction inside this document, with no visual rationale for the exception. §3.4 is the authority; 14% applies everywhere. **`running` pulses, `queued` spins** (v1.5 correction) — this row previously said `pulse 1.6s` for `queued`, contradicting §6.1's own animation table (`spin`, "Loading spinner (queued)"); §6.1 is the authority. Both corrections align this table with the implementation shipped in S-105/S-142.

### 8.2 Outcome Tags

Always `.tag-outline` style. Uppercase text. Known values: `FIXED`, `NO VULNS`, `PARTIAL`, `NEEDS REVIEW`, `N/A` (the `not_applicable` outcome — e.g. a run that exits without calling `succeed()`, or an invalid-payload rejection), `—` (pending/none, with opacity 0.45).

> **`N/A` added 2026-09-11.** The run-history screen (S-108) renders `N/A` for the `not_applicable` outcome (`outcomeLabel` in `panel/lib/domain/run-row.ts`), which this list originally omitted — a documentation gap, not a code change. `not_applicable` is a real outcome in the schema enum and is distinct from `—` (no outcome / pending). See `technical-guidelines.md` row 1.19.

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
| ⑃ | Repositories | `GitBranch` / `GitFork` |
| 🗓 | Schedules (nav, §5.7) | `CalendarDots` |
| 🔔 | Notifications (nav + top-bar bell, §5.8) | `Bell` |
| ✎ | Edit schedule (row action, §5.7) | `PencilSimple` |
| 🗑 | Delete schedule (row action, §5.7) | `Trash` |
| ▶ / ⏸ | Resume / Pause schedule (row action, §5.7) | `Play` / `Pause` |
| ⎇ | Open-PR block reason (§5.7) | `GitPullRequest` |
| ⚠ | Auto-pause block reason (§5.7) | `Warning` |
| ⏭ | Skipped reason — cap / missed tick (§5.7) | `SkipForward` |
| 🔒 | Always-on guardrail line (dialog, §5.7.2) | `LockSimple` |
| ⚓ | Webhooks (nav, §5.9) | `WebhooksLogo` |
| ⧉ | Copy URL / secret (§5.9) | `Copy` |
| ↻ | Rotate signing secret (§5.9) | `ArrowsClockwise` |
| ⚙ | Settings | `GearSix` |
| ◈ | System health | `Heartbeat` |
| ⏻ | Log out (sidebar footer, §4.1) | `Power` |
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
