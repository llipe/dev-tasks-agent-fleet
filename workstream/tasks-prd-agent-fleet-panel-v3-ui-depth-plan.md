# Implementation Plan - Agent Fleet Control Panel v3: UI Depth

Source: [`user-stories-prd-agent-fleet-panel-v3-ui-depth.md`](user-stories-prd-agent-fleet-panel-v3-ui-depth.md) v1.0, published as GitHub issues #202-#208 (see [`github-publication-prd-agent-fleet-panel-v3-ui-depth.md`](github-publication-prd-agent-fleet-panel-v3-ui-depth.md)). Scope: all 7 stories (S-142-S-148), full PRD.

## Relevant Files

- `panel/components/status-meta.ts` - `StatusMeta` gains `spin`; `queued` flips to `spin:true, pulse:false` (S-142)
- `panel/components/StatusDot.tsx` - consume `meta.spin` (S-142)
- `panel/components/StatusDot.module.css` - add `.spin` rule (S-142)
- `panel/tests/unit/status-meta.test.ts` - extend (S-142)
- `panel/tests/component/StatusDot.test.tsx` - extend (S-142)
- `panel/lib/domain/run-filter.ts` - new: URL <-> RunFilter parse/serialize (S-143)
- `panel/lib/domain/run-filter.test.ts` - new (S-143)
- `panel/lib/supabase/queries.ts` - add `getFilteredRuns` (S-143), `getPullRequestArtifactsForRuns` (S-144), `insertRepository`/`getRepositories`/`getSingleInstallation` (S-147), `archiveRepository` (S-148)
- `panel/tests/integration/filtered-runs.test.ts` - new (S-143); extend for cross-agent case (S-146)
- `panel/components/runs/RunFilterBar.tsx` (+ `.module.css`, `.test.tsx`) - new: segmented control, chips, search, connection indicator (S-143)
- `panel/app/(panel)/agents/[slug]/page.tsx` - wire `searchParams` -> `parseRunFilter` -> `getFilteredRuns` (S-143); wire PR-link read (S-144)
- `panel/components/runs/RunHistoryTable.tsx` - add empty-state rendering (S-143); add `showAgentColumn` prop (S-146)
- `panel/tests/integration/pull-request-artifacts.test.ts` - new (S-144)
- `panel/components/runs/RunHistoryRow.tsx` - add PR-link cell (S-144); add agent column rendering (S-146)
- `panel/tests/component/RunHistoryRow.test.tsx` - new (S-144); actual path deviates from the plan's `panel/components/runs/RunHistoryRow.test.tsx` — this codebase's real convention (per `vitest.config.ts`) is colocated-by-layer under `tests/component/`, not colocated-by-component; extend for S-146
- `panel/lib/domain/log-filter.ts` - new: step+level (severity-threshold) filter reducer over the loaded log window (S-145)
- `panel/tests/unit/log-filter.test.ts` - new; actual path deviates from the plan's colocated `panel/lib/domain/log-filter.test.ts` — this codebase's real convention (per `vitest.config.ts`) is `tests/unit/`, matching every other Layer 1 module, not colocation (same drift class as row 21's S-144 note) (S-145)
- `panel/lib/domain/run-detail.ts` - extend with `buildStepsPanel`/`RunStepInput`/`StepPanelRow`, plus an optional `stepId` on `LogLineView` (S-145)
- `panel/tests/unit/run-detail.test.ts` - extend (S-145)
- `panel/components/run-detail/StepsPanel.tsx` (+ `.module.css`) - new (S-145)
- `panel/tests/component/StepsPanel.test.tsx` - new (S-145)
- `panel/components/run-detail/RunDetailLogSection.tsx` (+ `.module.css`) - new: the `"use client"` filter-state wrapper owning `{ stepId, level }`, not itemized in the story's own file list but required by its own Technical Notes prose ("a small filter-state wrapper... a `use client` parent owning state") (S-145)
- `panel/tests/component/RunDetailLogSection.test.tsx` - new (S-145)
- `panel/components/run-detail/LogViewer.tsx` - add optional `filter` prop consumption, backward-compatible default (S-145)
- `panel/components/run-detail/LiveLogViewer.tsx` - add optional `filter` prop consumption; autoscroll effect re-pointed to the filtered lines (S-145)
- `panel/lib/hooks/useRunStream.ts` - carry `step_id` through onto live-appended `LogLineView`s so the step filter composes with the SSE tail (S-145, not itemized in the story's own file list but required for AC4)
- `panel/tests/component/use-run-stream.test.tsx` - extend (S-145)
- `panel/tests/component/live-log-viewer.test.tsx` - extend (S-145)
- `panel/tests/component/run-detail.test.tsx` - extend (S-145)
- `panel/tests/component/run-detail-page-wiring.test.tsx` - extend (S-145)
- `panel/app/(panel)/runs/[id]/page.tsx` - wire the filter-state wrapper + per-step event counts from the already-loaded window (S-145)
- `DESIGN.md` - §4.2 layout diagram now names the Steps panel + Log toolbar level-filter control explicitly, closing an ambiguity between the diagram and the pre-existing §5.3 prose (S-145)
- `docs/technical-guidelines.md` - changelog row 1.38 (S-145)
- `panel/lib/domain/run-row.ts` - add optional `agentName`/`agentSlug` to `RunRowInput`/`RunRow` (S-146)
- `panel/tests/unit/run-row.test.ts` - extend: agent-identity passthrough + omitted-field default (S-146)
- `panel/app/(panel)/runs/page.tsx` (+ `.module.css`) - new: All Runs screen (S-146)
- `panel/tests/component/runs-page-wiring.test.tsx` - new: `/runs` page wiring, `agentSlug: null`, Agent-column attribution, `/runs`-scoped "Load more" href (S-146)
- `panel/components/shell/Sidebar.tsx` - enable "All runs" link (S-146); enable "Repositories" link (S-147)
- `panel/tests/component/Sidebar.test.tsx` - new; actual path deviates from the plan's colocated `panel/components/shell/Sidebar.test.tsx` — this codebase's real convention (per `vitest.config.ts`) is `tests/component/`, matching every other Layer 2 test (same drift class as row 21/23's notes) (S-146; extend for S-147)
- `panel/tests/component/AppShell.test.tsx` - extend: "All runs" moves from the four-disabled-destinations assertion to a live-link assertion (S-146)
- `panel/lib/domain/repository-input.ts` - new: `parseFullName` validator (S-147)
- `panel/lib/domain/repository-input.test.ts` - new (S-147)
- `panel/tests/integration/repository-mutations.test.ts` - new (S-147); extend for archive (S-148)
- `panel/app/(panel)/repositories/actions.ts` - new: `addRepository` Server Action (S-147); add `archiveRepository` action (S-148)
- `panel/app/(panel)/repositories/page.tsx` - new (S-147)
- `panel/components/repositories/RepositoryTable.tsx` (+ `.module.css`, `.test.tsx`) - new (S-147); add Archive action + confirm dialog (S-148)
- `panel/components/repositories/AddRepositoryForm.tsx` (+ `.module.css`, `.test.tsx`) - new (S-147)
- `DESIGN.md` - new §5.6 Repositories (S-147, blocker-or-flag if no `ux-engineer` pass has landed first)

## Tasks

- [x] 1.0 Implement Story S-142: Fix the queued-status animation defect (#202)

  > Queued's status dot must spin (0.9s), distinct from running's pulse (1.6s), per `/DESIGN.md` §6.1/§8.1. Smallest, most contained story in this set - de-risks first.

  - [x] 1.1 Add `spin: boolean` to the `StatusMeta` interface in `panel/components/status-meta.ts`
  - [x] 1.2 Set `queued: { pulse: false, spin: true, ... }`; set `spin: false` on every other entry incl. the unknown-status fallback
  - [x] 1.3 Update `StatusDot.tsx`'s class list to include `meta.spin && styles.spin`
  - [x] 1.4 Add `.spin { animation: spin 0.9s linear infinite; }` to `StatusDot.module.css` (reuses the existing `@keyframes spin` in `styles/globals.css` - do not redefine it)
  - [x] 1.5 Migration: N/A opt-out - presentational CSS/TS only, no schema/data change
  - [x] 1.6 Verify Acceptance Criterion: a `queued` `StatusDot` renders `.spin` with `spin 0.9s linear infinite`
  - [x] 1.7 Verify Acceptance Criterion: a `running` `StatusDot` still renders `.pulse` (`pulse 1.6s ease-in-out infinite`), unchanged
  - [x] 1.8 Verify Acceptance Criterion: no other status's rendering changes
  - [x] 1.9 Verify Acceptance Criterion: `StatusPill` shows no visual regression for `queued`
  - [x] 1.10 Run Tests: extend `panel/tests/unit/status-meta.test.ts` (queued -> `{pulse:false, spin:true}`, every other status -> `spin:false`)
  - [x] 1.11 Run Tests: extend `panel/tests/component/StatusDot.test.tsx` (class-list assertion, queued vs running mutually exclusive)
  - [x] 1.12 Manual/UI: dev server requires `NEXT_PUBLIC_SUPABASE_URL`/auth env not present in this sandbox, so `panel/app/dev/gallery` could not be rendered live; verified equivalently via `StatusDot.test.tsx` class-list assertions (queued=.spin only, running=.pulse only) — flagged as a known limitation for a human to confirm visually
  - [x] 1.13 Run Tests: `pnpm --filter panel test:unit` and `pnpm --filter panel test`
  - [x] 1.14 Acceptance-criteria-to-test mapping: AC1/AC2 -> `StatusDot.test.tsx`; AC3 -> `token-discipline.test.ts` (no new literal); AC4 -> `StatusPill.test.tsx`

- [x] 2.0 Implement Story S-143: Run History - filter, search, and pagination (#203)

  > Foundational story for the run-list depth half of the PRD. Introduces `lib/domain/run-filter.ts` and `getFilteredRuns`, which S-146 reuses directly. Filters/pagination are URL-encoded and server-side (FR1-FR6, FR8).

  - [x] 2.1 Write `panel/lib/domain/run-filter.ts` (`parseRunFilter`/`serializeRunFilter`) test-first
  - [x] 2.2 Add `getFilteredRuns(client, filter, pageSize)` to `panel/lib/supabase/queries.ts` (`.select("*", {count:"exact"})` + conditional `.eq`/`.ilike` + `.range(0, filter.page*pageSize-1)`)
  - [x] 2.3 Build `panel/components/runs/RunFilterBar.tsx` (`"use client"`: segmented control + repo chips + search (300ms debounce) + connection indicator; mutates URL via `router.replace`)
  - [x] 2.4 Wire `panel/app/(panel)/agents/[slug]/page.tsx` to read `searchParams` -> `parseRunFilter` -> `getFilteredRuns`, replacing the direct `getAllRunsByAgentSlug` call for this screen; keep route-segment config declared inline
  - [x] 2.5 Grep for other callers of `getAllRunsByAgentSlug` before assuming it can be left as dead code; do not remove it if still referenced elsewhere
  - [x] 2.6 Add empty-state rendering + "Clear filters" CTA to `RunHistoryTable.tsx`
  - [x] 2.7 Migration: N/A opt-out - reads only, every column already exists
  - [x] 2.8 Verify Acceptance Criterion: status filter narrows to that `effective_status`, including a stale `running` row past threshold counting/filtering as `timed_out` (reaper paused fixture)
  - [x] 2.9 Verify Acceptance Criterion: repo chip narrows correctly; combined with status filter, the result is the intersection
  - [x] 2.10 Verify Acceptance Criterion: free-text search matches repo name/branch/run id; composes with other filters
  - [x] 2.11 Verify Acceptance Criterion: reloading a URL with `?status=failed&repo=<id>&q=foo` reproduces the identical filtered result from a fresh server-side query
  - [x] 2.12 Verify Acceptance Criterion: pagination renders "X of Y" + "Load more"; "Load more" under an active filter fetches the next cumulative page of the filtered set
  - [x] 2.13 Verify Acceptance Criterion: zero-match filter shows the empty state + working "Clear filters" CTA
  - [x] 2.14 Verify Acceptance Criterion: connection-state indicator present, reflecting last-fetch success (presentational only, no new Realtime subscription per spec §17 OQ1)
  - [x] 2.15 Run Tests: `panel/lib/domain/run-filter.test.ts` (round-trip, unknown-value fallback, default omission, never throws)
  - [x] 2.16 Run Tests: `panel/tests/integration/filtered-runs.test.ts` (Docker-gated, run live - status/repo/search combinations, stale-`running` fixture, paging beyond `max_rows`, `totalCount` accuracy)
  - [x] 2.17 Run Tests: edge cases - zero-match empty state; search string with regex metacharacters must not throw (literal substring only); repo chip with zero runs for this agent
  - [x] 2.18 Manual/UI: `/agents/dependency-update` against the seeded local stack - apply each filter individually and combined; confirm URL updates and reload reproduces the same view
  - [x] 2.19 Run Tests: `pnpm --filter panel test:unit`, `pnpm --filter panel test:integration` (`REQUIRE_LOCAL_DB=1`), `pnpm --filter panel test`
  - [x] 2.20 Acceptance-criteria-to-test mapping: AC1->`filtered-runs.test.ts::status filter`; AC2->`::repo filter`; AC3->`::search`; AC4->`run-filter.test.ts::round-trip` + `::url-reload parity`; AC5->`::pagination`; AC6->`RunFilterBar.test.tsx::empty state`; AC8->`RunFilterBar.test.tsx::connection indicator`

- [x] 3.0 Implement Story S-144: Run History - inline branch and PR links (#204) [depends: S-143]

  > Branch display already exists (`run-row.ts` reads `runs.params.branch`). Only the PR-link half is new - a grouped `run_artifacts` read mirroring the existing `getStepProgressForRuns` shape.

  - [x] 3.1 Add `getPullRequestArtifactsForRuns(client, runIds)` to `panel/lib/supabase/queries.ts`, test-first (integration test against the local stack)
  - [x] 3.2 Extend `RunHistoryRow.tsx`'s repository cell to render the PR link when present, guarded by the existing `isSafeArtifactUrl` (`lib/domain/artifact-url.ts`, S-109) - do not reimplement URL-safety
  - [x] 3.3 Wire the new query into `panel/app/(panel)/agents/[slug]/page.tsx` alongside the existing `getStepProgressForRuns` call
  - [x] 3.4 Migration: N/A opt-out - reads only, `run_artifacts.type`/`url` already exist
  - [x] 3.5 Verify Acceptance Criterion: a run with a `pull_request` artifact shows a clickable inline PR link
  - [x] 3.6 Verify Acceptance Criterion: a run with no `pull_request` artifact shows unchanged branch-only rendering
  - [x] 3.7 Verify Acceptance Criterion: the PR-link lookup is a single grouped query per page of rows, never N+1
  - [x] 3.8 Verify Acceptance Criterion: the link is https-only via the reused `isSafeArtifactUrl` guard
  - [x] 3.9 Run Tests: integration test extension - grouped-read shape (never N+1, empty-list -> `{}`, non-`pull_request` artifact type excluded)
  - [x] 3.10 Run Tests: edge cases - a `pull_request` artifact carrying an unsafe URL (`javascript:`/relative) renders inert; empty page -> zero-cost lookup
  - [x] 3.11 Manual/UI: a run history page with a mix of runs with/without `pull_request` artifacts - confirm the link renders only where expected
  - [x] 3.12 Run Tests: `pnpm --filter panel test:unit`, `pnpm --filter panel test:integration`, `pnpm --filter panel test`
  - [x] 3.13 Acceptance-criteria-to-test mapping: AC1/AC2 -> `RunHistoryRow.test.tsx`; AC3 -> integration grouped-read assertion; AC4 -> reuses `artifact-url.test.ts` (S-109), referenced in the PR description

- [x] 4.0 Implement Story S-145: Run Detail - steps panel with step and log-level filtering (#205)

  > Steps panel + step-click filter + log-level filter share one new `log-filter.ts` reducer, operating client-side over the already-loaded log window (no new server read; event counts derived from the same window, zero marginal DB reads).

  - [x] 4.1 Write `panel/lib/domain/log-filter.ts` (`applyLogFilter`) test-first
  - [x] 4.2 Extend `panel/lib/domain/run-detail.ts` with `buildStepsPanel(steps, eventCountByStep)`, test-first
  - [x] 4.3 Build `panel/components/run-detail/StepsPanel.tsx` (colored status dot from `run_steps.status`, mono name, duration, event count; click sets filter, "All steps" clears it)
  - [x] 4.4 Add a `"use client"` filter-state wrapper around `LogViewer.tsx`/`LiveLogViewer.tsx` owning `{ stepId, level }`, wired to both the steps panel and a new level-filter control
  - [x] 4.5 Confirm live-run autoscroll/pause-resume (S-110) still works correctly with a filter active
  - [x] 4.6 Migration: N/A opt-out - reads only, `run_steps`/`run_events` already fully read for this screen
  - [x] 4.7 Verify Acceptance Criterion: steps panel renders each `run_steps` row (dot, name, duration, event count)
  - [x] 4.8 Verify Acceptance Criterion: clicking a step filters the log to that step's events; "All steps" clears it
  - [x] 4.9 Verify Acceptance Criterion: level filter narrows independently and composes with the step filter
  - [x] 4.10 Verify Acceptance Criterion: steps panel + both filters work identically on terminal (`LogViewer`) and live (`LiveLogViewer`) runs
  - [x] 4.11 Verify Acceptance Criterion: a live run's step event counts may under-count until the SSE tail catches up (documented, non-blocking - no test asserts an under-count as correct)
  - [x] 4.12 Run Tests: `panel/lib/domain/log-filter.test.ts` (step-only, level-only, both combined, neither, "All steps" reset, unknown `stepId` -> empty not a crash)
  - [x] 4.13 Run Tests: `run-detail.test.ts` extension for `buildStepsPanel` (duration formatting reuse, zero-event step, in-progress step with no `finished_at`)
  - [x] 4.14 Run Tests: edge cases - zero-step run (empty panel, not an error); zero-event step; live run mid-tail with a step filter applied (filtered-out step's new events don't appear; filtered-in step's new events still autoscroll)
  - [x] 4.15 Manual/UI: a run with a failed step - click it, confirm log narrows; click "All steps", confirm restore; apply a level filter on top; repeat on a live run
  - [x] 4.16 Run Tests: `pnpm --filter panel test:unit`, `pnpm --filter panel test`
  - [x] 4.17 Acceptance-criteria-to-test mapping: AC1->`StepsPanel.test.tsx`; AC2/AC3->`log-filter.test.ts` + `StepsPanel.test.tsx`; AC4->`LiveLogViewer.test.tsx` extension; AC5->documented in PR description

- [x] 5.0 Implement Story S-146: All Runs - cross-agent run feed (#206) [depends: S-143]

  > Reverses the v2.1 non-goal per explicit user decision. Almost entirely composition: reuses S-143's `RunFilterBar`/`getFilteredRuns` minus agent scoping, plus a new Agent column.

  - [x] 5.1 Add `showAgentColumn` prop (default `false`) to `RunHistoryTable`/`RunHistoryRow`, test-first
  - [x] 5.2 Build `panel/app/(panel)/runs/page.tsx`, reusing `RunFilterBar` + `getFilteredRuns` with `agentSlug: null`
  - [x] 5.3 Update `panel/components/shell/Sidebar.tsx`: swap the "All runs" `DisabledNavItem` for a `NavItem` linking to `/runs`
  - [x] 5.4 Migration: N/A opt-out - reads only, reuses S-143's read path with a different filter value
  - [x] 5.5 Verify Acceptance Criterion: `/runs` shows runs from >=2 agents (fixture), newest-first, correctly attributed via the Agent column
  - [x] 5.6 Verify Acceptance Criterion: all of S-143's filter/pagination/empty-state/connection-indicator behavior works identically on `/runs`
  - [x] 5.7 Verify Acceptance Criterion: sidebar "All runs" is a live link to `/runs`
  - [x] 5.8 Verify Acceptance Criterion: `/agents/[slug]` is unaffected by this story
  - [x] 5.9 Run Tests: `filtered-runs.test.ts` extension - `agentSlug: null` returns rows across >=2 agents, newest-first, count accurate
  - [x] 5.10 Run Tests: edge cases - single-enabled-agent fleet (still renders correctly); a disabled agent's historical runs still appear in `/runs` (not agent-scoped, unlike `/agents/[slug]`'s disabled-agent-404 rule)
  - [x] 5.11 Manual/UI: seed two enabled agents locally, visit `/runs`, confirm both appear, filters work, sidebar link navigates correctly
  - [x] 5.12 Run Tests: `pnpm --filter panel test:unit`, `pnpm --filter panel test:integration`, `pnpm --filter panel test`; confirm the existing `/agents/[slug]` suite stays green unmodified
  - [x] 5.13 Acceptance-criteria-to-test mapping: AC1/AC2 -> `RunHistoryTable.test.tsx` (`showAgentColumn`) + `filtered-runs.test.ts` cross-agent case; AC3 -> `Sidebar.test.tsx`; AC4 -> existing `/agents/[slug]` suite green

- [ ] 6.0 Implement Story S-147: Repositories - list and add-by-reference (#207)

  > Reverses the v2.1 non-goal, redefined as manual reference (not GitHub App sync). The panel's second user-triggered write and first Server-Action-shaped write.

  - [ ] 6.1 Confirm `/DESIGN.md` §5.6 exists before building UI; if a `ux-engineer` pass has not landed, explicitly flag the gap in the PR description rather than improvising layout
  - [ ] 6.2 Write `panel/lib/domain/repository-input.ts` (`parseFullName`) test-first
  - [ ] 6.3 Add `insertRepository`, `getRepositories({includeArchived})`, `getSingleInstallation` to `panel/lib/supabase/queries.ts`, test-first against the local stack, including an RLS-deny-all-unchanged regression check
  - [ ] 6.4 Build `panel/app/(panel)/repositories/actions.ts` (`"use server"` `addRepository`, following the `signIn`/`resolveSignIn` pure-core-plus-thin-action pattern)
  - [ ] 6.5 Build `panel/app/(panel)/repositories/page.tsx` + `panel/components/repositories/{RepositoryTable,AddRepositoryForm}.tsx`
  - [ ] 6.6 Update `panel/components/shell/Sidebar.tsx`: swap the "Repositories" `DisabledNavItem` for a `NavItem` linking to `/repositories`
  - [ ] 6.7 Migration: N/A opt-out - every column (`full_name`, `default_branch`, `is_enabled`, `archived_at`) already exists in `supabase/migrations/20260902200101_initial_schema.sql`; this story only adds a write path against existing columns
  - [ ] 6.8 Verify Acceptance Criterion: `/repositories` lists non-archived rows by default (`full_name`, `default_branch`, enabled state)
  - [ ] 6.9 Verify Acceptance Criterion: "Add repository" inserts a new row without calling the GitHub API
  - [ ] 6.10 Verify Acceptance Criterion: a duplicate `full_name` under the installation shows a friendly `REPOSITORY_ALREADY_EXISTS` error, not a raw Postgres error, and does not insert a second row
  - [ ] 6.11 Verify Acceptance Criterion: a malformed `full_name` is rejected client-side before submission AND server-side inside the Server Action
  - [ ] 6.12 Verify Acceptance Criterion: sidebar "Repositories" is a live link to `/repositories`
  - [ ] 6.13 Verify Acceptance Criterion: the action is reachable only when authenticated (denied by the existing S-117 gate for an unauthenticated POST)
  - [ ] 6.14 Run Tests: `panel/lib/domain/repository-input.test.ts` (valid/invalid `owner/repo` shapes, trimming, case sensitivity, empty string, missing/multiple slashes)
  - [ ] 6.15 Run Tests: `panel/tests/integration/repository-mutations.test.ts` (Docker-gated, run live - success path, duplicate rejection via both the pre-check and the `23505` fallback, RLS-deny-all preserved after the write)
  - [ ] 6.16 Run Tests: edge cases - mixed-case `full_name` differing only by case from an existing row (verify against real Postgres collation before asserting either way); concurrent double-submit racing two adds of the same `full_name` (exercise the `23505` fallback path, not just the pre-check); empty repositories table renders empty list, not an error
  - [ ] 6.17 Manual/UI: add a valid repo, confirm it appears and is selectable in the Invoke dialog; attempt a duplicate; attempt a malformed name
  - [ ] 6.18 Run Tests: `pnpm --filter panel test:unit`, `pnpm --filter panel test:integration` (`REQUIRE_LOCAL_DB=1`), `pnpm --filter panel test`
  - [ ] 6.19 Acceptance-criteria-to-test mapping: AC1->`RepositoryTable.test.tsx`; AC2/AC3/AC4->`repository-mutations.test.ts` + `AddRepositoryForm.test.tsx`; AC5->`Sidebar.test.tsx`; AC6->manual verification against the existing S-117 gate suite (no new gate test needed)

- [ ] 7.0 Implement Story S-148: Repositories - archive (soft delete) (#208) [depends: S-147]

  > A soft delete via the existing `repositories.archived_at` column - never a hard DELETE, so `runs.repository_id` never dangles and historical runs keep displaying their repository name.

  - [ ] 7.1 Add `archiveRepository(client, id)` to `panel/lib/supabase/queries.ts` (`UPDATE ... SET archived_at = now()`), test-first including the idempotent-no-op case and the run-still-displays-name case
  - [ ] 7.2 Add the `archiveRepository` Server Action to `panel/app/(panel)/repositories/actions.ts`
  - [ ] 7.3 Add an "Archive" button + confirm dialog to `RepositoryTable.tsx` (the panel's first destructive-action confirm dialog)
  - [ ] 7.4 Migration: N/A opt-out - `archived_at` already exists; this story only writes to it
  - [ ] 7.5 Verify Acceptance Criterion: "Archive" sets `archived_at = now()`
  - [ ] 7.6 Verify Acceptance Criterion: archiving is idempotent - archiving an already-archived repo is a no-op `UPDATE`, not an error
  - [ ] 7.7 Verify Acceptance Criterion: an archived repository disappears from the default `/repositories` list view
  - [ ] 7.8 Verify Acceptance Criterion: an archived repository disappears from the Invoke-dialog selector with no code change to the invoke path (the existing `getEnabledRepositories` filter already excludes it)
  - [ ] 7.9 Verify Acceptance Criterion: a pre-existing run against an archived repository still displays its `repository_full_name` correctly on Run History and Run Detail
  - [ ] 7.10 Verify Acceptance Criterion: no "restore" affordance exists in this story (explicitly out of scope for v1)
  - [ ] 7.11 Run Tests: `repository-mutations.test.ts` extension (archive sets `archived_at`; archiving twice is a no-op, timestamp does not regress; a run against an archived repository still resolves `repository_full_name` via `v_runs`)
  - [ ] 7.12 Run Tests: edge cases - archiving a repository with zero runs against it; archiving mid-invocation-form-selection (no real-time sync required - a page reload picks up the change)
  - [ ] 7.13 Manual/UI: archive a repository via `/repositories`; confirm it disappears from the list and the Invoke dialog's selector; open an existing run against it and confirm its name still displays
  - [ ] 7.14 Run Tests: `pnpm --filter panel test:integration` (`REQUIRE_LOCAL_DB=1`), `pnpm --filter panel test`
  - [ ] 7.15 Acceptance-criteria-to-test mapping: AC1/AC2->`repository-mutations.test.ts::archive`; AC3->`RepositoryTable.test.tsx` (default view excludes archived); AC4->manual verification against the existing Invoke-dialog suite; AC5->`filtered-runs.test.ts`/run-history fixture extension; AC6->confirmed by the absence of a restore UI in this story's file list
