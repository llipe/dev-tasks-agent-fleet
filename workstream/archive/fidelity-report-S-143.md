# Verifier Audit (Audit Mode) — Story S-143

**Fidelity: High**
**Highest drift impact: Minor**

> Note: this report backfills a documentation-completeness gap flagged by
> `qa-engineer`'s PRD-scope coverage rollup
> (`workstream/coverage-report-prd-agent-fleet-panel-v3-ui-depth.md`): S-143
> was audited at merge time (PR #210 comment, posted by `developer` acting in
> `verifier`'s role because no separate subagent-invocation tool was available
> in that execution environment) but no `workstream/fidelity-report-S-143.md`
> file was ever written. This report is a genuine re-audit against the
> delivered code on `integration/panel-v3-ui-depth` @ `8bc29f4` — not a
> transcription of the PR #210 comment — though that comment's AC table and
> drift findings were used as a starting hypothesis and independently
> re-verified against `panel/lib/domain/run-filter.ts`,
> `panel/lib/supabase/queries.ts`, `panel/components/runs/RunFilterBar.tsx`,
> `panel/app/(panel)/agents/[slug]/page.tsx`,
> `panel/components/runs/RunHistoryTable.tsx`, and the corresponding
> `tests/unit/run-filter.test.ts`, `tests/integration/filtered-runs.test.ts`,
> and `tests/component/RunFilterBar.test.tsx` files, plus a live
> `pnpm --filter panel run validate` run against the local Supabase stack
> (see PRD rollup report for the full run transcript).

## Scope

Story S-143 (Run History — filter, search, and pagination), issue #203,
against `workstream/user-stories-prd-agent-fleet-panel-v3-ui-depth.md`
(S-143 section), `workstream/specification-prd-agent-fleet-panel-v3-ui-depth.md`
§8.1/§10/§11, and `docs/requirements/prd-agent-fleet-panel-v3-ui-depth.md`
FR1–FR6/FR8.

## Acceptance criteria — evidence

| AC | Requirement | Verdict | Evidence |
|---|---|---|---|
| AC1 (FR1) | Status segmented control (colored dot + live count), `effective_status`-derived, stale `running` past timeout counts/filters as `timed_out` | **Pass** | `RunFilterBar.tsx` (segmented control consuming `RunStatusCounts`); `queries.ts::getRunStatusCounts` (single grouped read, folded in JS, never N+1); `filtered-runs.test.ts::"status filter narrows to that effective_status (AC1)"` and `::"a stale running row past its timeout threshold counts/filters as timed_out...(FR11a)"` — both run live against the local Postgres stack, confirmed in this session's `pnpm --filter panel run validate` (14/14 `filtered-runs.test.ts` tests passed against real Postgres) |
| AC2 (FR2) | Repository filter chips narrow the list; combined with status, result is the intersection | **Pass** | `RunFilterBar.tsx` chips wired to `getEnabledRepositories` (existing helper, reused as documented, no new query); `applyRunFilterClauses` in `queries.ts` applies `repositoryId` via `.eq` alongside `effective_status`; `filtered-runs.test.ts::"repo chip narrows correctly; combined with status, the result is the intersection (AC2)"` |
| AC3 (FR3) | Free-text search matches repository name, branch, or run id substring; composes with other filters | **Partial pass — documented, Minor drift** | Delivered: `repository_full_name` substring (`ilike`, wildcard-escaped) **plus an exact `id` match only when the search term is itself a syntactically valid UUID** — not a partial run-id substring match, and `branch` is not matched at all. Root cause verified directly in `queries.ts::applyRunFilterClauses` (lines ~424–447): PostgREST's `.or()` logic-tree grammar rejects a `::type` cast in a filter-column reference, and Postgres itself rejects an un-cast `ilike` against the `uuid` `id` column (`42883 operator does not exist: uuid ~~* unknown`) — a real, reproducible platform constraint, not an unverified excuse. See Drift #1. |
| AC4 (FR4) | Reloading a URL carrying `?status=failed&repo=<id>&q=foo` reproduces the identical filtered result from a fresh server-side query | **Pass** | `run-filter.test.ts` parse/serialize round-trip (total, never throws, defaults omitted); `filtered-runs.test.ts::"reloading a URL reproduces the identical filtered result from a fresh server-side query (AC4)"` (live) |
| AC5 (FR5) | Pagination renders "`X of Y`" + "Load more"; "Load more" under a filter fetches the next page of the filtered set | **Pass** | `app/(panel)/agents/[slug]/page.tsx` lines ~195–223 render `{shownCount} of {totalCount}` + a conditional "Load more" link (verified by direct read, not just test evidence); `getFilteredRuns`'s `.range(0, Math.max(filter.page,1)*pageSize-1)` is cumulative-offset, never keyset; `filtered-runs.test.ts::"pagination is cumulative-offset and totalCount stays accurate under a filter (AC5)"` (live) |
| AC6 (FR6) | Zero-match filter combination renders empty state + working "Clear filters" CTA | **Pass** | `RunHistoryTable.tsx`'s `hasActiveFilter` prop (default `false`, so every pre-existing caller/test is unaffected) gates the empty-state branch with a "Clear filters" link to the unfiltered URL; `filtered-runs.test.ts::"a zero-match filter combination returns { rows: [], totalCount: 0 }, never an error (AC6, CT-2)"` (live, data layer) + component-level empty-state assertion in `run-history-edge.test.tsx` |
| AC8 (FR8) | Connection-state indicator present in the filter bar, reflecting fetch success | **Pass — as a documented, narrower-than-literal-PRD implementation** | `RunFilterBar.tsx` renders a static "Connected" `role="status"` indicator (spec §17 Open Question #1 resolved to presentational-only, no new Realtime subscription — this is the same scope narrowing the PRD's own Open Question §18 anticipated as a live spec decision, not an unauthorized cut); `RunFilterBar.test.tsx::"connection indicator"` |

6 of 7 ACs fully met; AC3 is a documented partial (Minor drift, not a Fail — the common real-world cases, repo-name search and pasting a full run id, both work).

## Business rules verified

- Filter/pagination state lives in the URL query string only (`parseRunFilter`/`serializeRunFilter`, no `localStorage`/component-state persistence found in `RunFilterBar.tsx`) — confirmed by direct code read, matching spec §8.1's deliberate divergence from the Dashboard's `localStorage`-persisted density toggle.
- Every status shown derives from `effective_status`, never raw `runs.status` — confirmed: `getFilteredRuns` and `getRunStatusCounts` both filter/read `v_runs.effective_status` exclusively; no new status-derivation logic was introduced (grep of `queries.ts` shows no new `runs.status` read path in this story's diff).
- Cumulative offset paging (not keyset) — confirmed via `.range(0, page*pageSize-1)`.

## Drift

Two items, both classified **Minor / Intended**:

1. **AC3/FR3 search scope narrower than the literal PRD/story wording ("repo name, branch, run id substring").** Root-caused to a genuine, reproduced-live PostgREST/Postgres constraint (see AC3 row above), not an oversight or an unverified claim — I independently confirmed the constraint is real by reading the exact `.or()` clause construction and its inline comment citing the specific Postgres/PostgREST error codes (`PGRST100`, `42883`). `branch` is separately out of scope because it lives inside the unindexed `runs.params` JSON blob and the spec's own binding query-shape text (§8.1) names only `repository_full_name` and "the run's short id" — narrower than the PRD/story prose but consistent with the spec that governs implementation. Documented in `queries.ts`, referenced in the PR description. Impact: Minor — the two common real operator workflows (search by repo name; paste a full run id) both work; only a *partial* run-id substring search is unreachable.
2. **`getRunStatusCounts` is a query helper not named in the story's own Technical Notes / Files-to-Create list.** Required because AC1's own text ("colored dot + **live count per option**") cannot be satisfied by `getFilteredRuns`'s `{rows, totalCount}` shape alone. Implemented as a single grouped, paged read (same "never N+1" pattern as the pre-existing `getStepProgressForRuns`) — additive only, no existing behavior/contract changed.

No Critical or Major drift. No Unintended drift — both items are traceable to a real technical constraint or a story-AC-entailed necessity, and both are disclosed in-code and in the PR description rather than silently introduced.

## Quality gates

Re-run live in this audit session (not trusted from the PR description alone): `pnpm --filter panel run validate` on `integration/panel-v3-ui-depth` @ `8bc29f4`, Node 22.23.2, local Supabase stack up —
`lint: PASS`, `format:check: PASS`, `typecheck: PASS`,
`test: 100 files / 1205 tests passed, 1 file / 4 tests skipped (the pre-existing, unrelated `RUN_BUNDLE_SECRET_TEST=1`-gated suite)`,
`audit: PASS`. `tests/integration/filtered-runs.test.ts` (14 tests, S-143/S-144/S-146 combined) printed `[integration] local Supabase Postgres reachable` and ran for real, not vacuously skipped.

## Manual verification

Not independently re-performed in this audit session (this pass is a grey-box code/test audit, not a fresh manual click-through). The PR #210 description records a manual pass against `getFilteredRuns`/`getRunStatusCounts` directly against the live seeded local stack, and states no full browser-based click-through (with the auth flow) was performed at merge time either. This is carried forward as a known limitation, not silently dropped.

## Known limitations (not drift — documented risk acceptance)

- Free-text "run id" search is exact-UUID-match only, not substring (AC3, Drift #1 above).
- `branch` is not part of the free-text search scope (consistent with the binding spec text, narrower than the PRD/story prose).
- No full interactive browser-based manual click-through was performed for this story, at merge time or in this audit pass — automated Layer 1/2/2.5 coverage (25 unit + 12 component + 12 integration tests, the integration suite genuinely executed against live Postgres) is the primary evidence.
- No new Playwright E2E spec was added for this story (`run-history-filters.spec.ts`, named in `workstream/test-plan-prd-agent-fleet-panel-v3-ui-depth.md` E2E-1/2/3/4, was never created). This is one instance of the PRD-wide 0/11 E2E finding — see the PRD-level rollup report (`workstream/fidelity-report-prd-agent-fleet-panel-v3-ui-depth-rollup.md`) for the aggregate judgment call; it is not re-litigated per-story here.

## Recommendation

No developer action required — Drift #1/#2 are Intended and non-blocking; recommended for `product-engineer`'s `activity-drift-reconciliation` PRD/spec changelog write-back (both are defensible implementation-shape decisions, not regressions). No action needed on Drift; this report itself is the remediation for the "missing fidelity report" gap the coverage rollup flagged.
