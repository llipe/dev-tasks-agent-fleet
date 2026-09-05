# Implementation Plan — Agent Fleet Control Panel, Phase 2 (Wave 3)

## Scope

Wave 3 is **the screens wave**: the shell every route renders inside, and the two read-only screens that prove the Wave 2 data boundary end to end. Nothing here writes to the database — the first panel write lands in Wave 4 with S-112.

| Task | Story | Issue | Size | Title |
| ---- | ----- | ----- | ---- | ----- |
| 1.0 | S-106 | [#119](https://github.com/llipe/dev-tasks-agent-fleet/issues/119) | S | App shell — sidebar, top bar, collapse persistence |
| 2.0 | S-107 | [#120](https://github.com/llipe/dev-tasks-agent-fleet/issues/120) | M | Agents Dashboard with three-variant density toggle |
| 3.0 | S-108 | [#121](https://github.com/llipe/dev-tasks-agent-fleet/issues/121) | M | Agent Run History |

Sources: [`user-stories-prd-agent-fleet-panel-v2.md`](user-stories-prd-agent-fleet-panel-v2.md) v1.2 (S-106, S-107, S-108), [`specification-prd-agent-fleet-panel-v2.md`](specification-prd-agent-fleet-panel-v2.md) v1.6 (SD2, SD4, §10, §11, §12, §14), [`/DESIGN.md`](../DESIGN.md) v1.1 (§3.5, §4.1, §4.3, §4.4, §5.1, §5.2, §6, §7, §9).

Predecessors: [`tasks-prd-agent-fleet-panel-v2-plan.md`](tasks-prd-agent-fleet-panel-v2-plan.md) (Wave 1 — S-101/S-102/S-103, merged and closed), [`tasks-prd-agent-fleet-panel-v2-wave2-plan.md`](tasks-prd-agent-fleet-panel-v2-wave2-plan.md) (Wave 2 — S-104/S-105/S-111, **all merged and closed**; PR #132, #133, #135).

**Project type:** existing codebase. Workspace, gates, token layer, primitives, and the server read boundary all exist. **No Task 0.**

### Dependency state

**All Wave 3 dependencies are satisfied as of 2026-09-04** — Wave 2 closed in full, so nothing in this wave waits on another wave.

| Story | Depends on | State |
| ----- | ---------- | ----- |
| S-106 | S-105 | ✅ merged and closed (#118 / PR [#133](https://github.com/llipe/dev-tasks-agent-fleet/pull/133)) |
| S-107 | S-104, S-105, S-106 | S-104 ✅ merged (#117); S-105 ✅ merged (#118); S-106 is task 1.0 |
| S-108 | S-104, S-106 | S-104 ✅ merged (#117); S-106 is task 1.0 |

**S-106 is the wave's serialization point.** Both screens compose inside its layout, so 1.0 completes before 2.0 and 3.0 begin. Once 1.0 merges, **2.0 and 3.0 are independent and may run on parallel branches** — they touch disjoint routes (`app/page.tsx` vs `app/agents/[slug]/page.tsx`) and disjoint domain modules (`lib/domain/dashboard.ts` vs `lib/domain/run-row.ts`). Their only shared file is `lib/supabase/queries.ts`, where each appends one helper; sequence the merges rather than the work if that produces a conflict.

**S-111 (#124) is merged and closed** (PR [#135](https://github.com/llipe/dev-tasks-agent-fleet/pull/135)) and was never a Wave 3 dependency — no Wave 3 task imports `lib/aws/*`. It unblocks Wave 4's S-112.

### `/DESIGN.md` decisions — resolved before this wave started

The S-105 audit ([`fidelity-report-S-105.md`](fidelity-report-S-105.md)) found three `/DESIGN.md` self-contradictions. All three are **resolved in `/DESIGN.md` v1.1** (2026-09-04), each in favor of the single consistent reading — which is also what S-105 already shipped, so no Wave 3 code changes:

| Finding | Contradiction | Resolution |
| --- | --- | --- |
| D1 | §3.4 specified a uniform 14% status-pill tint; §8.1 said 16% for `running`/`queued` | **Uniform 14%** everywhere (§3.4 was the authority). Inert for Wave 3 — both screens inherit the shipped pill |
| D2 | §8.1 gave `queued` a 1.4s pulse; every other pulse is 1.6s | **1.6s everywhere.** Inert for Wave 3 |
| **D3** | §7.1 defined a compact relative form (`14m ago`) that `lib/format.ts` does not implement | **The compact row is removed from §7.1** — one relative-time form, shared by the run history table and the dashboard "last run". Task 2.10 uses the existing `formatRelative`; **no `formatRelativeCompact`**, and a screen must never format a relative time itself (CT-10). This closes test-plan gap **G1** and unblocks CT-11 |

### Published GitHub artifacts

Every task checklist below is mirrored into its issue body. GitHub is the source of truth for execution status; if this file and an issue disagree, the issue wins and this file gets reconciled.

| Story | Issue | Task checklist | Compliance test plan (Design Mode) |
| --- | --- | --- | --- |
| S-106 | https://github.com/llipe/dev-tasks-agent-fleet/issues/119 | in issue body — 31 items (1.1–1.28, incl. 1.16a–c) | https://github.com/llipe/dev-tasks-agent-fleet/issues/119#issuecomment-5542767342 |
| S-107 | https://github.com/llipe/dev-tasks-agent-fleet/issues/120 | in issue body — 35 items (2.1–2.31, incl. 2.12a, 2.13a, 2.16a, 2.26a) | https://github.com/llipe/dev-tasks-agent-fleet/issues/120#issuecomment-5542767664 |
| S-108 | https://github.com/llipe/dev-tasks-agent-fleet/issues/121 | in issue body — 29 items (3.1–3.29) | https://github.com/llipe/dev-tasks-agent-fleet/issues/121#issuecomment-5542767945 |

Local test-plan artifact: [`test-plan-wave3-S-106-S-107-S-108.md`](test-plan-wave3-S-106-S-107-S-108.md) — 13 contract scenarios, 24 edge cases, all 20 ACs mapped.

**Flagged-gap status.** The test plan raised seven gaps; **G1, G3, and G4 are now closed before implementation.** G1 → `/DESIGN.md` v1.1 removes the compact relative-time row from §7.1, so both screens share `formatRelative` and CT-11 is unblocked. G3 → tasks 1.16a–c carry a real hydration instrument. G4 → the no-refetch assertion is a navigation assertion (tasks 2.9/2.16), and both open decisions are made: the ledger affordances **ship** and a dashboard **filter input is in scope** (stories v1.2, AC7 rewritten and AC8 added; tasks 2.12a/2.13/2.16a/2.26a). **G5** (AC-108.4's reaper-paused check is manual-only, so it verifies once and then rots — add a stale-row Layer 2.5 test alongside the runbook) is actioned inside task 3.15. **G2** (Layer 2.5 skip-to-green, [#134](https://github.com/llipe/dev-tasks-agent-fleet/issues/134)) is inherited and deferred by decision, but it now covers CT-1/CT-7/CT-8, each the only check on a distinct dashboard failure. **G6** (DESIGN conformance is review-only at screen scale) and **G7** (1024px is unverifiable in jsdom → manual now, Playwright in S-114) are recorded, low-cost mitigations noted in the plan.

### Execution rules

One sub-task at a time, marked `[x]` locally **and** in the GitHub Issue checklist, then stop for approval. Branch per story (`story/S-1xx-<short-description>`), draft PR opened immediately after the first commit with `Closes #<n>`, quality gates before completion. `pnpm` throughout; canonical scripts only.

### Wave-level notes carried forward

- **Route-segment config must be declared inline.** Next.js silently ignores `dynamic`/`revalidate`/`fetchCache` re-exported from another module and falls back to defaults. `lib/supabase/route-config.ts` is documentation; every data route in this wave copies the values inline (S-104 audit D4, `technical-guidelines.md` §12). A cached run list is exactly the staleness FR11a exists to prevent, so this is a correctness requirement, not a convention.
- **New Layer 2.5 suites inherit the G2 hole.** This wave adds `dashboard-query.test.ts` and `runs-by-agent.test.ts` behind the same `probeLocalDb` Docker gate, which skips to green when the stack is down. Making those skips fail CI is [#134](https://github.com/llipe/dev-tasks-agent-fleet/issues/134), filed separately. Until it lands, each story must state whether its integration suite **ran live** or skipped — a skip is not evidence.
- **`effectiveStatus` is the only status source.** Both screens display derived status (FR11a). Neither may read `runs.status` directly, and neither may re-implement the derivation — they import `lib/domain/status.ts`. This closes test-plan gap **G6** (derived status reaching `StatusPill`), which Wave 2 could not prove because no screen existed.
- **The SD2 lint rule is scoped to `components/**`.** This wave introduces the first client components under `app/**`, so the optional hardening from the S-104 audit (D1) is actioned inline in task 1.13. `import "server-only"` remains the hard guard either way.
- **No migrations in this wave.** All three stories are read-only. Each records an explicit migration opt-out rationale (plan activity rule 8).
- **Where the test-plan gaps land.** **G3** and **G4** now carry concrete instruments rather than intentions, added as lettered sub-items so the parent numbering is stable: **G3** → tasks **1.16a/b/c** (a `renderHydrated` helper using `hydrateRoot` + `onRecoverableError`, because RTL's `render()` never hydrates and therefore no current test can observe a mismatch; plus a standing `console.error` trap and a `suppressHydrationWarning` grep). **G4** → tasks **2.9/2.16** for the no-refetch instrument (assert the toggle never navigates, and that the page reads once per render — a client component cannot refetch Supabase at all, so navigation is the only real risk), plus **2.12a/2.13/2.16a/2.26a** now that both open decisions are made (affordances ship; filter input in scope). **G5** (a stale-row Layer 2.5 test alongside the manual reaper-paused runbook) is actioned inside task **3.15**; **G6** (assert the exact `grid-template-columns` strings) inside tasks **2.6** and **3.6**. **G1** was a `/DESIGN.md` decision and is resolved in v1.1.
- **S-107 gained a filter input (scope addition, decided 2026-09-04).** `/DESIGN.md` §5.1 lists a filter input among the dashboard's common header elements and §6.5 binds `/` to focusing it, so the `/` affordance had nothing to focus without it. It is client-side over the already-loaded list, matches name + slug, and is **transient** — density persists, the filter does not, because a remembered filter would hide agents on the next load with no visible cause. Recorded as AC-107.8 in `user-stories-prd-agent-fleet-panel-v2.md` v1.2. Not a PRD change: FR10 already requires the agent list, and this is presentation of it. Note that PRD §10 defers filtering on **run history** — that deferral is untouched, S-108 still ships no filters.
- **The harness code lands on the story branches, not here.** `tests/helpers/hydrate.tsx`, the `console.error` trap, and the grep rules are S-106 deliverables (tasks 1.16a–c); the `next/navigation` mock pattern is an S-107 deliverable. This plan records the instrument so it is not re-invented or quietly skipped.

## Relevant Files

### App shell (S-106)

- `panel/app/layout.tsx` — shell grid: 212px/52px sidebar, 38px top bar, content region owning its scroll, `100dvh` no outer scroll
- `panel/components/Sidebar.tsx` — client component; `NavItem` composition, active-route detection, disabled deferred destinations
- `panel/components/TopBar.tsx` — 38px bar with breadcrumb slot
- `panel/lib/ui/sidebar-state.ts` — `localStorage` read/write with corrupt-value and unavailable-storage fallbacks
- `panel/lib/ui/shortcuts.ts` — `Cmd+\` / `Ctrl+\` matcher
- `panel/tests/unit/sidebar-state.test.ts`, `panel/tests/unit/shortcuts.test.ts`
- `panel/tests/component/Sidebar.test.tsx`
- `panel/tests/helpers/hydrate.tsx` — `renderHydrated()`: `renderToString` → `hydrateRoot` with an `onRecoverableError` collector, so a hydration mismatch is observable at all (test-plan G3)
- `panel/tests/setup.ts` — `IS_REACT_ACT_ENVIRONMENT` for the bare `act` call; `console.error` trap with an `allowConsoleError()` opt-in
- `panel/tests/unit/no-suppress-hydration.test.ts` — mechanical grep rejecting `suppressHydrationWarning` without a naming comment
- `panel/eslint.config.mjs` — SD2 restricted-import glob extended to `app/**` client components

### Agents dashboard (S-107)

- `panel/app/page.tsx` — server component, inline `force-dynamic`
- `panel/components/dashboard/DenseRows.tsx` — variant 1a, default; `StatusBar` + legend, `/DESIGN.md` §4.3 grid
- `panel/components/dashboard/AgentCards.tsx` — variant 1b; 2-col grid, 24-bar `RunStrip`
- `panel/components/dashboard/Ledger.tsx` — variant 1c; keyboard-first
- `panel/components/dashboard/DensityToggle.tsx` — client component, `localStorage` persisted, presentation-only swap
- `panel/components/dashboard/AgentFilter.tsx` — header filter input; client-side, name + slug, transient (not persisted), `/` to focus, `Escape` to clear then blur
- `panel/lib/domain/dashboard.ts` — rows → per-agent summary shaper, plus the filter predicate
- `panel/lib/supabase/queries.ts` — dashboard aggregate helper (single grouped query, not N+1)
- `panel/tests/unit/dashboard.test.ts`, `panel/tests/component/dashboard.test.tsx`, `panel/tests/integration/dashboard-query.test.ts`

### Run history (S-108)

- `panel/app/agents/[slug]/page.tsx` — server component, inline `force-dynamic`, 404 on unknown/disabled slug
- `panel/components/runs/RunHistoryTable.tsx` — semantic `<table>`, `/DESIGN.md` §4.4 grid
- `panel/components/runs/RunHistoryRow.tsx` — status pill, outcome tag, repo + branch, duration, `n/m`, relative start
- `panel/components/runs/AgentHeader.tsx` — breadcrumb, name, description, params count, p50 duration, success rate
- `panel/lib/domain/run-row.ts` — row shaper + header metric derivations
- `panel/lib/supabase/queries.ts` — runs-by-agent helper (already present from S-104; extend if the header metrics need it)
- `panel/tests/unit/run-row.test.ts`, `panel/tests/component/run-history.test.tsx`, `panel/tests/integration/runs-by-agent.test.ts`
- `docs/runbooks/issue-121-ac10-reaper-paused.md` — the AC10 verification procedure and its evidence

## Tasks

- [ ] 1.0 Implement Story S-106 ([#119](https://github.com/llipe/dev-tasks-agent-fleet/issues/119)): App shell — sidebar, top bar, collapse persistence

  > Note: `/DESIGN.md` §4.1 is the layout contract. The trap is hydration: collapse state lives in `localStorage`, which the server cannot read, so the shell must render a server default and reconcile after mount rather than reading storage during render. PRD §10 defers four nav destinations — they render **disabled**, not as links, so the deferral is visible instead of a dead click.

  - [x] 1.1 Confirm #119 is open; create branch `story/S-106-app-shell` from latest `main` (S-105 dependency satisfied — #118 / PR #133 merged `2026-09-03`)
  - [x] 1.2 Write the unit tests **first** (test-first) for `lib/ui/shortcuts.ts` (`Cmd+\` on macOS, `Ctrl+\` elsewhere) and `lib/ui/sidebar-state.ts` (read/write, corrupt value, storage unavailable), then implement both
  - [x] 1.3 First commit; open draft PR against `main` with `Closes #119`
  - [x] 1.4 Build the shell grid in `app/layout.tsx` with token-driven dimensions: 212px sidebar (52px collapsed) with `width 0.14s ease`, 38px top bar, content region `flex:1; overflow-y:auto`, page `100dvh` with no outer scroll; sidebar background `color-mix(in srgb, var(--color-bg) 92%, #000)`, body 88%
  - [x] 1.5 Add `components/Sidebar.tsx` as a client component composing the S-105 `NavItem` primitive, with active-route detection from `usePathname()`
  - [x] 1.6 Render the four deferred destinations (All runs, Repositories, Settings, System health) as **disabled non-links** with an accessible "not available in this phase" affordance; they must not be focus traps
  - [x] 1.7 Wire the collapse store: server renders the default expanded shell, the client reconciles from `localStorage` after mount (no storage read during render — a hydration mismatch here is a real defect, not a warning to silence)
  - [x] 1.8 Add the `Cmd+\` / `Ctrl+\` handler and confirm it does not fire inside text inputs
  - [x] 1.9 Add `components/TopBar.tsx` with a breadcrumb slot the Wave 3 screens fill
  - [x] 1.10 Mark the sidebar as `<nav>` with an accessible label; verify focus visibility per `/DESIGN.md` §6.4 (2px accent outline, 2px offset, default rings suppressed)
  - [x] 1.11 Verify the layout holds at 1024px minimum width with no horizontal scroll (`/DESIGN.md` §9)
  - [x] 1.12 Confirm nav items match `/DESIGN.md` §3.5 — active state (12% accent tint + 2px accent left border) and hover tint
  - [x] 1.13 Extend the SD2 ESLint restricted-import glob to cover `app/**` client components (S-104 audit D1) and confirm `tests/unit/eslint-server-import.test.ts` still proves the rule fires; `import "server-only"` remains the hard guard
  - [x] 1.14 Run Tests — unit: `pnpm run test:unit` — shortcut matcher across platforms; persistence helper round-trip
  - [x] 1.15 Run Tests — component: `pnpm run test` — collapse toggles the width class; state restored from a seeded `localStorage`; disabled items render non-interactive; active item derives from the current route
  - [x] 1.16 Run Tests — edge cases: `localStorage` unavailable or throwing (private mode) → default expanded, no crash; corrupted stored value → default; rapid double toggle
  - [x] 1.16a Build the hydration instrument (**test-plan G3** — the gap's fix, not a nice-to-have): add `tests/helpers/hydrate.tsx` exposing `renderHydrated(element)` — `renderToString` into a container, then `hydrateRoot` with an `onRecoverableError` collector, wrapped in `act`. RTL's `render()` never hydrates, so **no existing test can observe a hydration mismatch**; a `console.error` spy alone would be a test that cannot fail. Set `globalThis.IS_REACT_ACT_ENVIRONMENT = true` in `tests/setup.ts` for the bare `act` call
  - [x] 1.16b Assert clean hydration with the instrument: seed `localStorage` to collapsed, `renderHydrated(<AppShell/>)`, then assert **both** `recoverable` is empty **and** the sidebar reads collapsed after mount. The correct implementation (server default + `useEffect` reconcile) passes both; the tempting `useState(() => readStoredCollapse())` fails the first — today nothing distinguishes them
  - [x] 1.16c Add the standing safety net: fail any `component`-project test that emits an unexpected `console.error`, with an explicit `allowConsoleError("reason")` opt-in rather than a widened filter. Expect fallout across the existing 232 tests (anything deliberately exercising an error path) — triage it before committing. Also add a mechanical grep rejecting `suppressHydrationWarning` under `app/**` and `components/**` unless the line carries a `// hydration-divergence:` comment naming the cause (shape of `tests/unit/token-discipline.test.ts`)
  - [x] 1.17 Manual/UI verification: `pnpm --filter panel dev` — toggle, reload, confirm persistence; drive the entire shell by keyboard only; compare against `docs/prototype/` at 1024px and 1440px
  - [x] 1.18 Verify Acceptance Criterion: shell dimensions, transition, content scroll ownership, and `100dvh` with no outer scroll
  - [x] 1.19 Verify Acceptance Criterion: collapse state persists across reload; `Cmd+\` toggles it
  - [x] 1.20 Verify Acceptance Criterion: Agents is the only enabled destination; the other four are disabled with an accessible affordance
  - [x] 1.21 Verify Acceptance Criterion: nav items match `/DESIGN.md` §3.5 active and hover states
  - [x] 1.22 Verify Acceptance Criterion: keyboard reaches every interactive element, focus is visible, the sidebar is a labeled `<nav>`
  - [x] 1.23 Verify Acceptance Criterion: layout holds at 1024px with no horizontal scroll
  - [x] 1.24 Map acceptance criteria to test evidence and record the mapping in the PR: AC1/AC4/AC6 → component tests + prototype comparison; AC2 → persistence test + manual reload; AC3 → disabled-item test; AC5 → keyboard walkthrough + focus assertions
  - [x] 1.25 Record `/DESIGN.md` §4.1 conformance notes in the PR — any prototype detail not reproduced
  - [x] 1.26 Run quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test`, `pnpm run audit`, then `make validate`
  - [x] 1.27 Migration lifecycle: **not applicable** — presentational story, no schema or data-model change. Opt-out rationale recorded here and in the issue
  - [ ] 1.28 Mark PR ready for review, notify the user, and close #119 only after the PR is approved and merged

- [x] 2.0 Implement Story S-107 ([#120](https://github.com/llipe/dev-tasks-agent-fleet/issues/120)): Agents Dashboard with three-variant density toggle

  > Note: implements **FR10** and **FR17**/**D17**, verified by **AC9**. Three variants ship because the right default is not knowable before real usage — but they are one query and three presentations, so the toggle must not refetch. The status breakdown is where FR11a is easy to lose: the aggregate must count `effective_status`, not `runs.status`, or a stale `running` run is counted in the wrong bucket while the row above it displays `timed_out`.

  - [x] 2.1 Confirm task 1.0 is merged; confirm #120 is open; create branch `story/S-107-agents-dashboard` from latest `main`
  - [x] 2.2 Write the aggregation-shaper unit tests **first**, then `lib/domain/dashboard.ts` — rows → per-agent summary (run count, status breakdown, last-run time + outcome), deriving every status through `effectiveStatus`
  - [x] 2.3 First commit; open draft PR against `main` with `Closes #120`
  - [x] 2.4 Add the dashboard aggregate helper to `lib/supabase/queries.ts` — a **single grouped query** over `v_runs`, never N+1 per agent; enabled agents only
  - [x] 2.5 Build `app/page.tsx` as a server component with **inline** `force-dynamic`/`revalidate = 0`/`fetchCache` (re-exported segment config is silently ignored)
  - [x] 2.6 Build the dense-rows variant (1a, default) with `StatusBar` + legend on the `/DESIGN.md` §4.3 grid (`26px minmax(0,1fr) 128px 300px 132px 92px`)
  - [x] 2.7 Build the cards variant (1b): 2-column grid, `gap: 14px`, 24-bar `RunStrip` newest-last, 2-line description clamp
  - [x] 2.8 Build the ledger variant (1c): maximum density, keyboard-first
  - [x] 2.9 Add `DensityToggle` as a client component persisting the selection in `localStorage`, defaulting to dense rows; **switching variants must not refetch** — presentation swap only. Concretely: the server component reads once and passes data as props to a single client component holding the variant state. The toggle **must not navigate** — no `router.push`/`replace`/`refresh`, no `<Link>`, no `searchParams` write; that is the only way a refetch can actually occur, since every query helper needs a `server-only` client a client component cannot construct
  - [x] 2.10 Render per-agent status dot, name, slug (mono, accent-400), description, run count, status breakdown, last-run time + outcome tag. Relative time comes from the existing `formatRelative` — `/DESIGN.md` v1.1 removed the compact `14m ago` form, so there is **one** relative-time form and no `formatRelativeCompact` (test-plan G1 resolved; CT-10 forbids the screen formatting its own)
  - [x] 2.11 Link agent name/slug to `/agents/[slug]`; add an "Invoke" action linking to the invoke route (the route itself lands in S-113 — link now, it must not 500 before then; render it disabled if the route does not yet exist)
  - [x] 2.12 Add empty states: zero agents, and an agent with zero runs — a legible message, never a blank region or `NaN`
  - [x] 2.12a Add the header filter input `components/dashboard/AgentFilter.tsx` (**decided — S-107 scope, stories v1.2 AC8**): client-side over the already-loaded list, matching **name + slug** case-insensitively, rendered in all three variants, **transient (never persisted)**, and never navigating. Add the filter predicate to `lib/domain/dashboard.ts` with unit tests. Add a **distinct** no-match empty state naming the query — "no agents configured" and "nothing matches `foo`" are different situations and must not read alike
  - [x] 2.13 Implement the ledger keyboard affordances (**decided — they ship; the "or render them absent" alternative is withdrawn, stories v1.2 AC7**): `Up`/`Down` move selection using **roving `tabindex`** (clamped at both ends, no wrap), `Enter` activates **the same target as the row's Invoke action** so the keyboard path cannot reach a route the mouse path deliberately does not (task 2.11 governs both), and `/` focuses the filter input from 2.12a. Bind `/` in every variant — a deliberate superset of `/DESIGN.md` §6.5's ledger-only binding, since the filter is a common header element; it must not fire while a text input has focus (same guard as `Cmd+\`, task 1.8), and `Escape` clears the filter, then blurs when already empty
  - [x] 2.13a Add the hint/behavior coupling guard: if a key's hint text renders, pressing that key must produce its effect. This makes "render the hints, wire nothing" a permanently failing state rather than a passing one
  - [x] 2.14 Decide the time-range chips (7d/30d/all): ship all three if the aggregate cost is trivial, otherwise ship "all" only and **record the reduction** in the PR rather than leaving dead controls
  - [x] 2.15 Run Tests — unit: `pnpm run test:unit` — aggregation shaper with zero runs, mixed statuses, and a stale `running` row that must land in the `timed_out` bucket; filter predicate (name match, slug match, case-insensitivity, whitespace-only query, no match, regex metacharacters treated literally)
  - [x] 2.16 Run Tests — component: `pnpm run test` — each variant renders from one fixture; persisted value selects the variant on mount; disabled agents excluded; the filter narrows the list in all three variants and clearing it restores the full list. **No-refetch instrument (test-plan G4):** mock `next/navigation`, switch dense → cards → ledger → dense, and assert `push`/`replace`/`refresh` were never called (assert the same across a filter keystroke); separately assert `page.tsx` calls the dashboard query exactly once per render with the query module mocked. "No refetch" here reduces to "no navigation and one read per render" — a network spy would assert something the `server-only` boundary already guarantees
  - [x] 2.16a Run Tests — keyboard (component): `pnpm run test` — `Up`/`Down` move the ledger selection and clamp at both ends; `Enter` activates the row's Invoke target; `/` focuses the filter from every variant; `/` typed **inside** the filter inserts a slash rather than re-focusing; `Escape` clears, then blurs when already empty; roving `tabindex` keeps exactly one row focusable
  - [x] 2.17 Run Tests — integration (2.5): `pnpm run test:integration` — the dashboard query returns the seeded `dependency-update` agent with correct counts against the local stack; **state in the PR whether this ran live or skipped** (#134)
  - [x] 2.18 Run Tests — edge cases: zero agents; agent with zero runs; last run `running` (pulse) and last run `failed_to_start` (hollow dot, muted); a stale `running` run displaying `timed_out`; very long description (ellipsis in rows, 2-line clamp in cards); 100+ runs (strip caps at 24); filter matching nothing → the distinct no-match message; ledger `Up`/`Down` at the first and last row; `Enter` with no Invoke target available
  - [x] 2.19 Manual/UI verification: `pnpm --filter panel dev` → `/` in all three variants at 1024px and 1440px against `docs/prototype/`; reload confirms density persistence **and** confirms the filter did not persist
  - [x] 2.20 Verify Acceptance Criterion: `/` lists every `is_enabled` agent with all seven documented fields
  - [x] 2.21 Verify Acceptance Criterion: all three `/DESIGN.md` §5.1 variants render from the same data
  - [x] 2.22 Verify Acceptance Criterion: density selection persists across reload (PRD AC9)
  - [x] 2.23 Verify Acceptance Criterion: displayed statuses derive from `effective_status` (FR11a) **including in the aggregate breakdown**
  - [x] 2.24 Verify Acceptance Criterion: agent name/slug links to run history; Invoke action links to the invoke route
  - [x] 2.25 Verify Acceptance Criterion: empty states render legibly, with no blank region and no `NaN`, and the no-match state reads differently from "no agents configured"
  - [x] 2.26 Verify Acceptance Criterion: the ledger's keyboard affordances all work — `Up`/`Down` clamped selection, `Enter` on the Invoke target, `/` focusing the filter
  - [x] 2.26a Verify Acceptance Criterion: the header filter input renders in all three variants, filters by name and slug case-insensitively, never refetches or navigates, and does not survive a reload
  - [x] 2.27 Map acceptance criteria to test evidence and record the mapping in the PR: AC1/AC4 → integration + component tests; AC2/AC3 → variant + persistence tests + manual reload (AC9); AC5 → link assertions; AC6 → both empty-state tests; AC7 → per-key keyboard tests + the 2.13a coupling guard; AC8 → filter component tests + the no-navigation assertion
  - [x] 2.28 Record `/DESIGN.md` §5.1 conformance notes for all three variants in the PR
  - [x] 2.29 Run quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test`, `pnpm run audit`, then `make validate`
  - [x] 2.30 Migration lifecycle: **not applicable** — read-only story, no schema or data-model change. Opt-out rationale recorded here and in the issue
  - [x] 2.31 Mark PR ready for review, notify the user, and close #120 only after the PR is approved and merged

- [ ] 3.0 Implement Story S-108 ([#121](https://github.com/llipe/dev-tasks-agent-fleet/issues/121)): Agent Run History

  > Note: implements **FR11** and **FR11a**, verified by **AC10**. The AC that carries the story is AC4: with the `pg_cron` reaper **paused** and a run past its threshold, the row must display `timed_out`. That is the two-layer design from `technical-guidelines.md` §3 observed from the UI — the view tells immediate truth while the reaper is behind. Filters, search, and pagination are deferred (PRD §10); the toolbar renders without them rather than with dead controls.

  - [x] 3.1 Confirm task 1.0 is merged; confirm #121 is open; create branch `story/S-108-run-history` from latest `main`
  - [x] 3.2 Write the row-shaper unit tests **first**, then `lib/domain/run-row.ts` — duration `Xm XXs`, `running · Xm`, step progress `n/m`, relative start time, outcome fallback `—` at 0.45 opacity, plus header metrics (p50 with even/odd counts, success rate with zero runs); reuse the S-105 `lib/format.ts` formatters rather than reimplementing them
  - [x] 3.3 First commit; open draft PR against `main` with `Closes #121`
  - [x] 3.4 Build `app/agents/[slug]/page.tsx` as a server component reading runs-by-agent from `v_runs` newest-first, unfiltered and unpaginated, with **inline** `force-dynamic` (a cached run list is precisely the staleness FR11a exists to prevent)
  - [x] 3.5 Build `AgentHeader` — breadcrumb, name, description, params count, p50 duration, success rate; compute metrics from the returned rows, and if that proves expensive move them into SQL and **record the change**
  - [x] 3.6 Build `RunHistoryTable` with **semantic `<table>` markup** (not divs — screen-reader navigation, spec §10) on the `/DESIGN.md` §4.4 grid (`118px 122px minmax(0,1fr) 96px 78px 104px 30px`)
  - [x] 3.7 Build `RunHistoryRow` — status pill, outcome tag, repository with branch when available, duration, `n/m`, relative start; every status routed through `effectiveStatus`, never `runs.status`
  - [x] 3.8 Add the empty state with an invoke CTA, and rows linking to `/runs/[id]` (the run detail route lands in S-109 — the link target may 404 until then; record that expectation)
  - [x] 3.9 Return a 404 for an unknown slug and for a disabled agent — not an empty list
  - [x] 3.10 Render the toolbar without filters, repo chips, search, or pagination (deferred to v3) rather than shipping dead controls
  - [x] 3.11 Write the AC10 verification procedure as `docs/runbooks/issue-121-ac10-reaper-paused.md`: `cron.unschedule('reap-stale-runs')` → insert a synthetic `running` run past `started_at + max_runtime_seconds + grace_seconds` → load the page → confirm `timed_out` → `cron.schedule` to restore → clean up the synthetic row. **Against the local Supabase stack, not the hosted project** — pausing the production reaper would leave real runs unreaped for the duration, and the hosted project holds real Phase 1 run data
  - [x] 3.12 Execute the AC10 procedure and record the evidence (SQL + observed UI state) in the PR and in the runbook; confirm the reaper schedule is restored afterward
  - [x] 3.13 Run Tests — unit: `pnpm run test:unit` — row shaper (duration, `n/m`, relative time, outcome fallback) and header metrics (p50 even/odd, success rate with zero runs)
  - [x] 3.14 Run Tests — component: `pnpm run test` — rows render every status; `running` shows `running · Xm`; a missing repository renders cleanly (no `null/null`); empty state renders the CTA
  - [x] 3.15 Run Tests — integration (2.5): `pnpm run test:integration` — seeded runs return newest-first; a synthetic stale `running` row reads `timed_out` through `v_runs`; **state in the PR whether this ran live or skipped** (#134)
  - [x] 3.16 Run Tests — edge cases: zero runs; single run; `finished_at` null with a terminal status; zero steps (`0/0`); sub-second duration; unknown slug → 404; disabled agent → 404; a `canceled` status (never written in v1) rendering as a neutral fallback
  - [ ] 3.17 Manual/UI verification: `pnpm --filter panel dev` → `/agents/dependency-update` at 1024px and 1440px against `docs/prototype/`
  - [ ] 3.18 Verify Acceptance Criterion: runs list newest-first, unfiltered, unpaginated, from `v_runs`
  - [ ] 3.19 Verify Acceptance Criterion: each row shows all six documented fields per `/DESIGN.md` §5.2
  - [ ] 3.20 Verify Acceptance Criterion: displayed status is `effective_status`, not `runs.status`
  - [ ] 3.21 Verify Acceptance Criterion: with the reaper paused, a past-threshold run displays `timed_out` — the AC10 evidence
  - [ ] 3.22 Verify Acceptance Criterion: the agent header shows breadcrumb, name, description, and the three metadata values
  - [ ] 3.23 Verify Acceptance Criterion: rows link to `/runs/[id]`; the empty state offers an invoke CTA
  - [ ] 3.24 Verify Acceptance Criterion: unknown slug and disabled agent both render 404
  - [ ] 3.25 Map acceptance criteria to test evidence and record the mapping in the PR: AC1–AC2/AC5–AC6 → component + integration tests; AC3 → shared `effectiveStatus` usage assertion; AC4 → the reaper-paused procedure (PRD AC10); AC7 → route test
  - [ ] 3.26 Record `/DESIGN.md` §5.2 conformance notes in the PR
  - [ ] 3.27 Run quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test`, `pnpm run audit`, then `make validate`
  - [ ] 3.28 Migration lifecycle: **not applicable** — read-only story. The AC10 procedure temporarily unschedules a cron job **on the local stack only** and restores it; that is a reversible test manipulation, not a schema or data-model change. Opt-out rationale recorded here and in the issue
  - [ ] 3.29 Mark PR ready for review, notify the user, and close #121 only after the PR is approved and merged

## Wave 3 Exit Criteria

- [ ] The shell renders at 212px/52px with persisted collapse state, and the four deferred destinations are visibly disabled rather than dead links
- [ ] `/` lists every enabled agent in three variants from one query, with the density selection persisted (PRD **AC9** closed) and a working header filter that is deliberately not persisted
- [ ] The ledger's keyboard affordances all function — `Up`/`Down` clamped, `Enter` on the row's Invoke target, `/` focusing the filter — and each has an unconditional test (test-plan gap **G4** closed)
- [ ] `/agents/[slug]` lists runs newest-first with `effective_status`, and the reaper-paused verification is recorded as evidence (PRD **AC10** closed)
- [ ] Every displayed status on both screens flows through `lib/domain/status.ts` — test-plan gap **G6** closed, since derived status now provably reaches `StatusPill`
- [ ] No screen reads `runs.status` directly and no screen re-implements the SD4 derivation
- [ ] Both new data routes declare `force-dynamic` **inline**; no Next.js data cache touches run data
- [ ] The SD2 lint glob covers `app/**` client components (S-104 audit D1 actioned)
- [ ] `make validate` green on both branches for all three stories; #119, #120, #121 merged and closed
- [ ] Wave 4 (S-109 → S-110, and S-112 → S-113) is unblocked

## Deferred — recorded so it is not mistaken for scope

- **Run detail** (`/runs/[id]`, SD11 bounded log viewer) is S-109. Wave 3's row links point at it and may 404 until it lands.
- **SSE live tail** (SD2/SD6) is S-110, which depends on S-109. Splitting the log viewer from its tail would mean building the viewer twice.
- **The invoke route and form** are S-112/S-113. The dashboard's Invoke action links forward; it does not implement anything.
- **`run_steps` steps panel** stays deferred to v3 (C8). S-108 shows step progress `n/m` only.
- **Filters, repo chips, search, pagination** on run history stay deferred to v3 (PRD §10).
- **Log-viewer virtualization** stays deferred to v3 (C13); the SD11 2,000-event bound is the Phase 2 answer.
- **Making Layer 2.5 skips fail CI** is [#134](https://github.com/llipe/dev-tasks-agent-fleet/issues/134), not a task in any story here.
- **A live service-role read against the hosted project** is an added AC on S-115 ([#128](https://github.com/llipe/dev-tasks-agent-fleet/issues/128)), from the S-104 audit's D3 finding.
- **The `ajv` bump to `>=8.18.0`** is an added task on S-113 ([#126](https://github.com/llipe/dev-tasks-agent-fleet/issues/126)), where `ajv` first does real work.

## Next Wave (proposed, not planned)

| Story | Issue | Size | Note |
| ----- | ----- | ---- | ---- |
| S-109 | [#122](https://github.com/llipe/dev-tasks-agent-fleet/issues/122) | L | Run detail — summary, artifacts, bounded log viewer |
| S-110 | [#123](https://github.com/llipe/dev-tasks-agent-fleet/issues/123) | M | SSE relay and live log tail |
| S-112 | [#125](https://github.com/llipe/dev-tasks-agent-fleet/issues/125) | L | Invoke route and payload translation (closes #89) — needs S-111 |

S-109 and S-110 belong together. S-112 can run in parallel with them once S-111 lands, since it shares no files with the log viewer.
