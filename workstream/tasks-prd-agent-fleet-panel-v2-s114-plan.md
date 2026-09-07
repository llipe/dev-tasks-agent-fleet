# Implementation Plan - S-114 Playwright E2E + CI Layer-2.5 Gating (Issues #127, #134)

> **Source:** [`user-stories-prd-agent-fleet-panel-v2.md`](user-stories-prd-agent-fleet-panel-v2.md) Story S-114 · Issue [#127](https://github.com/llipe/dev-tasks-agent-fleet/issues/127)
> **Folded in:** Issue [#134](https://github.com/llipe/dev-tasks-agent-fleet/issues/134) — *make Layer 2.5 integration suites gating in CI* — as parent task 2.0. Both concern CI test reachability against the local Supabase stack, so they share the CI-workflow surface and are delivered together to avoid two competing edits to `.github/workflows/ci.yml`.
> **Scope:** E2E test suite + CI hardening. No product-code change expected (this story *is* tests + CI); no schema/data change (documented migration opt-out).
> **Dependencies (must be merged first):** S-110 (#123 — SSE relay + live tail; Scenarios 2/3 assert it), S-113 (#126 — schema-driven invoke form; Scenario 1/5 assert it, **merged**). S-114 therefore starts only **after S-110 lands**.
> **Package manager:** `pnpm` (workspace root). Canonical scripts only.

## Context Notes

> - **E2E is the only composition layer:** every other layer mocks at least one boundary. S-114 exercises invoke → run detail → live tail through the UI and the database, never through internal function calls (story Business Rules).
> - **AgentCore stubbed at the network boundary:** the invoke path exercises the *real* credential branch selection (local branch, SSO/env) but never calls AWS. Stub at the HTTP boundary, not by mocking `lib/aws/*`.
> - **Determinism is a hard requirement:** seeded fixtures + explicit waits, no machine-tuned sleeps; reset state between scenarios (`supabase db reset` or per-test transactional fixtures); no dependence on scenario order.
> - **Every scenario traces to a PRD AC or spec decision** (story Business Rules) — the scenario-to-AC table in `TESTING.md` is a deliverable, not a nicety.
> - **#134 is the reason a green CI is trustworthy:** today `status-parity`/`rls-deny-all` (and the S-103 reaper/seed suites, S-107 `dashboard-query`, S-108 `runs-by-agent`, S-109 `run-detail-queries`, S-110 `stream-e2e`) **skip vacuously** when Docker is absent. In CI a skip of those must be a **failure**. The distinction is CI-vs-local via an env signal (`REQUIRE_LOCAL_DB=1`), not by deleting `probeLocalDb`.
> - **The negative demonstrations are the real test of #134:** a gate never observed failing is not a proven gate. Break `effectiveStatus` → CI red via `status-parity`; grant `select` to `anon` → CI red via `rls-deny-all`; record both, then revert.
> - **Playwright config stub already exists** (`panel/playwright.config.ts`, `test:e2e` wired from S-101) — this story fills it in; it does not create it from scratch.

## Relevant Files

### S-114 (E2E)
- `panel/playwright.config.ts` - **Modified:** projects, base URL, web-server launch, headless-in-CI / headed-local, retries=0 (determinism), the seeded-stack global setup.
- `panel/tests/e2e/global-setup.ts` - Bring up / reset the local Supabase stack and seed the `dependency-update` agent + fixtures; expose readiness (explicit wait, not a sleep).
- `panel/tests/e2e/fixtures/agentcore-stub.ts` - HTTP-boundary stub for `InvokeAgentRuntime` (accepts the invoke, returns a run id path; never calls AWS) so the real credential branch runs.
- `panel/tests/e2e/fixtures/seed.ts` - Deterministic per-scenario DB seed/reset helpers (agents, repos, runs, events, artifacts).
- `panel/tests/e2e/invoke.spec.ts` - Scenario 1 (invoke → `/runs/[id]`, DB row `queued` + non-null timeout snapshots) and Scenario 5 (invalid param blocked, no `runs` row).
- `panel/tests/e2e/live-tail.spec.ts` - Scenario 2 (insert events → appear without reload, PRD AC6) and Scenario 3 (drop SSE mid-stream, insert during the gap, reconnect → no dup/gap, SD6).
- `panel/tests/e2e/stale-and-artifact.spec.ts` - Scenario 4 (stale `running` → `timed_out` with reaper off, PRD AC10) and Scenario 7 (failed run + `pull_request` artifact shows the link, PRD AC14).
- `panel/tests/e2e/density.spec.ts` - Scenario 6 (density toggle survives reload, PRD AC9).
- `panel/tests/integration/e2e-fixture.smoke.test.ts` - Layer 2.5 smoke that the seeding/reset fixture helper itself works (story Testing Requirements).

### #134 (CI Layer-2.5 gating)
- `.github/workflows/ci.yml` - **Modified:** in the panel job, start a local Supabase stack + apply `supabase/migrations/` + `supabase/seed.sql` before the JS/TS test branch; set `REQUIRE_LOCAL_DB=1`; run E2E (or record its gating reason).
- `panel/tests/integration/db.ts` - **Modified:** honor `REQUIRE_LOCAL_DB` — when set, a probe failure or a skipped Docker-gated project is a hard **failure**, not a skip. Local behavior (unset) unchanged.
- `TESTING.md` - **Modified:** the CI-vs-local skip policy + the S-114 scenario-to-AC traceability table.

### Docs
- `docs/technical-guidelines.md` - §11 (test surface) + changelog entry (technical-writer at the doc gate).

## Tasks

- [ ] 1.0 Implement Story S-114 - [#127](https://github.com/llipe/dev-tasks-agent-fleet/issues/127): Playwright E2E against the local stack

  ### Branch & PR setup
  - [ ] 1.1 Verify HEAD is not `main`; create feature branch `story/S-114-e2e-and-ci-gating` off the latest `main` **after S-110 (#123) is merged** (delegate naming/creation to `github-ops`).
  - [ ] 1.2 After the first commit, open a **draft PR** targeting `main` (delegate to `github-ops`); PR body via `--body-file`, includes `Closes #127` **and** `Closes #134`; title Conventional Commits (`test: implement S-114 E2E suite and make Layer 2.5 gating in CI`).
  - [ ] 1.3 Sync issues #127 and #134 checklists with this task list (delegate to `github-ops`).

  ### Harness: config, seeding, AgentCore stub (Impl Step 1)
  - [ ] 1.4 Fill in `playwright.config.ts`: projects, base URL, `webServer` launching `pnpm --filter panel dev` (or a built server), `retries: 0`, headless in CI / headed locally, wired to `global-setup.ts`.
  - [ ] 1.5 Implement `tests/e2e/global-setup.ts`: bring up / `supabase db reset` the local stack, apply `supabase/migrations/` + `supabase/seed.sql`, wait for readiness with an explicit poll (no sleep), and fail fast with a clear message if the stack is unavailable.
  - [ ] 1.6 Implement `tests/e2e/fixtures/agentcore-stub.ts`: stub `InvokeAgentRuntime` at the HTTP boundary so the invoke path runs the real credential branch selection but never calls AWS; returns a deterministic accept.
  - [ ] 1.7 Implement `tests/e2e/fixtures/seed.ts`: deterministic seed/reset helpers for agents/repos/runs/events/artifacts; no cross-scenario order dependence.
  - [ ] 1.8 Add the Layer 2.5 smoke (`tests/integration/e2e-fixture.smoke.test.ts`) covering the seeding/reset helper itself (story Testing Requirements).

  ### Scenarios 1–2, then 3 (Impl Step 2 — reconnect needs deliberate connection control)
  - [ ] 1.9 Scenario 1 — invoke (PRD AC12): fill the form, submit, land on `/runs/[id]`; assert the `runs` row exists with `status='queued'` and all timeout snapshots (`max_runtime_seconds`/`grace_seconds`/`start_timeout_seconds`) non-null.
  - [ ] 1.10 Scenario 2 — live tail (PRD AC6): with run detail open, insert `run_events` rows; assert they appear with no reload.
  - [ ] 1.11 Scenario 3 — reconnect (SD6): drop the SSE connection mid-stream (deliberate connection control via the browser context / route interception), insert events during the gap, reconnect; assert no duplicates and no gaps after reconnect.

  ### Scenarios 4–7 (Impl Step 3)
  - [ ] 1.12 Scenario 4 — stale run (PRD AC10): a `running` run past its threshold displays `timed_out` with the reaper **not** running (read-time `effective_status` via `v_runs`).
  - [ ] 1.13 Scenario 5 — validation (PRD AC13): an invalid param submission is blocked and **no** `runs` row is created.
  - [ ] 1.14 Scenario 6 — density toggle (PRD AC9): switch variant, reload, assert the selection survived (localStorage vocabulary from S-107).
  - [ ] 1.15 Scenario 7 — artifact on a failed run (PRD AC14): a seeded `failed` run with a `pull_request` artifact shows the link.
  - [ ] 1.16 Cover the E2E edge-case matrix: empty database (no agents) → dashboard empty state; a run with zero events → detail opens without a stream error; two browser contexts tailing the same run; CI cold start where the stack is not ready → explicit wait, not a flake.

  ### Acceptance-criteria verification (S-114)
  - [ ] 1.17 Verify AC1: Playwright runs against the local stack with the seeded `dependency-update` agent and AgentCore stubbed at the network boundary (no real AWS call).
  - [ ] 1.18 Verify AC2–AC8 map: Scenario 1→AC12, 2→AC6, 3→SD6, 4→AC10, 5→AC13, 6→AC9, 7→AC14 — each scenario green and asserting through UI + DB only.
  - [ ] 1.19 Verify the story's `test:e2e` reachability AC: `test:e2e` is reachable from `make validate` **or** explicitly gated with a recorded reason; the scenario-to-AC traceability table is in `TESTING.md`.
  - [ ] 1.20 Manual/UI: one **headed** run of all seven scenarios to confirm the assertions match what a human sees (story Testing Requirements).
  - [ ] 1.21 Produce the acceptance-criteria → test-evidence mapping (Scenarios 1–7 → PRD ACs) in the PR.

- [ ] 2.0 Fold in Issue [#134](https://github.com/llipe/dev-tasks-agent-fleet/issues/134): make Layer 2.5 integration suites gating in CI

  > Note: no assertion in any existing integration suite changes (#134 Non-Goals). This is reachability + a CI-vs-local skip policy only.

  - [ ] 2.1 Modify `panel/tests/integration/db.ts`: when `REQUIRE_LOCAL_DB=1`, a `probeLocalDb` failure (and a Docker-gated project that would otherwise skip) is a hard **failure** naming which suite and why a skip is unacceptable in CI; when unset (local), keep the existing skip-with-recorded-reason behavior intact.
  - [ ] 2.2 Modify `.github/workflows/ci.yml` (panel job): start the local Supabase stack (`supabase start` / `db reset`, or the equivalent service container) and apply `supabase/migrations/` + `supabase/seed.sql` **before** the JS/TS test branch; export the local DB env + `REQUIRE_LOCAL_DB=1`.
  - [ ] 2.3 Ensure the S-103 integration suites (`reaper.test.ts`, `seed-schema.test.ts`, `schema.test.ts`) and every later Layer 2.5 suite (`queries`, `status-parity`, `rls-deny-all`, `dashboard-query`, `runs-by-agent`, `run-detail-queries`, `stream-e2e`) are covered by the same CI policy — i.e. a skip of any of them in CI fails the job.
  - [ ] 2.4 Verify #134 AC (negative demo A): a deliberately broken `effectiveStatus` (inverted comparison) makes CI red via `status-parity.test.ts` — demonstrate once, capture the red run as evidence, then revert. Record in the PR.
  - [ ] 2.5 Verify #134 AC (negative demo B): a deliberately granted `select` to `anon` makes CI red via `rls-deny-all.test.ts` — demonstrate once, capture evidence, then revert. Record in the PR.
  - [ ] 2.6 Verify #134 AC (local ergonomics preserved): local `make validate` **without** Docker still succeeds, printing the skip reason (run it with Docker stopped and record the output).
  - [ ] 2.7 Verify #134 AC (runtime impact): record the CI job's added runtime from starting the stack; note it rather than silently accepting it.
  - [ ] 2.8 Update `TESTING.md`: record the CI-vs-local skip policy (so the next Layer 2.5 suite inherits it by convention) **and** the S-114 scenario-to-AC traceability table.

  ### Quality gates & closeout (covers both #127 and #134)
  - [ ] 2.9 Run tests: `pnpm run test` (unit + component), `pnpm run test:integration` (Layer 2.5, live with the stack up), and `pnpm run test:e2e`; then `make validate` at the repo root (both branches must pass).
  - [ ] 2.10 `qa-engineer` pass — this is the story that closes the standing G2 obligation, so `qa-engineer` confirms the Layer 2.5 projects are genuinely gating (both negative demos observed) and records `coverage_gate` PASS/FAIL/SKIPPED(reason). `TESTING.md` updates land here.
  - [ ] 2.11 `technical-writer` doc-drift check; update `docs/technical-guidelines.md` §11 (test surface — E2E row now configured; the "standing G2 obligation" note in §11 flipped to resolved) + changelog. No new ADR expected (E2E + CI reachability trace to spec §14 and the pre-existing G2 decision).
  - [ ] 2.12 Run `verifier` in **audit** mode against the delivered suite + CI change; post the human-readable summary to issues/PR (mandatory, non-blocking on drift). Confirm the scenario-to-AC traceability is complete and each scenario is non-vacuous.
  - [ ] 2.13 Convert PR from draft to ready for review; notify the user for review/merge. Do not close #127 or #134 until the PR is approved AND merged.

## Notes

- **Migration lifecycle: N/A** — no schema/data-model change (documented opt-out). The CI change *applies* existing migrations; it does not author new ones.
- **Sequencing:** this plan is blocked on S-110 (#123). Do not start branch work until S-110 is merged, because Scenarios 2/3 assert the SSE relay S-110 delivers.
- **Why #134 rides with S-114:** both edit `.github/workflows/ci.yml` around the local-stack lifecycle, and S-114's E2E run needs the same started-stack CI step #134 introduces. Delivering them separately would mean two conflicting CI edits within days. If the reviewer prefers, #134's task group (2.0) can be split into its own PR merged first — flagged as a reviewer option, default is one PR closing both.
- **Determinism gate:** `retries: 0` in Playwright is deliberate — a scenario that only passes on retry is a flake to fix, not to paper over (story Business Rules).
- **No new product code:** if a scenario cannot be asserted without a new DOM hook, add a minimal stable `data-*` attribute to the relevant component rather than restructuring — and record it as intended drift for the verifier.
