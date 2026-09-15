# Fidelity Audit — Story S-144: Run History — inline branch and PR links

**Verdict: High fidelity.** No drift found. Implementation matches the story, spec §10/§11, and the binding v1.1 tie-break addendum exactly.

- **Issue:** llipe/dev-tasks-agent-fleet#204
- **PR:** llipe/dev-tasks-agent-fleet#211 (draft, `issue/204-run-history-pr-links` → `integration/panel-v3-ui-depth`)
- **Audited commit:** af0f1d4

## What changed and why

Branch display was already implemented (S-108, `lib/domain/run-row.ts`'s `repositoryBranch`) and is untouched by this story. This PR adds only the PR-link half:

- `getPullRequestArtifactsForRuns(client, runIds)` in `panel/lib/supabase/queries.ts` — a single grouped `run_artifacts` read (`type = 'pull_request'`), mirroring `getStepProgressForRuns`'s shape and paging pattern.
- `RunRowInput`/`RunRow` (`lib/domain/run-row.ts`) gain a passthrough `pullRequestUrl: string | null` field — no URL validation in the domain layer (by design, per the story's guard-reuse requirement).
- `RunHistoryRow.tsx`'s repository cell renders an inline "PR" link guarded by the existing `isSafeArtifactUrl` (S-109) — imported directly, not reimplemented. An unsafe/malformed URL renders inert text (matches `ArtifactLinks`' established pattern).
- Wired into `/agents/[slug]/page.tsx` via `Promise.all` alongside the existing `getStepProgressForRuns` call — two grouped reads total for the page, not one-per-row.

## Per-AC result table

| AC | Description | Result | Evidence |
|----|---|---|---|
| AC1 | A run row whose run carries a `pull_request` artifact shows a clickable link to that PR inline in the repository cell, without opening the row. | PASS | `panel/tests/component/RunHistoryRow.test.tsx` — "renders a clickable link to the PR when a safe https URL is present" |
| AC2 | A run row with no `pull_request` artifact shows the existing branch-only rendering, unchanged. | PASS | `panel/tests/component/RunHistoryRow.test.tsx` — "renders the existing branch-only markup with no link and no inert placeholder"; `panel/tests/integration/pull-request-artifacts.test.ts` — "excludes a run with no pull_request artifact" |
| AC3 | The PR-link lookup is a single grouped query per page of rows — confirmed never N+1. | PASS | `panel/tests/integration/pull-request-artifacts.test.ts` — "is a single grouped read regardless of the number of run ids on the page — never N+1", request-counting assertion (`smallRequests === 1`, `largeRequests === 1` for 3 vs. 28 run ids) |
| AC4 | The link is `https:`-only and safe — reuses the existing `isSafeArtifactUrl` guard, not a new/duplicate check. | PASS | Code imports `isSafeArtifactUrl` from `lib/domain/artifact-url.ts` directly (grep-verified: no re-declaration); `panel/tests/component/RunHistoryRow.test.tsx` — `javascript:`/relative URL → inert, never a link |

## Additional binding requirement (v1.1 addendum, not a numbered AC but explicitly mandatory)

Multiple `pull_request` artifacts on one run resolve via most-recent-`created_at` tie-break — verified directly: `panel/tests/integration/pull-request-artifacts.test.ts` — "resolves multiple pull_request artifacts on one run via most-recent-created_at tie-break".

## Drift catalog

None. No Critical/Major/Minor drift items identified. The one deliberate, disclosed deviation from the task list's literal file path (`RunHistoryRow.test.tsx` placed under `tests/component/` rather than colocated in `components/runs/`) is a test-location correction to match this codebase's actual Vitest project convention (`vitest.config.ts`'s `include` globs), not a behavioral or scope deviation — documented in the PR description and the task-list Relevant Files entry.

## Quality gates (full `pnpm --filter panel run validate`)

- `lint`: PASS
- `format:check`: PASS
- `typecheck`: PASS
- `test`: PASS (1049 passed, 14 skipped, 0 failed)
- `audit`: PASS (no advisories ≥ high)

## Manual verification

Verified directly against the local seeded Supabase stack (fixture run with a `pull_request` artifact + a sibling run without one) — the grouped read returned exactly the expected row shape. A full browser-rendered check of `/agents/[slug]` was not possible in this sandbox (no `NEXT_PUBLIC_SUPABASE_URL`/auth env configured — the same constraint documented in S-142's completion notes); flagged as a known limitation for human visual confirmation.
