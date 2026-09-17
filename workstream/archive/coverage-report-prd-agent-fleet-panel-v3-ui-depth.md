# Coverage and Gap Rollup — Agent Fleet Control Panel v3: UI Depth (S-142–S-148)

**Scope:** PRD-level aggregation across all 7 merged stories on `integration/panel-v3-ui-depth` (branch tip `21cf330`), not a repo-wide audit. Grounded against `workstream/user-stories-prd-agent-fleet-panel-v3-ui-depth.md`, `workstream/test-plan-prd-agent-fleet-panel-v3-ui-depth.md`, `workstream/traceability-matrix-prd-agent-fleet-panel-v3-ui-depth.md`, and the 5 available `workstream/fidelity-report-S-14{2,4,6,7,8}.md` files.
**Author:** qa-engineer
**Date:** 2026-09-15

---

## `/TESTING.md` status: `present`, but **materially stale for this scope**

The root `/TESTING.md` (`status: filled`, owned by `qa-engineer`) describes only the `@llipe.com/dev-tasks` CLI package. It states: *"This is a single-package TypeScript repository; no workspace manifest or additional package was detected."* That statement is factually false as of this branch: `pnpm-workspace.yaml` declares two packages (`panel`, `agents/dependency-update/agentcore/cdk`), and `panel` is the entire subject of this PRD. `/TESTING.md` contains zero mention of `panel`'s Vitest project taxonomy (unit/component/integration), its Layer 2.5 Docker-gated Supabase harness, its Playwright E2E harness, or its `test:coverage` command — all of which exist, are wired into `.github/workflows/ci.yml`'s `panel-quality` job, and are exercised live in this rollup (see below).

This is reported as a **harness/documentation defect**, not as "unfilled" (the document is filled, just scoped to the wrong package and stale against the current workspace). It does not block this rollup — the panel's own in-repo taxonomy comment (`panel/vitest.config.ts`) and `playwright.config.ts` are internally consistent and were used as ground truth instead — but a consumer relying on root `/TESTING.md` alone would not learn that Layer 2.5 and E2E exist for `panel`, or how to run them.

**Recommended fix (routed to `qa-engineer`'s own future standards pass, or `product-engineer` if it implies a scope decision on the CDK package):** add a `panel` row/section to `/TESTING.md` reflecting the real taxonomy (`panel/vitest.config.ts`'s own header comment is a ready-made source), and correct the false "single-package" claim.

---

## Harness defects found (this scope)

1. **`/TESTING.md` scope/staleness** (above) — file path `/TESTING.md`; expected state: covers every package in `pnpm-workspace.yaml`, including `panel`.
2. **Local/CI Node major mismatch confirmed live.** `panel/package.json` declares `"engines": { "node": ">=22 <25" }`; the sandbox's default `node` was v26.7.0, which `pnpm install --frozen-lockfile` **hard-rejected** (`ERR_PNPM_UNSUPPORTED_ENGINE`) before any test could run. I had to explicitly select a pinned Node 22.23.2 (matching `.github/workflows/ci.yml`'s `actions/setup-node@v4` `node-version: 22`) to get a real run. This is the same class of defect already flagged in root `/TESTING.md` for the CLI package, but it is a **live, reproduced-today** blocker for `panel` too, not just a documented risk — expected state: repo tooling (`.nvmrc`/`mise`/Volta pin at the workspace root, or a CI-parity check in a pre-flight script) should prevent an ad-hoc contributor shell from silently failing `pnpm install` on the panel workspace.
3. No harness defect found in `panel/vitest.config.ts` itself: `restoreMocks`/global-stub handling, the `singleFork` Layer-2.5 serialization comment, and the alias-based `server-only` neutralization are all correct and documented in-file.

## Script reachability

- Root `package.json`'s aggregate scripts (`test`, `validate`, etc.) are thin `pnpm --filter panel run ...` wrappers — they reach 100% of `panel`'s own test surface (unit + component + integration projects, all under `panel/vitest.config.ts`'s single `test` command).
- They do **not** reach the second workspace package, `agents/dependency-update/agentcore/cdk` — that package is tested separately (Python pytest, wired as its own `python-quality` CI job) and is out of scope for this PRD rollup, but the root `package.json`'s aggregate `test`/`validate` names do not reach it either. Flagged for completeness, not blocking this PRD-scoped report.
- **CI gate:** `.github/workflows/ci.yml`'s `panel-quality` job runs `REQUIRE_LOCAL_DB=1` + `supabase start` + `db reset` + `pnpm --filter panel run test:coverage` + Playwright E2E + audit — this is the correct, non-vacuous wiring: a Docker-gated Layer 2.5 skip is a **hard CI failure**, not a silent pass. Confirmed by reading the workflow directly, not assumed.
- **Deploy gate:** not evaluated in this pass (out of scope — PRD touches no deploy config).

---

## Ground-truth test run (executed live by `qa-engineer`, not trusted from prior reports)

Ran on branch `integration/panel-v3-ui-depth` @ `21cf330`, Node 22.23.2 (CI-parity), pnpm 10.11.0:

1. `supabase start` (already partially running; `docker ps` confirmed `db`/`auth`/`rest`/`kong`/`realtime`/`storage` all healthy).
2. `supabase db reset --local` — applied `20260902200101_initial_schema.sql`, `20260903090000_english_reaper_messages.sql`, `20260903090100_seed_params_schema_english.sql`, plus `seed.sql`.
3. Exported `SUPABASE_URL=http://127.0.0.1:54321`, `SUPABASE_ANON_KEY`/`SUPABASE_SERVICE_ROLE_KEY` (from `supabase status -o env`), `NEXT_PUBLIC_SUPABASE_URL`/`NEXT_PUBLIC_SUPABASE_ANON_KEY`, and `REQUIRE_LOCAL_DB=1`.
4. `node scripts/warm-realtime.mjs` → `[warm-realtime] Realtime SUBSCRIBED — warm.`
5. `pnpm --filter panel run validate` (lint → format:check → typecheck → test → audit):

```
lint:         PASS
format:check: PASS
typecheck:    PASS
test:         100 test files passed, 1 skipped (101); 1205 tests passed, 4 skipped (1209)
audit:        PASS (no advisories >= high)
```

- Every `tests/integration/*.test.ts` file printed `[integration] local Supabase Postgres reachable` and ran for real — none vacuously skipped. This includes the two Layer 2.5 files this PRD batch's stories added/extended: `tests/integration/filtered-runs.test.ts` (14 tests, S-143/S-144/S-146) and `tests/integration/repository-mutations.test.ts` (15 tests, S-147/S-148), plus `tests/integration/pull-request-artifacts.test.ts` (6 tests, S-144).
- The 4 skipped tests are all in `tests/unit/bundle-secrets.test.ts`, gated behind `RUN_BUNDLE_SECRET_TEST=1` (a pre-existing, documented, CI-only gate unrelated to this PRD's scope — confirmed by reading the file's own skip-reason string).

**This confirms the ground-truth run is genuine, not a vacuous green:** Layer 2.5 assertions for this PRD's scope actually executed against a real Postgres instance.

---

## Per-story fidelity-report status

| Story | Fidelity report | Verdict recorded |
|---|---|---|
| S-142 | `workstream/fidelity-report-S-142.md` | High, no drift |
| S-143 | **MISSING** | — |
| S-144 | `workstream/fidelity-report-S-144.md` | High, no drift |
| S-145 | **MISSING** | — |
| S-146 | `workstream/fidelity-report-S-146.md` | High, Minor/Intended drift (additive unit tests beyond stated scope) |
| S-147 | `workstream/fidelity-report-S-147.md` | High, Minor/Intended drift (ESLint SD2-exemption scope widened) |
| S-148 | `workstream/fidelity-report-S-148.md` | High, no drift |

**This is a gap, not an assumption I am waiving.** S-143 (Run History filter/search/pagination, High priority, size L, the foundational story this entire batch depends on) and S-145 (Run Detail steps panel + log filtering, High priority, size L) have **no per-story `verifier` Audit Mode report** in `workstream/`. Every other story's report explicitly notes it was produced by `developer` acting in `verifier`'s role "because no subagent-invocation tool was available" — S-143 and S-145 have no such report at all, missing or otherwise. I verified their delivered code and tests exist and pass (see below), but a per-story AC-by-AC fidelity verdict for these two — the two largest, highest-priority, most-depended-upon stories in the batch — was never produced. This is the single largest audit-trail gap in the PRD rollup and should be routed back for a fidelity pass on S-143 and S-145 specifically before this PRD is treated as fully audited, even though the code and tests I verified directly are present and green.

---

## Cross-story integration seams (specifically checked, not just each story in isolation)

### 1. S-146 reusing S-143's `RunFilterBar` / `getFilteredRuns`

Read `panel/app/(panel)/runs/page.tsx` directly. Confirmed:
- It imports and calls `getFilteredRuns`/`getRunStatusCounts`/`getPullRequestArtifactsForRuns`/`getStepProgressForRuns` — the exact same helpers S-143/S-144 introduced — with `agentSlug: null`, and introduces **no parallel filtering logic**.
- It reuses `<RunFilterBar>` and `<RunHistoryTable showAgentColumn>` unmodified beyond the new prop.
- `panel/app/(panel)/agents/[slug]/page.tsx` (re-read on this branch) still calls **both** `getAllRunsByAgentSlug` (deliberately retained, for the agent-level header stats which are documented as intentionally unfiltered) **and** `getFilteredRuns` (for the table) — exactly the two-reads shape the story's Context section specified, not an accidental regression or an orphaned call.
- `tests/component/Sidebar.test.tsx` directly tests the seam where S-146 and S-147 both modify the same file: one describe block per feature, plus an explicit regression assertion that Settings/System health stay disabled while only "All runs" and "Repositories" flip — this is exactly the kind of cross-story regression a single-story-scoped audit could miss, and it is covered.
- **No integration-seam gap found here.**

### 2. S-148 extending S-147's `RepositoryTable`

Read `panel/components/repositories/RepositoryTable.tsx` directly. Confirmed:
- The component's own doc comment explicitly states the list-filtering responsibility stays with `page.tsx`'s `getRepositories(client)` call (S-147), and the component "does not duplicate that filtering decision" — S-148 only adds the Archive action + confirm dialog, does not re-implement or shadow S-147's list logic.
- `tests/component/RepositoryTable.test.tsx` has both the pre-existing S-147 list-rendering describe blocks and a dedicated `describe("RepositoryTable — Archive action + confirm dialog (S-148, AC1/AC2)")` block in the same file — a single test file exercising both stories' behavior together, which is the correct place to catch a seam regression.
- `tests/integration/repository-mutations.test.ts` is shared and extended (not duplicated) across S-147 and S-148, per the story's own Technical Notes — confirmed by reading the file: it contains both `insertRepository`/duplicate-rejection tests (S-147) and archive/idempotency/FK-preserving tests (S-148) in one file.
- **No integration-seam gap found here.**

### 3. S-145's step/level filter composing with S-110's live-tail behavior (checked opportunistically — a third seam not named in the task but structurally identical)

`tests/component/live-log-viewer.test.tsx` has a dedicated `describe("LiveLogViewer — step/level filter composition with live tail (Story S-145, AC4)")` block with explicit tests for: default (no filter) backward compatibility, a step filter hiding a live-appended line for a different step, a live-appended line for the filtered-in step still autoscrolling (proving S-110's pre-existing autoscroll behavior was not broken by S-145's new filter state), and a level+step combined composition. **No integration-seam gap found.**

---

## PRD-level `coverage_gate`

**`coverage_gate: PASS`** (aggregated), with two caveats surfaced below that a per-story pass could not have caught in isolation:

1. **`test:coverage` provider exists for `panel`** (`vitest.config.ts` declares V8 provider, `package.json` has a real `test:coverage` script — unlike the root CLI package, this is not a "missing provider" situation for `panel`). I did not additionally run `pnpm --filter panel run test:coverage` to pull a numeric percentage in this pass (the `validate` ground-truth run above already proves every test genuinely executes); if a numeric coverage baseline is wanted for this PRD specifically, that is a follow-up run, not a blocker — flagging so it is not silently assumed measured. All 7 stories' own fidelity reports report `test`/`validate` pass counts but none report a numeric coverage percentage either, so this PRD batch has never had one recorded.
2. Each individual story's `coverage_gate: PASS` (as recorded implicitly by its fidelity report's "Quality gates... PASS" line, where present) **does hold in aggregate** — the live `pnpm --filter panel run validate` run above is the union of all 7 stories' changes and is green with zero failures, so no per-story pass was invalidated by a later story's changes.
3. The **one thing a per-story-scoped pass structurally could not surface**, and which I am surfacing here: **0 of the 11 E2E scenarios (E2E-1 through E2E-11) that `workstream/test-plan-prd-agent-fleet-panel-v3-ui-depth.md` §3 specified for this PRD were implemented.** Every one of the 5 individual fidelity reports that discuss E2E status says, verbatim or in substance, "no E2E added, consistent with every other story in this batch" — each story, read alone, treats this as an acceptable per-story scope cut. Read together at the PRD level, this is a 0% delivery rate against a test plan that explicitly named `run-history-filters.spec.ts`, `run-detail-steps.spec.ts`, `all-runs.spec.ts`, and `repositories.spec.ts` as new files, plus four scenario extensions to `edge-cases.spec.ts`/`stale-and-artifact.spec.ts`. `panel/tests/e2e/` today contains only the pre-existing `auth.spec.ts`, `density.spec.ts`, `edge-cases.spec.ts`, `invoke.spec.ts`, `live-tail.spec.ts`, `stale-and-artifact.spec.ts` — none extended with the new scenario IDs, none of the four new spec files present. This does not fail `coverage_gate` (Layer 1/2/2.5 automated coverage is genuinely strong and was verified live), but it is a real, cumulative PRD-level gap that no single story's own report could have flagged as a gap, because each story's own Testing Requirements section explicitly scoped E2E out for itself.

---

## Ranked gap inventory (largest / highest-risk first)

1. **[High] Two missing per-story fidelity reports (S-143, S-145).** The two highest-priority, largest (`L`-sized), most structurally load-bearing stories in the batch — the ones every other story either directly depends on (S-146→S-143) or shares files with (S-144→S-143's `RunHistoryRow`/`RunHistoryTable`) — have no recorded `verifier` Audit Mode verdict. Code and tests exist and pass (confirmed directly), but no AC-by-AC audit trail exists for them. Route to `verifier` for a dedicated audit pass before treating this PRD as fully closed out.
2. **[Medium] 0/11 planned E2E scenarios delivered against the pre-implementation test plan.** `workstream/test-plan-prd-agent-fleet-panel-v3-ui-depth.md` §3's E2E-1…E2E-11 table is entirely unimplemented. Every story's own report treats this as an individually-acceptable scope cut; at the PRD level it means the full compliance test plan's E2E layer was never executed for any of the 18 FRs in this batch. Layer 1/2/2.5 coverage is strong enough that this is not a correctness blocker, but it is a real, named gap in the delivered test plan versus what was promised pre-implementation.
3. **[Low] `/TESTING.md` does not describe the `panel` package at all** and contains a factually incorrect "single-package repository" claim against the actual `pnpm-workspace.yaml`. Non-blocking for this rollup (the panel's own config files were sufficient ground truth) but should be corrected so a future contributor does not have to independently rediscover the panel's real Layer 2.5/E2E/coverage setup.
4. **[Low] Local/CI Node major-version drift, reproduced live.** `pnpm install --frozen-lockfile` hard-fails under a contributor's ambient Node 26 for the `panel` workspace specifically; a pinned-version tool (`.nvmrc`/Volta) or an explicit pre-flight check would prevent this from recurring for the next person who runs this exact rollup.
5. **[Informational, not a gap] FR3/FR7/FR8 "at risk pending clarification" items from Design-Mode traceability matrix — all three resolved during implementation** (S-143's `ilike` wildcard handling confirmed exercised via edge-case tests reviewed in-file; S-144's multi-`pull_request`-artifact tie-break implemented and tested per its fidelity report's "v1.1 addendum" section; S-143's connection-indicator mechanism implemented and tested per `RunFilterBar.tsx`'s "v1.1 addendum" doc comment and `RunFilterBar.test.tsx`'s dedicated describe block). Confirmed directly, not assumed from the stale Design-Mode matrix (whose `Result` column is still blank/unpopulated — that matrix itself was never updated to Audit Mode, which is itself a minor traceability-hygiene gap worth a note to `verifier`/`product-engineer`, though not blocking).

## What was not analyzed, and why

- **Numeric coverage percentage** — `pnpm --filter panel run test:coverage` was not separately executed in this pass (time-bounded); the `validate` run already proves genuine, non-vacuous execution of every test, which was the higher-priority ground-truth question this task asked me to answer.
- **Full Playwright E2E suite execution** — not run live in this pass; the gap finding above (0/11 planned scenarios delivered) is based on direct file-presence/content inspection of `panel/tests/e2e/`, which is sufficient to establish the gap without needing to execute the existing 6 pre-existing specs (those are outside this PRD's own file-list scope and were not modified by any of the 7 stories).
- **The second workspace package** (`agents/dependency-update/agentcore/cdk`) — out of scope; this PRD touches only `panel/`.
- **A numeric source-to-test size ratio table per individual file** — spot-checked the five new `lib/domain/*.ts` modules directly (each has a larger test file than source file, by line count); did not extend this to every touched component/route file given the volume, but no file inspected showed a suspiciously thin or missing test companion beyond the E2E gap already named above.
