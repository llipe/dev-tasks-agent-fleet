# Compliance Test Plan — Wave 3 (S-106, S-107, S-108)

**Mode:** Design (test-first, pre-implementation)
**Produced:** 2026-09-04
**Fallback notice:** produced by `product-engineer` applying the `verifier` Design Mode activity skills (`activity-contract-test-design`, `activity-edge-case-refinement`) directly, because no `verifier` delegation tool is available in this runtime. Treat it as a Design Mode artifact; it has **not** been independently reviewed by the `verifier` agent. Same fallback as the Wave 1 and Wave 2 plans.

## Sources

| Artifact | Version | Consumed |
| --- | --- | --- |
| [`user-stories-prd-agent-fleet-panel-v2.md`](user-stories-prd-agent-fleet-panel-v2.md) | v1.1 | § S-106, S-107, S-108 |
| [`specification-prd-agent-fleet-panel-v2.md`](specification-prd-agent-fleet-panel-v2.md) | v1.5 | SD2, SD4, SD11, §10, §11, §12, §13, §14 |
| [`/DESIGN.md`](../DESIGN.md) | v1.1 | §3.4, §3.5, §4.1, §4.3, §4.4, §5.1, §5.2, §6, §7, §8.1, §9 |
| [`tasks-prd-agent-fleet-panel-v2-wave3-plan.md`](tasks-prd-agent-fleet-panel-v2-wave3-plan.md) | — | Tasks 1.0, 2.0, 3.0 |
| [`test-plan-wave2-S-104-S-105-S-111.md`](test-plan-wave2-S-104-S-105-S-111.md) | — | G2 (inherited), G6 (discharged here) |
| [`fidelity-report-S-105.md`](fidelity-report-S-105.md) | — | Drift D1/D2/D3 (all resolved in `/DESIGN.md` v1.1 — see G1) |
| [`TESTING.md`](../TESTING.md) | — | Layer taxonomy, reachability rule |

**What is different about this wave.** Waves 1 and 2 tested modules in isolation: a formatter, a pure derivation, a credential provider. Wave 3 is the first wave where things *compose* — a derived status reaches a pill, a database aggregate reaches a screen, a browser preference survives a server render. Every gap in this plan is a composition gap. None of them can be found by testing the pieces again.

## Acceptance Criteria Under Test

Renumbered for traceability; the story file is authoritative for wording.

**S-106 — app shell, sidebar, collapse persistence (#119)**

| ID | Criterion |
| --- | --- |
| AC-106.1 | `app/layout.tsx` renders the shell: 212px sidebar (52px collapsed) with `width 0.14s ease`, 38px top bar, content region `flex:1; overflow-y:auto`, page `100dvh` with no outer scroll |
| AC-106.2 | Collapse state persists in `localStorage` and survives a reload; `Cmd+\` toggles it |
| AC-106.3 | Agents is the only enabled nav destination; All runs, Repositories, Settings, System health render **disabled** with an accessible "not available in this phase" affordance |
| AC-106.4 | Nav items match `/DESIGN.md` §3.5 — active state (12% accent tint + 2px accent left border) and hover tint |
| AC-106.5 | Keyboard navigation reaches every interactive element; focus is visible per §6.4; the sidebar is a `<nav>` with an accessible label |
| AC-106.6 | Layout holds at 1024px minimum width with no horizontal scroll (§9) |

**S-107 — agents dashboard with density toggle (#120)**

| ID | Criterion |
| --- | --- |
| AC-107.1 | `/` lists every `is_enabled` agent with status dot, name, slug, description, run count, status breakdown, and last-run time + outcome |
| AC-107.2 | All three §5.1 variants render from the same data: dense rows (1a, default), cards with the 24-bar strip (1b), ledger (1c) |
| AC-107.3 | The density selection persists client-side and survives a reload (PRD AC9) |
| AC-107.4 | Displayed run statuses derive from `v_runs.effective_status` (FR11a), **including in the aggregate breakdown** |
| AC-107.5 | Agent name/slug links to that agent's run history; an "Invoke" action links to the invoke route |
| AC-107.6 | Empty state (no agents, or an agent with zero runs) renders a legible message, not a blank region or `NaN` |
| AC-107.7 | The ledger supports its documented keyboard affordances (`Up`/`Down`, `Enter`, `/`) **or** renders them absent rather than broken |

**S-108 — agent run history (#121)**

| ID | Criterion |
| --- | --- |
| AC-108.1 | `/agents/[slug]` lists that agent's runs newest-first, unfiltered and unpaginated, from `v_runs` |
| AC-108.2 | Each row shows status pill, outcome tag, repository (with branch when available), duration, step progress `n/m`, relative start time, per §5.2 |
| AC-108.3 | Status displayed is `effective_status`, not `runs.status` (FR11a) |
| AC-108.4 | With the `pg_cron` reaper paused and a run past its threshold, the row displays `timed_out` — recorded as evidence (PRD AC10) |
| AC-108.5 | An agent header shows breadcrumb, name, description, and metadata (params count, p50 duration, success rate) |
| AC-108.6 | Rows link to `/runs/[id]`; the empty state offers an invoke CTA |
| AC-108.7 | Unknown slug or a disabled agent renders a 404, not an empty list |

---

## Part 1 — Contract Scenarios

Eight boundaries. Two are new kinds for this project: a **browser-storage boundary** whose provider is the user's own machine (B3), and a **composition boundary** where a derived value must reach a presentational component unaltered (B2 — this is Wave 2's deferred G6).

| # | Boundary | Type | Provider | Consumer |
| --- | --- | --- | --- | --- |
| B1 | `v_runs` rows ↔ dashboard aggregate shaper | provider-driven | Postgres view | `lib/domain/dashboard.ts` |
| B2 | `effectiveStatus` output domain ↔ `StatusPill`/`StatusDot` `status` prop | schema-compat | `lib/domain/status.ts` | S-105 primitives |
| B3 | `localStorage` values ↔ shell + density readers | provider-driven (**untrusted**) | the browser (any prior version, any user) | `lib/ui/sidebar-state.ts`, `DensityToggle` |
| B4 | Route param `[slug]` ↔ `agents.slug` | provider-driven | Postgres | `app/agents/[slug]/page.tsx` |
| B5 | `/DESIGN.md` §4.1/§4.3/§4.4 grid specs ↔ layout CSS | schema-compat | DESIGN.md (normative) | shell + table components |
| B6 | `/DESIGN.md` §7 formatting ↔ screen rendering | schema-compat | `lib/format.ts` (S-105) | Wave 3 screens |
| B7 | PostgREST grouped read ↔ dashboard query helper | provider-driven | PostgREST (`max_rows=1000`) | `lib/supabase/queries.ts` |
| B8 | `v_runs` row optionality ↔ `RunHistoryRow` | schema-compat | Postgres nullability | row component |

### CT-1: Dashboard aggregate counts `effective_status`, not `runs.status`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.1, AC-107.4 |
| **Contract type** | provider-driven |
| **Boundary** | B1 |
| **Direction** | response |
| **Input** | A seeded agent with five runs: two `succeeded`, one `failed`, one genuinely `running` (fresh clock), and one `running` whose `started_at + max_runtime_seconds + grace_seconds` is in the past |
| **Expected Result** | The breakdown reads `2 succeeded, 1 failed, 1 running, 1 timed_out`. The stale row is counted as `timed_out` |
| **Pass Criteria** | The `running` bucket is exactly 1 and the `timed_out` bucket is exactly 1. A result of `2 running, 0 timed_out` fails — that is the FR11a violation this scenario exists to catch, and it is invisible if the row's own pill is computed separately from the aggregate |

### CT-2: The value that reaches `StatusPill` is the derived one (Wave 2 G6 discharged)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.4, AC-108.3 |
| **Contract type** | schema-compat |
| **Boundary** | B2 |
| **Direction** | response (rendered output) |
| **Input** | A run row with `status = "running"` and a past-threshold clock, rendered through the real screen component tree (not by calling `effectiveStatus` in the test) |
| **Expected Result** | The rendered pill shows the `timed_out` label and the `--st-timeout` treatment. `running` appears nowhere in the row's accessible text |
| **Pass Criteria** | Assertion is on rendered output, not on a function return. Both screens have this scenario. This is the composition Wave 2 could not prove: CT-1 of the Wave 2 plan proved the derivation, AC-105.4 proved the pill, nothing proved the wire between them |

### CT-3: Both screens consume the derivation rather than restating it

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.4, AC-108.3 |
| **Contract type** | schema-compat |
| **Boundary** | B2 |
| **Direction** | request (import surface) |
| **Input** | Static analysis over `app/**`, `components/dashboard/**`, `components/runs/**`, `lib/domain/dashboard.ts`, `lib/domain/run-row.ts` |
| **Expected Result** | No module outside `lib/domain/status.ts` compares a timestamp against `max_runtime_seconds`, `grace_seconds`, or `start_timeout_seconds`; no module reads a `.status` property for display purposes without routing it through `effectiveStatus` |
| **Pass Criteria** | A mechanical check (grep-based unit test, in the shape of `token-discipline.test.ts`) fails on a third copy of the SD4 expression. Two copies already exist by design (SQL + TS) and are pinned to each other; a third would be pinned to nothing |

### CT-4: Unknown persisted preference falls back to the documented default

| Field | Value |
| --- | --- |
| **AC(s)** | AC-106.2, AC-107.3 |
| **Contract type** | provider-driven |
| **Boundary** | B3 |
| **Direction** | request |
| **Input** | `localStorage` seeded with each of: `"cards"` (valid), `"ledger"` (valid), `"dense"` (valid), `"kanban"` (unknown), `"{"` (malformed), `""` (empty), `null` (absent) |
| **Expected Result** | The three valid values select their variant. Unknown, malformed, empty, and absent all render dense rows. Nothing throws |
| **Pass Criteria** | Seven cases, seven passes, zero exceptions. The collapse-state helper gets the same treatment with `"true"`/`"false"`/garbage. **This is a real contract, not a hypothetical:** the provider is a previous version of our own code, and a renamed variant string ships a crash to exactly the users who used the feature most |

### CT-5: Type mismatch in a persisted preference does not reach the component

| Field | Value |
| --- | --- |
| **AC(s)** | AC-106.2, AC-107.3 |
| **Contract type** | provider-driven |
| **Boundary** | B3 |
| **Direction** | request |
| **Input** | `localStorage` seeded with `'{"collapsed":"yes"}'` and with `'{"collapsed":1}'` where a boolean is expected |
| **Expected Result** | The reader returns the typed default (`expanded`), not a truthy string or number coerced into a layout decision |
| **Pass Criteria** | The reader's return type is validated at the boundary, not asserted by `as`. A `"false"` string must not read as `true` |

### CT-6: Unknown slug and disabled agent both produce 404

| Field | Value |
| --- | --- |
| **AC(s)** | AC-108.7 |
| **Contract type** | provider-driven |
| **Boundary** | B4 |
| **Direction** | response |
| **Input** | `/agents/does-not-exist`, `/agents/<slug of an agent with is_enabled = false>`, `/agents/` + a 300-character string, `/agents/dependency-update` (control) |
| **Expected Result** | The first three render 404. The control renders the run history |
| **Pass Criteria** | 404, not an empty table and not a 500. An empty table for a disabled agent is the failure mode worth naming: it reads as "this agent has never run", which is a false statement about a real agent |

### CT-7: The dashboard read is one query, not N+1

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.1 |
| **Contract type** | provider-driven |
| **Boundary** | B7 |
| **Direction** | request |
| **Input** | A local database seeded with 8 enabled agents, each with runs; the dashboard query executed once with the PostgREST request count instrumented |
| **Expected Result** | Request count does not grow with agent count — one grouped read (plus at most one companion read), never one per agent |
| **Pass Criteria** | Asserted by counting requests, not by reading the code. Seed 8 agents and then 16; the count must not double |

### CT-8: The dashboard read is bounded below PostgREST `max_rows`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.1, AC-107.4 |
| **Contract type** | provider-driven |
| **Boundary** | B7 |
| **Direction** | response |
| **Input** | An agent with more than 1,000 runs in the local database |
| **Expected Result** | Either the aggregate is computed server-side (counts are correct regardless of row count), or the helper pages internally as `getRunEvents` does. The run count must be the true count |
| **Pass Criteria** | A displayed run count of exactly `1000` against 1,400 seeded runs is a **fail**, not a rounding artifact. `max_rows` truncates silently — spec §9.2 records this as the trap it already sprang once in S-104 |

### CT-9: Run history rows tolerate every documented nullable field

| Field | Value |
| --- | --- |
| **AC(s)** | AC-108.2 |
| **Contract type** | schema-compat |
| **Boundary** | B8 |
| **Direction** | response |
| **Input** | Rows with, respectively: `repository_id` null (agent with `requires_repository = false`); repository present but branch null; `finished_at` null on a terminal status; zero steps; `outcome` null |
| **Expected Result** | Each renders a documented placeholder — `—` at 0.45 opacity for a missing outcome, `0/0` for steps, a clean repository cell. No `null`, `undefined`, `NaN`, `null/null`, or `Invalid Date` in the DOM |
| **Pass Criteria** | Assert on rendered text. A regex over the row's text content for `null|undefined|NaN|Invalid Date` must not match — cheap, and it catches the whole class |

### CT-10: Screens consume `lib/format.ts` rather than reimplementing §7

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.1, AC-108.2 |
| **Contract type** | schema-compat |
| **Boundary** | B6 |
| **Direction** | request (import surface) |
| **Input** | Static analysis over the Wave 3 component and domain modules |
| **Expected Result** | Duration, relative-time, run-ID, step-progress, and count rendering all come from `lib/format.ts`. No `toLocaleString`, `Intl.*`, `padStart` on a time value, or hand-rolled `Math.floor(ms / 60000)` outside that module |
| **Pass Criteria** | Mechanical grep test. S-105 centralized these on purpose; a second implementation on a screen makes §7 unenforceable and silently diverges |

### CT-11: The dashboard's relative-time form comes from `lib/format.ts`

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.1 |
| **Contract type** | schema-compat |
| **Boundary** | B6 |
| **Direction** | response |
| **Input** | Last-run timestamps at 45s, 14 minutes, 6 hours, 25 hours, 23 days, and 400 days before an injected `now` |
| **Expected Result** | `just now`, `14 min ago`, `6h ago`, `yesterday`, `23d ago`, `400d ago` — the single §7.1 form, identical to what the run history table renders for the same value |
| **Pass Criteria** | Output matches `formatRelative` exactly on both screens. **Unblocked:** `/DESIGN.md` v1.1 removed the compact `14m ago` row from §7.1, so there is one form and no `formatRelativeCompact`. A screen rendering `14m ago` now fails both this scenario and CT-10 |

### CT-12: The shell honors the §4.1 dimensional contract

| Field | Value |
| --- | --- |
| **AC(s)** | AC-106.1 |
| **Contract type** | schema-compat |
| **Boundary** | B5 |
| **Direction** | response |
| **Input** | The rendered shell in expanded and collapsed state |
| **Expected Result** | Sidebar 212px expanded / 52px collapsed; top bar 38px; the content region — not `<body>` — carries `overflow-y: auto`; page height `100dvh` |
| **Pass Criteria** | Values come from the token/CSS layer and match §4.1. Which element owns the scroll is the load-bearing part: S-109's log viewer assumes the content region owns it, so getting this wrong in S-106 produces a bug that surfaces two stories later |

### CT-13: Table markup is semantic, and grid columns match §4.4

| Field | Value |
| --- | --- |
| **AC(s)** | AC-108.2, AC-106.5 |
| **Contract type** | schema-compat |
| **Boundary** | B5 |
| **Direction** | response |
| **Input** | The rendered run history table with three rows |
| **Expected Result** | A real `<table>` with `<thead>`, `<th scope="col">`, and `<tbody>`; queryable by `getByRole("table")` / `getAllByRole("row")`. Column widths match `118px 122px minmax(0,1fr) 96px 78px 104px 30px` |
| **Pass Criteria** | Role-based queries succeed. Spec §10 requires semantic markup for screen-reader navigation; a CSS-grid-of-divs passes every visual check and fails every assistive one |

---

## Part 2 — Edge-Case Catalog

All nine categories evaluated. Two are `N/A` with reasons recorded.

### 1. Input Domain

### EC-1: Very long agent name and description in each variant

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.1, AC-107.2 |
| **Category** | Input Domain |
| **Input / Setup** | An agent with a 200-character name and a 600-character description, rendered in dense rows, cards, and ledger |
| **Expected Result** | Single-line ellipsis in rows and ledger; 2-line clamp in cards (§7.5). Layout does not reflow or overflow horizontally |
| **Risk if Missed** | One long description breaks the grid for every agent on the screen. This is the clamp explicitly deferred from S-105 task 2.15 because no primitive rendered an agent name in a card — Wave 3 is where it comes due |

### EC-2: Agent description containing markup and control characters

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.1 |
| **Category** | Input Domain |
| **Input / Setup** | Description containing `<script>alert(1)</script>`, `<img onerror=…>`, RTL override characters, and a zero-width joiner |
| **Expected Result** | Rendered as inert text. No script executes, no layout direction flips for the rest of the page |
| **Risk if Missed** | `agents.description` is operator-authored and therefore semi-trusted, but it is also the only free text on the dashboard. React escapes by default — the test exists to catch the day someone reaches for `dangerouslySetInnerHTML` to get formatting |

### EC-3: Slug with URL-significant characters

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.5, AC-108.7 |
| **Category** | Input Domain |
| **Input / Setup** | Navigate to `/agents/foo%2Fbar`, `/agents/..%2F..%2Fetc`, and `/agents/a b` |
| **Expected Result** | 404 for each. No traversal, no unhandled decode error, no 500 |
| **Risk if Missed** | An unhandled decode throws a 500 where a 404 belongs, and a 500 on a public route is an information leak about internals |

### 2. State Transitions

### EC-4: A terminal run is never re-derived by a screen

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.4, AC-108.3 |
| **Category** | State Transitions |
| **Input / Setup** | A `succeeded` run whose `started_at` is a year in the past (so a naive threshold comparison would call it stale) |
| **Expected Result** | Displays `succeeded`. Both in the row and in the aggregate breakdown |
| **Risk if Missed** | Every historical successful run reads `timed_out` — the whole registry becomes untrustworthy, and it would look like a data problem rather than a display bug |

### EC-5: Rapid double toggle of collapse and density

| Field | Value |
| --- | --- |
| **AC(s)** | AC-106.2, AC-107.3 |
| **Category** | State Transitions |
| **Input / Setup** | Fire the collapse shortcut twice within one frame; click the density toggle three times quickly |
| **Expected Result** | Final visual state matches the final persisted value. No stuck intermediate width, no torn state |
| **Risk if Missed** | A persisted value that disagrees with what is on screen — the bug reappears on next load and is hard to reproduce deliberately |

### EC-6: Navigating between screens preserves shell state

| Field | Value |
| --- | --- |
| **AC(s)** | AC-106.2 |
| **Category** | State Transitions |
| **Input / Setup** | Collapse the sidebar, navigate `/` → `/agents/dependency-update` → back |
| **Expected Result** | Sidebar stays collapsed throughout; no flash of expanded state on either navigation |
| **Risk if Missed** | The shell remounting per route defeats the persistence AC while still passing a single-page persistence test |

### 3. Timing & Concurrency

### EC-7: Hydration reconciliation does not flash or warn

| Field | Value |
| --- | --- |
| **AC(s)** | AC-106.2 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | `localStorage` says collapsed; the server cannot know that and renders expanded. Load the page with the console captured |
| **Expected Result** | No React hydration warning. The reconciliation to collapsed happens without a visible expanded frame, or with one that is explicitly accepted and documented |
| **Risk if Missed** | The story's own technical notes call this the trap. A silenced hydration warning is a class of bug that hides real server/client divergence for the rest of the project — see G3 for how to make this assertable rather than aspirational |

### EC-8: Variant switch does not refetch

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.2 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | Render the dashboard with the data-access layer instrumented; switch dense → cards → ledger → dense |
| **Expected Result** | Zero additional reads. The three variants are presentations of one payload |
| **Risk if Missed** | Four reads where one belongs, and — worse — the variants could show *different* data if a run lands between switches, making the toggle look like it changes the truth. See G4: this needs an instrument, not an eyeball |

### EC-9: Relative times do not go stale mid-session or jitter

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.1, AC-108.2 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | Render with an injected fixed `now`; confirm the same input yields the same output. Then confirm the page's stated behavior on refresh |
| **Expected Result** | `now` is injected, never read implicitly inside a formatter call during render, so component tests are deterministic |
| **Risk if Missed** | Tests that pass at 10:59 and fail at 11:00. `formatRelative` already takes an explicit `now` (S-105) — the risk is a screen calling it with `new Date()` inline |

### 4. Idempotency

### EC-10: Re-rendering with identical props produces identical output

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.2, AC-108.2 |
| **Category** | Idempotency |
| **Input / Setup** | Render each variant and the run history table twice with the same fixture and the same injected `now`; compare serialized output |
| **Expected Result** | Byte-identical. No `Math.random()` keys, no `Date.now()` in a render path |
| **Risk if Missed** | Unstable keys cause React to discard and rebuild rows, which shows up later as lost focus and scroll position — and it is nearly impossible to diagnose from the symptom |

### 5. Failure Modes

### EC-11: Database unreachable while rendering a screen

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.1, AC-108.1 |
| **Category** | Failure Modes |
| **Input / Setup** | The query helper rejects with a PostgREST/network error during a server render |
| **Expected Result** | A legible error surface. The Postgres code is logged, never rendered (spec §13). Not a blank page, not a stack trace in the browser |
| **Risk if Missed** | The panel's one job is visibility; a white screen during an incident is the worst possible moment for it. Leaking a pg code to the client also contradicts the S-104 `DATABASE_ERROR` contract |

### EC-12: `localStorage` throws on access

| Field | Value |
| --- | --- |
| **AC(s)** | AC-106.2, AC-107.3 |
| **Category** | Failure Modes |
| **Input / Setup** | A `localStorage` getter that throws (Safari private mode, storage disabled, quota exceeded on write) |
| **Expected Result** | Default expanded, default dense rows, no crash. Writes fail silently; the session still works |
| **Risk if Missed** | The entire panel fails to render because a preference could not be read — a total outage caused by a cosmetic feature |

### EC-13: A route links somewhere that does not exist yet

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.5, AC-108.6 |
| **Category** | Failure Modes |
| **Input / Setup** | Click the Invoke action (route lands in S-113) and a run row link (`/runs/[id]`, lands in S-109) |
| **Expected Result** | A 404 is acceptable and expected; a 500 or an unhandled client exception is not. Whichever is chosen — link-that-404s or rendered-disabled — is recorded in the PR |
| **Risk if Missed** | A wave-boundary artifact that looks like a defect in a demo. Recording the choice is what separates "known gap" from "shipped bug" |

### 6. Auth & Permissions

### EC-14: No client-side database access appears on either screen

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.1, AC-108.1 |
| **Category** | Auth & Permissions |
| **Input / Setup** | The SD2 lint glob extended to `app/**` (task 1.13); a client component under `app/**` attempting to import `lib/supabase/server` |
| **Expected Result** | Lint error, and `next build` failure via `server-only`. The existing `eslint-server-import.test.ts` still proves the rule fires |
| **Risk if Missed** | Wave 3 introduces the first client components under `app/**`. `server-only` remains the hard guard, but the lint hint is what catches it in one second instead of one build |

### EC-15: Disabled nav items are not reachable by any input method

| Field | Value |
| --- | --- |
| **AC(s)** | AC-106.3, AC-106.5 |
| **Category** | Auth & Permissions |
| **Input / Setup** | Tab through the sidebar; attempt to activate each disabled destination by click and by `Enter` |
| **Expected Result** | Not links, not focus traps, communicated as unavailable to assistive technology (not by color or opacity alone). No navigation occurs |
| **Risk if Missed** | Four dead clicks that read as breakage, or four `aria-disabled` items a screen reader still announces as links — the PRD deferral is meant to be *visible*, not merely inert |

### 7. Data Boundaries

### EC-16: p50 duration with even, odd, single, and zero run counts

| Field | Value |
| --- | --- |
| **AC(s)** | AC-108.5 |
| **Category** | Data Boundaries |
| **Input / Setup** | Run sets of size 0, 1, 2, 3, 4; one set where every duration is null (all runs still in flight) |
| **Expected Result** | Documented p50 for each; a legible placeholder for 0 runs and for all-null. Never `NaN`, never `Infinity`, never a thrown error |
| **Risk if Missed** | `NaN min` in the header of a brand-new agent — the exact moment a first-time user forms an impression of the tool |

### EC-17: Success rate with zero runs and with zero terminal runs

| Field | Value |
| --- | --- |
| **AC(s)** | AC-108.5 |
| **Category** | Data Boundaries |
| **Input / Setup** | An agent with no runs; an agent whose only run is still `running` |
| **Expected Result** | A placeholder (`—`), not `0%` and not `NaN%`. The denominator's definition is recorded: terminal runs only, or all runs |
| **Risk if Missed** | `0%` success for an agent that has simply never finished a run is an actively misleading number — worse than no number |

### EC-18: Sub-second, zero, and multi-hour durations

| Field | Value |
| --- | --- |
| **AC(s)** | AC-108.2 |
| **Category** | Data Boundaries |
| **Input / Setup** | Durations of 0ms, 400ms, 59.6s, 3600s, 7265s |
| **Expected Result** | Per §7.2 via `lib/format.ts`. `0s`, not empty; `1h 1m 05s` or the documented form for over an hour |
| **Risk if Missed** | An empty duration cell reads as missing data. §7.2 does not define an hours form explicitly — if the screens need one, that is a DESIGN.md clarification, not an improvisation |

### EC-19: Empty collections at every level

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.6, AC-108.6 |
| **Category** | Data Boundaries |
| **Input / Setup** | Zero enabled agents; an agent with zero runs; a run with zero steps |
| **Expected Result** | Legible empty states — the dashboard states there are no agents, the history offers an invoke CTA, steps read `0/0` |
| **Risk if Missed** | A blank region is indistinguishable from a failed load. This is the state a new deployment starts in, so it is the first thing anyone sees |

### EC-20: A run whose agent requires no repository

| Field | Value |
| --- | --- |
| **AC(s)** | AC-108.2 |
| **Category** | Data Boundaries |
| **Input / Setup** | A run with `repository_id` null (`requires_repository = false`) |
| **Expected Result** | A clean empty repository cell. No `null/null`, no `undefined/undefined` |
| **Risk if Missed** | Already flagged in Wave 2 (EC-18 there) at the query layer; Wave 3 is where it becomes visible. The row is where the two-part `org/name` render actually happens |

### 8. Resource Exhaustion

### EC-21: An agent with a very large run history

| Field | Value |
| --- | --- |
| **AC(s)** | AC-108.1, AC-107.1 |
| **Category** | Resource Exhaustion |
| **Input / Setup** | 2,000+ runs for one agent; the run history is unpaginated by design (PRD §10) |
| **Expected Result** | The page renders within a documented time budget, or the story records the observed degradation and the threshold at which pagination becomes necessary |
| **Risk if Missed** | "Unfiltered and unpaginated" is a deliberate Phase 2 simplification, and it has a breaking point. Finding it now costs one seeded fixture; finding it in production costs an unusable screen. `RunStrip` capping at 24 is separately asserted |

### EC-22: `max_rows` truncation is visible, not silent

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.1, AC-108.1 |
| **Category** | Resource Exhaustion |
| **Input / Setup** | More than 1,000 rows behind either screen's read |
| **Expected Result** | Either full data via internal paging, or an explicit "showing the most recent N" statement. Never a truncated list presented as complete |
| **Risk if Missed** | A silently truncated run list makes an operator conclude a run never happened. PostgREST returns 1,000 rows with no error — the failure has no signal unless one is built |

### 9. API Versioning

### EC-23: A future `run_status` enum value degrades gracefully

| Field | Value |
| --- | --- |
| **AC(s)** | AC-107.4, AC-108.3 |
| **Category** | API Versioning |
| **Input / Setup** | A row with `status = "cancelled_by_operator"` (not in the v1 enum), and a `canceled` row (in the enum, never written in v1) |
| **Expected Result** | Neutral fallback pill with the raw value as text. No crash, no blank cell |
| **Risk if Missed** | A future migration adding a status would take both screens down. S-105's `status-meta.ts` already has the fallback; this proves it survives composition |

### EC-24: A persisted preference from a previous panel version

| Field | Value |
| --- | --- |
| **AC(s)** | AC-106.2, AC-107.3 |
| **Category** | API Versioning |
| **Input / Setup** | `localStorage` holding a key or value shape from a hypothetical earlier release (e.g. a numeric variant index instead of a name) |
| **Expected Result** | Ignored in favor of the default; optionally cleaned up. No crash |
| **Risk if Missed** | Self-inflicted breakage on upgrade, affecting only returning users — the ones whose experience matters most. Cheap to prevent by validating at the boundary (CT-4/CT-5) |

**Categories marked N/A:** *Idempotency of writes* — this wave writes nothing to the database; EC-10 covers render idempotency instead. *Cross-tenant data access* — single-tenant system with no user auth (D16/D18); EC-14 covers the only privilege boundary that exists (browser ↔ server).

---

## Part 3 — Flagged Gaps and Harness Risks

These require a decision before or during implementation. They are not test scenarios.

### G1 — RESOLVED: `/DESIGN.md` §7.1 now defines one relative-time form (was High)

**Original finding.** The S-105 audit's drift D3 recorded that §7.1 defined a compact relative form (`14m ago`, "Dashboard last run") alongside the longer form (`14 min ago`, "Run history table"), and `lib/format.ts` implements only the latter. §5.1 requires the dashboard to show "last run time", so CT-11 could not be written, and the implementer could not resolve it without either violating CT-10 (screen formats its own string) or silently contradicting DESIGN.md.

**Resolution (2026-09-04, `/DESIGN.md` v1.1).** The compact row is **removed from §7.1**. There is one relative-time form — `just now` / `N min ago` / `Nh ago` / `yesterday` / `Nd ago` — shared by the run history table and the dashboard's last-run column, and it is exactly what `formatRelative` already emits. No `formatRelativeCompact`, no new task on S-107. If a compact form is ever wanted it must be added to §7.1 and to `lib/format.ts` as a named formatter first; a screen never formats a relative time itself.

CT-11 is unblocked and now asserts the single form on both screens. `/DESIGN.md` v1.1 resolved D1 (uniform 14% pill tint) and D2 (1.6s pulse everywhere) in the same pass — both match what S-105 shipped, so neither affects Wave 3 code.

### G2 — Two new Layer 2.5 suites inherit the skip-to-green hole (High)

`dashboard-query.test.ts` and `runs-by-agent.test.ts` sit behind the same `probeLocalDb` guard as Wave 2's suites, so they skip — green — when Docker is down. Wave 3 makes this materially worse than in Wave 2: **CT-1, CT-7, and CT-8 are all Layer 2.5**, and each is the only check on a specific way the dashboard can be wrong (miscounted status buckets, N+1 growth, silent `max_rows` truncation). A green `make validate` on a machine without Docker asserts none of it.

Observed while checking Wave 3 readiness: on a run where the local stack **was** reachable and `status-parity`, `schema`, `seed-schema`, and `reaper` all executed live, `queries.test.ts` and `rls-deny-all.test.ts` still skipped 15 tests. So the gate is narrower than `probeLocalDb` alone — some suites have an additional precondition (env var or grant) that silently disables them even with a healthy database.

**Recommendation:** [#134](https://github.com/llipe/dev-tasks-agent-fleet/issues/134) remains the CI fix and is not a task in this wave. Two things this wave must do anyway: each story states in its PR whether its integration suite **ran live or skipped** (a skip is not evidence), and someone establishes why a healthy stack still skips two suites — an unexplained skip is a test that no one can rely on.

### G3 — "No hydration warning" is not assertable by default (High)

AC-106.2's real risk is a hydration mismatch, and EC-7 asserts the absence of a warning — but a React hydration warning is a `console.error` in development, which by default fails nothing. Testing Library will not surface it; the test passes while the defect ships. Worse, the usual local fix (`suppressHydrationWarning`) makes the symptom disappear permanently for the whole subtree.

**Recommendation:** make it mechanical — spy on `console.error`/`console.warn` in the shell test setup and fail on any hydration-related message. Better still, add a project-wide setup that fails **any** test emitting an unexpected `console.error`, which pays off for every wave after this one. And treat `suppressHydrationWarning` as prohibited in this codebase unless a comment names the exact divergence it covers.

### G4 — Two ACs have escape hatches that make them unfalsifiable as written (Medium)

Two criteria contain a documented "or else" that a test cannot adjudicate:

- **AC-107.7:** the ledger's keyboard affordances work "**or** render them absent rather than broken". Both branches pass a suite that asserts nothing.
- **AC-107.2 / EC-8:** "switching variants must not refetch". Without an instrumented data layer, "no refetch" is an eyeball claim, and the natural implementation (three server components) would refetch invisibly.

**Recommendation:** for AC-107.7, pick the branch **before** implementation and record it in the plan; if affordances ship, test all three keys, and if they do not, assert the controls are absent from the DOM. Escape hatches are legitimate in a story and useless in a test plan. For AC-107.2, decide the instrument now — a spy on the query helper, or an assertion that the variant components receive props and issue no reads — so CT-7/EC-8 have a mechanism rather than an intention.

### G5 — AC-108.4 is a manual procedure, so it verifies once and then rots (Medium)

The reaper-paused check (PRD AC10) is the story's most valuable assertion: it proves the two-layer design from `technical-guidelines.md` §3 is observable from the UI. As written it is a hand-executed runbook — real evidence on the day it runs, and no protection against a later refactor.

**Recommendation:** do both. Keep the manual procedure and its recorded evidence (task 3.11/3.12, local stack only — pausing the hosted reaper would leave real Phase 1 runs unreaped), **and** encode the same assertion as a Layer 2.5 test that inserts a past-threshold `running` row and reads `timed_out` through `v_runs` without touching the cron schedule. The test does not need the reaper paused; it needs a row the reaper has not reached yet, which a fresh insert already is. That gives a repeatable regression guard plus a one-time live proof.

### G6 — DESIGN.md conformance on three screens is review-only (Medium)

S-105 made token discipline mechanical for twelve components. Wave 3 adds three screens, four dashboard variants, and three run-history components — and their §4.3/§4.4 grid definitions, §5.1/§5.2 field lists, and 1024px behavior are all checked by human comparison against `docs/prototype/`. That was tractable at twelve small files; it is where visual drift starts at this size.

**Recommendation:** do not add a visual-regression harness in this wave — that is a story, not a sub-task. Do two cheap things: assert the §4.3/§4.4 `grid-template-columns` strings directly in component tests (they are exact strings in DESIGN.md, so this is a contract, not a snapshot), and keep the token-discipline gate passing over the new `components/dashboard/**` and `components/runs/**` trees. Note that the existing gate scans `components/**`, so new subdirectories are covered automatically — confirm the vacuity guard's minimum module count is raised accordingly, or it will keep passing on a stale scan.

### G7 — AC-106.6's 1024px claim cannot be verified in jsdom (Low)

"Layout holds at 1024px with no horizontal scroll" needs a real layout engine. jsdom computes no geometry, so a component test cannot see an overflow. Playwright is configured but has no committed scenarios until S-114.

**Recommendation:** verify manually at 1024px and 1440px in this wave (tasks 1.11/1.17) and record it as manual evidence, then carry it as a Playwright scenario in S-114 (#127). Do not write a jsdom test that appears to check this — a test that cannot fail is worse than an honest manual note.

---

## Part 4 — Coverage Matrix

| AC | Layer | Scenarios | Command |
| --- | --- | --- | --- |
| AC-106.1 | 2 | CT-12 | `test` |
| AC-106.2 | 1, 2 | CT-4, CT-5, EC-5, EC-6, EC-7 (**G3**), EC-12, EC-24 | `test:unit` + `test` |
| AC-106.3 | 2 | EC-15 | `test` |
| AC-106.4 | 2 | nav active/hover assertions | `test` |
| AC-106.5 | 2 | CT-13, EC-15 | `test` |
| AC-106.6 | manual | manual at 1024/1440px (**G7** — Playwright in S-114) | `pnpm --filter panel dev` |
| AC-107.1 | 2, 2.5 | CT-1, CT-7, CT-8, CT-10, CT-11, EC-1, EC-2, EC-9, EC-19, EC-21, EC-22 | `test` + `test:integration` |
| AC-107.2 | 2 | CT-2, EC-1, EC-8 (**G4**), EC-10 | `test` |
| AC-107.3 | 1, 2 | CT-4, CT-5, EC-5, EC-12, EC-24 | `test:unit` + `test` |
| AC-107.4 | 1, 2, 2.5 | CT-1, CT-2, CT-3, EC-4, EC-14, EC-23 | `test:unit` + `test:integration` |
| AC-107.5 | 2 | EC-3, EC-13 | `test` |
| AC-107.6 | 2 | EC-19 | `test` |
| AC-107.7 | 2 | keyboard assertions **or** absence assertions (**decide first — G4**) | `test` |
| AC-108.1 | 2.5 | CT-8, EC-11, EC-21, EC-22 | `test:integration` |
| AC-108.2 | 1, 2 | CT-9, CT-10, CT-13, EC-18, EC-20 | `test:unit` + `test` |
| AC-108.3 | 1, 2, 2.5 | CT-2, CT-3, EC-4, EC-23 | `test:unit` + `test:integration` |
| AC-108.4 | 2.5 + manual | reaper-paused procedure **plus** a stale-row integration test (**G5**) | `test:integration` + runbook |
| AC-108.5 | 1 | EC-16, EC-17 | `test:unit` |
| AC-108.6 | 2 | EC-13, EC-19 | `test` |
| AC-108.7 | 2 | CT-6, EC-3 | `test` |

**Totals:** 13 contract scenarios, 24 edge cases, 20 acceptance criteria. Every AC has at least one mapped scenario. Two are conditional: AC-107.7 is unfalsifiable until G4 is decided, and AC-106.6 is manual-only by harness limitation (G7). G1 was the third and is resolved — `/DESIGN.md` v1.1 (see Part 3).

**Highest-value scenarios if effort must be cut:** CT-2 (the derived status actually reaching the pill — the composition Wave 2 could not prove, and the entire point of FR11a), CT-1 (the aggregate counting `effective_status`, the same bug one level up and much easier to miss), CT-8/EC-22 (silent `max_rows` truncation, which has already caught this project once), and CT-4 (untrusted `localStorage`, the cheapest crash to prevent and the one whose provider we cannot control).

**Not in this plan:** end-to-end scenarios. Playwright lands in S-114 (#127), which is where AC-106.6, PRD AC9's cross-reload behavior, and PRD AC10's user-visible path get browser-level coverage. This plan stops at Layer 2.5 deliberately rather than describing E2E tests no harness will run this wave.
