# User Stories — Agent Fleet Control Panel, Phase 2

## Changelog

| Version | Date       | Summary         | Author             |
| ------- | ---------- | --------------- | ------------------ |
| 1.0     | 2026-09-02 | Initial version. Fifteen stories (S-101–S-115) derived from [`specification-prd-agent-fleet-panel-v2.md`](specification-prd-agent-fleet-panel-v2.md) v1.1 and PRD v2.4 Phase 2 scope (FR10–FR18, AC6–AC14). Adds **S-103** — English-only SQL surface — which extends spec F3 beyond `params_schema` labels to the Spanish `run_events.message` / `error_message` text emitted by `reap_stale_runs()` and the stale `start_timeout_seconds` invariant comment in the seed. | product-engineer |
| 1.1     | 2026-09-03 | Wave 2 write-back pass, companion to spec v1.4. One correction, no scope change: **S-103 AC-3 rescoped to the *effective* SQL surface.** The delivered story translated `supabase/seed.sql` and shipped two forward migrations, but left the Spanish string literals inside the already-applied `20260902200101_initial_schema.sql` baseline in place — a user-approved exception the S-103 audit flagged as drift against the AC's literal "no Spanish remains in … the migrations directory" wording. The intent (no Spanish in what the database executes or the panel renders) was fully met; the wording was stricter than the agreed reality. AC-3 now states the exemption explicitly and requires `grep` evidence scoped to the effective surface, so a future literal-grep audit does not re-flag a corrected-forward baseline as a defect. | product-engineer |

> **Source documents.** PRD [`docs/requirements/prd-agent-fleet-panel-v2.md`](../docs/requirements/prd-agent-fleet-panel-v2.md) v2.4 (§7 FR10–FR18, §8 D1–D17, §10 Non-Goals, §13 AC6–AC14, §19 F1–F7) · Spec [`specification-prd-agent-fleet-panel-v2.md`](specification-prd-agent-fleet-panel-v2.md) v1.1 (SD1–SD12) · [`/DESIGN.md`](../DESIGN.md) v1.0 (visual contract) · [`TESTING.md`](../TESTING.md) (layer taxonomy, reachability) · [`docs/technical-guidelines.md`](../docs/technical-guidelines.md) v1.10.

---

## Scope Delta vs. Specification v1.1

Two deltas the reader must know about, both recorded here rather than silently absorbed:

1. **S-103 extends F3.** Spec §5 states "no schema changes" and scopes F3 to the seed's `params_schema` labels. Review of `docs/reference/001_schema.sql` found Spanish operator-facing text **inside the DDL**: line 288 writes `'El sistema marcó esta ejecución como timed_out: el agente nunca reportó término.'` into `run_events.message`, and line 315 writes `'El agente no reportó inicio tras %s s.'` into `runs.error_message`. Both are rendered verbatim by the Phase 2 Run Detail log viewer (S-109), so the panel would ship a Spanish UI string it does not own. Fixing them is a `create or replace function` migration — a real, reversible DDL change that S-103 carries under the migration-confirmation gate.
2. **A stale invariant in the seed.** `002_seed.sql:48` asserts `start_timeout_seconds (300) DEBE coincidir con idleRuntimeSessionTimeout`. Issue #98 raised `idleRuntimeSessionTimeout` to **900** (`agentcore/agentcore.json`), so either the stated invariant is wrong — likely, since `start_timeout_seconds` is a queue clock (`queued_at`-based, D9) and `idleRuntimeSessionTimeout` is an output-idle clock — or the seeded value is stale and a slow cold start can be reaped as `failed_to_start`. S-103 resolves it in one direction and records which.

Spec v1.1 §17 **Open Question 3** is answered without a probe and folded into S-112's business rules: `001_schema.sql:131` declares `runs.max_runtime_seconds integer not null` with **no default**, while `grace_seconds` and `start_timeout_seconds` are `not null default 60 / 300`. A panel insert omitting the first fails loudly at the database; the other two would silently take defaults, so the panel must still send all three explicitly.

---

## Conventions Applying to Every Story

- **Package manager:** `pnpm` (workspace root). `npm` only where a package is npm-locked (`agents/dependency-update/agentcore/cdk`).
- **Canonical scripts** (per `docs/technical-guidelines.md` §12): `lint`, `lint:fix`, `format`, `format:check`, `typecheck`, `test`, `test:unit`, `test:integration`, `test:e2e`, `audit`, `validate`.
- **Aggregate gate:** `make validate` at the repo root must run both the Python agent branch and the new JS/TS branch (F7). A test package unreachable from the aggregate gate is a harness defect by `TESTING.md`'s own definition.
- **Test-first:** every story's tests are written before or alongside its implementation, per the repository default. `verifier` Design Mode runs on the selected stories before `developer` starts.
- **Design contract:** `/DESIGN.md` is normative for every UI story. Tokens only — no hardcoded hex, font, or pixel values.
- **Branching:** `story/S-1xx-<short-description>`; Conventional Commits; PRs use `--body-file`; no agent pushes or merges to `main`.
- **Migrations:** no migration is applied autonomously. Every apply step is gated on explicit human confirmation (spec SD3).

---

## Story Index

| ID | Title | Priority | Size | Depends on |
|---|---|---|---|---|
| S-101 | pnpm workspace, Next.js panel scaffold, and gate reachability | Critical | M | — |
| S-102 | Adopt Supabase CLI migrations and a local database stack | Critical | M | — |
| S-103 | English-only SQL surface and seed correctness | Critical | S | S-102 |
| S-104 | Server-side data access layer and `effectiveStatus` parity | Critical | M | S-101, S-102 |
| S-105 | Design token layer, Nocturne primitives, and data formatters | Critical | L | S-101 |
| S-106 | App shell — sidebar, top bar, collapse persistence | High | S | S-105 |
| S-107 | Agents Dashboard with three-variant density toggle | High | M | S-104, S-105, S-106 |
| S-108 | Agent Run History | High | M | S-104, S-106 |
| S-109 | Run Detail — summary, artifacts, bounded log viewer | High | L | S-104, S-105, S-106 |
| S-110 | SSE relay and live log tail | High | M | S-109 |
| S-111 | AWS credential provider — Fly OIDC and local chain | Critical | M | S-101 |
| S-112 | Invoke route handler and agent payload translation (closes #89) | Critical | L | S-104, S-111, S-103 |
| S-113 | Schema-driven invoke form | High | M | S-105, S-112 |
| S-114 | Playwright E2E against the local stack | Medium | M | S-110, S-113 |
| S-115 | Fly deployment, privacy release gate, and OIDC probe | High | M | S-114 |

---

### Story S-101: pnpm workspace, Next.js panel scaffold, and gate reachability

**Priority:** Critical
**Estimated Size:** M
**Dependencies:** None

#### User Story

As the fleet operator,
I want the panel to exist as a workspace package wired into the repository's quality gate,
So that every subsequent Phase 2 story is verified by the same `make validate` the agent already passes.

#### Context

The repo has no root `package.json` and no `pnpm-workspace.yaml`; the only JS/TS package is the CDK app, which is jest-with-no-coverage and an explicitly weak precedent (SD12). This story creates the container everything else lands in and closes **F7** on day one, so the panel is never briefly outside the gate.

#### Acceptance Criteria

- [ ] `pnpm-workspace.yaml` and a root `package.json` exist; `pnpm install` succeeds from a clean checkout.
- [ ] `panel/` is a Next.js 15 App Router + TypeScript package that builds (`pnpm --filter panel build`) and serves a placeholder route.
- [ ] Canonical scripts `lint`, `lint:fix`, `format`, `format:check`, `typecheck`, `test`, `test:unit`, `test:integration`, `test:e2e`, `audit`, `validate` exist at the root and delegate to `panel/`.
- [ ] `make validate` at the repo root runs both the Python agent branch and the JS/TS branch, and fails if either fails.
- [ ] `.github/workflows/ci.yml` gains a Node job running the JS/TS branch on every push/PR to `main`.
- [ ] Vitest runs with `@vitest/coverage-v8` wired from the first commit; one trivial passing test proves the harness.
- [ ] `TESTING.md` gains a `panel` package row with its layer assignments and reachability status.
- [ ] No `NEXT_PUBLIC_SUPABASE_*` variable exists anywhere; `.env.example` documents server-only variables.

#### Business Rules

- SD1 — the panel lives at `panel/`, not the repo root, so `pnpm --filter` can scope commands and the root stays neutral between Python and TypeScript.
- SD12 — Vitest + React Testing Library for Layers 1–2.5, Playwright for E2E. Do not follow the CDK app's jest precedent.
- Dependencies pinned exactly (`technical-guidelines.md` §16). All four `@aws-sdk/*` packages pinned to the same minor.

#### Technical Notes

- Baseline versions from spec §16, to be re-confirmed current at implementation: `next@15.5.4`, `react`/`react-dom@19.1.1`, `@supabase/supabase-js@2.58.0`, `ajv@8.17.1`, `ajv-formats@3.0.1`, `@phosphor-icons/react@2.1.10`. AWS SDK packages pinned at implementation time, same minor.
- An ESLint rule must forbid importing `lib/supabase/server.ts` from a client component (SD2). Add the rule now even though the module arrives in S-104, so the guard predates the risk.
- `export const dynamic = "force-dynamic"` is required on run routes (spec §11); establish the convention here.

#### Testing Requirements

- **Unit Tests:** one smoke test asserting the Vitest + coverage harness runs.
- **Integration Tests:** none (no data layer yet).
- **Manual/UI Testing:** `pnpm --filter panel dev` serves the placeholder at `http://localhost:3000`.
- **Edge-Case Matrix:** `make validate` fails when the JS branch fails (inject a temporary failing test and confirm non-zero exit, then remove); clean-checkout `pnpm install` with no lockfile drift (`--frozen-lockfile`).
- **Acceptance-Criteria Mapping:** AC1–AC3 → `pnpm install && pnpm run validate`; AC4 → `make validate` exit-code check; AC5 → CI run on the story PR; AC6 → coverage report emitted; AC7 → `TESTING.md` diff; AC8 → `grep -r "NEXT_PUBLIC_SUPABASE" .` returns nothing.
- **Execution Commands:** `pnpm install`, `pnpm run validate`, `make validate`.

#### Implementation Steps

1. Add `pnpm-workspace.yaml` (`panel`, `agents/dependency-update/agentcore/cdk`) and a root `package.json` with delegating scripts.
2. Scaffold `panel/` (Next.js 15 App Router, TypeScript strict, ESLint, Prettier) with the `/DESIGN.md` font preconnect in `app/layout.tsx`.
3. Wire Vitest + RTL + `@vitest/coverage-v8`; add the smoke test.
4. Add the Playwright dev dependency and config stub (suite lands in S-114).
5. Extend the root `Makefile` `validate` target with the JS/TS branch.
6. Add the CI Node job; confirm path gating does not skip `panel/`.
7. Add the ESLint restricted-import rule for `lib/supabase/server.ts`.
8. Update `TESTING.md` with the `panel` package row; add `.env.example` and `panel/README.md`.

#### Files to Create/Modify

- `pnpm-workspace.yaml`, `package.json`, `pnpm-lock.yaml` — workspace root
- `panel/package.json`, `panel/tsconfig.json`, `panel/next.config.ts`, `panel/eslint.config.mjs`, `panel/.prettierrc`
- `panel/vitest.config.ts`, `panel/playwright.config.ts`, `panel/tests/smoke.test.ts`
- `panel/app/layout.tsx`, `panel/app/page.tsx` — placeholder shell
- `panel/README.md`, `.env.example`
- `Makefile`, `.github/workflows/ci.yml`, `TESTING.md`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] Migration lifecycle complete — N/A, no schema change (documented opt-out)
- [ ] Pull Request created and merged

---

### Story S-102: Adopt Supabase CLI migrations and a local database stack

**Priority:** Critical
**Estimated Size:** M
**Dependencies:** None (may run in parallel with S-101)

#### User Story

As the fleet operator,
I want the schema and seed to be Supabase CLI migrations instead of reference documents,
So that the live database has a migration history and Layer 2.5 tests can run against a real local Postgres.

#### Context

Resolves **F6** and unblocks two things that are currently impossible: a repeatable database test layer (`TESTING.md` records Layer 2.5 as "not configured — and now a live gap") and safe local development that does not write to the production Supabase (**SR7**/R7). The live project already holds real Phase 1 run data, so the baseline migration must be proven a no-op before it is applied.

#### Acceptance Criteria

- [ ] `supabase/migrations/<ts>_initial_schema.sql` contains `001_schema.sql` verbatim, including the `pg_cron` extension and the `reap-stale-runs` schedule.
- [ ] `002_seed.sql` becomes `supabase/seed.sql`; both `docs/reference/` copies are replaced by links to the new canonical files so they cannot drift.
- [ ] `supabase start` + `supabase db reset` brings up a local stack whose schema matches the migration and whose seed applies idempotently.
- [ ] `supabase db diff` (or equivalent) against the live project shows the baseline migration is a **no-op**, and that evidence is recorded before any apply.
- [ ] `supabase migration repair`/baseline registration marks the live database as at the baseline without re-running DDL, after explicit user confirmation.
- [ ] A `test:integration` script exists that runs Vitest Layer 2.5 tests against the local stack, reachable from `make validate` (may be skipped with a recorded reason when Docker is unavailable, per `TESTING.md`).
- [ ] `TESTING.md` Layer 2.5 row flips from "not configured" to configured, naming the harness.

#### Business Rules

- SD3 — migrations are adopted, not rewritten. The baseline is a record of existing state, not a re-apply.
- **Migration apply is gated on explicit user confirmation.** No autonomous apply against the live project.
- The reaper schedule (`cron.schedule('reap-stale-runs', ...)`) must remain registered after adoption — verify `cron.job` still lists it (issue #94 / ADR-004).

#### Technical Notes

- `supabase/.temp/` already holds a linked-project ref; confirm it points at the intended project and that `.gitignore` excludes `.temp` contents but not `migrations/`.
- Local stack ports must not collide with anything the operator runs; record the chosen ports in `panel/README.md`.
- The baseline migration is the one migration with **no rollback** and needs none.

#### Testing Requirements

- **Unit Tests:** none.
- **Integration Tests:** Layer 2.5 harness proof — one test asserting `v_runs` exists and `reap_stale_runs()` is callable against the local stack.
- **Manual/UI Testing:** `supabase start`, `supabase db reset`, then `psql` verification of `cron.job` and table counts.
- **Edge-Case Matrix:** seed re-applied twice produces no duplicates (`on conflict` paths); `db reset` from empty; migration applied against a database that already has the objects (must be a no-op, not an error); Docker absent → integration layer skips with a recorded reason rather than failing silently.
- **Acceptance-Criteria Mapping:** AC1–AC2 → file diff review; AC3, AC6 → `pnpm run test:integration`; AC4–AC5 → recorded `db diff` output + confirmation transcript in the PR; AC7 → `TESTING.md` diff.
- **Execution Commands:** `supabase start`, `supabase db reset`, `pnpm run test:integration`, `make validate`.

#### Migration Requirements

- **Migration artifact:** `supabase/migrations/<ts>_initial_schema.sql` — required.
- **Rollback/impact notes:** baseline only; expected no-op against live. Impact if it is *not* a no-op: the diff must be reviewed and a corrective migration written instead of forcing the baseline.
- **Apply step:** requires explicit user confirmation. Baseline registration only — never a destructive re-apply.
- **Verification after apply:** `supabase migration list` shows the baseline as applied; `cron.job` still lists `reap-stale-runs`; row counts on `runs`/`run_events` unchanged.

#### Implementation Steps

1. Create `supabase/migrations/` and move `001_schema.sql` in verbatim as the timestamped baseline.
2. Move `002_seed.sql` to `supabase/seed.sql`; replace `docs/reference/` copies with links.
3. Bring up the local stack; confirm `db reset` reproduces schema + seed.
4. Produce and record the live-vs-baseline diff; present it for confirmation.
5. After confirmation, register the baseline against the live project; verify the reaper schedule survived.
6. Wire the Vitest integration project and `test:integration` script; add the harness-proof test.
7. Update `Makefile`, `TESTING.md`, and `panel/README.md`.

#### Files to Create/Modify

- `supabase/migrations/<ts>_initial_schema.sql`, `supabase/seed.sql`, `supabase/config.toml`
- `docs/reference/001_schema.sql`, `docs/reference/002_seed.sql` — replaced by links
- `panel/vitest.config.ts` (integration project), `panel/tests/integration/schema.test.ts`
- `Makefile`, `TESTING.md`, `panel/README.md`, `.gitignore`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] Migration lifecycle complete — artifact, rollback notes, confirmation, apply, verification
- [ ] Pull Request created and merged

---

### Story S-103: English-only SQL surface and seed correctness

**Priority:** Critical
**Estimated Size:** S
**Dependencies:** S-102

#### User Story

As the fleet operator,
I want every operator-facing string the database writes or the panel renders to be English and every seeded timeout comment to be true,
So that the panel does not ship Spanish UI text it does not own and the invoke form is not built against labels that will change.

#### Context

Extends **F3**. Three distinct defects share one migration:

1. `params_schema` `title`/`description` values in the seed are Spanish and feed the schema-driven invoke form directly (S-113). Building the form first means rebuilding it — spec §15 makes F3 an ordering constraint.
2. `reap_stale_runs()` writes Spanish text into `run_events.message` (`001_schema.sql:288`) and `runs.error_message` (`:315`). The Run Detail log viewer (S-109) renders both verbatim. This violates the repository's English-only output rule inside shipped DDL.
3. `002_seed.sql:48` claims `start_timeout_seconds (300)` must equal `idleRuntimeSessionTimeout`, which #98 changed to 900. The invariant as stated is almost certainly wrong — `start_timeout_seconds` is a `queued_at` clock (D9) and `idleRuntimeSessionTimeout` is an output-idle clock — but it must be resolved deliberately, because if the value is instead stale, a slow cold start gets reaped as `failed_to_start`.

#### Acceptance Criteria

- [ ] A migration replaces `reap_stale_runs()` via `create or replace function` with English `run_events.message` and `runs.error_message` text, preserving every existing behavior: `error_code` values (`RUNTIME_TIMEOUT` / `START_TIMEOUT`), `seq = max(seq)+1` assignment, `data.reaped_by` / `data.reason`, and the issue #99 open-`run_steps` closure on **both** branches.
- [ ] A migration updates the seeded `params_schema` so every `title` and `description` is English, covering `fix_mode`, `fail_on_findings`, `max_fix_attempts`, and `base_branch`; `additionalProperties: false` and the `required` list are unchanged.
- [ ] The seed's Spanish comments and block headers are translated. **No Spanish remains in the *effective* SQL surface** — that is, in what `supabase db reset` applies and what the live database executes: `supabase/seed.sql` and every forward migration. String literals inside the already-applied `20260902200101_initial_schema.sql` baseline are **exempt**, because a baseline registered against a live database is a historical record and is corrected *forward* by a later `create or replace function` migration, not edited in place. `grep` evidence in the PR must scope to the effective surface, so a future literal-grep audit does not re-flag the baseline as a defect.
- [ ] The `start_timeout_seconds` question is resolved one way and recorded: either the comment is corrected (invariant was wrong) or the value is changed with a stated rationale. `docs/technical-guidelines.md` §8's clock table is updated if the relation changes.
- [ ] Existing agent behavior is unaffected: the agent's own `error_code`s and `INVALID_PARAMS` path are untouched, and `make validate` still passes for the Python package.
- [ ] After apply, a synthetic reaped run produces an English explanatory event and an English `error_message`.

#### Business Rules

- English-only output is a repository rule; it applies to strings written by SQL, not only to code comments and docs.
- The reaper's observable contract must not change. This is a text-only change plus, if chosen, one integer.
- Idempotent `on conflict` update for the seed — rollback is re-applying the prior `params_schema` JSON.

#### Technical Notes

- `run_events.message` is truncated at 8 KB; English replacements stay far below.
- The function body is the only DDL touched. No enum, table, index, or RLS change.
- The `data.reason` JSON key names stay as-is — they are machine-read, not operator-facing prose.
- If the value (not the comment) changes, note the interaction with the accepted ~61-minute stale window documented in `technical-guidelines.md` §18.

#### Testing Requirements

- **Unit Tests:** none in the panel (no TS code).
- **Integration Tests (Layer 2.5, the primary evidence):** against the local stack — insert a `running` run past `started_at + max_runtime + grace`, call `reap_stale_runs()`, assert `status = 'timed_out'`, `error_code = 'RUNTIME_TIMEOUT'`, the event message is the English string, `seq = max(seq)+1`, and any open `run_steps` closed as `failed`. Same for a stale `queued` run → `failed_to_start` / `START_TIMEOUT`. Assert the seeded `params_schema` has no non-ASCII prose and that all four properties carry English titles.
- **Manual/UI Testing:** after apply, query the live `run_events` row produced by the next real reap (or a deliberate synthetic one) and read the message.
- **Edge-Case Matrix:** run with zero steps (0-row step update, no error); run whose `max(seq)` is null (first event); already-terminal run untouched by a second reaper pass; re-running the seed migration twice (idempotency); a run whose steps are already terminal (left alone).
- **Acceptance-Criteria Mapping:** AC1, AC6 → `pnpm run test:integration` reaper cases; AC2–AC3 → integration assertion + a non-ASCII scan scoped to the effective surface (`supabase/seed.sql` plus forward migrations, excluding the already-applied baseline per AC-3); AC4 → doc diff + PR rationale; AC5 → `make validate` Python branch.
- **Execution Commands:** `supabase db reset`, `pnpm run test:integration`, `make validate`.

#### Migration Requirements

- **Migration artifact:** `supabase/migrations/<ts>_english_reaper_messages.sql` (function replacement) and `<ts>_seed_params_schema_english.sql` (seed correction) — both required.
- **Rollback/impact notes:** the function migration is reversible by re-applying the prior body (keep it in the PR description). The seed migration is reversible by re-applying the prior `params_schema` JSON. Impact of a bad function body: the reaper stops materializing terminal states — the layer that writes the *only* record of why an unreported run ended. Verify on the local stack before touching live.
- **Apply step:** requires explicit user confirmation, live project.
- **Verification after apply:** `select prosrc from pg_proc where proname = 'reap_stale_runs'` contains the English text; `cron.job` still lists `reap-stale-runs`; a synthetic reap writes English; `agents.params_schema` reads back English.

#### Implementation Steps

1. Write the local-stack Layer 2.5 reaper tests **first**, asserting current behavior with the Spanish strings so the refactor is provably behavior-preserving.
2. Author the `create or replace function` migration with English message text; re-run the tests with the expected strings flipped.
3. Author the seed `params_schema` English migration; update `supabase/seed.sql` to match so a fresh `db reset` and the live project converge.
4. Translate remaining Spanish comments and headers in `supabase/seed.sql`.
5. Investigate and resolve the `start_timeout_seconds` / `idleRuntimeSessionTimeout` claim; update the seed comment (and value, if that is the resolution) plus `technical-guidelines.md` §8.
6. Present the migration pair, diff, and rollback text for confirmation; apply after confirmation; verify.

#### Files to Create/Modify

- `supabase/migrations/<ts>_english_reaper_messages.sql`, `supabase/migrations/<ts>_seed_params_schema_english.sql`
- `supabase/seed.sql`
- `panel/tests/integration/reaper.test.ts`, `panel/tests/integration/seed-schema.test.ts`
- `docs/technical-guidelines.md` (§8 clock table, if the relation changes), `docs/reference/001_schema.sql` link target

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] Migration lifecycle complete — artifacts, rollback notes, confirmation, apply, verification
- [ ] Pull Request created and merged

---

### Story S-104: Server-side data access layer and `effectiveStatus` parity

**Priority:** Critical
**Estimated Size:** M
**Dependencies:** S-101, S-102

#### User Story

As the fleet operator,
I want every database read to happen server-side with a single shared status derivation,
So that no credential reaches the browser and the UI never shows a run as `running` when its timeout has already passed.

#### Context

Resolves **F2** (SD2) and **F4** (SD4). RLS is deny-all with zero policies, so the browser cannot read Supabase at all — this story establishes that boundary in code before any screen exists. It also lands `effectiveStatus`, the TypeScript mirror of the `v_runs` `case` expression, together with the Layer 2.5 test that pins the two implementations to each other (**SR3**).

#### Acceptance Criteria

- [ ] `lib/supabase/server.ts` creates a per-request client with the service role key from a server-only env var; importing it from a client component fails lint.
- [ ] Typed query helpers exist for: enabled agents, one agent by slug, enabled non-archived repositories, runs by agent slug (newest-first, from `v_runs`), one run by id, `run_steps` by run, `run_events` by run bounded and `seq`-ordered, `run_artifacts` by run.
- [ ] `lib/domain/status.ts` exports `effectiveStatus(run, now)` implementing SD4 exactly: `running` past `started_at + max_runtime + grace` → `timed_out`; `queued` past `queued_at + start_timeout` → `failed_to_start`; otherwise pass through.
- [ ] A Layer 2.5 parity test proves `effectiveStatus` agrees with `v_runs.effective_status` across a fixture matrix of run rows, including exact-boundary rows.
- [ ] A Layer 2.5 security-negative test proves an **anon-key** client reads zero rows from every table and from `v_runs`.
- [ ] A build-artifact test proves no client chunk contains the service role key.
- [ ] Run routes are non-cached (`dynamic = "force-dynamic"`); no Next.js data cache is introduced for run data.

#### Business Rules

- SD2 — no `NEXT_PUBLIC_SUPABASE_*` variable exists. All reads happen in server components or route handlers.
- FR11a — displayed run status derives from `v_runs.effective_status` on first read and from `effectiveStatus()` on every live update, so the two paths cannot disagree.
- PostgREST errors surface as `DATABASE_ERROR` (500) with the Postgres code logged, never returned (§13).

#### Technical Notes

- `v_runs` supplies `effective_status`, `agent_slug`, `repository_full_name` — prefer it over joins for read paths.
- Boundary comparison must use the same inclusive/exclusive sense as the SQL (`now() > started_at + interval`), or the parity test will fail on exact-boundary fixtures. That is the point of testing them.
- Keep `effectiveStatus` pure and `now`-injected so tests need no clock mocking.

#### Testing Requirements

- **Unit Tests:** `effectiveStatus` truth table — `queued` fresh/stale, `running` fresh/stale, each terminal status pass-through, null `started_at` with `running`, exact-boundary equality, negative/zero grace.
- **Integration Tests (2.5):** parity against `v_runs` over the same fixture matrix; anon-client zero-rows across all tables and the view; query helpers return expected shapes against seeded data.
- **Manual/UI Testing:** none (no UI yet); verify via the placeholder route rendering a server-fetched agent count.
- **Edge-Case Matrix:** empty result sets; run with no repository (`requires_repository = false`); `run_events` empty; malformed/absent env var → clear startup error, not a silent `undefined` client; a row whose `max_runtime_seconds` is null (must not silently derive `timed_out`).
- **Acceptance-Criteria Mapping:** AC1 → lint rule test + import failure; AC2 → helper unit/integration tests; AC3 → `status.test.ts`; AC4 → `status-parity.test.ts`; AC5 → `rls-deny-all.test.ts`; AC6 → `bundle-secrets.test.ts`; AC7 → route config assertion.
- **Execution Commands:** `pnpm run test:unit`, `pnpm run test:integration`, `pnpm run validate`.

#### Implementation Steps

1. Add `lib/supabase/server.ts` with env validation and a per-request factory.
2. Write `effectiveStatus` and its unit truth table first.
3. Add typed query helpers with generated or hand-written row types.
4. Write the Layer 2.5 parity test and the anon-key deny-all test.
5. Add the bundle-grep security-negative test to the build pipeline.
6. Establish the `force-dynamic` convention and document it in `panel/README.md`.

#### Files to Create/Modify

- `panel/lib/supabase/server.ts`, `panel/lib/supabase/queries.ts`, `panel/lib/supabase/types.ts`
- `panel/lib/domain/status.ts`
- `panel/tests/unit/status.test.ts`, `panel/tests/integration/status-parity.test.ts`, `panel/tests/integration/rls-deny-all.test.ts`, `panel/tests/integration/queries.test.ts`, `panel/tests/unit/bundle-secrets.test.ts`
- `panel/eslint.config.mjs`, `panel/README.md`, `.env.example`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] Migration lifecycle complete — N/A, read-only story (documented opt-out)
- [ ] Pull Request created and merged

---

### Story S-105: Design token layer, Nocturne primitives, and data formatters

**Priority:** Critical
**Estimated Size:** L
**Dependencies:** S-101

#### User Story

As the fleet operator,
I want the Nocturne design system available as tokens and reusable components,
So that every screen renders the prototype's visual language without redefining colors, spacing, or status semantics.

#### Context

`/DESIGN.md` §2 defines the token set and §11.2 enumerates the component inventory the four screens compose from. **SD10** flags the trap: the four app-level status colors (`--st-ok`, `--st-fail`, `--st-timeout`, plus accent for `running` and muted for `failed_to_start`) are **not** in the Nocturne stylesheet — they are prototype-page-local and must be defined explicitly. Every status pill and dot depends on them.

#### Acceptance Criteria

- [ ] `styles/tokens.css` defines every token in `/DESIGN.md` §2: core colors, neutral 100–900, accent 100–900, the four `--st-*` status colors (SD10), utility aliases (`--rule`, `--muted`, `--faint`), typography, spacing, radii, shadows.
- [ ] No component contains a hardcoded hex, font family, or pixel spacing value; all reference tokens (enforced by review plus a lint/stylelint check where practical).
- [ ] Components exist and are unit-tested per `/DESIGN.md` §11.2: `Button` (primary/secondary/ghost × sm/md/default, disabled), `Tag` (accent/neutral/outline), `StatusPill`, `StatusDot`, `NavItem`, `Input`, `LogLine`, `StatusBar`, `RunStrip`, `Toggle`, `KLabel`, `Breadcrumb`.
- [ ] `StatusPill`/`StatusDot` cover all six statuses including `failed_to_start` (hollow dot) and the `running`/`queued` pulse animation.
- [ ] Status meaning is conveyed by text, never by color alone; `:focus-visible` is a 2px accent outline with 2px offset and browser default rings are suppressed.
- [ ] Formatters in `lib/format.ts` implement `/DESIGN.md` §7: 24h `HH:MM:SS`, relative times, `Xm XXs` durations, `running · Xm`, short run IDs (uppercase mono), step progress `n/m`, event counts, status legends.
- [ ] Icons come from `@phosphor-icons/react` per `/DESIGN.md` §10, rendered on `currentColor` — no Unicode glyph stand-ins.

#### Business Rules

- Tokens are the source of truth; Tailwind utilities alone are not acceptable (`/DESIGN.md` §11.1).
- `color-mix()` is used extensively — document the browser floor (Chrome 111+, Safari 16.2+, Firefox 113+).
- Do not bolden past weight 500; do not flood the accent; rules fade at both ends.

#### Technical Notes

- Monospace is the system stack; only Inter is loaded (`/DESIGN.md` §1.2).
- `LogLine` is a 4-column grid (`82px 46px 108px minmax(0,1fr)`) with `pre-wrap` and never truncates message content (§7.5).
- Keep components presentational and server-render-safe; interactive ones (`Toggle`, `NavItem`) are client components.

#### Testing Requirements

- **Unit Tests:** formatter table-driven tests including zero/negative/sub-second durations, exactly-1-minute boundaries, far-past relative times, and short-ID casing.
- **Component Tests (Layer 2):** each component renders its variants; `StatusPill` renders accessible text for every status; `Toggle` fires `onChange` and is keyboard-operable; `LogLine` wraps rather than truncates a 8 KB message.
- **Manual/UI Testing:** a `/dev/gallery` route (dev-only, excluded from production build) rendering every component variant side by side against the prototype at `docs/prototype/` for visual comparison.
- **Edge-Case Matrix:** unknown status value → renders a neutral fallback, not a crash; empty `RunStrip` (fewer than 24 runs → 33%-height placeholders); `StatusBar` with all-zero segments; extremely long agent name (single-line ellipsis) and 2-line clamp in card variant.
- **Acceptance-Criteria Mapping:** AC1–AC2 → token file review + stylelint; AC3–AC5 → component tests; AC6 → `format.test.ts`; AC7 → import audit.
- **Execution Commands:** `pnpm run test:unit`, `pnpm run validate`, `pnpm --filter panel dev` → `/dev/gallery`.

#### Implementation Steps

1. Transcribe `/DESIGN.md` §2 into `styles/tokens.css`, including the SD10 status colors, and import it in the root layout.
2. Write the formatter unit tests, then `lib/format.ts`.
3. Build the primitives in dependency order: `KLabel`, `Tag`, `Button`, `Input`, `StatusDot`, `StatusPill`, `Toggle`, `Breadcrumb`, `NavItem`, `StatusBar`, `RunStrip`, `LogLine`.
4. Add the `pulse`, `spin`, and `rise` keyframes and the hover/focus rules from `/DESIGN.md` §6.
5. Add the dev-only gallery route and compare against the prototype.
6. Record any prototype detail that cannot be reproduced as a `/DESIGN.md` impact note in the PR.

#### Files to Create/Modify

- `panel/styles/tokens.css`, `panel/styles/globals.css`
- `panel/components/{Button,Tag,StatusPill,StatusDot,NavItem,Input,LogLine,StatusBar,RunStrip,Toggle,KLabel,Breadcrumb}.tsx`
- `panel/lib/format.ts`
- `panel/tests/unit/format.test.ts`, `panel/tests/component/*.test.tsx`
- `panel/app/dev/gallery/page.tsx` (dev-only)

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] `/DESIGN.md` impact notes recorded (tokens/components added or clarified)
- [ ] Migration lifecycle complete — N/A, no schema change (documented opt-out)
- [ ] Pull Request created and merged

---

### Story S-106: App shell — sidebar, top bar, collapse persistence

**Priority:** High
**Estimated Size:** S
**Dependencies:** S-105

#### User Story

As the fleet operator,
I want a persistent shell with a collapsible sidebar,
So that I can navigate the panel and keep my preferred layout across page loads.

#### Context

`/DESIGN.md` §4.1 specifies the shell: 212px sidebar collapsing to 52px, 38px top bar, content region owning its own scroll. PRD §10 defers four destinations (All runs, Repositories, Settings, System health) — the spec requires they render **disabled**, not as links, so the deferral is visible rather than a dead click.

#### Acceptance Criteria

- [ ] `app/layout.tsx` renders the shell: 212px sidebar (52px collapsed) with `width 0.14s ease` transition, 38px top bar, content region `flex:1; overflow-y:auto`, page height `100dvh` with no outer scroll.
- [ ] Collapse state persists in `localStorage` and survives a reload; `Cmd+\` toggles it.
- [ ] Agents is the only enabled nav destination; All runs, Repositories, Settings, and System health render disabled with an accessible "not available in this phase" affordance.
- [ ] Nav items match `/DESIGN.md` §3.5 including the active state (12% accent tint + 2px accent left border) and hover tint.
- [ ] Keyboard navigation reaches every interactive element; focus is visible per §6.4; the sidebar is a `<nav>` with an accessible label.
- [ ] Layout holds at 1024px minimum width with no horizontal scroll (`/DESIGN.md` §9).

#### Business Rules

- Sidebar state is a user preference persisted client-side, not a responsive breakpoint response.
- Disabled nav items must not be links and must not be focus traps.

#### Technical Notes

- The shell is a server component; the collapse control and shortcut handler are client components reading `localStorage` after mount to avoid a hydration mismatch — render the server default, then reconcile.
- Sidebar background is `color-mix(in srgb, var(--color-bg) 92%, #000)`; body is 88%.

#### Testing Requirements

- **Unit Tests:** the shortcut matcher (`Cmd+\` on macOS, `Ctrl+\` elsewhere) and the persistence read/write helper.
- **Component Tests:** collapse toggles width class; state restored from a seeded `localStorage`; disabled items render as non-interactive; active item derives from the current route.
- **Manual/UI Testing:** toggle, reload, confirm state; drive the whole shell by keyboard only; compare against `docs/prototype/` at 1024px and 1440px.
- **Edge-Case Matrix:** `localStorage` unavailable or throwing (private mode) → default expanded, no crash; corrupted stored value → default; rapid double toggle; no hydration warning in the console.
- **Acceptance-Criteria Mapping:** AC1, AC4, AC6 → component tests + manual comparison; AC2 → persistence test + manual reload; AC3 → disabled-item test; AC5 → keyboard walkthrough + focus assertions.
- **Execution Commands:** `pnpm run test:unit`, `pnpm run test`, `pnpm --filter panel dev`.

#### Implementation Steps

1. Build the shell grid in `app/layout.tsx` with the token-driven dimensions.
2. Add the `Sidebar` client component with `NavItem` composition, active-route detection, and disabled deferred items.
3. Add the collapse store (`localStorage` + reducer) and the `Cmd+\` handler.
4. Add the top bar with breadcrumb slot.
5. Verify keyboard traversal and focus visibility; compare against the prototype.

#### Files to Create/Modify

- `panel/app/layout.tsx`
- `panel/components/Sidebar.tsx`, `panel/components/TopBar.tsx`
- `panel/lib/ui/sidebar-state.ts`, `panel/lib/ui/shortcuts.ts`
- `panel/tests/unit/sidebar-state.test.ts`, `panel/tests/component/Sidebar.test.tsx`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] `/DESIGN.md` §4.1 conformance reviewed
- [ ] Migration lifecycle complete — N/A, no schema change (documented opt-out)
- [ ] Pull Request created and merged

---

### Story S-107: Agents Dashboard with three-variant density toggle

**Priority:** High
**Estimated Size:** M
**Dependencies:** S-104, S-105, S-106

#### User Story

As the fleet operator,
I want to see every configured agent with its run summary in the density I prefer,
So that I can judge fleet health at a glance and pick the layout that suits my agent count.

#### Context

Implements **FR10** and **FR17**/**D17**, verified by **AC9**. The three variants in `/DESIGN.md` §5.1 (dense rows, cards, ledger) share one query and differ only in presentation — the correct default is not knowable before real usage, so all three ship behind a persisted toggle defaulting to dense rows.

#### Acceptance Criteria

- [ ] `/` lists every `is_enabled` agent from `agents` with status dot, name, slug (mono, accent-400), description, run count, status breakdown, and last-run time + outcome.
- [ ] All three `/DESIGN.md` §5.1 variants render from the same data: dense rows (1a, default), cards with the 24-bar run strip (1b), ledger (1c).
- [ ] The density selection persists client-side and survives a page reload (AC9).
- [ ] Displayed run statuses derive from `v_runs.effective_status` (FR11a), including in the aggregate breakdown.
- [ ] Agent name/slug links to that agent's run history; an "Invoke" action links to the invoke route.
- [ ] Empty state (no agents, or an agent with zero runs) renders a legible message, not a blank region or `NaN`.
- [ ] The ledger variant supports its documented keyboard affordances (`Up`/`Down` select, `Enter` run, `/` focus filter) or renders them absent rather than broken.

#### Business Rules

- D17 — all three variants ship; default is dense rows; selection is persisted client-side.
- FR10 — the list is driven by the `agents` table. A new agent row appears with no code change (supports AC7, fully verified in S-113).
- Time-range filter chips (7d/30d/all) from `/DESIGN.md` §5.1 are presentation of the same query; if the aggregate cost is non-trivial, ship "all" only and record the reduction.

#### Technical Notes

- Aggregate run counts per agent with a single grouped query over `v_runs`, not N+1 per agent.
- Server-render the data; the toggle is a client component that swaps presentation only — no refetch on variant change.
- `RunStrip` takes the most recent 24 runs newest-last per `/DESIGN.md` §3.9.

#### Testing Requirements

- **Unit Tests:** the aggregation shaper (rows → per-agent summary), including agents with zero runs and mixed statuses.
- **Component Tests:** each variant renders from one fixture; toggle switches variants without refetch; persisted value selects the variant on mount; disabled agents are excluded.
- **Integration Tests (2.5):** the dashboard query returns the seeded `dependency-update` agent with correct counts against the local stack.
- **Manual/UI Testing:** `/` in all three variants at 1024px and 1440px, compared against `docs/prototype/`; reload confirms persistence.
- **Edge-Case Matrix:** zero agents; agent with zero runs; agent whose last run is `running` (pulse) and one whose last run is `failed_to_start` (hollow dot, muted); a stale `running` run displaying as `timed_out`; very long description (ellipsis in rows, 2-line clamp in cards); 100+ runs (strip caps at 24).
- **Acceptance-Criteria Mapping:** AC1, AC4 → integration + component tests; AC2, AC3 → variant + persistence tests, plus PRD AC9 manual reload; AC5 → link assertions; AC6 → empty-state test; AC7 → keyboard test.
- **Execution Commands:** `pnpm run test`, `pnpm run test:integration`, `pnpm --filter panel dev`.

#### Implementation Steps

1. Add the dashboard query + aggregation shaper with unit tests.
2. Build the dense-rows variant (default) with `StatusBar` and legend.
3. Build the cards variant with `RunStrip`, then the ledger variant.
4. Add the density toggle with `localStorage` persistence, defaulting to dense rows.
5. Add empty states and links to run history and invoke.
6. Compare all three variants against the prototype.

#### Files to Create/Modify

- `panel/app/page.tsx`
- `panel/components/dashboard/{DenseRows,AgentCards,Ledger,DensityToggle}.tsx`
- `panel/lib/domain/dashboard.ts`
- `panel/lib/supabase/queries.ts` (dashboard aggregate)
- `panel/tests/unit/dashboard.test.ts`, `panel/tests/component/dashboard.test.tsx`, `panel/tests/integration/dashboard-query.test.ts`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] `/DESIGN.md` §5.1 conformance reviewed for all three variants
- [ ] Migration lifecycle complete — N/A, read-only story (documented opt-out)
- [ ] Pull Request created and merged


---

### Story S-108: Agent Run History

**Priority:** High
**Estimated Size:** M
**Dependencies:** S-104, S-106

#### User Story

As the fleet operator,
I want to see every run of a given agent newest-first with its true status,
So that I can find the run I care about and trust the status I am shown.

#### Context

Implements **FR11** and **FR11a**, verified by **AC10**. The story's hard requirement is the one that is easy to get wrong: a run whose timeout threshold has passed but which the reaper has not yet materialized must display as `timed_out`, not `running` — verified with the `pg_cron` job paused.

#### Acceptance Criteria

- [ ] `/agents/[slug]` lists that agent's runs newest-first, unfiltered and unpaginated, from `v_runs`.
- [ ] Each row shows status pill, outcome tag, repository (with branch when available), duration, step progress `n/m`, and relative start time, per `/DESIGN.md` §5.2.
- [ ] Status displayed is `effective_status`, not `runs.status` (FR11a).
- [ ] With the `pg_cron` reaper paused and a run past its threshold, the row displays `timed_out` — the AC10 verification, recorded as evidence.
- [ ] An agent header shows breadcrumb, name, description, and metadata (params count, p50 duration, success rate).
- [ ] Rows link to `/runs/[id]`; the empty state offers an invoke CTA.
- [ ] Unknown slug or a disabled agent renders a 404, not an empty list.

#### Business Rules

- Filters, repo chips, search, and pagination are deferred to v3 (PRD §10) — the toolbar renders without them rather than with dead controls.
- The list is a read of `v_runs`; the panel writes nothing here.

#### Technical Notes

- Semantic table markup, not divs, for screen-reader navigation (spec §10).
- Grid columns per `/DESIGN.md` §4.4: `118px 122px minmax(0,1fr) 96px 78px 104px 30px`.
- `force-dynamic` — a cached run list is exactly the staleness FR11a exists to prevent.
- p50 duration and success rate are computed from the returned rows; if that proves expensive, compute in SQL and note the change.

#### Testing Requirements

- **Unit Tests:** the row-shaping function (duration, `n/m`, relative time, outcome fallback `—` at 0.45 opacity) and the header metric derivations (p50 with even/odd counts, success rate with zero runs).
- **Component Tests:** rows render every status; `running` shows `running · Xm`; missing repository renders cleanly; empty state renders the CTA.
- **Integration Tests (2.5):** seeded runs return newest-first; a synthetic stale `running` row reads `timed_out` through `v_runs`.
- **Manual/UI Testing:** pause the reaper (`cron.unschedule`), insert a stale `running` run, load the page, confirm `timed_out`, re-enable the reaper. Procedure and evidence recorded in the PR (mirrors `docs/runbooks/issue-94-reaper-verification.md`).
- **Edge-Case Matrix:** zero runs; single run; a run with `finished_at` null and `status` terminal; a run with zero steps (`0/0`); duration under one second; unknown slug → 404; disabled agent → 404; a `canceled` status (never written in v1) rendering as a neutral fallback.
- **Acceptance-Criteria Mapping:** AC1–AC2, AC5–AC6 → component + integration tests; AC3 → shared `effectiveStatus` usage assertion; AC4 → the manual reaper-paused procedure (PRD AC10); AC7 → route test.
- **Execution Commands:** `pnpm run test`, `pnpm run test:integration`, `pnpm --filter panel dev`.

#### Implementation Steps

1. Add the runs-by-agent query and the row shaper with unit tests.
2. Build the agent header (breadcrumb + metadata).
3. Build the table with semantic markup and the `/DESIGN.md` §4.4 grid.
4. Add empty state and 404 handling.
5. Execute the reaper-paused AC10 verification and record the evidence.

#### Files to Create/Modify

- `panel/app/agents/[slug]/page.tsx`
- `panel/components/runs/{RunHistoryTable,RunHistoryRow,AgentHeader}.tsx`
- `panel/lib/domain/run-row.ts`
- `panel/lib/supabase/queries.ts` (runs by agent)
- `panel/tests/unit/run-row.test.ts`, `panel/tests/component/run-history.test.tsx`, `panel/tests/integration/runs-by-agent.test.ts`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including the reaper-paused AC10 evidence
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] `/DESIGN.md` §5.2 conformance reviewed
- [ ] Migration lifecycle complete — N/A, read-only story (documented opt-out)
- [ ] Pull Request created and merged

---

### Story S-109: Run Detail — summary, artifacts, bounded log viewer

**Priority:** High
**Estimated Size:** L
**Dependencies:** S-104, S-105, S-106

#### User Story

As the fleet operator,
I want one page showing everything a run did — status, timings, artifacts, and its full log,
So that I can diagnose a run without opening the AWS console.

#### Context

The static half of **FR12** plus **AC14**. `/DESIGN.md` §5.3 specifies a full-height layout where the log viewer owns the scroll. **SD11** bounds the initial fetch at 2,000 events because `run_events` grows two orders of magnitude beyond every other table (R3). **AC14** is the requirement most likely to be missed: a `failed` run carrying a `pull_request` artifact must surface the link alongside the red pill, not hide it behind the failure state.

#### Acceptance Criteria

- [ ] `/runs/[id]` renders full-height with no outer scroll; the log region owns the scroll (`/DESIGN.md` §4.2).
- [ ] Summary shows status pill (from `effective_status`), outcome tag, run ID (short uppercase mono), repository, and the metadata grid (queued / started / finished / duration / branch).
- [ ] `run_artifacts` render as pill links, **including on `failed` runs** (AC14), with `rel="noopener noreferrer"` and only when the URL scheme is `https:`.
- [ ] The log viewer renders `run_events` as a 4-column grid (time / level / step / message) ordered by `seq`, with level coloring and hover highlight; step names label lines via `run_steps`.
- [ ] Initial fetch is bounded at the most recent 2,000 events; if earlier events exist, a "load earlier" control fetches the prior window.
- [ ] Terminal-state banners render for `timed_out` and `failed_to_start` per `/DESIGN.md` §8.3, carrying the reaper's explanatory event text.
- [ ] Log messages render as inert text — never `dangerouslySetInnerHTML`; HTML or script content in a message displays literally.
- [ ] The log region is `aria-live="polite"` so appended lines are announced.
- [ ] Unknown run id renders a 404.

#### Business Rules

- Agent-authored `message` and `run_artifacts.url` are **untrusted input** (spec §12, A10 SSRF note). Scheme validation before linking is mandatory.
- The steps *panel* is deferred to v3; `run_steps` is read only to label log lines.
- Virtualization is deferred (v3). The 2,000 bound is a bound, not a capacity estimate — record observed events-per-run from the first real 60-minute `llm_fix` run (SD11 sizing note).

#### Technical Notes

- Message column is `pre-wrap` with `word-break: break-word` and never truncated (`/DESIGN.md` §7.5).
- Query the newest 2,000 by `seq desc` then reverse for display, so the bound is on the recent end.
- `force-dynamic`; no caching of run data.
- Keep the SSE mount point in the markup so S-110 attaches without restructuring.

#### Testing Requirements

- **Unit Tests:** artifact URL scheme validation (`https`, `http`, `javascript:`, `data:`, relative, empty, whitespace-padded); the 2,000-window selector; banner selection by status.
- **Component Tests:** summary renders each status/outcome pair; artifact pill appears on a `failed` run (AC14); a message containing `<script>alert(1)</script>` renders as literal text; `aria-live` present on the log region.
- **Integration Tests (2.5):** a seeded run with steps, events, and a `pull_request` artifact returns the expected shapes; a run with 2,500 events returns exactly the most recent 2,000 in `seq` order.
- **Manual/UI Testing:** open a real Phase 1 run from the live database (read-only) and compare against `docs/prototype/`; confirm the log region scrolls while the page does not.
- **Edge-Case Matrix:** zero events; one event; 2,000 exactly; > 2,000 (load-earlier path); a run with no repository; null `finished_at` on a terminal run; an 8 KB message (wraps, no layout break); an event whose `step_id` is null; a `failed_to_start` run with no steps and no events (banner only).
- **Acceptance-Criteria Mapping:** AC1–AC2, AC6 → component tests + manual comparison; AC3 → AC14 component test + URL-scheme unit tests (security-negative #5); AC4–AC5 → integration window tests; AC7 → security-negative #6; AC8 → accessibility assertion; AC9 → route test.
- **Execution Commands:** `pnpm run test`, `pnpm run test:integration`, `pnpm --filter panel dev`.

#### Implementation Steps

1. Add queries for run, steps, artifacts, and the bounded events window with integration tests.
2. Build the summary panel (2-column grid per `/DESIGN.md` §4.2) and the artifact pills with scheme validation.
3. Build the log viewer with the `LogLine` grid, level coloring, and the "load earlier" control.
4. Add the terminal-state banners for `timed_out` / `failed_to_start`.
5. Add `aria-live`, focus handling, and 404 handling.
6. Compare against the prototype; record observed event counts for the SD11 sizing note.

#### Files to Create/Modify

- `panel/app/runs/[id]/page.tsx`
- `panel/components/run-detail/{RunSummary,ArtifactLinks,LogViewer,StateBanner}.tsx`
- `panel/lib/domain/artifact-url.ts`, `panel/lib/domain/log-window.ts`
- `panel/lib/supabase/queries.ts` (run, steps, events, artifacts)
- `panel/tests/unit/{artifact-url,log-window}.test.ts`, `panel/tests/component/run-detail.test.tsx`, `panel/tests/integration/run-detail-queries.test.ts`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Mandatory security-negative tests #5 and #6 present and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] `/DESIGN.md` §5.3 / §8.3 conformance reviewed
- [ ] Migration lifecycle complete — N/A, read-only story (documented opt-out)
- [ ] Pull Request created and merged

---

### Story S-110: SSE relay and live log tail

**Priority:** High
**Estimated Size:** M
**Dependencies:** S-109

#### User Story

As the fleet operator,
I want the run log to append itself while I watch,
So that I can follow a run in progress without reloading the page.

#### Context

Completes **FR12** and satisfies **AC6**. Because RLS is deny-all, the browser cannot subscribe to Supabase Realtime directly (**F2**/SD2) — the server subscribes and re-publishes over SSE. **SD6** makes reconnect gap-free by `seq` rather than timestamp, which matters because the agent buffers (D5), so arrival order is not emission order.

#### Acceptance Criteria

- [ ] `GET /api/runs/[id]/events/stream` returns `text/event-stream` and accepts `after_seq` (integer, default 0) as the resume cursor.
- [ ] The handler backfills `seq > after_seq` **first**, then opens the server-side Realtime subscription, and drops pushed rows at or below the highest `seq` already sent — no duplicates, no gaps.
- [ ] Four event types are emitted: `event` (a `run_events` row), `run` (run row changed), `heartbeat` (every 15s), `closed` (`{ reason }` on terminal state).
- [ ] The client stops reconnecting after `closed`; on an unexpected drop it reconnects with its highest rendered `seq` as `after_seq`.
- [ ] Live-updated run status is recomputed through `effectiveStatus` so a Realtime push carrying `status = 'running'` cannot overwrite a derived `timed_out` (SD4).
- [ ] Auto-scroll follows `/DESIGN.md` §6.6: appends scroll when within 24px of the bottom; scrolling up pauses and shows the paused state; clicking "live tail" resumes and re-scrolls.
- [ ] The server-side subscription is unsubscribed on request `abort`, and open/close are logged as a pair with `run_id` and last `seq` so an imbalance is visible (**SR5**).
- [ ] AC6 verified end-to-end: a run in progress appends log lines in the browser with no reload.

#### Business Rules

- No browser Supabase client, no anon key, no `NEXT_PUBLIC_SUPABASE_*` — the relay is the only path (SD2).
- Full reconciliation for long disconnects is deferred to v3; the durable `seq` cursor is what makes that deferral safe.

#### Technical Notes

- Use a `ReadableStream` in the route handler; register cleanup on `request.signal`'s `abort`.
- The heartbeat exists to stop intermediaries idling the connection out — keep it even though Fly may not need it.
- Log subscription open/close/reconnect with `run_id` and last `seq` (spec §13).

#### Testing Requirements

- **Unit Tests:** the dedupe/cursor reducer (backfill then push overlap, out-of-order pushes, duplicate `seq`, `seq` regression); the SSE frame serializer; the auto-scroll threshold predicate at 0/23/24/25px.
- **Component Tests:** route handler with Supabase and Realtime mocked — backfill order, dedupe, `closed` on terminal status, heartbeat cadence, unsubscribe on abort; client hook reconnects with the correct `after_seq`.
- **Integration Tests (2.5):** against the local stack, insert events after the stream opens and assert every one arrives exactly once in `seq` order.
- **Manual/UI Testing:** invoke a run (or replay events into a run row) and watch the viewer append; scroll up to pause, click "live tail" to resume; kill the network briefly and confirm no gap after reconnect.
- **Edge-Case Matrix:** run already terminal at connect (immediate `closed`); `after_seq` beyond the highest existing `seq`; unknown run id; two concurrent clients on one run; client disconnects mid-backfill (no leaked subscription); a 2 KB single-line message; burst of 200 events in one flush (D5 buffering).
- **Acceptance-Criteria Mapping:** AC1–AC4 → handler component tests; AC5 → shared `effectiveStatus` assertion on the push path; AC6 → auto-scroll unit + manual; AC7 → abort test + log-pair assertion (SR5); AC8 → manual live verification and the S-114 Playwright scenario (PRD AC6).
- **Execution Commands:** `pnpm run test`, `pnpm run test:integration`, `pnpm --filter panel dev`.

#### Implementation Steps

1. Write the cursor/dedupe reducer and its unit tests first — this is where gaps and duplicates come from.
2. Implement the route handler: backfill, subscribe, dedupe, heartbeat, `closed`, abort cleanup.
3. Add the client `EventSource` hook with `seq` tracking and reconnect.
4. Wire appended events into the S-109 log viewer with `effectiveStatus` recomputation on `run` events.
5. Implement auto-scroll / pause / resume per `/DESIGN.md` §6.6.
6. Add structured logging for open/close/reconnect; verify pairing under repeated connect/disconnect.

#### Files to Create/Modify

- `panel/app/api/runs/[id]/events/stream/route.ts`
- `panel/lib/sse/{serialize,cursor}.ts`
- `panel/lib/hooks/useRunStream.ts`
- `panel/components/run-detail/{LogViewer,LiveTailButton}.tsx` (modified)
- `panel/tests/unit/{sse-cursor,sse-serialize,autoscroll}.test.ts`, `panel/tests/component/stream-route.test.ts`, `panel/tests/integration/stream-e2e.test.ts`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including PRD AC6
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] Subscription-leak check (SR5) recorded
- [ ] Migration lifecycle complete — N/A, read-only story (documented opt-out)
- [ ] Pull Request created and merged

---

### Story S-111: AWS credential provider — Fly OIDC and local chain

**Priority:** Critical
**Estimated Size:** M
**Dependencies:** S-101

#### User Story

As the fleet operator,
I want the panel to obtain AWS credentials without any static keys,
So that invocation works on Fly and locally with the same code and no secret to rotate.

#### Context

Implements **FR15**/**D12** and resolves **F5** via **SD9**. `docs/reference/credentials.ts` is adopted with three corrections, the important one being the unsafe token-extraction chain: `parsed.value ?? parsed.token ?? parsed.aud` would send the *audience* string to STS as a web identity token, producing a misleading auth error instead of a clear parse failure. **SR1** — the real socket response shape is unverified — is why the failure mode must name what it actually received.

#### Acceptance Criteria

- [ ] `lib/aws/credentials.ts` exists with branch detection by `FLY_APP_NAME` + socket existence; callers receive a provider and do not know which branch ran.
- [ ] The Fly branch requests an OIDC token from `/.fly/api` with `aud=sts.amazonaws.com` and exchanges it via `AssumeRoleWithWebIdentity`.
- [ ] Token extraction accepts `value` or `token` only; any other shape throws `FlyOidcShapeError` naming the keys actually received. The `aud` fallback and the `data.trim()` raw-body fallback are removed.
- [ ] The local branch uses `fromNodeProviderChain()` — SSO profile, shared credentials, or environment variables — with no code change between environments.
- [ ] Credentials are cached in memory with a 60-second refresh margin and a single-flight promise so concurrent invokes trigger one STS call.
- [ ] `credentialSource()` reports which branch is active and is logged on every invoke (**R6** diagnosis).
- [ ] All comments are English; the embedded `curl` verification command for probing the socket is retained (it is the procedure that closes OQ1).
- [ ] `CREDENTIALS_UNAVAILABLE` (500) is distinct from `INVOCATION_FAILED` (502) in the error taxonomy, because the runbooks differ.

#### Business Rules

- No static AWS keys anywhere — not in `fly secrets`, not in `.env` (D12, AC8).
- IAM permission is scoped to `bedrock-agentcore:InvokeAgentRuntime` on the runtimes ARN, never `*`.
- OQ1 stays open until a real Machine is probed (S-115); this story defines the contract and fails loudly when reality differs.

#### Technical Notes

- `DurationSeconds: 900` must be compatible with the role's `MaxSessionDuration` — unverified until S-115.
- Keep the module free of Next.js imports so it is unit-testable in isolation.
- Never log the token, the STS response, or the assumed-role credentials — log `credentialSource()` and error codes only.

#### Testing Requirements

- **Unit Tests:** branch detection (env set + socket present, env set + socket absent, env absent); token extraction accepting `value`, accepting `token`, rejecting `{aud}`, rejecting a non-JSON body, rejecting `{}` — with `FlyOidcShapeError` naming received keys; cache hit within margin; cache miss past margin; single-flight (two concurrent calls → one STS call); STS failure surfaces `CREDENTIALS_UNAVAILABLE`.
- **Integration Tests:** none — the real socket only exists on Fly (S-115).
- **Manual/UI Testing:** run locally with an SSO profile and confirm `credentialSource()` reports the local branch; confirm no AWS env keys are required.
- **Edge-Case Matrix:** socket present but connection refused; socket returns 500; expired-token retry; clock skew inside the refresh margin; missing role ARN env var → clear startup error; secret material absent from all log output (assert by capturing logs).
- **Acceptance-Criteria Mapping:** AC1–AC5 → `credentials.test.ts`; AC6 → log assertion; AC7 → file review; AC8 → error-taxonomy test in S-112.
- **Execution Commands:** `pnpm run test:unit`, `pnpm run validate`.

#### Implementation Steps

1. Move `docs/reference/credentials.ts` to `panel/lib/aws/credentials.ts`; leave a link behind.
2. Replace the token-extraction chain with the `value`/`token`-only version plus `FlyOidcShapeError`.
3. Translate comments to English; retain the `curl` probe command.
4. Write the unit suite including every rejection shape.
5. Add `lib/aws/invoke.ts` wrapping `InvokeAgentRuntime` against `runtime_arn` + `runtime_qualifier` (used by S-112).
6. Verify locally with an SSO profile.

#### Files to Create/Modify

- `panel/lib/aws/credentials.ts`, `panel/lib/aws/invoke.ts`, `panel/lib/aws/errors.ts`
- `docs/reference/credentials.ts` — replaced by a link
- `panel/tests/unit/credentials.test.ts`
- `.env.example`, `panel/README.md`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified (AC8 remains blocked on S-115 / OQ1 — recorded, not silently passed)
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] No secret material in logs — verified
- [ ] Migration lifecycle complete — N/A, no schema change (documented opt-out)
- [ ] Pull Request created and merged

---

### Story S-112: Invoke route handler and agent payload translation (closes #89)

**Priority:** Critical
**Estimated Size:** L
**Dependencies:** S-104, S-111, S-103

#### User Story

As the fleet operator,
I want to trigger an agent from the panel with validated parameters,
So that a run is recorded before the agent is contacted and a failed launch is never invisible.

#### Context

Implements **FR14** and resolves **F1**/**SD5** — the boundary that closes [#89](https://github.com/llipe/dev-tasks-agent-fleet/issues/89). The panel emits a payload a Python agent validates, and nothing across that boundary is type-checked, so drift is silent by construction. The authoritative contract is `main.py:64`: `run_id`, `repository_org`, `repository_name` as three non-empty top-level strings. Ordering is normative (**D1**): the `runs` row exists before AgentCore is contacted.

#### Acceptance Criteria

- [ ] `POST /api/agents/[slug]/invoke` accepts `{ repository_id, params }` and returns `202 { run_id, status: "queued" }` on success.
- [ ] Order is exactly: resolve agent → resolve repository → Ajv-validate `params` → generate `run_id` → split `full_name` → **insert `queued` run** → assume role → `InvokeAgentRuntime` → update `session_id`/`runtime_invocation_id`.
- [ ] `buildAgentPayload` emits `run_id`, `repository_org`, `repository_name`, `base_branch` (from `repositories.default_branch`), and `params`. `repository_id` is **never** sent to the agent.
- [ ] A `full_name` that does not split into exactly two non-empty halves is rejected with `MALFORMED_REPOSITORY` (400) **before** any `runs` row is inserted.
- [ ] Invalid `params` are rejected with `INVALID_PARAMS` (400) and leave no database trace (AC13).
- [ ] The insert snapshots `params`, `agent_version`, `max_runtime_seconds`, `grace_seconds`, and `start_timeout_seconds` explicitly — never relying on column defaults — and fails the request rather than writing a row the reaper cannot resolve.
- [ ] If `InvokeAgentRuntime` throws, the handler marks the run `failed_to_start` with an `error_code` itself and returns `502` with the `run_id` — no waiting for the reaper (AC12).
- [ ] Credential failure returns `CREDENTIALS_UNAVAILABLE` (500), distinct from `INVOCATION_FAILED` (502).
- [ ] `tests/fixtures/agent-invocation-payload.json` is the shared contract fixture: the panel's Layer 1 test asserts `buildAgentPayload` emits it, and a **new Python test** asserts the agent's `validate_payload` accepts it (**SR4**).
- [ ] Whether `InvokeAgentRuntime` requires an explicit `prompt` wrapper is **confirmed by observation** on the first real integration and recorded (OQ2) — not assumed in either direction.
- [ ] Every invoke logs `run_id`, `agent_slug`, `repository_full_name`, and `credentialSource()` as structured JSON.

#### Business Rules

- D1 — the panel generates the `run_id` and inserts the `queued` row before invoking. Per issue #100, an invocation without that row leaves the agent's `start()` PATCH matching zero rows.
- D7 — fire-and-forget, no durable queue, no retry on invocation failure.
- Spec OQ3, now answered: `runs.max_runtime_seconds` is `not null` with **no default**, while `grace_seconds` / `start_timeout_seconds` are `not null` with defaults — so the panel must send all three explicitly, or two of them silently take schema defaults that no longer match the seeded agent (3600/120/300).
- `params` passes through only keys present in `params_schema`, after Ajv validation with `additionalProperties: false`.
- `runs.triggered_by` is written as the constant `"panel"` (SD7) — not an identity.

#### Technical Notes

- Ajv 8 with `ajv-formats`; compile per agent schema and cache the validator by agent id + schema hash.
- Errors use the single shape `{ error: { code, message, details } }` (spec §13).
- `agent_version` comes from `agents.version`; the snapshot exists so a later config change does not re-interpret history.
- The Python-side fixture test belongs in the agent's suite (`tests/unit/`) and must not modify agent production code — the agent contract is authoritative and unchanged.

#### Testing Requirements

- **Unit Tests:** `buildAgentPayload` happy path; malformed `full_name` matrix (no slash, leading slash, trailing slash, multiple slashes, empty, whitespace-only halves) — security-negative #4; snapshot builder completeness.
- **Component Tests:** route handler with Supabase, STS, and AgentCore mocked — full ordering assertion (insert precedes invoke), `400` with no insert for invalid params (security-negative #3) and for malformed `full_name`, `404` for unknown/disabled slug, `400` for disabled/archived repository, `failed_to_start` written on throw (AC12), `502` carries `run_id`, `CREDENTIALS_UNAVAILABLE` distinct from `INVOCATION_FAILED`.
- **Integration Tests (2.5):** against the local stack — a successful invoke (AgentCore mocked) writes exactly one `runs` row with all snapshots non-null; a rejected invoke writes zero rows.
- **Cross-language contract test:** shared fixture consumed by the panel unit test and by a new Python test asserting `validate_payload` accepts it; the test fails if any required field is dropped, renamed, or nested (#89 AC3).
- **Manual/UI Testing:** one real invocation against the deployed runtime transitioning `queued → running` (#89 AC1), and one deliberately malformed payload confirming the agent's `INVALID_PARAMS` (#89 AC2). Requires the deployed agent runtime.
- **Edge-Case Matrix:** `requires_repository = true` with `repository_id` absent; `repository_id` for a repo under a different installation; concurrent double-submit (two runs, two ids — idempotency is not claimed in v1); `params: {}` against a schema with required fields; a schema with an unknown JSON-Schema type; agent row missing `runtime_arn`; STS success followed by AgentCore throw (row must end `failed_to_start`, not `queued`).
- **Acceptance-Criteria Mapping:** AC1–AC2, AC7–AC8 → handler component tests; AC3–AC4 → payload unit tests; AC5 → security-negative #3 + PRD AC13; AC6 → snapshot integration test; AC9 → shared-fixture tests both sides; AC10 → recorded observation in the PR; AC11 → log assertion.
- **Execution Commands:** `pnpm run test`, `pnpm run test:integration`, `make validate` (runs the new Python fixture test too).

#### Implementation Steps

1. Write `buildAgentPayload` and its malformed-`full_name` matrix first; commit the shared fixture.
2. Add the Python-side fixture test in the agent suite; confirm `make validate` runs it.
3. Implement the route handler in the normative order with the error taxonomy from spec §13.
4. Add Ajv validation with validator caching and the timeout-snapshot builder.
5. Add the `failed_to_start` write-on-throw path and structured logging.
6. Run the integration tests; then perform the two live #89 verifications against the deployed runtime and record the `prompt`-wrapping observation.
7. Close #89 referencing the evidence.

#### Files to Create/Modify

- `panel/app/api/agents/[slug]/invoke/route.ts`
- `panel/lib/domain/payload.ts`, `panel/lib/domain/run-insert.ts`, `panel/lib/schema/validate.ts`, `panel/lib/errors.ts`
- `tests/fixtures/agent-invocation-payload.json` (shared, repo root)
- `panel/tests/unit/payload.test.ts`, `panel/tests/component/invoke-route.test.ts`, `panel/tests/integration/invoke-insert.test.ts`
- `agents/dependency-update/app/dependencyUpdate/tests/unit/test_payload_contract_fixture.py`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Mandatory security-negative tests #3 and #4 present and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including the two live #89 checks
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] Issue #89 closed with evidence; OQ2 observation recorded
- [ ] Migration lifecycle complete — N/A, no schema change; writes only existing columns (documented opt-out)
- [ ] Pull Request created and merged

---

### Story S-113: Schema-driven invoke form

**Priority:** High
**Estimated Size:** M
**Dependencies:** S-105, S-112

#### User Story

As the fleet operator,
I want the invocation form to be generated from the agent's own parameter schema,
So that adding an agent needs one database row and no front-end deploy.

#### Context

Implements **FR13**/**D2** and proves **FR16**/**AC7**. **SD8** rejects generic JSON-Schema form libraries: they impose markup and theming that fight `/DESIGN.md`'s token system, and the actual need is small — `enum` → select, `boolean` → toggle, bounded `integer` → number input, `string` → text input. The repository field is rendered separately because it is not part of `params_schema` at all.

#### Acceptance Criteria

- [ ] `/agents/[slug]/invoke` renders a centered dialog per `/DESIGN.md` §5.4 with the agent slug, a schema-driven field list, and Cancel / Run actions.
- [ ] `lib/schema/form.ts` maps `params_schema` to a field-descriptor array; `dependency-update` renders `fix_mode` as a select, `fail_on_findings` as a toggle, `max_fix_attempts` as a bounded number input, and `base_branch` as a text input — derived solely from the schema (AC11).
- [ ] The repository selector renders separately, outside the params, and only when `requires_repository = true`, listing enabled non-archived repositories.
- [ ] An unsupported schema type renders a **disabled field with a visible "unsupported type" note** — parameters never vanish silently.
- [ ] Client-side Ajv validation blocks submission of invalid params, and the server re-validates; a rejected submission leaves no `runs` row (AC13).
- [ ] Submission calls the S-112 route and navigates to `/runs/[id]` on `202`; a `502` also navigates, where the run shows `failed_to_start`.
- [ ] Field labels and help text come from the schema's `title`/`description` (English after S-103); defaults come from `default` / `agents.default_params`.
- [ ] AC7 proven: inserting a **second** agent row with a different `params_schema` renders a correct form with zero code change — demonstrated by an integration/component test using a synthetic agent row.
- [ ] Errors render inline per field for `INVALID_PARAMS`, and as a banner for `MALFORMED_REPOSITORY` / `CREDENTIALS_UNAVAILABLE` / `DATABASE_ERROR`.
- [ ] The schema preview toggle from `/DESIGN.md` §5.4 shows the raw `params_schema`.

#### Business Rules

- D2/FR16 — a new agent is a database row, not a deploy. Any hardcoded field name for `dependency-update` violates this story.
- The repository is never part of `params_schema` (spec §4 API standards).
- Client validation is a convenience; the server is authoritative (S-112).

#### Technical Notes

- Reuse the S-105 `Toggle`, `Input`, `Button`, and `KLabel` primitives; the two-column field grid is `minmax(0,1fr) 292px`.
- Share the Ajv setup with the route handler so client and server cannot diverge in strictness.
- Success state uses the `rise` animation with the run ID and a link to the detail page.

#### Testing Requirements

- **Unit Tests:** `form.ts` mapping — enum, boolean, bounded integer, string, integer without bounds, `oneOf` (unsupported → disabled note), nested object (unsupported), missing `title` (falls back to key name), `default` propagation, required-field marking.
- **Component Tests:** the seeded schema renders the four expected controls (AC11); a synthetic second schema renders correctly with no code change (AC7); repository selector hidden when `requires_repository = false`; invalid input blocks submit; inline vs. banner error rendering; success navigation.
- **Integration Tests (2.5):** insert a synthetic agent row into the local stack and assert the form route renders its fields.
- **Manual/UI Testing:** submit a real `audit_only` invocation and land on the run detail with the log tailing (joins S-110).
- **Edge-Case Matrix:** empty `params_schema` (`{}`) → no fields, submit still valid; schema with `required` field having no default; zero enabled repositories → selector empty state and blocked submit; `max_fix_attempts` at 0 and 5 (inclusive bounds) and 6 (rejected); very long enum list; disabled agent → 404.
- **Acceptance-Criteria Mapping:** AC1–AC4, AC7, AC9–AC10 → component tests; AC5 → client Ajv test + S-112 server test (PRD AC13); AC6 → navigation test + manual; AC8 → synthetic-agent test (PRD AC7).
- **Execution Commands:** `pnpm run test`, `pnpm run test:integration`, `pnpm --filter panel dev`.

#### Implementation Steps

1. Write the `form.ts` mapping and its unit matrix first, including the unsupported-type path.
2. Build the dialog shell per `/DESIGN.md` §5.4 with the two-column field grid.
3. Render controls from descriptors using the S-105 primitives; add the repository selector separately.
4. Wire client-side Ajv, submission to the S-112 route, and navigation.
5. Add inline/banner error rendering and the schema preview toggle.
6. Add the synthetic-second-agent test proving AC7.

#### Files to Create/Modify

- `panel/app/agents/[slug]/invoke/page.tsx`
- `panel/components/invoke/{InvokeDialog,FieldRow,RepositorySelect,SchemaPreview,SuccessState}.tsx`
- `panel/lib/schema/form.ts`, `panel/lib/schema/ajv.ts` (shared with the route)
- `panel/tests/unit/form.test.ts`, `panel/tests/component/invoke-form.test.tsx`, `panel/tests/integration/synthetic-agent-form.test.ts`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/integration/manual/edge-case tests written and passing
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including PRD AC7 and AC11
- [ ] Acceptance criteria explicitly mapped to test evidence
- [ ] `/DESIGN.md` §5.4 conformance reviewed
- [ ] Migration lifecycle complete — N/A, no schema change (documented opt-out)
- [ ] Pull Request created and merged

---

### Story S-114: Playwright E2E against the local stack

**Priority:** Medium
**Estimated Size:** M
**Dependencies:** S-110, S-113

#### User Story

As the fleet operator,
I want an end-to-end test that invokes an agent and watches its log arrive,
So that the four screens and two route handlers are proven to work together and not just in isolation.

#### Context

Spec §14 requires E2E coverage of the invoke → run detail → live tail path against a seeded local stack. This is the only layer that exercises the composition; every other layer mocks at least one boundary. It also gives PRD **AC6** a repeatable assertion instead of a one-time manual observation.

#### Acceptance Criteria

- [ ] Playwright runs against the local Supabase stack with the seeded `dependency-update` agent and AgentCore stubbed at the network boundary (no real AWS call).
- [ ] Scenario 1 — invoke: fill the form, submit, land on `/runs/[id]`, assert the run row exists in the database with `status = queued` and all timeout snapshots non-null.
- [ ] Scenario 2 — live tail: with the run detail open, insert `run_events` rows and assert they appear without a reload (PRD **AC6**).
- [ ] Scenario 3 — reconnect: drop the SSE connection mid-stream, insert events during the gap, and assert no duplicates and no gaps after reconnect (SD6).
- [ ] Scenario 4 — stale run: a `running` run past its threshold displays `timed_out` with the reaper not running (PRD **AC10**).
- [ ] Scenario 5 — validation: an invalid param submission is blocked and no `runs` row is created (PRD **AC13**).
- [ ] Scenario 6 — density toggle: switch variant, reload, assert the selection survived (PRD **AC9**).
- [ ] Scenario 7 — artifact on a failed run: a seeded `failed` run with a `pull_request` artifact shows the link (PRD **AC14**).
- [ ] `test:e2e` is reachable from `make validate` or explicitly gated with a recorded reason if it requires Docker; `TESTING.md` records the E2E row as configured with its scenario-to-AC traceability.

#### Business Rules

- E2E asserts behavior through the UI and the database, never through internal function calls.
- Every scenario maps to a PRD acceptance criterion or a spec design decision; no scenario exists without a traceable reason.
- The suite must be deterministic — seeded fixtures and explicit waits, no sleeps tuned to a machine.

#### Technical Notes

- Reset state between scenarios with `supabase db reset` or per-test transactional fixtures; do not depend on scenario order.
- Stub AgentCore at the HTTP boundary so the invoke path exercises the real credential branch selection but never calls AWS.
- Run headless in CI, headed locally for debugging.

#### Testing Requirements

- **Unit Tests:** none (this story *is* tests).
- **Integration Tests:** the seeding/reset fixture helper is itself covered by a smoke test.
- **Manual/UI Testing:** headed run of all seven scenarios once, to confirm the assertions match what a human sees.
- **Edge-Case Matrix:** empty database (no agents) renders the dashboard empty state; a run with zero events opens the detail without a stream error; two browser contexts tailing the same run; CI cold start where the stack is not ready → explicit wait, not a flake.
- **Acceptance-Criteria Mapping:** Scenario 1 → PRD AC12; 2 → AC6; 3 → SD6; 4 → AC10; 5 → AC13; 6 → AC9; 7 → AC14. Recorded as a traceability table in `TESTING.md`.
- **Execution Commands:** `pnpm run test:e2e`, `make validate`.

#### Implementation Steps

1. Add the Playwright config, seeding fixtures, and the AgentCore network stub.
2. Implement scenarios 1–2, then 3 (the reconnect case needs deliberate connection control).
3. Implement scenarios 4–7.
4. Wire `test:e2e` into the aggregate gate or record the gating reason.
5. Add the scenario-to-AC traceability table to `TESTING.md`.

#### Files to Create/Modify

- `panel/playwright.config.ts`, `panel/tests/e2e/*.spec.ts`, `panel/tests/e2e/fixtures/*`
- `Makefile`, `.github/workflows/ci.yml`, `TESTING.md`

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] All seven scenarios passing locally and in CI
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified
- [ ] Scenario-to-AC traceability recorded in `TESTING.md`
- [ ] Migration lifecycle complete — N/A (documented opt-out)
- [ ] Pull Request created and merged

---

### Story S-115: Fly deployment, privacy release gate, and OIDC probe

**Priority:** High
**Estimated Size:** M
**Dependencies:** S-114

#### User Story

As the fleet operator,
I want the panel deployed to a private Fly app with verified OIDC credentials,
So that I can use it from anywhere I am authorized to reach it, with no AWS keys and no public exposure.

#### Context

Closes **AC8** and the spec's **Open Question 1** — the Fly OIDC socket response shape and AWS's `sub` claim normalization cannot be resolved from documents. It also implements **SR2**, the highest-severity risk in the spec: the panel's *only* security boundary is that the Fly app is not publicly reachable, and a future deploy that adds a public service silently removes it. That is why privacy is a release gate, not a checklist nicety.

#### Acceptance Criteria

- [ ] `panel/Dockerfile` + `fly.toml` are committed. `fly.toml` has **no** `[http_service]` and no public ports, with a comment stating why (SR2/D16).
- [ ] Fly is registered as an OIDC IdP in AWS; an IAM role trusts the app's `sub` (`<org>:<app>:*`) and grants only `bedrock-agentcore:InvokeAgentRuntime` on the runtimes ARN.
- [ ] The Supabase service role key is a Fly secret; `fly secrets list` contains **no** AWS key of any kind (AC8).
- [ ] The OIDC socket is probed on a live Machine using the retained `curl` command; the actual response shape and the normalized `sub` claim are **recorded** in a runbook, and `credentials.ts` is corrected if reality differs from SD9's assumption.
- [ ] `DurationSeconds: 900` is confirmed compatible with the role's `MaxSessionDuration`.
- [ ] A release-process check asserts the deployed app has no allocated public IP and no public service; the check fails the release if it does.
- [ ] `panel/README.md` documents the private-app requirement as a **precondition**, not an implementation detail.
- [ ] One real end-to-end invocation from the deployed panel transitions a run `queued → running` against the deployed AgentCore runtime, with the log tailing live in the browser.
- [ ] The `prompt`-wrapping question (OQ2) is settled by observation and recorded.
- [ ] Local development still works unchanged with an SSO profile (AC8's second half).

#### Business Rules

- D12 — no static AWS keys, in any environment.
- D16 — no user authentication is added here. This story does **not** make the app public; it makes the boundary explicit and checked.
- The agent runtime must be deployed before the live invocation check (spec §15 ordering).

#### Technical Notes

- Record Fly region and machine sizing (spec OQ5) in the runbook — not a spec concern, but needed before deploy.
- Local dev against the production Supabase remains a live risk (**SR7**/R7): the runbook must state which project the deployed panel and the local stack each point at.
- Rollback is redeploying the prior image — the panel is stateless.

#### Testing Requirements

- **Unit Tests:** the privacy-check script (parses `fly status` / IP list output; fails on any public IP).
- **Integration Tests:** none beyond the live checks.
- **Manual/UI Testing:** deploy; probe the socket; invoke a real run; watch the live tail; confirm the app is unreachable from a network without access.
- **Edge-Case Matrix:** OIDC socket returns an unexpected shape → `FlyOidcShapeError` names the received keys (the SD9 design paying off); STS `AccessDenied` (trust policy `sub` mismatch) → `CREDENTIALS_UNAVAILABLE`, distinguishable from an AgentCore failure; role `MaxSessionDuration` below 900 → clear failure; a deliberately misconfigured public service → release check fails.
- **Acceptance-Criteria Mapping:** AC1, AC6–AC7 → committed config + privacy-check run; AC2–AC3, AC5 → AWS/Fly console evidence in the runbook (PRD AC8); AC4, AC9 → recorded probe output; AC8 → live run evidence (PRD AC6 in production); AC10 → local SSO run.
- **Execution Commands:** `pnpm run validate`, `fly deploy`, the privacy-check script, `fly secrets list`.

#### Implementation Steps

1. Write the Dockerfile and `fly.toml` (no public service) plus the privacy-check script and its unit test.
2. Register the OIDC IdP and IAM role; scope the invoke permission to the runtimes ARN.
3. Set Fly secrets; confirm no AWS credentials are present.
4. Deploy; run the privacy check; confirm unreachability.
5. Probe the OIDC socket; record the shape; correct `credentials.ts` if needed and re-run its unit suite.
6. Perform the live invocation and live-tail verification; record the `prompt`-wrapping observation.
7. Write `docs/runbooks/panel-deployment.md`; update spec §17 open questions and PRD open question #5 as resolved.

#### Files to Create/Modify

- `panel/Dockerfile`, `panel/fly.toml`, `panel/.dockerignore`
- `scripts/verify-fly-private.sh`, `panel/tests/unit/fly-privacy-check.test.ts`
- `docs/runbooks/panel-deployment.md`
- `panel/lib/aws/credentials.ts` (only if the probe contradicts SD9)
- `panel/README.md`, `workstream/specification-prd-agent-fleet-panel-v2.md` (§17), `docs/requirements/prd-agent-fleet-panel-v2.md` (§18)

#### Definition of Done Checklist

- [ ] Code implemented per technical guidelines
- [ ] Unit/manual/edge-case verification complete and recorded
- [ ] Quality gates passing (`lint`, `format:check`, `typecheck`, `test`, `audit`)
- [ ] Code reviewed and approved
- [ ] Acceptance criteria verified, including PRD AC8 and the live invocation
- [ ] Privacy release gate demonstrated to fail on a public service
- [ ] Open Questions 1 and 2 recorded as resolved in the spec and PRD with changelog rows
- [ ] Migration lifecycle complete — N/A, no schema change (documented opt-out)
- [ ] Pull Request created and merged

---

## Coverage Validation

### Summary

- **Total PRD Phase 2 requirements:** 32 (FR10–FR18 + FR11a = 10; AC6–AC14 = 9; F1–F7 = 7; Phase-2-relevant business rules D1, D2, D7, D11, D12, D16, D17 = 7 — D3/D4/D5/D6/D8/D9/D10/D13/D14/D15 are Phase 1 and unchanged)
- **Total spec design decisions:** 12 (SD1–SD12)
- **Total User Stories:** 15
- **Coverage:** 100% (32/32 requirements, 12/12 design decisions, 6/6 mandatory security-negative tests, 8/8 spec risks addressed)
- **Status:** Complete

### Requirement Mapping

| PRD requirement | Story ID(s) | Status |
|---|---|---|
| FR10 — list agents | S-107 | ✅ Covered |
| FR11 — list runs per agent | S-108 | ✅ Covered |
| FR11a — read `v_runs` / `effective_status` | S-104, S-108, S-110 | ✅ Covered |
| FR12 — log with live tail | S-109, S-110 | ✅ Covered |
| FR13 — schema-driven form | S-113 | ✅ Covered |
| FR14 — invoke flow ordering (a–f) | S-112 | ✅ Covered |
| FR15 — no static AWS keys | S-111, S-115 | ✅ Covered |
| FR16 — new agent = one DB row | S-113 (AC7 proof) | ✅ Covered |
| FR17 — density toggle | S-107 | ✅ Covered |
| FR18 — no user auth | S-106 (no login route), S-112 (`triggered_by` constant), S-115 (privacy gate) | ✅ Covered |
| AC6 — live log, no reload | S-110, S-114 (scenario 2), S-115 (in production) | ✅ Covered |
| AC7 — new agent, zero deploys | S-113 | ✅ Covered |
| AC8 — no AWS keys on Fly, SSO locally | S-111 (contract), S-115 (verification) | ✅ Covered |
| AC9 — dashboard + density persistence | S-107, S-114 (scenario 6) | ✅ Covered |
| AC10 — run history + stale run displays `timed_out` | S-108, S-114 (scenario 4) | ✅ Covered |
| AC11 — form controls derived from schema | S-113 | ✅ Covered |
| AC12 — queued row before invoke; `failed_to_start` on throw | S-112, S-114 (scenario 1) | ✅ Covered |
| AC13 — invalid params leave no DB trace | S-112, S-113, S-114 (scenario 5) | ✅ Covered |
| AC14 — artifact link on a `failed` run | S-109, S-114 (scenario 7) | ✅ Covered |
| F1 — payload contract (#89) | S-112 | ✅ Covered |
| F2 — RLS blocks browser reads | S-104 (server-only + anon deny test), S-110 (SSE relay) | ✅ Covered |
| F3 — seed `params_schema` defects | S-103 (extended to the full English-only SQL surface) | ✅ Covered |
| F4 — `v_runs` vs. Realtime source | S-104 (parity test), S-110 (recompute on push) | ✅ Covered |
| F5 — `credentials.ts` defects | S-111 | ✅ Covered |
| F6 — schema/seed are documents, not migrations | S-102 | ✅ Covered |
| F7 — no JS/TS package in the aggregate gate | S-101 | ✅ Covered |
| D1 — panel generates `run_id`, inserts `queued` first | S-112 | ✅ Covered |
| D2 — form from `params_schema` | S-113 | ✅ Covered |
| D7 — fire-and-forget from the route handler | S-112 | ✅ Covered |
| D11 — RLS deny-all preserved, no policies added | S-102, S-104 | ✅ Covered |
| D12 — Fly OIDC + `AssumeRoleWithWebIdentity` | S-111, S-115 | ✅ Covered |
| D16 — no user auth; privacy is the boundary | S-115 | ✅ Covered |
| D17 — three density variants, default dense rows | S-107 | ✅ Covered |

### Spec Design Decision Mapping

| SD | Story ID(s) |
|---|---|
| SD1 — pnpm workspace, panel as a package | S-101 |
| SD2 — all Supabase access server-side; SSE relay | S-104, S-110 |
| SD3 — Supabase CLI migrations | S-102, S-103 |
| SD4 — `effectiveStatus` recomputed client-side | S-104, S-108, S-110 |
| SD5 — payload translation in `lib/domain/payload.ts` | S-112 |
| SD6 — gap-free reconnect by `seq` | S-110, S-114 (scenario 3) |
| SD7 — no user auth; Fly privacy is the boundary | S-112 (`triggered_by`), S-115 |
| SD8 — Ajv validation, hand-rendered form | S-113 |
| SD9 — `credentials.ts` with F5 corrections | S-111 |
| SD10 — token layer includes the four `--st-*` colors | S-105 |
| SD11 — log viewer bounds its initial fetch at 2,000 | S-109 |
| SD12 — Vitest for Layers 1–2.5, Playwright for E2E | S-101, S-114 |

### Mandatory Security-Negative Test Mapping

| # | Test | Story |
|---|---|---|
| 1 | No bundle artifact contains the service role key | S-104 |
| 2 | Anon-key client reads zero rows from every table and `v_runs` | S-104 |
| 3 | Ajv rejects `additionalProperties`; no `runs` row written | S-112 |
| 4 | `buildAgentPayload` rejects every malformed `full_name` shape | S-112 |
| 5 | Non-`https:` `run_artifacts.url` is not rendered as a link | S-109 |
| 6 | Log messages containing HTML/script render as inert text | S-109 |

### Risk Mapping

| Risk | Story | Treatment |
|---|---|---|
| SR1 — Fly OIDC shape unverified, blocks AC8 | S-111, S-115 | Explicit `FlyOidcShapeError`; probe closes it |
| SR2 — future deploy exposes the Fly app | S-115 | Committed `fly.toml` without a public service + release-gate check |
| SR3 — `effectiveStatus` drifts from the SQL view | S-104 | Layer 2.5 parity test |
| SR4 — F1 contract drifts again across TS/Python | S-112 | Shared JSON fixture consumed by both suites |
| SR5 — SSE relay leaks subscriptions | S-110 | Unsubscribe on abort; paired open/close logging |
| SR6 — `run_events` volume slows the viewer | S-109 | 2,000-event bound; record real counts for the v3 decision |
| SR7 — local dev writes to production Supabase | S-102, S-115 | Local stack via migrations; documented project targets |
| SR8 — `InvokeAgentRuntime` payload wrapping differs | S-112, S-115 | Confirm by observation; agent tolerates both |

### Non-Goals Validation

Confirmed **not** covered by any story (PRD §10, deferred to `prd-agent-fleet-panel-v3-ui-depth.md` or later):

- [x] All runs screen — S-106 renders it disabled, no route exists
- [x] Repositories screen — disabled nav item only
- [x] Settings screen — disabled nav item only
- [x] System health screen — disabled nav item only
- [x] User authentication / login / roles — explicitly excluded (D16, FR18)
- [x] Run cancellation — no UI, no route
- [x] Scheduled or webhook-triggered runs — manual invocation only
- [x] `findings` table / vulnerability browser — not modeled
- [x] `run_events` retention policy — R3 remains open
- [x] Run-history filters, search, repo chips, pagination — v3 C4
- [x] Log virtualization — v3 C13; the 2,000 bound is the Phase 2 answer
- [x] Steps timeline panel — v3 C8; `run_steps` read only to label log lines
- [x] RLS policy changes — deny-all preserved; policies belong to `prd-panel-auth-and-rls.md`
- [x] Agent code changes — the agent's payload contract is authoritative; the panel conforms

### Gaps

None. Two items are **carried, not gaps**:

- **AC8 cannot close before S-115.** S-111 defines and tests the credential contract; only a live Machine closes the acceptance criterion. Recorded in S-111's DoD rather than silently marked passing.
- **OQ2 (`prompt` wrapping) and OQ5 (Fly region/sizing)** are resolved by observation during S-112 and S-115 respectively, and must be written back to the spec with a changelog row.

---

## Execution Plan

**Wave 1 — foundations (parallelizable):** S-101 (workspace + gate) and S-102 (migrations + local stack) have no dependencies on each other. S-103 follows S-102 and must land **before** S-113, per spec §15 — building the form against a Spanish schema means rebuilding it.

**Wave 2 — platform:** S-104 (data layer + status parity) and S-105 (tokens + primitives) unlock everything visual. S-111 (credentials) can run in parallel with either.

**Wave 3 — screens:** S-106 → then S-107, S-108, S-109 in any order. S-110 follows S-109.

**Wave 4 — invocation:** S-112 (route + payload contract, closes #89) → S-113 (form).

**Wave 5 — verification and release:** S-114 (E2E) → S-115 (deploy, privacy gate, OIDC probe).

**Critical path:** S-101 → S-104 → S-105 → S-106 → S-109 → S-110 → S-114 → S-115, with S-102 → S-103 → S-112 → S-113 joining before Wave 5.

**Recommended first slice for `plan` + `verifier` Design Mode:** S-101, S-102, S-103 — they are the three stories with no UI dependency, they close three of the seven fix proposals (F6, F7, and F3-extended), and S-103 carries the only migrations in the phase, so its confirmation gate should be exercised while the change is small.
