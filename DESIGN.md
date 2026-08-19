# DESIGN.md — Agent Control Plane

The design contract for `apps/control-plane`. Every story that touches UI, UX, or visual behaviour references this document and notes its impact on it.

## Changelog

| Version | Date       | Summary                                              | Author           |
| ------- | ---------- | ---------------------------------------------------- | ---------------- |
| 1.0     | 2026-08-19 | Baseline, derived from PRD v1.0 §11                   | product-engineer |

---

## 1. What this interface is

Four views over one entity. The run is the only entity; the Agents, Agent, and Repos views are the same table under different filters, and the Run panel is a detail surface that opens over any of them.

This is a tool one person opens when they want to know whether something worked, and if not, why. It is read-mostly, dense, and used briefly. It is not a dashboard to be admired and not a product to be onboarded into.

Consequences that follow directly:

- **Density over breathing room.** Scanning twenty runs matters more than a generous layout.
- **No decorative chrome.** No hero sections, no illustrated empty states, no marketing surface.
- **The table is the product.** Everything else supports it.
- **Never lose context.** Opening a run must not replace the list that led to it.

---

## 2. Foundations

Tailwind CSS with shadcn/ui. Tokens are defined once as CSS custom properties following the shadcn convention and consumed through Tailwind theme extensions. **Do not hardcode a colour, spacing, or radius value in a component.**

### Colour

Use the shadcn semantic set — `background`, `foreground`, `card`, `muted`, `muted-foreground`, `border`, `input`, `ring`, `primary`, `destructive`, `accent`. Components reference semantic names, never raw palette values.

Both light and dark schemes are supported from the start, driven by `prefers-color-scheme` with a manual override. Dark is the expected default for this kind of tool; both must be legible.

### Status semantics

Four run states, each with a reserved token pair. These are the only status colours in the interface, and they must not be reused for anything else.

| Status    | Token             | Hue family | Meaning                                             |
| --------- | ----------------- | ---------- | --------------------------------------------------- |
| `running` | `--status-running` | Blue       | In progress, invoked and not yet closed out          |
| `success` | `--status-success` | Green      | Completed successfully                               |
| `failed`  | `--status-failed`  | Red        | Completed with failure                               |
| `stale`   | `--status-stale`   | Amber      | Derived: still `running` after 6 hours. Probably dead. |

`stale` is amber rather than red because it is an inference, not a reported outcome. It says "this looks wrong" rather than "this failed," and the visual language should carry that difference. It is also the one status nobody writes — see PRD §9.

**Status is never communicated by colour alone.** Every status indicator pairs its colour with a text label, and a shape or icon where space allows. Roughly one in twelve men has some form of colour vision deficiency, red/green being the common axis — which is exactly the pair doing the most work here. A badge reading "failed" in red is accessible; a bare red dot is not.

### Typography

One sans-serif family for prose and UI. One monospace family, used strictly for machine identifiers: `session_id`, model IDs, and JSON in the params editor. Monospace is a signal that a value is exact and copyable, so do not use it for emphasis.

Scale is limited: a page title, a section heading, body, and a small size for table metadata. Four steps is enough. Table content sits at body or small, never smaller than 12px.

### Spacing, radius, elevation

Spacing follows Tailwind's 4px-based scale; no arbitrary values. Radius comes from a single `--radius` token. Elevation is used sparingly and only to signal layering — the run panel sits above the table, and nothing else needs a shadow.

---

## 3. Component inventory

Prefer a shadcn/ui primitive over a custom component. Where a primitive needs project-specific behaviour, wrap it rather than forking it.

| Component        | Built on                    | Notes                                                                        |
| ---------------- | --------------------------- | ---------------------------------------------------------------------------- |
| `DataTable`      | TanStack Table + shadcn `Table` | One shared implementation for all four tables. Sorting, filtering, row click, and the loading/empty/error states live here, not in each view. |
| `StatusBadge`    | shadcn `Badge`              | Colour plus label, always both. The single place status maps to visuals.       |
| `RunPanel`       | shadcn `Sheet`              | Right-side overlay. Metadata, span timeline, logs.                            |
| `EnabledToggle`  | shadcn `Switch`             | Optimistic, with rollback and a visible error on failure.                     |
| `ParamsEditor`   | shadcn `Textarea` + `Dialog` | JSON, validated before save. Inline error naming the problem.                 |
| `AddRepoForm`    | shadcn `Input` + `Button`   | Single field, validated repository name.                                      |
| `SpanTimeline`   | Custom                      | Horizontal bars per model/tool call, with latency and tokens.                 |
| `LogViewer`      | Custom                      | Monospace, scrollable, JSON lines from `FilterLogEvents`.                     |
| `CostEstimate`   | Custom                      | Formatted value, always labelled as an estimate.                              |
| `RelativeTime`   | Custom                      | Relative text, absolute UTC timestamp in the title attribute.                 |

---

## 4. Interaction patterns

### Row click opens the panel, not a page

Every table row opens the Run panel as an overlay. The table stays mounted, scrolled where it was, filters intact. This is the mechanism behind the PRD's "under 3 clicks from the run list to a failed run's logs" metric — a navigation that unmounts the list would cost a click on the way back and lose the scroll position.

Panel dismissal: `Esc`, backdrop click, or explicit close. Focus returns to the row that opened it.

### Filter state lives in the URL

Status filters, date ranges, and the selected run serialize to query parameters. Reloading restores the view, and a link to a specific failed run can be saved or shared. It also means server components read filters as props rather than the client re-fetching.

### Writes are optimistic, failures are loud

The `enabled` toggle flips immediately and reconciles against the server. On failure it reverts and shows an error naming what went wrong. A toggle that silently fails is worse than one that blocks, because scope configuration is the one thing here with consequences — a repository the operator believes is enabled but isn't will simply never run, and nothing will report it.

Params saves validate client-side first, then confirm server-side. Invalid JSON never reaches the server.

### Loading is a designed state, not an absence

Cold run queries take seconds because Logs Insights is a start-query-and-poll API. Every table and panel section has an explicit skeleton. Stream server components so metadata renders before logs arrive.

Three distinct states, never conflated:

- **Empty** — the query succeeded and there are no runs. Say so plainly.
- **Error** — the query failed. Say what failed and offer a retry.
- **Timed out** — the Logs Insights query exceeded its window. This is its own state, distinct from empty, because "no runs" and "we couldn't find out" are different facts and must not look alike.

---

## 5. Data display conventions

| Value            | Presentation                                                                       |
| ---------------- | ---------------------------------------------------------------------------------- |
| Dates            | Relative in tables ("4h ago"), absolute UTC on hover. Absolute in the run panel.     |
| `session_id`     | Monospace, truncated with a copy affordance. Full value on hover.                    |
| Duration         | Human units — `1.4s`, `2m 13s`. Never raw milliseconds.                             |
| Tokens           | Thousands-separated. `in / out` shown as a pair, labelled.                           |
| Estimated cost   | Currency-formatted with an explicit estimate marker, and the word "estimated" in the column header. It excludes runtime compute; the label is what keeps it honest. |
| Unknown cost     | When `model_id` is missing from the pricing table, show "unknown", **never `$0.00`**. A zero reads as free rather than unmeasured. |
| Outcome          | A link labelled by type (PR, report). `outcome.type = "none"` renders as a dash, not an empty cell. |
| Repository       | Short name in agent-scoped views, `org/repo` where ambiguity is possible.             |
| Tabular numbers  | Numeric columns use tabular figures and right alignment so digits line up down the column. |

---

## 6. Layout

Single-column application shell. A slim top bar carries the app name and top-level navigation between Agents and Repos; there is no sidebar, because three destinations do not need one.

Content is width-constrained for prose and full-width for tables. Tables scroll horizontally on narrow viewports rather than dropping columns — a hidden column is worse than a scroll when every column is data.

The run panel is a right-side sheet, roughly 40% viewport width on desktop and full-width on small screens.

**Desktop-first, not desktop-only.** This is a tool used at a desk, so the dense table layout is tuned for a large viewport. It must remain usable on a phone, because checking a failed run from away from the desk is a real case.

---

## 7. Accessibility

Target WCAG 2.1 AA. Full validation requires manual testing with assistive technologies and expert review; the items below are the baseline this project commits to.

- **Contrast:** 4.5:1 for body text, 3:1 for large text and UI boundaries. Status colours must meet contrast against both light and dark backgrounds — verify rather than assume, since mid-tone greens and ambers commonly fail on light backgrounds.
- **Status never by colour alone.** Restating this because it is the most likely thing to be quietly dropped for visual tidiness.
- **Keyboard:** every action reachable and operable by keyboard. Tables support arrow-key navigation; a row is activated with `Enter` or `Space`. Row click handlers must not be the only way to open a run.
- **Focus:** visible focus rings from the `--ring` token, never removed. The panel traps focus while open and restores it to the triggering row on close.
- **Semantics:** real `<table>` markup with proper headers, not a grid of divs. The toggle is a real switch with an accessible label naming the repository and agent it controls.
- **Live regions:** async results — a completed query, a failed toggle — announce via a polite live region.
- **Motion:** respect `prefers-reduced-motion`. No animated status indicator; a pulsing "running" dot is decorative and costs more than it conveys.
- **Targets:** minimum 24×24px, and 44×44px for primary touch targets.

---

## 8. Rules for contributors

1. Use tokens. A hardcoded colour, spacing, or radius value fails review.
2. Reach for a shadcn/ui primitive first; wrap, don't fork.
3. All four tables use `DataTable`. A second table implementation is a defect.
4. Status visuals come from `StatusBadge`, nowhere else.
5. Every async surface defines loading, empty, error, and — where applicable — timed-out states.
6. Every interactive element is keyboard-operable and labelled.
7. Any UI story states its DESIGN.md impact: tokens added, components added or changed, or prose to update here.
8. Changes to this document add a changelog row.
