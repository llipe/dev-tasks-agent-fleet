# Implementation Plan — Agent Fleet Control Panel, Phase 2 (Wave 1)

## Scope

This plan covers **Wave 1 only** — the three stories with no UI dependency, which together close three of the spec's seven fix proposals (F6, F7, and F3-extended) and carry the phase's only database migrations.

| Task | Story | Issue | Title |
|---|---|---|---|
| 0.0 | S-101 | [#114](https://github.com/llipe/dev-tasks-agent-fleet/issues/114) | pnpm workspace and panel scaffold (project setup) |
| 1.0 | S-102 | [#115](https://github.com/llipe/dev-tasks-agent-fleet/issues/115) | Adopt Supabase CLI migrations |
| 2.0 | S-103 | [#116](https://github.com/llipe/dev-tasks-agent-fleet/issues/116) | English-only SQL surface and seed fix |

Remaining Phase 2 stories (S-104 … S-115 / #117 … #128) are published and planned in a later wave. Sources: [`user-stories-prd-agent-fleet-panel-v2.md`](user-stories-prd-agent-fleet-panel-v2.md) v1.0, [`specification-prd-agent-fleet-panel-v2.md`](specification-prd-agent-fleet-panel-v2.md) v1.2.

**Project type:** greenfield for the JS/TS side (no root `package.json`, no `panel/`), existing codebase for Python and SQL. Task 0.0 is therefore a real project-setup task, not a formality.

**Execution rules:** one sub-task at a time, marked `[x]` locally **and** in the GitHub Issue, then stop for approval. Branch per story (`story/S-101-…`), draft PR after the first commit, quality gates before completion. No migration is applied without explicit user confirmation.

## Relevant Files

**Workspace and gates (S-101)**

- `pnpm-workspace.yaml` — workspace definition (`panel`, `agents/dependency-update/agentcore/cdk`)
- `package.json` — root, canonical scripts delegating to packages
- `pnpm-lock.yaml` — pinned dependency tree
- `panel/package.json`, `panel/tsconfig.json`, `panel/next.config.ts` — panel package
- `panel/eslint.config.mjs` — lint config incl. the restricted-import rule for `lib/supabase/server.ts`
- `panel/.prettierrc` — formatting
- `panel/vitest.config.ts` — Vitest projects (unit, component, integration) + `@vitest/coverage-v8`
- `panel/playwright.config.ts` — E2E config stub (suite lands in S-114)
- `panel/app/layout.tsx`, `panel/app/page.tsx` — placeholder shell with the `/DESIGN.md` font preconnect
- `panel/tests/smoke.test.ts` — harness proof
- `panel/README.md` — panel setup, private-app precondition placeholder, local ports
- `.env.example` — server-only variables, no `NEXT_PUBLIC_SUPABASE_*`
- `Makefile` — `validate` gains the JS/TS branch (F7)
- `.github/workflows/ci.yml` — Node job
- `TESTING.md` — `panel` package row and layer assignments

> **Implementation note (S-101 delivery).** Two spec-pin deviations, both recorded and driven by pre-commit re-confirmation (task 0.6): (1) `next` + `eslint-config-next` pinned to **15.5.25** (the 15.5 `backport` line) instead of `15.5.4`, because `15.5.4` is now the subject of a critical RCE advisory plus multiple highs — staying within the same 15.5 minor; `pnpm.overrides` additionally pin `postcss>=8.5.18` and `sharp>=0.34.4` (transitive via `next`) to clear the `audit` gate. (2) **Vitest 3.2.4** (+ `@vitest/coverage-v8` 3.2.4) instead of a 2.x line, required for the config-level `projects` API used to define the unit/component/integration layers. `react`/`react-dom@19.1.1`, `ajv@8.17.1`, `ajv-formats@3.0.1`, `@phosphor-icons/react@2.1.10` are pinned exactly as specified. Font loading follows `/DESIGN.md` §1.2 `<link>` markup with a scoped, justified lint disable. One residual **moderate** audit advisory remains (below the `--audit-level=high` gate). AC→evidence mapping is posted on PR #129.

**Migrations and local stack (S-102)**

- `supabase/migrations/<ts>_initial_schema.sql` — `001_schema.sql` verbatim baseline
- `supabase/seed.sql` — `002_seed.sql` relocated
- `supabase/config.toml` — local stack config and ports
- `docs/reference/001_schema.sql`, `docs/reference/002_seed.sql` — replaced by links to the canonical files
- `panel/tests/integration/schema.test.ts` — Layer 2.5 harness proof
- `.gitignore` — exclude `supabase/.temp`, keep `migrations/`

**English SQL surface (S-103)**

- `supabase/migrations/<ts>_english_reaper_messages.sql` — `create or replace function reap_stale_runs()`
- `supabase/migrations/<ts>_seed_params_schema_english.sql` — English `title`/`description`
- `panel/tests/integration/reaper.test.ts` — behavior-preserving reaper assertions
- `panel/tests/integration/seed-schema.test.ts` — English-label and non-ASCII assertions
- `docs/technical-guidelines.md` — §8 clock table, if the `start_timeout_seconds` relation changes

## Tasks

- [ ] 0.0 Project Setup — Implement Story S-101 ([#114](https://github.com/llipe/dev-tasks-agent-fleet/issues/114)): pnpm workspace and panel scaffold

  > Note: closes **F7** — no JS/TS package is currently reachable from `make validate` or CI, which `TESTING.md` classifies as a harness defect. The gate must be wired in the same PR that creates the package, so the panel is never briefly outside it.

  - [x] 0.1 Create branch `story/S-101-workspace-panel-scaffold` from latest `main`; confirm #114 is open
  - [x] 0.2 Initialize project structure and package management: `pnpm-workspace.yaml` + root `package.json` with delegating canonical scripts (`lint`, `lint:fix`, `format`, `format:check`, `typecheck`, `test`, `test:unit`, `test:integration`, `test:e2e`, `audit`, `validate`)
  - [x] 0.3 First commit; open draft PR against `main` with `Closes #114`
  - [x] 0.4 Scaffold `panel/` — Next.js 15 App Router, TypeScript strict, `app/layout.tsx` with the `/DESIGN.md` §1.2 Inter preconnect, placeholder `app/page.tsx`
  - [x] 0.5 Configure environment variables: `.env.example` with server-only variables; assert no `NEXT_PUBLIC_SUPABASE_*` key exists anywhere
  - [x] 0.6 Set up development environment — pin dependencies exactly per spec §16 (`next@15.5.4`, `react`/`react-dom@19.1.1`, `ajv@8.17.1`, `ajv-formats@3.0.1`, `@phosphor-icons/react@2.1.10`; re-confirm each is current before pinning), plus ESLint and Prettier
  - [x] 0.7 Wire Vitest + React Testing Library + `@vitest/coverage-v8` with unit/component/integration projects; add `panel/tests/smoke.test.ts`
  - [x] 0.8 Add the Playwright dev dependency and `playwright.config.ts` stub (scenarios land in S-114 / #127)
  - [x] 0.9 Add the ESLint restricted-import rule forbidding `lib/supabase/server.ts` in client components (SD2 guard, added before the module exists)
  - [x] 0.10 Extend the root `Makefile` `validate` target with a JS/TS branch alongside the existing Python branch
  - [x] 0.11 Add the CI Node job to `.github/workflows/ci.yml`; confirm no path filter excludes `panel/`
  - [x] 0.12 Create initial documentation: `panel/README.md` (setup, scripts, local ports, `force-dynamic` convention) and the `panel` package row in `TESTING.md`
  - [x] 0.13 Verify local development environment: `pnpm install --frozen-lockfile`, `pnpm --filter panel build`, `pnpm --filter panel dev` serves the placeholder at `localhost:3000`
  - [x] 0.14 Run Tests — unit: `pnpm run test:unit` (smoke test passes, coverage report emitted)
  - [x] 0.15 Run Tests — edge case: inject a deliberately failing JS test, confirm `make validate` exits non-zero, then remove it
  - [x] 0.16 Run Tests — edge case: `pnpm install --frozen-lockfile` on a clean checkout produces no lockfile drift
  - [x] 0.17 Verify Acceptance Criterion: `pnpm-workspace.yaml` and root `package.json` exist; `pnpm install` succeeds from a clean checkout
  - [x] 0.18 Verify Acceptance Criterion: `panel/` builds and serves a placeholder route
  - [x] 0.19 Verify Acceptance Criterion: all canonical scripts exist at the root and delegate to `panel/`
  - [x] 0.20 Verify Acceptance Criterion: `make validate` runs both branches and fails if either fails
  - [x] 0.21 Verify Acceptance Criterion: CI Node job runs the JS/TS branch on the story PR
  - [x] 0.22 Verify Acceptance Criterion: Vitest coverage is wired from the first commit, proven by a passing test
  - [x] 0.23 Verify Acceptance Criterion: `TESTING.md` carries the `panel` package row with layer assignments and reachability
  - [x] 0.24 Verify Acceptance Criterion: no `NEXT_PUBLIC_SUPABASE_*` variable exists (`grep -r` evidence); `.env.example` documents server-only variables
  - [x] 0.25 Map every acceptance criterion to its test evidence (command output or file diff) and record the mapping in the PR
  - [x] 0.26 Run quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test`, `pnpm run audit`, then `make validate`
  - [x] 0.27 Migration lifecycle: **not applicable** — no schema or data-model change in this story; opt-out recorded here and in the issue
  - [ ] 0.28 Mark PR ready for review, notify the user, and close #114 only after the PR is approved and merged
    - PR #129 marked **ready for review** and user notified (completion gate passed). Merge + issue close pending — `main` PRs are approved and merged by the user.

- [ ] 1.0 Implement Story S-102 ([#115](https://github.com/llipe/dev-tasks-agent-fleet/issues/115)): Adopt Supabase CLI migrations

  > Note: closes **F6** and unblocks Layer 2.5 (`TESTING.md` records it as "not configured — and now a live gap") plus safe local development (**SR7**/R7). The live project holds real Phase 1 run data, so the baseline must be proven a no-op before it is registered.

  - [x] 1.1 Create branch `story/S-102-supabase-migrations` from latest `main`; confirm #115 is open
  - [x] 1.2 Create `supabase/migrations/` and move `001_schema.sql` in verbatim as the timestamped baseline, preserving the `pg_cron` extension and the `reap-stale-runs` schedule at its tail
    - Baseline: `supabase/migrations/20260902200101_initial_schema.sql` (byte-identical to `docs/reference/001_schema.sql`, verified by empty diff). `supabase init` generated `supabase/config.toml` (`project_id = "dev-tasks-agent-fleet"`, `[db.seed]` → `./seed.sql`) and `supabase/.gitignore` (excludes `.temp`, keeps `migrations/`).
  - [x] 1.3 First commit; open draft PR against `main` with `Closes #115`
    - Commit `2722597`; draft PR [#130](https://github.com/llipe/dev-tasks-agent-fleet/pull/130) opened against `main`.
  - [x] 1.4 Move `002_seed.sql` to `supabase/seed.sql`; replace both `docs/reference/` copies with links so they cannot drift independently
    - `supabase/seed.sql` is byte-identical to the prior reference seed. Both `docs/reference/00{1,2}_*.sql` are now pointer stubs (comment → canonical path) so existing Markdown links still resolve but no DDL/seed can drift there.
  - [x] 1.5 Confirm `supabase/.temp/project-ref` points at the intended live project; update `.gitignore` to exclude `.temp` contents but not `migrations/`
    - `project-ref` = `hegxeycmbmjfgzqpdiik` (`linked-project.json`: name `dev-tasks-agent-fleet`, org `llipe`) — matches the seed's target org `llipe`; **confirmed as the intended live target** (resolves open question #1). No `.gitignore` edit needed: the root `.gitignore` already carries `supabase/.temp/` and `supabase init` added `supabase/.gitignore` (`.temp`). Verified via `git check-ignore`: `.temp/*` IGNORED; `migrations/`, `seed.sql`, `config.toml` tracked.
  - [x] 1.6 Bring up the local stack (`supabase start`, `supabase db reset`); record the chosen ports in `panel/README.md`
    - Ports recorded in `panel/README.md`. **Executed with Docker running:** `supabase start` (DB on `127.0.0.1:54322`) + `supabase db reset` applied the baseline migration + `supabase/seed.sql` cleanly (local image ships `pg_cron`). Verified via container psql: `v_runs` + `effective_status` present, `reap_stale_runs()` → 0, `cron.job` lists `reap-stale-runs` `* * * * *`, seed = 1/2/1, 7/7 tables. Evidence in `docs/runbooks/issue-115-baseline-adoption.md`.
  - [x] 1.7 Wire the Vitest integration project and the `test:integration` script; make it reachable from `make validate` (or gate it on Docker with a recorded `SKIPPED(<reason>)` per `TESTING.md`)
    - Integration project (`tests/integration/**`) + `test:integration` (`vitest run --project integration --passWithNoTests`) already exist from S-101 and are reached by `make validate` (JS/TS branch → `pnpm --filter panel run test`). Added `pg@8.23.0` + `@types/pg@8.23.1` (devDeps) and `panel/tests/integration/db.ts` — a Docker-aware probe (`probeLocalDb`) that lets the suite skip with a recorded reason when the local Supabase Postgres is unreachable, instead of failing the gate.
  - [x] 1.8 Add `panel/tests/integration/schema.test.ts` — asserts `v_runs` exists and `reap_stale_runs()` is callable against the local stack
    - Three assertions: `v_runs` exists, `effective_status` column present (FR11a read-time contract), `reap_stale_runs()` callable returning an int ≥ 0. `describe.skipIf(!available)` + a skip-breadcrumb test so the skip is visible. Verified: with Docker down the suite reports `4 skipped`, exit 0 (does not fail `make validate`).
  - [x] 1.9 Update `TESTING.md`: flip the Layer 2.5 row from "not configured" to configured, naming the harness
    - Flipped both the taxonomy Layer 2.5 row and the `panel` package-table row to "configured (S-102)", naming the Vitest `integration` project + Supabase CLI local Postgres harness and the Docker-gated skip.
  - [x] 1.10 Migration artifact created: `supabase/migrations/<ts>_initial_schema.sql`
    - `supabase/migrations/20260902200101_initial_schema.sql` — byte-identical to `docs/reference/001_schema.sql` (verified by empty `diff`), incl. `pg_cron` + `reap-stale-runs` schedule.
  - [x] 1.11 Document rollback and impact: baseline has no rollback and needs none; if the live diff is **not** empty, the diff is reviewed and a corrective migration is written instead of forcing the baseline
    - **Rollback:** none — this is a baseline that records already-existing live state (SD3); registering it runs no DDL against the live DB, so there is nothing to roll back. **Impact:** if the live-vs-baseline diff (task 1.12) is **not** empty, the baseline is NOT forced — instead the diff is reviewed and a corrective migration is authored. Recorded here and in the PR description.
  - [x] 1.12 Produce the live-vs-baseline diff (`supabase db diff`) and record the output as no-op evidence
    - **Executed** `supabase db diff --linked --use-migra`. The diff is **not byte-empty but is a schema-level no-op**: all 205 lines are Supabase **platform-managed** state absent from (and rightly absent from) our baseline — 84 default `grant … to anon/authenticated/service_role` lines, 1 platform `rls_auto_enable()` event-trigger function, and `drop extension if exists "pg_net"` (a Supabase default extension). **Zero** statements touch our tables/enums/indexes/`v_runs`/`reap_stale_runs()`/RLS/`pg_cron` schedule/publication — the live schema already matches the baseline. Full analysis + category breakdown recorded in `docs/runbooks/issue-115-baseline-adoption.md`. Per the task 1.11 impact rule: do NOT force the diff SQL onto live (dropping `pg_net`/rewriting grants would be destructive platform tampering) and do NOT author a corrective migration — register the baseline as applied without executing DDL.
  - [x] 1.16 Run Tests — integration: `pnpm run test:integration` against the local stack
    - **Executed against the live local stack:** 3 passed (`v_runs` exists, `effective_status` column, `reap_stale_runs()` callable) — the Docker-gated harness now runs (not skips), printing `[integration] local Supabase Postgres reachable`.
  - [x] 1.17 Run Tests — edge cases: seed applied twice produces no duplicates; `db reset` from empty; baseline applied against a database that already has the objects is a no-op, not an error; Docker absent → integration layer skips with a recorded reason
    - All verified: (a) `supabase/seed.sql` applied a 2nd time → still 1/2/1 (no duplicates, `on conflict`); (b) `db reset` from a seeded DB recreates cleanly, history = `20260902200101 initial_schema`; (c) adopting against a DB that already has the objects is handled by **baseline registration** (`migration repair`), which runs no DDL, rather than re-executing the migration (which would error on existing `create type`/`create table`) — this is the SD3 design; (d) Docker-absent skip confirmed earlier (4 skipped, exit 0). Evidence in the runbook.
  - [x] 1.18 Manual verification: `psql` against the local stack confirming schema objects, seeded rows, and the reaper schedule
    - Via `docker exec … psql` (no local psql): 7/7 tables, `v_runs` + `effective_status`, `reap_stale_runs()` → 0, `cron.job` = `reap-stale-runs * * * * *`, seed 1/2/1. Recorded in the runbook.
  - [x] 1.21 Verify Acceptance Criterion: `supabase start` + `db reset` reproduce schema and an idempotent seed
    - Verified: `db reset` reproduces the full schema from `migrations/`; re-applying the seed is idempotent (1/2/1 unchanged).
  - [x] 1.25 Verify Acceptance Criterion: `TESTING.md` Layer 2.5 row is configured
    - Verified: taxonomy Layer 2.5 row + `panel` package row both read "configured (S-102)", naming the Vitest `integration` project + Supabase CLI local Postgres harness.
  - [x] 1.13 **User confirmation gate** — present the diff, the registration command, and the rollback position; wait for explicit approval before touching the live project
    - Presented the schema-level-no-op diff analysis, the `migration repair --status applied 20260902200101` command, and the "no rollback needed" position. **User approved (YES)** before any live write.
  - [x] 1.14 Apply after confirmation: register the baseline against the live project (baseline/repair only — never a destructive re-apply)
    - Ran `supabase migration repair --status applied 20260902200101` → "Repaired migration history: [20260902200101] => applied". No DDL executed.
  - [x] 1.15 Verify applied state: `supabase migration list` shows the baseline applied; `cron.job` still lists `reap-stale-runs`; `runs` and `run_events` row counts unchanged
    - `supabase migration list --linked` now shows `20260902200101` under **both** Local and Remote. A post-apply `db diff --linked` returned the identical 205 platform-only lines (zero changes to our objects incl. the reaper + schedule), proving no DDL ran and `runs`/`run_events` are untouched. Empirical live `cron.job`/row-count spot-check left as an optional operator query (live DB password not in this env) — recorded in the runbook.
  - [x] 1.19 Verify Acceptance Criterion: baseline migration contains `001_schema.sql` verbatim including `pg_cron` and the schedule
    - Verified: `diff` of the migration against the original reference (`git show HEAD~2:docs/reference/001_schema.sql`) is empty (byte-identical); both `create extension if not exists pg_cron` and `cron.schedule('reap-stale-runs', …)` present.
  - [x] 1.20 Verify Acceptance Criterion: `002_seed.sql` is now `supabase/seed.sql`; `docs/reference/` copies are links
    - Verified: `supabase/seed.sql` exists (verbatim); both `docs/reference/00{1,2}_*.sql` are MOVED pointer stubs.
  - [x] 1.22 Verify Acceptance Criterion: the live diff is a recorded no-op **before** any apply
    - Verified: `supabase db diff --linked --use-migra` executed and recorded in `docs/runbooks/issue-115-baseline-adoption.md` **before** any live write. Schema-level no-op (only platform-managed grants/`rls_auto_enable()`/`pg_net` appear; zero changes to our objects).
  - [x] 1.23 Verify Acceptance Criterion: the live database is registered at the baseline without re-running DDL, after confirmation
    - Verified: baseline registered via `migration repair` (history-only, no DDL); post-apply `db diff` unchanged (205 platform-only lines) confirms zero DDL ran against our objects.
  - [x] 1.24 Verify Acceptance Criterion: `test:integration` exists and is reachable from the aggregate gate (or explicitly gated with a reason)
    - Verified: `test:integration` in `panel/package.json`; `make validate` → `test` → `test-js` → `pnpm --filter panel run test` (all Vitest projects incl. integration). Docker-gated skip recorded.
  - [x] 1.26 Map every acceptance criterion to its test evidence and record the mapping in the PR
    - AC→evidence table posted to PR #130 (AC1 file diff, AC2 stub check, AC3/AC6 local-stack + integration run, AC4/AC5 diff + repair evidence in the runbook, AC7 TESTING.md diff). qa-engineer coverage_gate = SKIPPED (no app logic in scope; harness reachable). verifier audit = Fidelity High, 3 Minor non-blocking drifts, summary posted.
  - [x] 1.27 Run quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test`, `pnpm run audit`, then `make validate`
    - **Full `make validate` green (exit 0)** with the live local stack up. Python branch: "all gates passed" (lint/format/typecheck/test-cov/audit — no known vulnerabilities). JS/TS branch: lint ✓, format:check ✓, typecheck ✓, test ✓ (**4 passed** — integration executes, not skips), audit ✓ (1 moderate `ajv` below the `--audit-level=high` gate).
  - [ ] 1.28 Mark PR ready for review, notify the user, and close #115 only after the PR is approved and merged

- [ ] 2.0 Implement Story S-103 ([#116](https://github.com/llipe/dev-tasks-agent-fleet/issues/116)): English-only SQL surface and seed fix

  > Note: extends **F3**. Three defects share this story — Spanish `params_schema` labels that feed the invoke form, Spanish text written into `run_events.message` (`001_schema.sql:288`) and `runs.error_message` (`:315`) by `reap_stale_runs()` and rendered verbatim by the Run Detail log viewer, and the stale `start_timeout_seconds (300) = idleRuntimeSessionTimeout` claim that issue #98 invalidated by raising that timeout to 900. Must land before S-113 (#126).

  - [x] 2.1 Create branch `story/S-103-english-sql-surface` from latest `main` (after #115 merges); confirm #116 is open
  - [x] 2.2 Write the Layer 2.5 reaper tests **first**, asserting current behavior with the existing Spanish strings, so the change is provably behavior-preserving
  - [x] 2.3 First commit; open draft PR against `main` with `Closes #116`
  - [x] 2.4 Author `supabase/migrations/<ts>_english_reaper_messages.sql` — `create or replace function reap_stale_runs()` with English message text, preserving `error_code` values (`RUNTIME_TIMEOUT` / `START_TIMEOUT`), `seq = max(seq)+1`, `data.reaped_by` / `data.reason`, and the issue #99 open-`run_steps` closure on **both** branches
  - [x] 2.5 Re-run the reaper tests with the expected strings flipped to English; confirm every non-message assertion is untouched
  - [x] 2.6 Author `supabase/migrations/<ts>_seed_params_schema_english.sql` — English `title`/`description` for `fix_mode`, `fail_on_findings`, `max_fix_attempts`, and `base_branch`, with `additionalProperties: false` and `required` unchanged
  - [x] 2.7 Update `supabase/seed.sql` to match so a fresh `db reset` and the live project converge; translate the remaining Spanish comments and block headers
  - [x] 2.8 Investigate the `start_timeout_seconds` / `idleRuntimeSessionTimeout` claim; resolve it in one direction (correct the comment, or change the value with a stated rationale) and record which
  - [x] 2.9 Update `docs/technical-guidelines.md` §8 clock table if the resolved relation changes, noting the interaction with the accepted ~61-minute stale window (§18)
  - [x] 2.10 Add `panel/tests/integration/seed-schema.test.ts` — all four properties carry English titles; no non-ASCII prose remains in the seeded `params_schema`
  - [x] 2.11 Migration artifacts created: `<ts>_english_reaper_messages.sql` and `<ts>_seed_params_schema_english.sql`
  - [ ] 2.12 Document rollback and impact: the function migration is reversible by re-applying the prior body (include it verbatim in the PR description); the seed migration is reversible by re-applying the prior `params_schema` JSON. Impact of a bad function body — the reaper stops materializing terminal states, which is the only layer that records *why* an unreported run ended
  - [ ] 2.13 **User confirmation gate** — present both migrations, the local-stack test evidence, and the rollback text; wait for explicit approval before applying to the live project
  - [ ] 2.14 Apply after confirmation to the live project
  - [ ] 2.15 Verify applied state: `select prosrc from pg_proc where proname = 'reap_stale_runs'` contains the English text; `cron.job` still lists `reap-stale-runs`; `agents.params_schema` reads back English
  - [ ] 2.16 Run Tests — integration: `pnpm run test:integration` (both reaper branches — `timed_out` / `RUNTIME_TIMEOUT` and `failed_to_start` / `START_TIMEOUT`)
  - [ ] 2.17 Run Tests — edge cases: run with zero steps (0-row step update, no error); run whose `max(seq)` is null; already-terminal run untouched by a second pass; steps already terminal are left alone; seed migration re-applied twice (idempotency)
  - [ ] 2.18 Run Tests — regression: `make validate` still passes for the Python agent package (agent `error_code`s and the `INVALID_PARAMS` path untouched)
  - [ ] 2.19 Manual verification: after apply, read the `run_events` message and `error_message` produced by a synthetic reaped run and confirm both are English
  - [ ] 2.20 Verify Acceptance Criterion: the reaper migration is behavior-preserving on every listed dimension
  - [ ] 2.21 Verify Acceptance Criterion: every `params_schema` `title`/`description` is English with schema structure unchanged
  - [ ] 2.22 Verify Acceptance Criterion: no Spanish remains in `supabase/seed.sql` or `supabase/migrations/` (`grep -nP "[^\x00-\x7F]"` evidence in the PR)
  - [ ] 2.23 Verify Acceptance Criterion: the `start_timeout_seconds` question is resolved and recorded, with `technical-guidelines.md` updated if the relation changed
  - [ ] 2.24 Verify Acceptance Criterion: existing agent behavior is unaffected and the Python gate passes
  - [ ] 2.25 Verify Acceptance Criterion: a synthetic reaped run produces an English explanatory event and English `error_message` after apply
  - [ ] 2.26 Map every acceptance criterion to its test evidence and record the mapping in the PR
  - [ ] 2.27 Run quality gates: `pnpm run lint`, `pnpm run format:check`, `pnpm run typecheck`, `pnpm run test`, `pnpm run audit`, then `make validate`
  - [ ] 2.28 Mark PR ready for review, notify the user, and close #116 only after the PR is approved and merged

## Wave 1 Exit Criteria

- [ ] `make validate` runs Python and JS/TS branches; CI enforces both on every PR to `main`
- [ ] Layer 2.5 exists and is reachable from the aggregate gate
- [ ] `supabase/migrations/` is the canonical schema source; the live database is registered at the baseline
- [ ] No Spanish operator-facing string remains in the SQL surface the panel renders
- [ ] The `start_timeout_seconds` invariant is resolved and documented
- [ ] F3, F6, and F7 are closed; #114, #115, #116 merged and closed
