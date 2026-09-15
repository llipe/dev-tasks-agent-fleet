# Test Plan — Agent Fleet Control Panel v3: UI Depth

**Mode:** Design Mode (pre-implementation)
**Scope:** PRD `prd-agent-fleet-panel-v3-ui-depth.md` v1.0, FR1–FR18, 7 stories (S-142–S-148), GitHub issues #202–#208.
**Prepared by:** verifier
**Date:** 2026-09-15

## Changelog

| Version | Date       | Summary                                                                 | Author   |
| ------- | ---------- | ------------------------------------------------------------------------ | -------- |
| 1.0     | 2026-09-15 | Initial compliance test plan, derived from PRD v1.0 (FR1–FR18, §13 AC1–AC12), spec v1.0 (resolved Open Questions §17), and the 7 stories' own numbered ACs/Testing Requirements sections. | verifier |

---

## 1. Source Input Summary

- **PRD** (`docs/requirements/prd-agent-fleet-panel-v3-ui-depth.md` v1.0): 18 functional requirements across 4 capability groups (Run History depth FR1–FR8, Run Detail depth FR9–FR12, All Runs FR13–FR14, Repositories FR15–FR18), 12 acceptance criteria (§13), non-goals (§10).
- **Spec** (`workstream/specification-prd-agent-fleet-panel-v3-ui-depth.md` v1.0): resolves PRD Open Question #1 — FR8's connection indicator is **presentational only**, no new Realtime subscription. Resolves pagination to **cumulative offset paging** (not keyset). Resolves FR9 event counts to be derived from the **already-loaded event window** (no new query). Adds the concrete module/query/action shapes this plan cites by name.
- **Stories** (`workstream/user-stories-prd-agent-fleet-panel-v3-ui-depth.md` v1.0): S-142–S-148, each with its own numbered ACs and a Testing Requirements section already proposing concrete test files. This plan validates and extends those, and is cross-referenced against the story-level AC numbering (distinct from PRD §13's AC numbering — see the traceability matrix's "Story AC" column).
- **Tasks** (`workstream/tasks-prd-agent-fleet-panel-v3-ui-depth-plan.md`): execution checklist, 7 top-level tasks (1.0–7.0) mapped 1:1 to S-142–S-148 and issues #202–#208.
- **Existing test taxonomy** (`docs/technical-guidelines.md` §11): Layer 1 (unit, Vitest, no I/O), Layer 2 (component, jsdom), Layer 2.5 (integration, Docker-gated against a real local Supabase stack, `REQUIRE_LOCAL_DB=1` — a skip is a hard CI failure, not a vacuous pass), E2E (Playwright, `panel/tests/e2e/`, one worker, `next dev` webServer). This plan slots entirely into that taxonomy — no new layer is introduced.

## 2. Acceptance Criteria Extraction

Numbered against PRD §13 (`AC-1`…`AC-12`), cross-referenced to the corresponding story-level AC (which uses its own per-story numbering, e.g. S-143's own "AC1–AC7"). See traceability matrix §4 for the full FR→AC→Test mapping table; this section lists the AC statements themselves.

| PRD AC | Statement | FR(s) |
|---|---|---|
| AC-1 | Filtering to `failed` shows only `effective_status=failed` runs, count matches filtered set; a stale `running` row past timeout counts as `timed_out`, not `running`. | FR1 |
| AC-2 | Combining a repo chip with free-text search narrows to the intersection, not the union. | FR2, FR3 |
| AC-3 | Reloading a URL with `?status=failed&repo=org/repo` reproduces the same filtered, server-queried result — not a client re-filter. | FR4 |
| AC-4 | "Load more" on a filtered result fetches the next page under the current filter. | FR5 |
| AC-5 | Zero-match filter renders empty state with a working "Clear filters" CTA. | FR6 |
| AC-6 | A run with a `pull_request` artifact shows a clickable PR link inline without opening the row. | FR7 |
| AC-7 | Clicking a `failed` step filters the log viewer to that step's events; "All steps" restores the full tail. | FR9, FR10 |
| AC-8 | Filtering to `error`-level lines while a step filter is active shows only lines matching both. | FR11 |
| AC-9 | `queued` dot visibly `spin`s, distinct from `running`'s `pulse`, in the same screen. | FR12 |
| AC-10 | `/runs` shows runs from ≥2 agents newest-first, each correctly attributed. | FR13 |
| AC-11 | Adding a duplicate `full_name` (case-sensitive exact match) shows a friendly error, not a raw constraint error; no second row inserted. | FR15, FR16 |
| AC-12 | Archiving removes a repo from the default list and Invoke selector; a pre-existing run against it still displays its name correctly. | FR17 |

**Non-goal boundary (must NOT regress into scope):** command palette (C21–C22), Settings (C19), System health (C20), GitHub App sync/verification, repository edit/rename or per-agent enablement, archive restore UI, responsive <1024px (declined permanently), auth changes. These are asserted as **negative/absence checks** in §5.6 below, not merely omitted.

## 3. E2E Scenarios (Playwright, `panel/tests/e2e/`)

Following the existing scenario→AC traceability convention (`docs/technical-guidelines.md` §11, e.g. S-114's table). Proposed additions to the existing suite (new spec files, or extensions of existing ones where a screen is already covered):

| ID | Scenario | New/Extend spec file | AC(s) |
|---|---|---|---|
| E2E-1 | Filter Run History by status, then repo, then free text, individually and combined; confirm URL reflects each; reload reproduces identical filtered view. | `panel/tests/e2e/run-history-filters.spec.ts` (new) | AC-1, AC-2, AC-3 |
| E2E-2 | Paginate a filtered Run History result via "Load more"; confirm "X of Y" updates and the next page is scoped to the active filter. | same | AC-4 |
| E2E-3 | Apply a filter combination matching zero runs; confirm empty state + "Clear filters" CTA returns to the unfiltered view. | same | AC-5 |
| E2E-4 | A run history row with a `pull_request` artifact shows a working inline PR link; a row without one shows branch-only. | `panel/tests/e2e/run-history-filters.spec.ts` or extend `stale-and-artifact.spec.ts` | AC-6 |
| E2E-5 | On Run Detail for a failed run, click the failed step; confirm the log viewer narrows to that step's events; click "All steps"; confirm full tail restores. | `panel/tests/e2e/run-detail-steps.spec.ts` (new) | AC-7 |
| E2E-6 | Apply a log-level filter (e.g. "errors only") on top of an active step filter; confirm only lines matching both render. | same | AC-8 |
| E2E-7 | On a screen showing both a `queued` and a `running` run (e.g. dashboard or run history with a seeded queued fixture), visually assert distinct animation classes (`.spin` vs `.pulse`) are present — Playwright can assert the CSS class/computed `animation-name`, not the visual motion itself. | `panel/tests/e2e/edge-cases.spec.ts` (extend) or `panel/app/dev/gallery`-adjacent manual check (see §5.7 — flagged gap) | AC-9 |
| E2E-8 | Visit `/runs`; confirm rows from ≥2 seeded agents appear, newest-first, each attributed via the Agent column; confirm the sidebar "All runs" link navigates there. | `panel/tests/e2e/all-runs.spec.ts` (new) | AC-10 |
| E2E-9 | Add a repository end-to-end via `/repositories`; confirm it appears in the list and becomes selectable in the Invoke dialog. Attempt a duplicate `full_name`; confirm the friendly error and no second row. Attempt a malformed name; confirm client-side rejection before submission. | `panel/tests/e2e/repositories.spec.ts` (new) | AC-11 |
| E2E-10 | Archive a repository; confirm it disappears from the default `/repositories` list and the Invoke-dialog selector, while an existing run against it still shows its name on Run History and Run Detail; confirm no restore affordance exists anywhere in `/repositories`. | same | AC-12 |
| E2E-11 | Sidebar "All runs" and "Repositories" items are live links (not `aria-disabled` `DisabledNavItem`s) post-implementation; every other still-parked sidebar item (Settings, System health) remains disabled. | `panel/tests/e2e/edge-cases.spec.ts` (extend) | FR14, FR18, non-goals boundary |

**Note on E2E-7:** Playwright cannot assert perceived animation motion; it can assert `getComputedStyle(dot).animationName === "spin"` vs `"pulse"`. Recommend keeping the primary compliance evidence for AC-9 at Layer 1/2 (`status-meta.test.ts`, `StatusDot.test.tsx`) per S-142's own testing plan, with the E2E class-name assertion as a light confirmatory check only — flagged so no one over-invests in a brittle E2E visual test for what is fundamentally a Layer 1/2 concern.

## 4. Contract Validation Scenarios

This feature has no external/consumer-facing API surface (spec §6: "internal, non-consumer-facing action, same posture as every existing panel endpoint"). The applicable "contracts" here are **internal type/shape contracts** between layers — still worth validating explicitly because a shape mismatch here breaks a client component silently (TypeScript catches type mismatches but not runtime shape drift from Supabase/PostgREST):

| ID | Contract | Validation |
|---|---|---|
| CT-1 | `RunFilter` URL↔object round-trip (`parseRunFilter`/`serializeRunFilter`) is total and lossless for every valid value, and degrades safely (never throws) for any invalid input. | `run-filter.test.ts` — property: `parseRunFilter(serializeRunFilter(f))` is idempotent for every valid `RunFilter`; fuzz malformed query strings (see §5 Random Tactics). |
| CT-2 | `getFilteredRuns`'s `{ rows, totalCount }` shape stays stable under every filter combination, including the zero-match case (`rows: []`, `totalCount: 0`, never `null`/`undefined`). | `filtered-runs.test.ts` |
| CT-3 | Server Action response shape `{ ok: true, repository } \| { ok: false, code, message, fieldErrors? }` is a closed discriminated union — every `code` the action can return is one of the three documented (`REPOSITORY_ALREADY_EXISTS`, `INVALID_REPOSITORY_FORMAT`, `DATABASE_ERROR`), and `ok:false` never leaks a raw Postgres error message into `message`. | `repository-mutations.test.ts` (integration) + `AddRepositoryForm.test.tsx` (component, asserts the client branches on `code` correctly) |
| CT-4 | `applyLogFilter`'s output is always a subset of its input (`result.length <= lines.length`, every returned line satisfies the active filter predicate) — a composability contract between the step filter and level filter. | `log-filter.test.ts` — property-based, see §5. |
| CT-5 | `buildStepsPanel`'s event-count-from-already-loaded-window contract: the sum of per-step counts it derives must never exceed the total event count in the loaded window (it is a partition of a bounded window, not an independent count). | `run-detail.test.ts` extension |

## 5. Edge-Case Catalog

Organized by the standing category taxonomy (input domain, state transition, timing, idempotency, failure modes, auth/permissions, data boundaries, resource exhaustion, API versioning). Each item marked **[Story-covered]** if already in a story's own Edge-Case Matrix, or **[Gap — verifier-added]** if this compliance pass is adding it.

### 5.1 Input domain

- **[Story-covered, S-143]** Search string containing regex metacharacters must not throw — literal substring match only (mirrors dashboard `AgentFilter` EC-25 precedent).
- **[Story-covered, S-147]** `parseFullName`: empty string, missing slash, multiple slashes, leading/trailing whitespace, case sensitivity.
- **[Gap — verifier-added]** `search` containing SQL-wildcard characters meaningful to `ilike` (`%`, `_`) — must not behave as an unintended wildcard from the operator's point of view (e.g. searching literally for a run id substring containing `%` should not silently broaden the match). Add to `run-filter.test.ts`/`filtered-runs.test.ts`: assert `%`/`_` in the search term are either escaped before `.ilike()` or documented as accepted wildcard behavior — currently unspecified in spec §8.1's query shape description. **Route to `developer`/`product-engineer` for a shape decision before S-143 lands its integration test.**
- **[Gap — verifier-added]** `search` containing Unicode/emoji/very-long strings (resource-exhaustion-adjacent) — confirm no crash and a bounded query (no unbounded `LIKE '%...%'` cost blowup at current volume; not a hard requirement given `product-context.md` §11's low-volume assumption, but worth one fuzz case, see §6).
- **[Gap — verifier-added]** `repo` filter chip carrying a `repositoryId` that is a syntactically valid UUID but does not exist (deleted/never-existed row, distinct from S-143's covered "repo with zero runs" case) — must resolve to the FR6 empty state, not a query error.

### 5.2 State transition

- **[Story-covered, S-143]** Stale `running` row past timeout threshold (reaper paused) must filter/count as `timed_out`, never `running` — the standing FR11a invariant, now exercised under a *filter*, not just the dashboard breakdown.
- **[Story-covered, S-146]** A disabled agent's historical runs still appear in `/runs` (not agent-scoped) — explicitly distinct from `/agents/[slug]`'s disabled-agent-404 rule.
- **[Story-covered, S-148]** Archiving an already-archived repository is a no-op, not an error (idempotency, also listed under 5.4).
- **[Gap — verifier-added]** A run's `effective_status` transitions from `running` to `timed_out` (reaper fires) **while an operator has that status filter active in an open tab** — since FR4 is server-rendered per-request (no live subscription per the resolved FR8 scope), the operator sees the stale value until next navigation/reload. This is not a defect (matches the resolved "presentational, no live subscription" posture) but **should be asserted as expected, not silently assumed** — add one test asserting a full-page reload (not a soft client refresh) is what re-resolves `effective_status`, so a future regression that tries to "fix" this with client-side polling doesn't silently violate spec §17 OQ1's resolution.

### 5.3 Timing

- **[Story-covered, S-145]** Live run mid-tail with a step filter applied: new events for a filtered-out step must not appear; new events for the filtered-in step must still autoscroll (S-110 behavior preserved under a filter).
- **[Story-covered, S-145]** A live run's step event counts may under-count until the SSE tail catches up — documented as accepted, not asserted as a bug.
- **[Gap — verifier-added]** 300ms search-debounce interaction with rapid sequential keystrokes plus a fast intervening navigation (e.g. operator types, then immediately clicks a status chip before the debounce fires) — confirm the debounce does not fire a stale `router.replace` that clobbers the status-chip's URL update (a race between two URL-mutation sources). Add to `RunFilterBar.test.tsx`.

### 5.4 Idempotency

- **[Story-covered, S-147/S-148]** Duplicate `full_name` insert rejected both at the pre-check and the `23505` fallback path (concurrent double-submit race) — explicitly called out as needing both paths exercised, not just the pre-check.
- **[Story-covered, S-148]** Archive twice: second call is a no-op, timestamp does not regress.

### 5.5 Failure modes

- **[Gap — verifier-added]** `getFilteredRuns` / `getRepositories` / `insertRepository` failure paths (a real Postgres error, not just the duplicate-constraint case) — confirm the existing `DatabaseError`/`lib/supabase/errors.ts` "log the pg code, never return it" convention holds for **every new query/mutation this PRD adds**, not only the ones explicitly named in spec §13's error-code table. The stories' Testing Requirements sections do not explicitly enumerate a generic-DB-failure test for `getFilteredRuns` or `getRepositories` (only for `insertRepository`'s `REPOSITORY_ALREADY_EXISTS`/`INVALID_REPOSITORY_FORMAT` paths). **Recommend `developer` add one `DATABASE_ERROR`-path test per new query helper**, matching the existing `errors.test.ts` pattern (S-104).
- **[Gap — verifier-added]** FR8's connection indicator "disconnected"/failure state has no described trigger or test in any story. Per spec §17 OQ1, the indicator "reflects whether the page's last server fetch succeeded" — but a server-rendered Next.js page whose data fetch throws does not reach the client to render a "disconnected" indicator at all (it hits the route's error boundary instead). **This is a design ambiguity, not just a missing test**: as specified, it is unclear what state the indicator can ever show besides "connected." Flag to `product-engineer`/`developer` before S-143 implementation locks in a specific mechanism — the traceability matrix marks AC-FR8 coverage as **at risk** pending this clarification (see §7 Recommendations).

### 5.6 Non-goal boundary (absence assertions)

- **[Gap — verifier-added, compliance-specific]** None of the 7 stories' file lists touch `Settings`, `System health`, or command-palette-adjacent files — confirmed by inspection of the tasks file's Relevant Files section. Recommend one lightweight assertion per screen (already partially covered by the existing `AppShell.test.tsx`'s "four deferred items are non-links with `aria-disabled`" check, S-106) is **extended, not just left as-is**, to confirm exactly two of those four (`All runs`, `Repositories`) flip to live links while `Settings`/`System health` remain disabled — i.e. a regression test that a future story doesn't accidentally enable all four at once. Add to `Sidebar.test.tsx`.
- **[Story-covered, S-147]** No live GitHub API call at add-time (asserted by absence — no `fetch`/GitHub-client mock is ever invoked in `repository-mutations.test.ts`; recommend an explicit "spy on the GitHub client module, assert zero calls" test rather than only an implicit absence, since implicit absence tests are easy to silently break).
- **[Story-covered, S-148]** No restore UI — confirmed by the absence of a restore action in `RepositoryTable.tsx`'s file list; recommend also a **negative E2E assertion** (E2E-10 above) rather than relying solely on "this component doesn't have a restore button" by omission, since omission-only compliance is fragile against future PRs.

### 5.7 Resource exhaustion / data boundaries

- **[Story-covered, S-143]** Paging beyond a simulated `max_rows=1000` PostgREST ceiling under a filtered result set.
- **[Story-covered, S-146]** All Runs unfiltered-by-default cross-agent scan — flagged as a performance risk, not required to be fixed (PRD Open Question §18), so no test asserts a performance SLA here; correctly left as non-blocking per spec §16.
- **[Gap — verifier-added]** FR7's PR-link lookup: a single run carrying **more than one** `pull_request`-type artifact (e.g. a superseded/reopened PR scenario) — spec/stories describe the lookup as `Record<string, RunArtifactRow>` (one row per run id), which implies "last write wins" or "first match wins" with no documented tie-break rule. Recommend `getPullRequestArtifactsForRuns` have an explicit, tested tie-break (e.g. most recent `created_at`) rather than depending on incidental DB/PostgREST row order. **Route to `developer` for a shape decision.**

## 6. Randomized / Property-Based Tactics

Per `activity-random-test-tactics`, targeting the pure modules this PRD introduces (all are prime property-testing candidates — pure functions, no I/O):

| Module | Property | Seed policy |
|---|---|---|
| `lib/domain/run-filter.ts` | `parseRunFilter` never throws for any `URLSearchParams` constructed from an arbitrary string (fuzz raw query strings, including malformed percent-encoding); `serializeRunFilter(parseRunFilter(x))` is idempotent on its second application. | Fixed seed per CI run, logged on failure; `fast-check`-style generators if the project takes a property-testing dependency, or a hand-rolled table of ~30 adversarial strings if it does not (no new dependency per spec §16 — **prefer the hand-rolled table** to honor that constraint). |
| `lib/domain/log-filter.ts` | `applyLogFilter(lines, filter).length <= lines.length` for any `lines`/`filter` combination; applying the same filter twice is idempotent; the empty filter (`{stepId: null, level: "all"}`) is always the identity function. | Same as above. |
| `lib/domain/repository-input.ts` | `parseFullName` accepts iff the trimmed input matches `/^[\w.-]+\/[\w.-]+$/` exactly — fuzz random ASCII/Unicode strings and assert the accept/reject decision always agrees with a direct regex re-check (a metamorphic property, not a fixed fixture list). | Same as above. |

**Reproducibility:** every randomized case that surfaces a failure **must** log the exact input string/seed in the test failure output (not just "test failed") so it is directly replayable — a hand-rolled adversarial-string table already satisfies this trivially (the table itself is the fixed input set, no seed needed); if the implementer chooses a true property-testing library later, it must still be pinned to a logged seed per the Non-Negotiable Operating Rules.

**Failure triage:** any randomized case that fails follows the standard capture→isolate→minimize→classify→report sequence (verifier operating rules), with a 3-attempt retry budget before marking `inconclusive`.

## 7. Traceability Summary

See `/workstream/traceability-matrix-prd-agent-fleet-panel-v3-ui-depth.md` for the full FR→AC→Test-Case-ID mapping. Coverage status: **18/18 FRs covered by at least one story-level test target; 12/12 PRD §13 ACs mapped to ≥1 positive + ≥1 negative/edge test**, with 3 items flagged **at risk pending a spec-level clarification** (FR8 failure-state mechanism; FR3 `ilike` wildcard-character handling in search; FR7 multi-artifact tie-break) rather than blocking — these are recommendations to `developer`/`product-engineer`, not blockers to starting implementation, since none of the three affects the already-well-specified happy path.

## 8. Execution Checklist

- [ ] `pnpm --filter panel test:unit` — all new Layer 1 modules (`run-filter.ts`, `log-filter.ts`, `repository-input.ts`, `status-meta.ts` extension, `run-detail.ts` extension)
- [ ] `pnpm --filter panel test` (component/Layer 2) — `RunFilterBar`, `StepsPanel`, `AddRepositoryForm`, `RepositoryTable`, `StatusDot`/`StatusPill` extensions, `RunHistoryTable`/`RunHistoryRow` extensions, `Sidebar` extension
- [ ] `REQUIRE_LOCAL_DB=1 pnpm --filter panel test:integration` — `filtered-runs.test.ts`, `pull-request-artifacts.test.ts`, `repository-mutations.test.ts` (incl. the RLS-deny-all regression check every prior auth-adjacent story includes)
- [ ] `pnpm --filter panel test:e2e` — new/extended specs per §3
- [ ] `coverage_gate` PASS (100%) on every new pure module, per the standing project convention
- [ ] `pnpm --filter panel validate` (lint + format:check + typecheck + test + audit) green
- [ ] Manual/UI passes per each story's Testing Requirements section (dev gallery for S-142; seeded local stack for S-143/S-144/S-146/S-147/S-148; live + terminal run fixtures for S-145)
- [ ] Confirm the 3 "at risk" items in §7 are resolved (or explicitly accepted as-is) before the corresponding story (S-143 for FR8/FR3, S-144 for FR7) is marked done
