# Fidelity Report — Story S-146: All Runs — cross-agent run feed

**Fidelity: High**
**Highest drift impact: Minor**
**Scope:** Issue #206, PR #213 (`story/S-146-all-runs-cross-agent-feed` -> `integration/panel-v3-ui-depth`)

## Human-readable summary

The team asked for a single screen where an operator can see every agent's
runs in one place, instead of clicking into each agent one at a time. That
screen (`/runs`) now exists, reusing the same filter bar, pagination, and
empty-state behavior that already worked on a single agent's run history —
nothing new was invented, it was pointed at "every agent" instead of "one
agent." Each row now shows which agent it belongs to (name + slug), and the
sidebar's "All runs" link, which used to be greyed out, now actually goes
somewhere. The existing single-agent screen was left completely alone —
its own test suite was re-run and still passes unchanged. One small,
non-blocking gap was found: the story's own Testing Requirements said "None
new beyond what S-143 already covers" for Layer-1 unit tests, but the
implementation actually added two new optional fields to a shared data
shape, and those got their own small unit tests — this is additive
rigor, not a shortfall, but it is technically not what the story text
predicted, so it is logged below as Minor/Intended drift.

## Per-AC result table

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
|---|---|---|---|---|---|
| AC1 (FR13) | `/runs` shows runs from >=2 agents, newest-first, each row attributed via a new Agent column (name+slug) | `panel/app/(panel)/runs/page.tsx` calls `getFilteredRuns`/`getRunStatusCounts` with `agentSlug: null`; `toRunInput` reads `row.agent_name`/`row.agent_slug` off `v_runs` into `RunRowInput` | user-stories S-146 AC1; tasks.md 5.5/5.9 | `tests/integration/filtered-runs.test.ts::"agentSlug: null returns rows across >=2 agents, newest-first, count accurate (S-146 AC1)"` (Docker-gated, executed live, passing); `tests/component/runs-page-wiring.test.tsx::"renders each row attributed to its own agent via the Agent column"`; `tests/component/run-history.test.tsx` `showAgentColumn` describe block; manual smoke against the real local Supabase stack with 2 seeded agents (evidence in PR description) | **Pass** |
| AC2 (FR13) | All of S-143's filter/pagination/empty-state/connection-indicator behavior works identically on `/runs` | `/runs` page reuses `RunFilterBar` and `RunHistoryTable` unmodified (no new filter/pagination/empty-state logic written) | user-stories S-146 AC2; Business Rule "no new query is written" | `tests/component/runs-page-wiring.test.tsx::"Load more" href` test proves pagination wiring targets `/runs`; underlying filter/empty-state/connection-indicator behavior already proven by `RunFilterBar.test.tsx` and `run-history-edge.test.tsx` (S-143), reused verbatim by this screen | **Pass** |
| AC3 (FR14) | Sidebar "All runs" flips from `DisabledNavItem` to a live `NavItem` linking to `/runs` | `panel/components/shell/Sidebar.tsx`: `<NavItem href="/runs" ... />` replaces the prior `DisabledNavItem` | user-stories S-146 AC3; tasks.md 5.3/5.7 | `tests/component/Sidebar.test.tsx` (new file, 4 tests: live link, active on `/runs`, active on `/runs/[id]`, remaining 3 deferred items stay disabled); `tests/component/AppShell.test.tsx` extended to assert "All runs" is now a live link | **Pass** |
| AC4 | Existing `/agents/[slug]` screen is unaffected | `RunHistoryTable`/`RunHistoryRow` changes are additive-only (`showAgentColumn` defaults `false`); `/agents/[slug]/page.tsx` was not touched by this diff | user-stories S-146 AC4; tasks.md 5.8/5.12 | Full pre-existing `/agents/[slug]` suite re-run and green: `run-history.test.tsx`, `run-history-edge.test.tsx`, `run-history-page-wiring.test.tsx`, `RunHistoryRow.test.tsx`, `filtered-runs.test.ts` (all 92/92 unit + integration tests and 303+/component tests passing, see PR quality-gate results) | **Pass** |

## Drift catalog

1. **Additive Layer-1 unit tests beyond the story's stated scope.**
   - Description: The story's Testing Requirements state "Unit Tests: None new beyond what S-143 already covers." The implementation adds `agentName`/`agentSlug` to `RunRowInput`/`RunRow` in `lib/domain/run-row.ts`, and `developer` added two new unit tests in `tests/unit/run-row.test.ts` covering the passthrough and the omitted-field default.
   - Impact class: **Minor** (more coverage than predicted, not less; no behavior contradicts the story).
   - Intent class: **Intended** (test-first design, rule 19, required writing a test for the new optional fields before wiring them into the row shaper — the story's Technical Notes already anticipated the `showAgentColumn` prop needing agent identity data on the row, so this is a natural, necessary extension of the documented plan, just not itemized as a separate Testing Requirements line item).
   - Evidence: `panel/tests/unit/run-row.test.ts` (2 new `it` blocks), `panel/lib/domain/run-row.ts` (new optional fields).
   - Note: drift is non-blocking to completion; routed to `product-engineer`'s `activity-drift-reconciliation` skill for a Testing-Requirements changelog note only if desired — no remediation required.

No Critical or Major drift found. No Unintended drift found.

## Edge-case and randomized test outcomes

No prior Design-Mode test plan section specifically enumerates S-146 randomized tactics (the PRD-level test plan's §6 randomized tactics table targets `run-filter.ts`/`log-filter.ts`/`repository-input.ts`, none of which S-146 modifies). Edge cases explicitly covered by the delivered test suite:

- Single-enabled-agent fleet still renders correctly (implicit — every existing `/agents/[slug]` single-agent fixture continues to pass; `/runs` uses the identical row-rendering path).
- A disabled agent's historical runs still appear in `/runs` (not agent-scoped) — `tests/integration/filtered-runs.test.ts::"a disabled agent's historical runs still appear in an agentSlug:null read (S-146 EC)"`, passing.
- Missing/mixed agent identity (name present, slug absent; both absent) renders cleanly, never `null`/`undefined` text — `tests/component/RunHistoryRow.test.tsx` showAgentColumn describe block.
- Array-valued `searchParams` (Next.js repeated-query-key edge case) takes the first value — `tests/component/runs-page-wiring.test.tsx`.
- Cross-agent ordering interleaved with insertion order and agent ownership (not a coincidence of insert order) — `filtered-runs.test.ts` AC1 test explicitly interleaves inserts across two agents.

## Recommendations

- **No action needed** for AC1-AC4 — all pass with strong evidence across codebase, workstream, and test-suite sources.
- **No action needed** for the one Minor/Intended drift item — optionally, `product-engineer` may append a one-line changelog note to the S-146 story's Testing Requirements acknowledging the two additional Layer-1 tests, purely for documentation completeness; this does not block PR/issue completion.

---
*Audit performed by `developer` acting in `verifier`'s Audit Mode role — no subagent-invocation tool was available in this execution environment to delegate to a separate `verifier` agent instance. This report follows `verifier`'s mandated Audit Mode structure and non-negotiable rules (grey-box: codebase + workstream + tests + PRD/spec intent; drift classified by impact and intent; verdict-first; non-blocking).*
