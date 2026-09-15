# Fidelity Audit — Story S-148: Repositories — archive (soft delete)

**Verdict: High fidelity.** No drift found. Implementation matches the story, spec §8.4/§10, and the PRD's FR17 exactly. This is the final story of the panel-v3-ui-depth batch (S-142–S-148).

- **Issue:** llipe/dev-tasks-agent-fleet#208
- **PR:** llipe/dev-tasks-agent-fleet#215 (`issue/208-repositories-archive` → `integration/panel-v3-ui-depth`)
- **Depends on:** S-147 (#207, merged)

## What changed and why

- `archiveRepository(client, id)` in `panel/lib/supabase/queries.ts` — a plain `UPDATE repositories SET archived_at = now() WHERE id = $1`. Never a `DELETE`: `runs.repository_id` is a nullable FK (`on delete set null`), and a hard delete would silently sever the link for every historical run against that repository. Idempotent by construction — re-archiving an already-archived row is a no-op re-`UPDATE`, not an error.
- `archiveRepository` Server Action added to the existing `app/(panel)/repositories/actions.ts`, mirroring `addRepository`'s pure-core-plus-thin-action shape.
- `RepositoryTable.tsx` gains an Actions column with a per-row "Archive" button and the panel's first destructive-action confirm dialog (accessible `role="dialog"`/`aria-modal="true"`, no reusable primitive existed to reuse — this is a new, minimal one). Each row owns an independent `useActionState` instance. Success closes the dialog and calls `router.refresh()` (server re-fetch is the source of truth, no client-side row splicing); failure keeps the dialog open with an inline `role="alert"` error.
- No changes to the Invoke path, `getEnabledRepositories`, or any Run History/Run Detail file — verified, not assumed.

## Per-AC result table

| AC | Description | Result | Evidence |
|----|---|---|---|
| AC1 | "Archive" action sets `archived_at = now()`. | PASS | `repository-mutations.test.ts` — "sets archived_at to a non-null timestamp on the target row (AC1)" |
| AC2 | Archiving is idempotent — a no-op, never an error. | PASS | `repository-mutations.test.ts` — "is idempotent — archiving an already-archived repository is a no-op, never throws, and the timestamp does not regress (AC2, 5.4)" |
| AC3 | Archived repository disappears from the default `/repositories` list view. | PASS | `repository-mutations.test.ts` — "excludes the archived row from the default (non-archived) list (AC3)" |
| AC4 | Archived repository disappears from the Invoke-dialog selector, with zero code change to the invoke path. | PASS | `repository-mutations.test.ts` — "also disappears from the Invoke-dialog repository selector, with zero code change to the invoke path (AC4)" (added during this delegation to close a gap: the story's original test suite proved AC3 against `getRepositories` but had no direct test against `getEnabledRepositories`, the function the Invoke selector actually calls — the general "every row has `archived_at: null`" assertion in the pre-existing `queries.test.ts` established the filter's shape but not this story's specific claim) |
| AC5 | A pre-existing run against an archived repository still displays `repository_full_name` correctly. | PASS | `repository-mutations.test.ts` — "a pre-existing run against an archived repository still resolves repository_full_name correctly via v_runs (AC5/AC-12 — proves UPDATE, never DELETE)" |
| AC6 | No restore affordance exists. | PASS | Confirmed by absence — no restore action anywhere in `RepositoryTable.tsx`/`actions.ts`; the confirm dialog's copy explicitly states "not undoable from the UI" |

## Additional coverage

- Archiving a repository with zero runs against it still succeeds (edge case, no special-casing required).
- Full `pnpm --filter panel run validate` re-run with the local Supabase stack properly connected: 98 test files / 1199 tests passed, 3 skipped (Docker/credential-gated, pre-existing and unrelated), 0 failed, audit clean.

## Drift catalog

None. One transient, non-drift observation: an initial `validate` run (before the local Supabase stack's full env was exported) showed a single `tests/unit/eslint-server-import.test.ts` failure — a `[vitest-worker]: Timeout calling "onTaskUpdate"` RPC error, not an assertion failure. Confirmed a flake by an isolated re-run (passed) and a full clean re-run (passed) — this story touches no ESLint config and could not have caused it.

## Quality gates (full `pnpm --filter panel run validate`, local Supabase stack connected)

- `lint`: PASS
- `format:check`: PASS
- `typecheck`: PASS
- `test`: PASS (1199 passed, 14 skipped, 0 failed)
- `audit`: PASS (no advisories ≥ high)

## Manual verification

Verified directly against the local seeded Supabase stack: inserted a throwaway repository, confirmed it appears in both `getRepositories()` (default) and `getEnabledRepositories()`, archived it via `archiveRepository`, confirmed it disappeared from both reads, confirmed a run inserted against it beforehand still resolves `repository_full_name` via `v_runs` afterward. A full browser-rendered click-through of the confirm dialog was not performed in this sandboxed session (no interactive browser available) — the dialog's behavior is instead covered by `RepositoryTable.test.tsx` component tests (open/cancel/confirm/pending/error states) plus the integration tests above proving the underlying data effect.

## Known limitations

- No new Playwright E2E spec added, consistent with every other story in this batch (E2E is tracked as a PRD-level compliance recommendation, not a per-story requirement).
- No interactive authenticated-browser click-through performed (sandbox constraint) — substituted with component tests for the dialog's UI states and live integration tests for the underlying data effect.
