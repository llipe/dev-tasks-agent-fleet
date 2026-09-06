## chore(panel): remove stray duplicate " 2" files

Housekeeping. Eight byte-identical, macOS-style duplicate files ("` 2`" in the name) were committed alongside S-108 and have sat unreferenced in the repo since. This removes them.

### Files removed (all confirmed byte-identical to their canonical original)

- `panel/components/runs/AgentHeader 2.tsx`
- `panel/components/runs/AgentHeader.module 2.css`
- `panel/components/runs/RunHistoryRow 2.tsx`
- `panel/components/runs/RunHistoryTable 2.tsx`
- `panel/components/runs/RunHistoryTable.module 2.css`
- `panel/lib/domain/run-row 2.ts`
- `panel/tests/integration/runs-by-agent.test 2.ts`
- `panel/tests/unit/run-row.test 2.ts`

### Why they're safe to delete

- Every one has a canonical original still present (confirmed with `diff` — identical).
- Nothing references them: an `import` path cannot contain a space, and a repo-wide grep for the `" 2"` basenames found no matches.
- The two `*.test 2.ts` duplicates matched Vitest's include globs, so they were silently running as **redundant** suites — removing them removes wasted execution, not coverage. The canonical `run-row.test.ts` / `runs-by-agent.test.ts` still run.

### Verification

- `git diff`-confirmed each duplicate identical to its canonical file.
- `pnpm run typecheck`, `pnpm run lint`, `pnpm run format:check` clean.
- `pnpm run test`: **617 passed / 9 Docker-gated skips** (down from 627 — exactly the removed duplicate unit suite; no canonical coverage lost).
- `pnpm run audit` clean (exit 0).
- `make validate` green on both branches (Python 452 passed).

### Migration lifecycle

**Not applicable** — file deletions only, no schema/data/API change, no behavior change.

### Scope

Pure cleanup; no source, test logic, or dependency changes beyond deleting the dead duplicates. Flagged originally in PR #144's notes.
