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
  - [x] 1.1 Verify HEAD is not `main`; create feature branch `story/S-114-e2e-and-ci-gating` off the latest `main` **after S-110 (#123) is merged** (delegate naming/creation to `github-ops`).
  - [x] 1.2 After the first commit, open a **draft PR** targeting `main` (delegate to `github-ops`); PR body via `--body-file`, includes `Closes #127` **and** `Closes #134`; title Conventional Commits (`test: implement S-114 E2E suite and make Layer 2.5 gating in CI`). → PR #153
  - [x] 1.3 Sync issues #127 and #134 checklists with this task list (delegate to `github-ops`).

  ### Harness: config, seeding, AgentCore stub (Impl Step 1)
  - [x] 1.4 Fill in `playwright.config.ts`: projects, base URL, `webServer` launching `pnpm --filter panel dev` (or a built server), `retries: 0`, headless in CI / headed locally, wired to `global-setup.ts`.
  - [x] 1.5 Implement `tests/e2e/global-setup.ts`: bring up / `supabase db reset` the local stack, apply `supabase/migrations/` + `supabase/seed.sql`, wait for readiness with an explicit poll (no sleep), and fail fast with a clear message if the stack is unavailable.
  - [x] 1.6 Implement `tests/e2e/fixtures/agentcore-stub.ts`: stub `InvokeAgentRuntime` at the HTTP boundary so the invoke path runs the real credential branch selection but never calls AWS; returns a deterministic accept.
  - [x] 1.7 Implement `tests/e2e/fixtures/seed.ts`: deterministic seed/reset helpers for agents/repos/runs/events/artifacts; no cross-scenario order dependence.
  - [x] 1.8 Add the Layer 2.5 smoke (`tests/integration/e2e-fixture.smoke.test.ts`) covering the seeding/reset helper itself (story Testing Requirements).

  ### Scenarios 1–2, then 3 (Impl Step 2 — reconnect needs deliberate connection control)
  - [x] 1.9 Scenario 1 — invoke (PRD AC12): fill the form, submit, land on `/runs/[id]`; assert the `runs` row exists with `status='queued'` and all timeout snapshots (`max_runtime_seconds`/`grace_seconds`/`start_timeout_seconds`) non-null. → `invoke.spec.ts`, passes live.
  - [x] 1.10 Scenario 2 — live tail (PRD AC6): with run detail open, insert `run_events` rows; assert they appear with no reload. → `live-tail.spec.ts`, passes live.
  - [x] 1.11 Scenario 3 — reconnect (SD6): drop the SSE connection mid-stream (via `context.setOffline`), insert events during the gap, reconnect; assert no duplicates and no gaps after reconnect. → `live-tail.spec.ts`, passes live.

  ### Scenarios 4–7 (Impl Step 3)
  - [x] 1.12 Scenario 4 — stale run (PRD AC10): a `running` run past its threshold displays `timed_out` (banner "Run timed out" + pill) with the reaper **not** running (read-time `effective_status` via `v_runs`). → `stale-and-artifact.spec.ts`, passes live.
  - [x] 1.13 Scenario 5 — validation (PRD AC13): an invalid param submission is blocked and **no** `runs` row is created. → `invoke.spec.ts`, passes live.
  - [x] 1.14 Scenario 6 — density toggle (PRD AC9): switch variant, reload, assert the selection survived (localStorage vocabulary from S-107). → `density.spec.ts`, passes live.
  - [x] 1.15 Scenario 7 — artifact on a failed run (PRD AC14): a seeded `failed` run with a `pull_request` artifact shows the link. → `stale-and-artifact.spec.ts`, passes live.
  - [x] 1.16 Cover the E2E edge-case matrix: empty database (no agents) → dashboard empty state; a run with zero events → detail opens without a stream error; two browser contexts tailing the same run; CI cold start where the stack is not ready → explicit wait, not a flake. → `edge-cases.spec.ts` (3 tests) + `global-setup.ts` readiness poll; all pass live.

  ### Acceptance-criteria verification (S-114)
  - [x] 1.17 Verify AC1: Playwright runs against the local stack with the seeded `dependency-update` agent and AgentCore stubbed at the network boundary (no real AWS call). → confirmed: invoke logs show `credential_source: local-chain` reaching the stub, 202, no AWS call.
  - [x] 1.18 Verify AC2–AC8 map: Scenario 1→AC12, 2→AC6, 3→SD6, 4→AC10, 5→AC13, 6→AC9, 7→AC14 — each scenario green and asserting through UI + DB only. → all 10 E2E tests pass live.
  - [x] 1.19 Verify the story's `test:e2e` reachability AC: `test:e2e` is **explicitly gated** (needs a browser + running stack) — reached from CI's dedicated E2E step, not `make validate` (which stays browser-free). Recorded reason in `TESTING.md`; scenario-to-AC traceability table in `TESTING.md`.
  - [x] 1.20 Manual/UI: one real-browser run of all seven scenarios (via `PW_CHANNEL=chrome` against installed Chrome) confirmed the assertions match what a human sees. → 10 passed.
  - [x] 1.21 Produce the acceptance-criteria → test-evidence mapping (Scenarios 1–7 → PRD ACs) in the PR. → scenario-to-AC table in `TESTING.md` + PR #153 body + verifier per-AC table.

- [ ] 2.0 Fold in Issue [#134](https://github.com/llipe/dev-tasks-agent-fleet/issues/134): make Layer 2.5 integration suites gating in CI

  > Note: no assertion in any existing integration suite changes (#134 Non-Goals). This is reachability + a CI-vs-local skip policy only.

  - [x] 2.1 Modify `panel/tests/integration/db.ts`: when `REQUIRE_LOCAL_DB=1`, a `probeLocalDb` failure is a hard **failure** naming why a skip is unacceptable in CI; when unset (local), keep the existing skip-with-recorded-reason behavior intact. → enforced in `probeLocalDb` (throws), applied uniformly since every suite calls it at module load. Both behaviors verified.
  - [x] 2.2 Modify `.github/workflows/ci.yml` (panel job): start the local Supabase stack + apply `supabase/migrations/` + `supabase/seed.sql` **before** the JS/TS test branch; export the local DB env + `REQUIRE_LOCAL_DB=1`. → done (supabase/setup-cli, `supabase start`, `db reset`, env export, E2E step).
  - [x] 2.3 Ensure the S-103 integration suites (`reaper.test.ts`, `seed-schema.test.ts`, `schema.test.ts`) and every later Layer 2.5 suite are covered by the same CI policy — a skip of any fails the job. → covered uniformly: enforcement lives in the shared `probeLocalDb`, verified all 13 files fail with the gate on + stack down.
  - [x] 2.4 Verify #134 AC (negative demo A): a broken `effectiveStatus` makes CI red via `status-parity.test.ts` — demonstrated once, captured, reverted. → recorded in `workstream/s114-negative-demos.md`.
  - [x] 2.5 Verify #134 AC (negative demo B): a permissive `anon` SELECT policy makes CI red via `rls-deny-all.test.ts` — demonstrated once, captured, reverted. → recorded in `workstream/s114-negative-demos.md`.
  - [x] 2.6 Verify #134 AC (local ergonomics preserved): local `make validate` **without** Docker still skips with a recorded reason (verified via a dead DB port — 13 files skip, no failure); `make validate` with the stack up exits 0.
  - [x] 2.7 Verify #134 AC (runtime impact): recorded — CI adds `supabase/setup-cli` + `supabase start` + `db reset` + `playwright install --with-deps chromium` + the E2E run to the panel job (roughly 2–4 min of stack/browser provisioning on a GitHub Ubuntu runner). Noted in the PR, not silently accepted.
  - [x] 2.8 Update `TESTING.md`: record the CI-vs-local skip policy **and** the S-114 scenario-to-AC traceability table.

  ### Quality gates & closeout (covers both #127 and #134)
  - [x] 2.9 Run tests: `pnpm run test` (unit + component), `pnpm run test:integration` (Layer 2.5, live with the stack up), and `pnpm run test:e2e`; then `make validate` at the repo root (both branches must pass). → `make validate` exits 0 (Python 452, panel 773/4 skipped); E2E 10 passed live.
  - [x] 2.10 `qa-engineer` pass — closes the standing G2 obligation; confirmed both negative demos observed and recorded `coverage_gate` **PASS**. `TESTING.md` updates landed.
  - [x] 2.11 `technical-writer` doc-drift check; updated `docs/technical-guidelines.md` §11 (E2E row configured; G2 obligation flipped to resolved) + changelog row 1.23. No new ADR (traces to spec §14 + pre-existing G2 decision). Also reconciled stale S-106/S-108 forward-refs to the 1024px check.
  - [x] 2.12 Ran `verifier` in **audit** mode; posted the human-readable summary to PR #153 + issues #127/#134. Verdict HIGH, 9/9 ACs Pass, highest drift Minor (all Intended), non-blocking. Scenario-to-AC traceability confirmed complete + non-vacuous.
  - [ ] 2.13 Convert PR from draft to ready for review; notify the user for review/merge. Do not close #127 or #134 until the PR is approved AND merged.

- [x] 2.0 (parent) Fold in Issue #134 — all sub-tasks complete.

- [x] 1.0 (parent) Implement Story S-114 — Playwright E2E against the local stack — all sub-tasks complete except closeout (2.13, awaiting user review/merge).

## Notes

- **Migration lifecycle: N/A** — no schema/data-model change (documented opt-out). The CI change *applies* existing migrations; it does not author new ones.
- **Sequencing:** this plan is blocked on S-110 (#123). Do not start branch work until S-110 is merged, because Scenarios 2/3 assert the SSE relay S-110 delivers.
- **Why #134 rides with S-114:** both edit `.github/workflows/ci.yml` around the local-stack lifecycle, and S-114's E2E run needs the same started-stack CI step #134 introduces. Delivering them separately would mean two conflicting CI edits within days. If the reviewer prefers, #134's task group (2.0) can be split into its own PR merged first — flagged as a reviewer option, default is one PR closing both.
- **Determinism gate:** `retries: 0` in Playwright is deliberate — a scenario that only passes on retry is a flake to fix, not to paper over (story Business Rules).
- **No new product code:** if a scenario cannot be asserted without a new DOM hook, add a minimal stable `data-*` attribute to the relevant component rather than restructuring — and record it as intended drift for the verifier.
