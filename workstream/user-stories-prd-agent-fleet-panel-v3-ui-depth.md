# User Stories — Agent Fleet Control Panel v3: UI Depth

## Changelog

| Version | Date       | Summary                                                                 | Author           |
| ------- | ---------- | ----------------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-09-15 | Initial version, generated from [`specification-prd-agent-fleet-panel-v3-ui-depth.md`](specification-prd-agent-fleet-panel-v3-ui-depth.md) v1.0 and [`prd-agent-fleet-panel-v3-ui-depth.md`](../docs/requirements/prd-agent-fleet-panel-v3-ui-depth.md) v1.0. Seven stories, numbered **S-142–S-148** continuing the project-wide story sequence (highest prior: S-141, `security-analyst` PRD). Full FR1–FR18 coverage — see Coverage Validation. | product-engineer |

---

## Story S-142: Fix the queued-status animation defect

**Priority:** Medium
**Estimated Size:** XS
**Dependencies:** None

#### User Story

As the operator,
I want a `queued` run's status dot to visibly spin, distinct from a `running` run's pulse,
So that I can tell the two states apart at a glance instead of seeing the same animation for both.

#### Context

`/DESIGN.md` §6.1/§8.1 specifies `queued` uses the `spin 0.9s` keyframe (a loading spinner), distinct from `running`'s `pulse 1.6s`. `components/status-meta.ts` currently marks both `queued` and `running` as `pulse: true` — a defect against the design contract, not a design ambiguity (the `@keyframes spin` rule already exists, unused, in `styles/globals.css`). This is FR12 (PRD §7) and is deliberately sequenced first: smallest, most contained, zero risk of blocking any other story in this set (spec §15).

#### Acceptance Criteria

- [ ] A `queued` run's `StatusDot` renders with the `.spin` class and the `spin 0.9s linear infinite` animation.
- [ ] A `running` run's `StatusDot` still renders with `.pulse` (`pulse 1.6s ease-in-out infinite`) — unchanged.
- [ ] No other status's rendering changes (`succeeded`/`failed`/`timed_out`/`failed_to_start`/`canceled` all unaffected).
- [ ] `StatusPill` (which also consumes `statusMeta`) does not regress — its `queued` pill still renders correctly with the new `spin` flag present but unused there (pills don't animate the dot the same way; confirm no visual regression).

#### Business Rules

- Status visualization continues to derive its color/animation metadata from the single `statusMeta` lookup (`components/status-meta.ts`) — no screen may special-case `queued` locally.

#### Technical Notes

- Spec §8.3. Three-file change: `components/status-meta.ts` (`StatusMeta` interface gains `spin: boolean`; `queued` entry becomes `{ pulse: false, spin: true, ... }`; every other entry gets `spin: false`), `components/StatusDot.tsx` (class list gains `meta.spin && styles.spin`), `components/StatusDot.module.css` (new `.spin { animation: spin 0.9s linear infinite; }` rule — reuses the existing `@keyframes spin` in `styles/globals.css`, does not redefine it).
- Reference `/DESIGN.md` §6.1 (animation table) and §8.1 (status→visual mapping) in the PR description as the design source for this fix.

#### Testing Requirements

- **Unit Tests:** `tests/unit/status-meta.test.ts` — extend the existing suite (or add if none exists at this granularity) to assert `queued` is `{ pulse: false, spin: true }` and every other status is `{ spin: false }`.
- **Integration Tests:** None (presentational-only, no data layer touched).
- **Manual/UI Testing:** `panel/app/dev/gallery` (the existing dev-only variant gallery, S-105) — visually confirm `queued` spins and `running` pulses side by side.
- **Edge-Case Matrix:** Unknown/future status string still falls back to the existing neutral `statusMeta` default (`spin: false`, unchanged fallback behavior).
- **Acceptance-Criteria Mapping:** AC1/AC2 → `StatusDot.test.tsx` (extend existing suite with a `queued` vs `running` class-list assertion); AC3 → `token-discipline.test.ts` unaffected (no new literal); AC4 → `StatusPill.test.tsx` unaffected-regression check.
- **Execution Commands:** `pnpm --filter panel test:unit`, `pnpm --filter panel test`.

#### Migration Requirements

- Migration artifact: **N/A opt-out** — no schema/data change, presentational CSS/TS only.
- Rollback/impact notes: A plain revert; no data to reverse.
- Apply step: N/A.
- Verification after apply: N/A.

#### Implementation Steps

1. Add `spin: boolean` to `StatusMeta` in `components/status-meta.ts`; set `queued: { ..., pulse: false, spin: true }`; set `spin: false` on every other entry (including the unknown-status fallback).
2. Update `StatusDot.tsx`'s class-list construction to include `meta.spin && styles.spin`.
3. Add `.spin { animation: spin 0.9s linear infinite; }` to `StatusDot.module.css`.
4. Update/extend unit tests; run `pnpm --filter panel test:unit` and the dev gallery visual check.

#### Files to Create/Modify

- `panel/components/status-meta.ts` — add `spin` field, flip `queued`
- `panel/components/StatusDot.tsx` — consume `meta.spin`
- `panel/components/StatusDot.module.css` — add `.spin` rule
- `panel/tests/unit/status-meta.test.ts` — extend
- `panel/tests/component/StatusDot.test.tsx` — extend

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines (Nocturne token discipline — no new literal introduced)
- [ ] Unit/component tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] Migration lifecycle: N/A opt-out documented
- [ ] Pull Request created and merged

---

## Story S-143: Run History — filter, search, and pagination

**Priority:** High
**Estimated Size:** L
**Dependencies:** None

#### User Story

As the operator,
I want to filter the Run History screen by status, repository, and free text, and page through results,
So that I can find a specific run without scrolling an unbounded, unfiltered list.

#### Context

Implements FR1–FR6 and FR8 (spec §8.1, §10). This is the foundational story for the whole "run list depth" half of the PRD: it introduces the shared `lib/domain/run-filter.ts` URL↔filter model and the `getFilteredRuns` query helper that S-146 (All Runs) will reuse directly. Today, `/agents/[slug]` reads the full unfiltered history via `getAllRunsByAgentSlug` (v2.1 FR11 scope) — this story replaces that read path for this screen only; `getAllRunsByAgentSlug` itself is not deleted (verify no other caller depends on it before removing, per Implementation Steps).

#### Acceptance Criteria

- [ ] *(FR1)* A status segmented control (colored dot + live count per option) filters the table to that `effective_status`; a stale `running` row past its timeout threshold counts and filters as `timed_out`, never `running` (FR11a, verified against a `v_runs` fixture with the reaper paused).
- [ ] *(FR2)* Repository filter chips (populated from `getEnabledRepositories`, per spec §8.1's documented simplification) narrow the list to that repository; combined with a status filter, the result is the intersection.
- [ ] *(FR3)* A free-text search box matches repository name, branch, or run id substring; combined with other filters, narrows the intersection.
- [ ] *(FR4)* Reloading a URL carrying `?status=failed&repo=<id>&q=foo` reproduces the identical filtered result from a fresh server-side query — not a client-side re-filter of a larger fetch.
- [ ] *(FR5)* Pagination renders as "`X of Y`" plus a "Load more" button (never numbered pages); "Load more" under an active filter fetches the next cumulative page of the **filtered** set, not the unfiltered list.
- [ ] *(FR6)* A filter combination matching zero runs renders an empty state with an explanatory message and a working "Clear filters" CTA that resets the URL to the unfiltered view.
- [ ] *(FR8)* A connection-state indicator is present in the filter bar, reflecting whether the last server fetch for this page succeeded (per spec §17 Open Question #1 resolution: presentational only, no new Realtime subscription).

#### Business Rules

- Filter/pagination state lives in the URL query string only — never `localStorage`, never bare component state (spec §8.1's Business Rule, deliberately different from the Dashboard's `localStorage`-persisted density toggle, D17).
- Every status shown anywhere in this story derives from `effective_status` (`v_runs`), never raw `runs.status` — no new status-derivation logic is introduced; `lib/domain/run-filter.ts` and `getFilteredRuns` consume the existing `lib/domain/status.ts` derivation, never restate it.
- Pagination is **cumulative offset paging** (`page` = "show pages 1..page"), not keyset — see spec §8.1 for the rationale (matches the codebase's existing exclusive use of `.range()`).

#### Technical Notes

- Spec §8.1, §10, §11 (Performance caveat: filtering `effective_status` has no index — accepted at current volume).
- New pure module `lib/domain/run-filter.ts`: `parseRunFilter(searchParams): RunFilter` (total, never throws — unknown values fall back to `"all"`/`null`/`1`) and `serializeRunFilter(filter): URLSearchParams` (omits default values).
- New query helper in the **existing** `lib/supabase/queries.ts` (not a new file, per the `insertQueuedRun` precedent): `getFilteredRuns(client, filter, pageSize): Promise<{ rows: VRunRow[]; totalCount: number }>` using `.select("*", { count: "exact" })` + conditional `.eq`/`.ilike` + `.range(0, filter.page * pageSize - 1)`.
- New `"use client"` component `components/runs/RunFilterBar.tsx` — mutates the URL via `router.replace`, search input debounced 300ms.
- `app/(panel)/agents/[slug]/page.tsx` reads `searchParams`, calls `parseRunFilter` + `getFilteredRuns` instead of `getAllRunsByAgentSlug`. Route-segment config (`dynamic`/`revalidate`/`fetchCache`) stays declared **inline** (S-104 audit D4, §12 convention) — do not re-export from a shared module.
- Repository chips reuse the **existing** `getEnabledRepositories` helper as-is — do not write a new "repositories referenced in this agent's runs" query (documented spec-level simplification, not a PRD change).

#### Testing Requirements

- **Unit Tests:** `run-filter.test.ts` (parse/serialize round-trip; unknown value → default fallback for each field independently; default values omitted from the serialized URL; never throws on malformed input).
- **Integration Tests (Layer 2.5, Docker-gated, run live):** `filtered-runs.test.ts` — status/repo/search combinations against a seeded fixture including a stale `running` row (reaper paused) to prove FR1's `effective_status` invariant; paging beyond a simulated `max_rows` boundary; `totalCount` accuracy under each filter combination.
- **Manual/UI Testing:** `/agents/dependency-update` with the local stack seeded — apply each filter individually and in combination; confirm the URL updates and reload reproduces the same view.
- **Edge-Case Matrix:** zero-match filter combination (empty state + CTA); search string containing regex metacharacters (must not throw — literal substring match only, mirroring the existing dashboard `AgentFilter` EC-25 precedent); a repository chip for a repo with zero runs for this agent (empty state, not an error).
- **Acceptance-Criteria Mapping:** AC1→`filtered-runs.test.ts::status filter`; AC2→`::repo filter`; AC3→`::search`; AC4→`run-filter.test.ts::round-trip` + `filtered-runs.test.ts::url-reload parity`; AC5→`::pagination`; AC6→`RunFilterBar.test.tsx::empty state`; AC8→`RunFilterBar.test.tsx::connection indicator`.
- **Execution Commands:** `pnpm --filter panel test:unit`, `pnpm --filter panel test:integration` (requires local Supabase stack — `REQUIRE_LOCAL_DB=1`), `pnpm --filter panel test`.

#### Migration Requirements

- Migration artifact: **N/A opt-out** — reads only, no schema/data change (confirmed: every column already exists, spec §5).
- Rollback/impact notes: Plain revert; no data to reverse.
- Apply step: N/A.
- Verification after apply: N/A.

#### Implementation Steps

1. Write `lib/domain/run-filter.ts` (`parseRunFilter`/`serializeRunFilter`) with Layer 1 unit tests first (test-first per repo default).
2. Add `getFilteredRuns` to `lib/supabase/queries.ts`; write the Layer 2.5 integration test against the local stack.
3. Build `components/runs/RunFilterBar.tsx` (segmented control, chips, search, connection indicator) as a `"use client"` component.
4. Wire `app/(panel)/agents/[slug]/page.tsx` to read `searchParams` → `parseRunFilter` → `getFilteredRuns`, replacing the direct `getAllRunsByAgentSlug` call for this screen; confirm no other caller of `getAllRunsByAgentSlug` breaks (grep before removing anything).
5. Add the empty state to `RunHistoryTable.tsx` (or a new sibling component) with the "Clear filters" CTA.
6. Run `pnpm --filter panel validate`; manual pass against the seeded local stack.

#### Files to Create/Modify

- `panel/lib/domain/run-filter.ts` — new
- `panel/lib/domain/run-filter.test.ts` — new
- `panel/lib/supabase/queries.ts` — add `getFilteredRuns`
- `panel/tests/integration/filtered-runs.test.ts` — new
- `panel/components/runs/RunFilterBar.tsx` (+ `.module.css`) — new
- `panel/components/runs/RunFilterBar.test.tsx` — new
- `panel/app/(panel)/agents/[slug]/page.tsx` — modify (searchParams → filter → query)
- `panel/components/runs/RunHistoryTable.tsx` — add empty-state rendering

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines (SD2 server-only boundary preserved, inline route-segment config, Nocturne token discipline)
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] Migration lifecycle: N/A opt-out documented
- [ ] Pull Request created and merged

---

## Story S-144: Run History — inline branch and PR links

**Priority:** Medium
**Estimated Size:** S
**Dependencies:** S-143 (touches the same `RunHistoryRow.tsx`/`RunHistoryTable.tsx` this story modifies — sequence after to avoid a merge conflict, not a hard functional dependency)

#### User Story

As the operator,
I want to see the branch and, when one exists, a link to the PR directly in the run history table,
So that I don't have to open each run to check them.

#### Context

Implements FR7 (spec §10). Branch display is **already implemented** — `lib/domain/run-row.ts`'s `repositoryBranch` field, sourced from `runs.params.branch`, already renders in `RunHistoryRow.tsx`. Only the PR-link half is new: it requires reading `run_artifacts` (type `pull_request`) for the visible page of run rows, via a new grouped helper mirroring the existing `getStepProgressForRuns` shape (one grouped read, never N+1).

#### Acceptance Criteria

- [ ] A run row whose run carries a `pull_request` artifact shows a clickable link to that PR inline in the repository cell, without opening the row.
- [ ] A run row with no `pull_request` artifact shows the existing branch-only rendering, unchanged.
- [ ] The PR-link lookup is a single grouped query per page of rows — confirmed never N+1 (one query regardless of row count on the page).
- [ ] The link is `https:`-only and safe — reuses the existing `isSafeArtifactUrl` guard from `lib/domain/artifact-url.ts` (S-109), not a new/duplicate URL-safety check.

#### Business Rules

- Reuses, never duplicates, the existing artifact-URL safety guard (`isSafeArtifactUrl`) — an agent-written non-`https:` URL renders inert, exactly as it already does on Run Detail.

#### Technical Notes

- Spec §10, §11 (Performance: bounded to `PAGE_SIZE` run ids, never N+1).
- New helper in `lib/supabase/queries.ts`: `getPullRequestArtifactsForRuns(client, runIds): Promise<Record<string, RunArtifactRow>>` — same shape as the existing `getStepProgressForRuns`.
- `RunHistoryRow.tsx` gains a conditional PR-link render in the existing repository cell; import `isSafeArtifactUrl` from `lib/domain/artifact-url.ts` (do not reimplement).

#### Testing Requirements

- **Unit Tests:** None new beyond what `artifact-url.ts` already covers (reused, not modified).
- **Integration Tests:** `tests/integration/` extension — `getPullRequestArtifactsForRuns` grouped-read shape (never N+1, empty-list → `{}`, a run with a non-`pull_request` artifact type is excluded).
- **Manual/UI Testing:** A run history page with a mix of runs with/without `pull_request` artifacts — confirm the link renders only where expected and opens the correct PR.
- **Edge-Case Matrix:** a run with a `pull_request` artifact carrying an unsafe URL (`javascript:`/relative) — confirm it renders inert, matching Run Detail's existing behavior; empty page (zero rows) → zero-cost lookup.
- **Acceptance-Criteria Mapping:** AC1/AC2 → `RunHistoryRow.test.tsx` extension; AC3 → integration test grouped-read assertion; AC4 → reuses `artifact-url.test.ts` (S-109), no new test needed, referenced in the PR description.
- **Execution Commands:** `pnpm --filter panel test:unit`, `pnpm --filter panel test:integration`, `pnpm --filter panel test`.

#### Migration Requirements

- Migration artifact: **N/A opt-out** — reads only, `run_artifacts` table and its `type`/`url` columns already exist.
- Rollback/impact notes: Plain revert.
- Apply step: N/A.
- Verification after apply: N/A.

#### Implementation Steps

1. Add `getPullRequestArtifactsForRuns` to `lib/supabase/queries.ts`, test-first (integration test against the local stack).
2. Extend `RunHistoryRow.tsx`'s repository cell to render the PR link when present, guarded by `isSafeArtifactUrl`.
3. Wire the new query into `app/(panel)/agents/[slug]/page.tsx` (and, once it lands, S-146's `/runs` page) alongside the existing `getStepProgressForRuns` call.
4. Manual verification against the seeded local stack with a fixture run carrying a `pull_request` artifact.

#### Files to Create/Modify

- `panel/lib/supabase/queries.ts` — add `getPullRequestArtifactsForRuns`
- `panel/tests/integration/pull-request-artifacts.test.ts` — new
- `panel/components/runs/RunHistoryRow.tsx` — add PR-link cell
- `panel/components/runs/RunHistoryRow.test.tsx` — extend
- `panel/app/(panel)/agents/[slug]/page.tsx` — wire the new read

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines (reuses `isSafeArtifactUrl`, never a duplicate check)
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] Migration lifecycle: N/A opt-out documented
- [ ] Pull Request created and merged

---

## Story S-145: Run Detail — steps panel with step and log-level filtering

**Priority:** High
**Estimated Size:** L
**Dependencies:** None

#### User Story

As the operator,
I want a steps panel on Run Detail that I can click to filter the log viewer, plus a log-level filter,
So that I can jump straight to a failing step's log lines instead of scrolling the full tail.

#### Context

Implements FR9, FR10, FR11 (spec §8.2, §10). Kept as one story because all three share the same new `lib/domain/log-filter.ts` reducer and the same `LogViewer`/`LiveLogViewer` touch points — splitting them would mean re-touching the same files twice for no independent-value gain. Both filters are resolved in the spec to be **client-side only**, over the log window already loaded by the existing S-109/S-110 windowing (`selectRecentWindow`) — no new server read for either filter, and event counts per step are derived from that same already-loaded window (zero marginal DB reads).

#### Acceptance Criteria

- [ ] *(FR9)* A steps panel renders each `run_steps` row as a vertical list item: colored status dot, mono step name, duration, event count.
- [ ] *(FR10)* Clicking a step filters the log viewer to that step's events only (`run_events.step_id` match); a visible "All steps" control clears the filter back to the full tail.
- [ ] *(FR11)* A level filter (e.g., "errors and warnings only") narrows the log viewer independently of the step filter; both filters apply together (a step + level combination shows only lines matching both).
- [ ] The steps panel and both filters work identically on a terminal run (`LogViewer`) and a live run (`LiveLogViewer`) — clicking a step or a level on a live tail does not break autoscroll/pause-resume (S-110 behavior untouched).
- [ ] A live run's step event counts may under-count until the SSE tail catches up (documented, non-blocking behavior per spec §16 — not a bug to fix in this story).

#### Business Rules

- `run_steps.status` (not `effective_status`) drives the steps panel's per-step color — steps are not reaper-computed the way run-level status is (technical-guidelines §8, "Reaper mirrors the agent's step-closure" — a reaped run's orphan steps are already closed `failed` by the reaper, so the steps panel needs no additional stale-step handling).
- Log message rendering stays an inert text node — filtering must not introduce any `dangerouslySetInnerHTML` path (security guard #6, unchanged).

#### Technical Notes

- Spec §8.2, §16 (live-run under-count caveat, explicitly accepted).
- Extend the existing `lib/domain/run-detail.ts` with `buildStepsPanel(steps: RunStepRow[], eventCountByStep: Record<string, number>): StepPanelRow[]` — event counts computed by the **caller** from the already-fetched event window (no new query).
- New pure reducer `lib/domain/log-filter.ts`: `applyLogFilter(lines: LogLine[], filter: { stepId: string | null; level: LogLevel | "all" }): LogLine[]`.
- New component `components/run-detail/StepsPanel.tsx`; a small filter-state wrapper around `LogViewer.tsx`/`LiveLogViewer.tsx` (a `"use client"` parent owning `{ stepId, level }` state, passed down).

#### Testing Requirements

- **Unit Tests:** `log-filter.test.ts` (step-only, level-only, both combined, neither → full tail, "All steps" resets, unknown `stepId` → empty result not a crash); `run-detail.test.ts` extension for `buildStepsPanel` (duration formatting reuse from `lib/format.ts`, zero-event step, in-progress step with no `finished_at`).
- **Integration Tests:** None new (no new server read).
- **Manual/UI Testing:** A run with a failed step — click it, confirm the log narrows; click "All steps", confirm it restores; apply a level filter on top, confirm both compose. Repeat on a **live** (non-terminal) run to confirm autoscroll/pause-resume still works with a filter active.
- **Edge-Case Matrix:** a run with zero steps (steps panel renders empty, not an error); a step with zero events (event count `0`, clicking it shows an empty filtered log, not a crash); a live run mid-tail when a step filter is applied (new events for the filtered-out step must not appear; a new event for the filtered-in step must still autoscroll per S-110 behavior).
- **Acceptance-Criteria Mapping:** AC1 → `StepsPanel.test.tsx`; AC2/AC3 → `log-filter.test.ts` + `StepsPanel.test.tsx` click-to-filter; AC4 → `LiveLogViewer.test.tsx` extension (filter + live tail composition); AC5 → documented in the PR description, no test asserts an under-count as correct behavior (nothing to assert against).
- **Execution Commands:** `pnpm --filter panel test:unit`, `pnpm --filter panel test`.

#### Migration Requirements

- Migration artifact: **N/A opt-out** — reads only (`run_steps`, `run_events` already fully read for this screen).
- Rollback/impact notes: Plain revert.
- Apply step: N/A.
- Verification after apply: N/A.

#### Implementation Steps

1. Write `lib/domain/log-filter.ts` test-first (Layer 1 unit tests).
2. Extend `lib/domain/run-detail.ts` with `buildStepsPanel`, test-first.
3. Build `components/run-detail/StepsPanel.tsx`.
4. Add the filter-state wrapper around `LogViewer.tsx`/`LiveLogViewer.tsx`; wire step-click and level-filter controls to update the shared `{ stepId, level }` state.
5. Manual pass on both a terminal and a live run fixture.

#### Files to Create/Modify

- `panel/lib/domain/log-filter.ts` — new
- `panel/lib/domain/log-filter.test.ts` — new
- `panel/lib/domain/run-detail.ts` — extend with `buildStepsPanel`
- `panel/lib/domain/run-detail.test.ts` — extend
- `panel/components/run-detail/StepsPanel.tsx` (+ `.module.css`) — new
- `panel/components/run-detail/StepsPanel.test.tsx` — new
- `panel/components/run-detail/LogViewer.tsx` — add filter consumption
- `panel/components/run-detail/LiveLogViewer.tsx` — add filter consumption
- `panel/app/(panel)/runs/[id]/page.tsx` — wire the filter-state wrapper

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines (security guard #6 preserved — no `dangerouslySetInnerHTML`)
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] Migration lifecycle: N/A opt-out documented
- [ ] Pull Request created and merged

---

## Story S-146: All Runs — cross-agent run feed

**Priority:** Medium
**Estimated Size:** M
**Dependencies:** S-143 (reuses `RunFilterBar` and the `getFilteredRuns`/`run-filter.ts` foundation directly)

#### User Story

As the operator,
I want to see every agent's runs in one feed,
So that I don't have to check each agent's history in turn.

#### Context

Implements FR13, FR14 (spec §10). Reverses the v2.1 §10 non-goal that moved "All runs" out of Phase 2 scope, per explicit user decision during PRD refinement (brought forward now rather than gated on a second agent shipping). This is almost entirely composition: the same `RunFilterBar` and `getFilteredRuns` from S-143, minus the agent scoping, plus one new column.

#### Acceptance Criteria

- [ ] *(FR13)* `/runs` shows runs from at least two different agents (in a fixture seeded with two enabled agents), newest-first, each row correctly attributed to its agent via a new Agent column (name + slug).
- [ ] *(FR13)* All of S-143's filter/pagination/empty-state/connection-indicator behavior works identically on `/runs` (status, repo, search, "Load more", empty state).
- [ ] *(FR14)* The sidebar "All runs" item, currently a non-link `DisabledNavItem`, becomes a live `NavItem` link to `/runs`.
- [ ] The existing `/agents/[slug]` screen is unaffected — this story adds a new route, it does not change agent-scoped behavior.

#### Business Rules

- `getFilteredRuns` (from S-143) is called with `filter.agentSlug = null` on this screen — no new query is written; the same helper, same URL model, same `effectiveStatus` derivation.

#### Technical Notes

- Spec §10, §11 (Performance: first agent-unscoped `created_at desc` scan — existing indexes are `(agent_id, created_at desc)` and `(repository_id, created_at desc)`, neither covers this optimally; flagged, not fixed, per PRD Open Question §18 — acceptable at current agent/run volume).
- `RunHistoryTable`/`RunHistoryRow` gain a `showAgentColumn` prop (default `false`, so `/agents/[slug]` is unchanged) rendering agent name + slug (mono, accent-400, matching the existing dashboard agent-identity treatment).
- New route `app/(panel)/runs/page.tsx` — same server-component/inline-route-config shape as `/agents/[slug]`.
- `components/shell/Sidebar.tsx`: swap the "All runs" `DisabledNavItem` for a `NavItem` pointing at `/runs`.

#### Testing Requirements

- **Unit Tests:** None new beyond what S-143 already covers for the shared filter model (reused, not duplicated).
- **Integration Tests:** `filtered-runs.test.ts` extension — `getFilteredRuns` with `agentSlug: null` returns rows across ≥2 agents, newest-first, count accurate.
- **Manual/UI Testing:** Seed two enabled agents locally; visit `/runs`; confirm both appear, filters work, and the sidebar link navigates correctly.
- **Edge-Case Matrix:** a fleet with exactly one enabled agent (still renders correctly, just shows one agent's runs — not an error state); an agent that is `is_enabled = false` (its historical runs still appear in `/runs`, since disabling an agent doesn't delete its runs — confirm this matches the existing `/agents/[slug]` disabled-agent-404 behavior does *not* apply here, since `/runs` is not agent-scoped).
- **Acceptance-Criteria Mapping:** AC1/AC2 → `RunHistoryTable.test.tsx` extension (`showAgentColumn`) + `filtered-runs.test.ts` cross-agent case; AC3 → `Sidebar.test.tsx` extension; AC4 → existing `/agents/[slug]` test suite must stay green unmodified.
- **Execution Commands:** `pnpm --filter panel test:unit`, `pnpm --filter panel test:integration`, `pnpm --filter panel test`.

#### Migration Requirements

- Migration artifact: **N/A opt-out** — reads only, reuses S-143's read path with a different filter value.
- Rollback/impact notes: Plain revert.
- Apply step: N/A.
- Verification after apply: N/A.

#### Implementation Steps

1. Add `showAgentColumn` to `RunHistoryTable`/`RunHistoryRow` (default `false`), test-first.
2. Build `app/(panel)/runs/page.tsx`, reusing `RunFilterBar` + `getFilteredRuns` with `agentSlug: null`.
3. Update `components/shell/Sidebar.tsx` to link "All runs" to `/runs`.
4. Manual pass with ≥2 seeded agents.

#### Files to Create/Modify

- `panel/app/(panel)/runs/page.tsx` — new
- `panel/components/runs/RunHistoryTable.tsx` — add `showAgentColumn`
- `panel/components/runs/RunHistoryRow.tsx` — add agent column rendering
- `panel/components/shell/Sidebar.tsx` — enable "All runs" link
- `panel/tests/integration/filtered-runs.test.ts` — extend (cross-agent case)
- `panel/components/runs/RunHistoryTable.test.tsx` — extend
- `panel/components/shell/Sidebar.test.tsx` — extend

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines (inline route-segment config, SD2 boundary preserved)
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] Migration lifecycle: N/A opt-out documented
- [ ] Pull Request created and merged

---

## Story S-147: Repositories — list and add-by-reference

**Priority:** High
**Estimated Size:** L
**Dependencies:** None

#### User Story

As the operator,
I want to see the registered repositories and add a new one by reference,
So that I can make a repository available for agent invocation without touching Supabase or GitHub directly.

#### Context

Implements FR15, FR16, FR18 (spec §6, §7, §8.4, §10). Reverses the v2.1 §10 non-goal that moved "Repositories" out of Phase 2 scope, redefined per explicit user decision as a manually-managed reference list — **not** GitHub App repo sync (that stays backlog, per technical-guidelines §8). This is the panel's **second** user-triggered database write (after S-112's Invoke), and its first Server-Action-shaped write (S-112 used a route handler because it also crosses into AgentCore invocation; this does not).

#### Acceptance Criteria

- [ ] *(FR15)* `/repositories` lists rows from the `repositories` table, excluding archived rows by default, showing `full_name`, `default_branch`, and enabled state.
- [ ] *(FR16)* An "Add repository" action inserts a new row (`full_name`, `default_branch` defaulting `main`, `is_enabled = true`) against the single seeded `github_installations` row, **without calling the GitHub API**.
- [ ] *(FR16)* Adding a `full_name` that already exists under the installation (case-sensitive exact match) shows a friendly `REPOSITORY_ALREADY_EXISTS` error, not a raw Postgres constraint error, and does not insert a second row.
- [ ] *(FR16)* Adding a malformed `full_name` (not `owner/repo` shape) is rejected client-side before submission **and** server-side inside the Server Action (never trust client-only validation) with `INVALID_REPOSITORY_FORMAT`.
- [ ] *(FR18)* The sidebar "Repositories" item, currently a non-link `DisabledNavItem`, becomes a live `NavItem` link to `/repositories`.
- [ ] The action is reachable only when authenticated — an unauthenticated POST to the action is denied by the existing S-117 middleware gate (no `route-policy.ts` change needed, since `/repositories` is not a listed `public` path).

#### Business Rules

- No live GitHub API call at add-time — a repository that does not actually exist on GitHub can be added; the resulting invocation against it fails normally at the GitHub-App-auth or clone step, same as any other misconfiguration (PRD §8, an explicit accepted risk, not an oversight).
- RLS stays deny-all (D11) — the write goes through the existing server-only service-role client (`createServerClient()`), never a new credential path.

#### Technical Notes

- Spec §6, §7, §8.4, §12.
- New pure validator `lib/domain/repository-input.ts`: `parseFullName(raw: string)` — `/^[\w.-]+\/[\w.-]+$/` after trim.
- New helpers in the **existing** `lib/supabase/queries.ts` (matching the `insertQueuedRun` precedent, not a new `mutations.ts` file): `insertRepository`, `getRepositories({ includeArchived })`, `getSingleInstallation`.
- New Server Action `app/(panel)/repositories/actions.ts` (`"use server"` `addRepository`), built the same way as `app/login/actions.ts`'s `signIn` — a pure, injectable core function wrapped by a thin action, returning `{ ok: true, repository } | { ok: false, code, message, fieldErrors? }` for `useActionState`.
- `components/repositories/{RepositoryTable,AddRepositoryForm}.tsx` — `AddRepositoryForm` mirrors `LoginForm`'s pending/disabled double-submit guard via `useFormStatus`.
- `/DESIGN.md` needs a new §5.6 before this ships (list + add-form layout) — per the refined PRD's UI-scope recommendation, this should come from a `ux-engineer` pass; if that pass has not landed by the time this story starts, flag it as a blocker rather than improvising the layout.
- `components/shell/Sidebar.tsx`: swap the "Repositories" `DisabledNavItem` for a `NavItem`.

#### Testing Requirements

- **Unit Tests:** `repository-input.test.ts` (valid/invalid `owner/repo` shapes, trimming, case sensitivity, empty string, missing slash, multiple slashes).
- **Integration Tests (Layer 2.5, run live):** `repository-mutations.test.ts` — `insertRepository` success path; duplicate `full_name` rejection round-trip against the real local stack (both the pre-check and the `23505` fallback path); **RLS stays deny-all after the write** (the standing regression pattern every prior auth-adjacent story includes, per spec §14).
- **Manual/UI Testing:** `/repositories` against the local seeded stack — add a valid repo, confirm it appears and is selectable in the Invoke dialog; attempt a duplicate, confirm the friendly error; attempt a malformed name, confirm client-side rejection.
- **Edge-Case Matrix:** a `full_name` with mixed case that differs only by case from an existing row (confirm the exact case-sensitive-match behavior matches the DB constraint, and document the surprising case if the DB constraint is actually case-insensitive at the collation level — verify against the real Postgres default collation before asserting either way); a concurrent double-submit racing two adds of the same `full_name` (the `23505` fallback path, not just the pre-check, must be exercised); an empty repositories table (renders an empty list, not an error).
- **Acceptance-Criteria Mapping:** AC1 → `RepositoryTable.test.tsx`; AC2/AC3/AC4 → `repository-mutations.test.ts` + `AddRepositoryForm.test.tsx`; AC5 → `Sidebar.test.tsx` extension; AC6 → manual verification (unauthenticated POST denied) referencing the existing S-117 gate test suite, no new gate test needed.
- **Execution Commands:** `pnpm --filter panel test:unit`, `pnpm --filter panel test:integration` (requires local stack, `REQUIRE_LOCAL_DB=1`), `pnpm --filter panel test`.

#### Migration Requirements

- Migration artifact: **N/A opt-out** — every column (`full_name`, `default_branch`, `is_enabled`, `archived_at`) already exists in `supabase/migrations/20260902200101_initial_schema.sql`; this story only adds a write path against existing columns.
- Rollback/impact notes: A plain code revert. No migration to reverse. A repository added via this feature can be removed manually (`DELETE FROM repositories WHERE ...`) if ever needed, same as any manually-seeded row today.
- Apply step: N/A (no migration to apply).
- Verification after apply: N/A.

#### Implementation Steps

1. Confirm `/DESIGN.md` §5.6 exists (or explicitly proceed without it and flag the gap in the PR description) before building UI.
2. Write `lib/domain/repository-input.ts` test-first.
3. Add `insertRepository`, `getRepositories`, `getSingleInstallation` to `lib/supabase/queries.ts`, test-first against the local stack (including the RLS-deny-all regression check).
4. Build `app/(panel)/repositories/actions.ts` (`addRepository` Server Action) following the `signIn` pattern.
5. Build `app/(panel)/repositories/page.tsx` + `components/repositories/{RepositoryTable,AddRepositoryForm}.tsx`.
6. Update `components/shell/Sidebar.tsx` to link "Repositories" to `/repositories`.
7. Manual pass: add, attempt duplicate, attempt malformed, confirm Invoke-dialog selector picks up the new repo.

#### Files to Create/Modify

- `panel/lib/domain/repository-input.ts` — new
- `panel/lib/domain/repository-input.test.ts` — new
- `panel/lib/supabase/queries.ts` — add `insertRepository`, `getRepositories`, `getSingleInstallation`
- `panel/tests/integration/repository-mutations.test.ts` — new
- `panel/app/(panel)/repositories/actions.ts` — new
- `panel/app/(panel)/repositories/page.tsx` — new
- `panel/components/repositories/RepositoryTable.tsx` (+ `.module.css`, `.test.tsx`) — new
- `panel/components/repositories/AddRepositoryForm.tsx` (+ `.module.css`, `.test.tsx`) — new
- `panel/components/shell/Sidebar.tsx` — enable "Repositories" link
- `DESIGN.md` — new §5.6 (if not already added by a `ux-engineer` pass)

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines (SD2 boundary preserved — new write uses `createServerClient()`, no new credential path)
- [ ] Unit/integration/manual/edge-case tests written and passing, including the RLS-deny-all regression check
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] Migration lifecycle: N/A opt-out documented
- [ ] Pull Request created and merged

---

## Story S-148: Repositories — archive (soft delete)

**Priority:** Medium
**Estimated Size:** S
**Dependencies:** S-147 (the Repositories screen and its list/query layer must exist first)

#### User Story

As the operator,
I want to archive a repository I no longer use,
So that it stops appearing as an active invocation target without losing its historical run data.

#### Context

Implements FR17 (spec §8.4, §10). A soft delete via the existing `repositories.archived_at` column (already present, no migration) — never a hard `DELETE`, so `runs.repository_id` never dangles and historical runs keep displaying their repository name correctly.

#### Acceptance Criteria

- [ ] An "Archive" action per repository row sets `archived_at = now()`.
- [ ] Archiving is idempotent — archiving an already-archived repository is a no-op `UPDATE`, not an error.
- [ ] An archived repository disappears from the default `/repositories` list view (per S-147's `includeArchived: false` default).
- [ ] An archived repository disappears from the Invoke-dialog repository selector, with **no code change to the invoke path** — the existing `getEnabledRepositories` filter (`is_enabled = true and archived_at is null`) already excludes it.
- [ ] A pre-existing run against an archived repository still displays its `repository_full_name` correctly on both Run History and Run Detail — unaffected by the archive action (verified by the foreign-key-preserving `UPDATE`, not `DELETE`).
- [ ] There is no "restore" affordance in this story (PRD Open Question §18 / spec Open Question #3 — explicitly out of scope for v1; reversal requires a direct DB action, a documented limitation, not a defect).

#### Business Rules

- Archive is an `UPDATE`, never a `DELETE` — this is the one place FR17 must not regress into a hard delete, since it would orphan `runs.repository_id` (a nullable FK with `on delete set null`, which would silently sever the run→repository link on every historical run against that repository — the soft-delete design exists specifically to avoid this).

#### Technical Notes

- Spec §8.4, §12 (idempotent-safe write).
- New helper in `lib/supabase/queries.ts`: `archiveRepository(client, id): Promise<void>` — a plain `UPDATE ... SET archived_at = now() WHERE id = $1`.
- New Server Action `archiveRepository` in `app/(panel)/repositories/actions.ts` (alongside `addRepository`), gated behind a confirmation step in the UI (archiving is the first destructive action in the panel — no other screen has one — so it needs a confirm dialog, unlike `addRepository`).

#### Testing Requirements

- **Unit Tests:** None new beyond what S-147 already covers for the query-layer pattern.
- **Integration Tests (Layer 2.5, run live):** `repository-mutations.test.ts` extension — archive sets `archived_at`; archiving twice is a no-op (second call does not error, timestamp does not regress); a run against an archived repository still resolves `repository_full_name` correctly via `v_runs`.
- **Manual/UI Testing:** Archive a repository via `/repositories`; confirm it disappears from the list and from the Invoke dialog's selector; open an existing run against that repository and confirm its name still displays correctly.
- **Edge-Case Matrix:** archiving a repository that has zero runs against it (still succeeds — no special-casing); archiving a repository mid-invocation-form-selection (an already-open Invoke dialog that loaded the repository list before the archive should not need to handle this live — a page reload picks up the change, no real-time sync required for this story).
- **Acceptance-Criteria Mapping:** AC1/AC2 → `repository-mutations.test.ts::archive`; AC3 → `RepositoryTable.test.tsx` extension (default view excludes archived); AC4 → manual verification against the existing (unmodified) `getEnabledRepositories`/Invoke-dialog test suite; AC5 → `filtered-runs.test.ts` or `run-history` fixture extension (archived-repo run still displays name); AC6 → confirmed by the absence of a restore UI in this story's file list.
- **Execution Commands:** `pnpm --filter panel test:integration` (requires local stack), `pnpm --filter panel test`.

#### Migration Requirements

- Migration artifact: **N/A opt-out** — `archived_at` already exists; this story only writes to it.
- Rollback/impact notes: A plain code revert. An already-archived repository stays archived after a revert (this is a data-layer effect, not a schema change, so reverting the code does not undo any archive actions already taken — document this in the PR description so it is not mistaken for an automatic rollback of data).
- Apply step: N/A.
- Verification after apply: N/A.

#### Implementation Steps

1. Add `archiveRepository` to `lib/supabase/queries.ts`, test-first (integration test including the idempotent-no-op case and the run-still-displays-name case).
2. Add the `archiveRepository` Server Action to `app/(panel)/repositories/actions.ts`.
3. Add an "Archive" button + confirm dialog to `RepositoryTable.tsx`.
4. Manual pass: archive, confirm list/Invoke-selector/existing-run behavior all match the acceptance criteria.

#### Files to Create/Modify

- `panel/lib/supabase/queries.ts` — add `archiveRepository`
- `panel/tests/integration/repository-mutations.test.ts` — extend
- `panel/app/(panel)/repositories/actions.ts` — add `archiveRepository` action
- `panel/components/repositories/RepositoryTable.tsx` — add Archive action + confirm dialog
- `panel/components/repositories/RepositoryTable.test.tsx` — extend

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines (soft delete only, FK-preserving)
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] Migration lifecycle: N/A opt-out documented
- [ ] Pull Request created and merged

---

## Coverage Validation

### Summary

- **Total PRD Requirements:** 18 (FR1–FR18)
- **Total User Stories:** 7 (S-142–S-148)
- **Coverage:** 100%
- **Status:** Complete

### Requirement Mapping

| PRD Requirement | Story ID(s) | Status |
|---|---|---|
| FR1 — status segmented control | S-143 | ✅ Covered |
| FR2 — repository filter chips | S-143 | ✅ Covered |
| FR3 — free-text search | S-143 | ✅ Covered |
| FR4 — URL-encoded, server-paginated filters | S-143 | ✅ Covered |
| FR5 — "X of Y" + Load more pagination | S-143 | ✅ Covered |
| FR6 — empty state + CTA | S-143 | ✅ Covered |
| FR7 — inline branch/PR links | S-144 | ✅ Covered |
| FR8 — connection-state indicator | S-143 | ✅ Covered |
| FR9 — steps panel | S-145 | ✅ Covered |
| FR10 — click-step filters log | S-145 | ✅ Covered |
| FR11 — log-level coloring/filter | S-145 | ✅ Covered |
| FR12 — queued spin vs. running pulse | S-142 | ✅ Covered |
| FR13 — All runs cross-agent feed | S-146 | ✅ Covered |
| FR14 — sidebar "All runs" enabled | S-146 | ✅ Covered |
| FR15 — Repositories list | S-147 | ✅ Covered |
| FR16 — add repository (manual reference) | S-147 | ✅ Covered |
| FR17 — archive repository (soft delete) | S-148 | ✅ Covered |
| FR18 — sidebar "Repositories" enabled | S-147 | ✅ Covered |

### Non-Goals Validation

- [x] Command palette / ledger keyboard shortcuts (C21–C22) — confirmed NOT in any story.
- [x] Settings (C19) — confirmed NOT in any story.
- [x] System health (C20) — confirmed NOT in any story.
- [x] GitHub App repository sync/verification — confirmed NOT in any story (S-147's `insertRepository` explicitly makes no GitHub API call).
- [x] Repository edit/rename, per-agent repository enablement (`agent_repository_settings`) — confirmed NOT in any story.
- [x] Restoring an archived repository from the UI — confirmed explicitly excluded from S-148's acceptance criteria.
- [x] Responsive/mobile layout below 1024px — confirmed NOT in any story.
- [x] Already-shipped items (C10, C12, C13, C14, C15, C24 — terminal-state banners, live-tail pause/resume, log windowing, reconnect backfill, artifact links, Phosphor icons) — confirmed NOT re-implemented by any story; S-144/S-145 explicitly reuse the existing `isSafeArtifactUrl` and windowing/SSE mechanisms rather than rebuilding them.
