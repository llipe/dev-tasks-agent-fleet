# Traceability Matrix — Agent Fleet Control Panel v3: UI Depth

**Mode:** Design Mode (pre-implementation)
**Scope:** PRD `prd-agent-fleet-panel-v3-ui-depth.md` v1.0, FR1–FR18, 7 stories (S-142–S-148), GitHub issues #202–#208.
**Companion:** `/workstream/test-plan-prd-agent-fleet-panel-v3-ui-depth.md`

## Changelog

| Version | Date       | Summary                                     | Author   |
| ------- | ---------- | -------------------------------------------- | -------- |
| 1.0     | 2026-09-15 | Initial FR→AC→Test-Case-ID matrix.            | verifier |

---

## Legend

- **FR** — PRD Functional Requirement (§7).
- **PRD AC** — PRD §13 Acceptance Criteria (AC-1…AC-12).
- **Story** — S-142…S-148 / issue #202…#208.
- **Story AC** — the story's own numbered/bulleted acceptance criteria (order as listed in the story; referenced positionally since stories use unlabeled bullet lists).
- **Test-Case ID** — this plan's identifier, cross-referenced to the concrete file the story/spec proposes.
- **Result** column is left blank (`—`) in Design Mode; populated during Audit Mode against delivered code.

## Full FR → AC → Test-Case Mapping

| FR | PRD AC | Story (Issue) | Story AC (positional) | Positive Test-Case ID(s) | Negative/Edge Test-Case ID(s) | Result |
|---|---|---|---|---|---|---|
| FR1 — status segmented control, colored dot + live count, `effective_status`-derived | AC-1 | S-143 (#203) | AC1 | TC-FR1-01 `filtered-runs.test.ts::status filter narrows to effective_status`; TC-FR1-02 `filtered-runs.test.ts::stale running row (reaper paused) counts as timed_out` | TC-FR1-N1 `filtered-runs.test.ts::unknown/future status value falls back to "all"` (via `run-filter.test.ts` fallback contract) | — |
| FR2 — repository filter chips (from `getEnabledRepositories`) | AC-2 | S-143 (#203) | AC2 | TC-FR2-01 `filtered-runs.test.ts::repo filter narrows result` | TC-FR2-N1 `filtered-runs.test.ts::repo chip for a repo with zero runs for this agent → empty state, not error` | — |
| FR3 — free-text search (repo name, branch, run id) | AC-2 | S-143 (#203) | AC3 | TC-FR3-01 `filtered-runs.test.ts::search narrows to repo/branch/run-id substring` | TC-FR3-N1 `run-filter.test.ts::search string with regex metacharacters does not throw, literal match only`; TC-FR3-N2 (gap) `filtered-runs.test.ts::search containing % or _ does not silently broaden match via ilike` — **at risk, needs shape decision** (test plan §5.1) | — |
| FR4 — URL-encoded, server-paginated filters (not client-side re-filter) | AC-3 | S-143 (#203) | AC4 | TC-FR4-01 `run-filter.test.ts::parse/serialize round-trip is idempotent`; TC-FR4-02 `filtered-runs.test.ts::reload of ?status=failed&repo=<id>&q=foo reproduces identical server-queried result` | TC-FR4-N1 `run-filter.test.ts::unknown query values fall back to defaults, never throws`; TC-FR4-N2 (gap) `run-filter.test.ts::stale effective_status under an open tab is not live-updated (expected, not a defect)` | — |
| FR5 — "X of Y" + "Load more" pagination (cumulative offset) | AC-4 | S-143 (#203) | AC5 | TC-FR5-01 `filtered-runs.test.ts::Load more fetches next cumulative page of the filtered set`; TC-FR5-02 `filtered-runs.test.ts::totalCount accurate under each filter combination` | TC-FR5-N1 `filtered-runs.test.ts::paging beyond simulated max_rows=1000 boundary` | — |
| FR6 — empty state + CTA | AC-5 | S-143 (#203) | AC6 | TC-FR6-01 `RunFilterBar.test.tsx::empty state renders explanatory message + Clear filters CTA` | TC-FR6-N1 `RunFilterBar.test.tsx::Clear filters CTA resets URL to unfiltered view` | — |
| FR7 — inline branch/PR links | AC-6 | S-144 (#204) | AC1–AC4 | TC-FR7-01 `RunHistoryRow.test.tsx::run with pull_request artifact shows clickable inline link`; TC-FR7-02 integration `::getPullRequestArtifactsForRuns grouped read, never N+1` | TC-FR7-N1 `RunHistoryRow.test.tsx::run without pull_request artifact shows unchanged branch-only rendering`; TC-FR7-N2 `::unsafe URL (javascript:/relative) renders inert via isSafeArtifactUrl`; TC-FR7-N3 `integration::empty page → zero-cost lookup, {} for empty runIds`; TC-FR7-N4 (gap) `::run with >1 pull_request artifact has an explicit, tested tie-break` — **at risk, needs shape decision** (test plan §5.7) | — |
| FR8 — connection-state indicator (presentational only, per spec §17 OQ1) | — (implicit, referenced in AC-3 context) | S-143 (#203) | AC7 | TC-FR8-01 `RunFilterBar.test.tsx::connection indicator present, reflects last fetch` | TC-FR8-N1 (gap) — **no test/mechanism currently describes the "disconnected" state's trigger; AC coverage at risk pending clarification** (test plan §5.5) | — |
| FR9 — steps panel (dot, name, duration, event count) | AC-7 | S-145 (#205) | AC1 | TC-FR9-01 `StepsPanel.test.tsx::renders each run_steps row correctly`; TC-FR9-02 `run-detail.test.ts::buildStepsPanel duration formatting reuse` | TC-FR9-N1 `run-detail.test.ts::zero-event step → count 0`; TC-FR9-N2 `StepsPanel.test.tsx::zero-step run renders empty panel, not an error`; TC-FR9-N3 `run-detail.test.ts::in-progress step with no finished_at` | — |
| FR10 — click-step filters log; "All steps" clears | AC-7 | S-145 (#205) | AC2 | TC-FR10-01 `log-filter.test.ts::step-only filter`; TC-FR10-02 `StepsPanel.test.tsx::click sets filter, All steps clears` | TC-FR10-N1 `log-filter.test.ts::unknown stepId → empty result, not a crash` | — |
| FR11 — log-level coloring/filter, composes with step filter | AC-8 | S-145 (#205) | AC3 | TC-FR11-01 `log-filter.test.ts::level-only filter`; TC-FR11-02 `log-filter.test.ts::step+level combined shows intersection` | TC-FR11-N1 `LiveLogViewer.test.tsx::filter + live tail composition, autoscroll/pause-resume preserved (S-110)`; TC-FR11-N2 `log-filter.test.ts::neither filter active → full tail` | — |
| FR12 — `queued` spin vs `running` pulse | AC-9 | S-142 (#202) | AC1–AC4 | TC-FR12-01 `status-meta.test.ts::queued → {pulse:false, spin:true}`; TC-FR12-02 `StatusDot.test.tsx::queued renders .spin, running renders .pulse` | TC-FR12-N1 `status-meta.test.ts::every other status → spin:false, unchanged`; TC-FR12-N2 `StatusPill.test.tsx::no visual regression for queued pill`; TC-FR12-N3 `status-meta.test.ts::unknown/future status falls back to neutral, spin:false` | — |
| FR13 — All Runs cross-agent feed | AC-10 | S-146 (#206) | AC1, AC2 | TC-FR13-01 `filtered-runs.test.ts::agentSlug:null returns rows across ≥2 agents, newest-first, count accurate`; TC-FR13-02 `RunHistoryTable.test.tsx::showAgentColumn renders name+slug` | TC-FR13-N1 `filtered-runs.test.ts::single-enabled-agent fleet still renders correctly`; TC-FR13-N2 `::disabled agent's historical runs still appear in /runs (not agent-scoped)`; TC-FR13-N3 existing `/agents/[slug]` suite stays green unmodified (regression guard) | — |
| FR14 — sidebar "All runs" enabled | — | S-146 (#206) | AC3 | TC-FR14-01 `Sidebar.test.tsx::All runs is a live NavItem link to /runs` | TC-FR14-N1 (gap) `Sidebar.test.tsx::Settings/System health remain disabled while All runs/Repositories flip` (test plan §5.6) | — |
| FR15 — Repositories list (excl. archived by default) | AC-11 (context) | S-147 (#207) | AC1 | TC-FR15-01 `RepositoryTable.test.tsx::lists full_name, default_branch, enabled state` | TC-FR15-N1 `RepositoryTable.test.tsx::archived rows hidden by default`; TC-FR15-N2 `repository-mutations.test.ts::empty repositories table renders empty list, not an error` | — |
| FR16 — add repository (manual reference, no GitHub call) | AC-11 | S-147 (#207) | AC2–AC4 | TC-FR16-01 `repository-mutations.test.ts::insertRepository success path`; TC-FR16-02 `repository-input.test.ts::parseFullName valid owner/repo shapes` | TC-FR16-N1 `repository-mutations.test.ts::duplicate full_name (case-sensitive) → REPOSITORY_ALREADY_EXISTS, no second row`; TC-FR16-N2 `::concurrent double-submit race exercises the 23505 fallback path, not just the pre-check`; TC-FR16-N3 `repository-input.test.ts::malformed full_name → INVALID_REPOSITORY_FORMAT, client- and server-side`; TC-FR16-N4 `::mixed-case full_name differing only by case — verified against real Postgres collation before asserting either way`; TC-FR16-N5 (gap) `repository-mutations.test.ts::no live GitHub API call — explicit spy-and-assert-zero-calls, not implicit absence` (test plan §5.6); TC-FR16-N6 (gap) `queries.test.ts::generic DATABASE_ERROR path for getRepositories/getFilteredRuns` (test plan §5.5) | — |
| FR17 — archive repository (soft delete, idempotent) | AC-12 | S-148 (#208) | AC1–AC5 | TC-FR17-01 `repository-mutations.test.ts::archive sets archived_at`; TC-FR17-02 `::archived repo disappears from default list and Invoke selector`; TC-FR17-03 `::pre-existing run against archived repo still displays repository_full_name on Run History and Run Detail` | TC-FR17-N1 `repository-mutations.test.ts::archiving twice is a no-op, timestamp does not regress`; TC-FR17-N2 `::archiving a repo with zero runs still succeeds` | — |
| FR17 (restore explicitly out of scope) | AC-12 (context) | S-148 (#208) | AC6 | — | TC-FR17-N3 `RepositoryTable.test.tsx` + E2E-10 — absence of a restore action asserted explicitly, not just by omission (test plan §5.6) | — |
| FR18 — sidebar "Repositories" enabled | — | S-147 (#207) | AC5 | TC-FR18-01 `Sidebar.test.tsx::Repositories is a live NavItem link to /repositories` | TC-FR18-N1 `::unauthenticated POST to addRepository is denied by the existing S-117 middleware gate` (manual/existing-suite reference, per story AC6) | — |

## Non-Goals Coverage (absence assertions, not a positive FR)

| Non-goal | Assertion mechanism | Test-Case ID | Result |
|---|---|---|---|
| Command palette / keyboard shortcuts (C21–C22) | Confirmed not touched by any story's file list (tasks-file Relevant Files audit) | TC-NG-01 (inspection, not automated) | — |
| Settings (C19) | Same | TC-NG-02 (inspection) | — |
| System health (C20) | Same | TC-NG-03 (inspection) | — |
| GitHub App repo sync/verification | `insertRepository` makes no GitHub API call | TC-FR16-N5 (see above — recommend upgraded from implicit to explicit spy assertion) | — |
| Repository edit/rename, per-agent enablement | Confirmed not in any story's file list | TC-NG-04 (inspection) | — |
| Restore an archived repository | No restore action in S-148's file list; recommend explicit negative test | TC-FR17-N3 | — |
| Responsive <1024px (declined permanently) | No new viewport-geometry test added or expected — consistent with the already-standing gap noted for S-106/S-108 (`docs/technical-guidelines.md` §11) | TC-NG-05 (documented gap, non-blocking, pre-existing across the whole panel) | — |

## Coverage Summary

- **FR1–FR18:** 18/18 mapped to ≥1 positive test-case ID.
- **PRD §13 AC-1–AC-12:** 12/12 mapped to ≥1 positive + ≥1 negative/edge test-case ID.
- **Items flagged "at risk pending clarification" (not blocking, tracked for follow-up before their owning story is marked done):**
  1. FR8 (TC-FR8-N1) — connection-indicator failure-state mechanism undefined in spec/stories.
  2. FR3 (TC-FR3-N2) — `ilike` wildcard-character (`%`/`_`) handling in free-text search undefined.
  3. FR7 (TC-FR7-N4) — multi-`pull_request`-artifact tie-break rule undefined.
- **Recommended additions beyond what the stories already specify (non-blocking, additive):** TC-FR14-N1 (sidebar boundary regression guard), TC-FR16-N5/N6 (explicit absence + generic DB-error coverage), TC-FR4-N2 (documented stale-under-open-tab expectation).

## Status

**Complete** — every FR and PRD AC has a mapped test-case ID; no AC is left uncovered. Three items are marked at-risk pending a spec-level shape decision (see above) but do not block Design Mode completion or handoff to `developer`.
