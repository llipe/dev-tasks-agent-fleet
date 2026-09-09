---
version: alpha
name: Testing Standard
description: Canonical testing contract for this repository — declares what to test at which layer, which commands to run, and how coverage is judged.
status: filled
---

<!--
FILLED by qa-engineer from repository inspection. This file is the canonical
testing contract for this repository — the layer taxonomy and section structure
are fixed; the values are project-specific and reflect what actually exists in
the repo at fill time.

Content here is preserved: this file is listed in `consumer_owned_paths`, so
`dev-tasks update` will never overwrite it. Owned by `qa-engineer`; `developer`
keeps it current when the testing contract changes.

Findings recorded below are gaps, not satisfied requirements. Where a gate has
no tooling it is stated plainly and marked as a finding — absence of tooling is
never reported as a pass.
-->

## Test Layers

The layer taxonomy below is fixed. What belongs in each layer is project-specific.

| Layer    | Name                      | Scope                                                                                 | Status            |
| -------- | ------------------------- | ------------------------------------------------------------------------------------- | ----------------- |
| 1        | Deterministic foundations | Unit tests, schema validation. No I/O, no network, no real database.                  | active — `tests/unit/` (pytest `unit` marker); covers `scrubber.py`, `credentials.py`, `toolchain.py`, `validator.py`, `eligibility.py`, `classifier.py`, `fix_agent.py` (`_safe_path`, mandate check, fix tools), and `pull_request.py` (PR-body builder + branch naming). |
| 2        | Constrained model/tool    | Backend component tests, mocked APIs, fixtures and gold datasets.                     | active — `tests/component/` holds ~56 tests across `test_pipeline.py`, `test_pr_creation.py`, and `test_fix_agent.py` (mocked `git`/`gh`/`subprocess`, Secrets Manager, PostgREST, and the Strands `Agent`). `tests/fixtures/` still holds no recorded payloads (`.gitkeep` only). |
| 2.5      | Integration               | Real database, real migrations, RLS policies, schema contracts. No mocked data layer. | **configured (S-102 / #115)** — harness is Vitest's `integration` project in `panel` (`panel/tests/integration/`, runner Vitest 3.2.4), talking to a **real local Postgres** brought up by the Supabase CLI (`supabase start` / `supabase db reset` against `supabase/migrations/` + `supabase/seed.sql`). `panel/tests/integration/schema.test.ts` asserts `v_runs` exists, carries `effective_status`, and that `reap_stale_runs()` is callable. Docker-gated via `panel/tests/integration/db.ts` (`probeLocalDb`): when the local stack is unreachable the suite skips with a recorded reason instead of failing `make validate`. Reachable from the repo-root `make validate` JS/TS branch: `make validate` → panel `validate` → `test` (`vitest run`), which executes **all** Vitest projects including `integration` (the `test:integration` script is the same project, run standalone). The production `pg_cron` schedule and `v_runs` read-time contract (issue #94) remain additionally verified by live operator SQL (`docs/runbooks/issue-94-reaper-verification.md`). |
| E2E      | End-to-end                | Playwright CLI — committed browser automation, full-stack, scenario-driven.           | **configured (S-114 / #127)** — `panel/playwright.config.ts` + `panel/tests/e2e/` hold seven scenarios (plus an edge-case file) driving invoke → run detail → live tail through the browser against the **real** local Supabase stack, with AgentCore stubbed at the HTTP boundary (`tests/e2e/fixtures/agentcore-stub.ts`) so the real credential branch runs but no AWS call is made. `test:e2e` is **gated separately** (it needs a browser + a running stack): CI runs it in a dedicated step after `playwright install --with-deps chromium`; it is intentionally NOT part of `make validate`, which stays browser-free. See the scenario-to-AC table below. |
| Contract | Contract validation       | API spec drift, breaking-change detection, consumer impact. `dt verify` family.       | not configured — no OpenAPI/AsyncAPI spec in repo; `dt` not wired. |
| 3        | Product evaluation        | Semantic, tone, groundedness, hallucination evals. Only for LLM features.             | not configured — the agent uses an LLM (`strands-agents`) in `fix_agent.py`. `fix_agent.py` now has Layer 1 + Layer 2 tests (with the model mocked), but no semantic/groundedness eval harness exists. Finding: the LLM output quality is unevaluated. |
| 4        | Human evaluation          | Review gates, safeguards, risk alerts.                                                | out of band — human PR review is the enforcement backstop (see git-guard). No automated gate in repo. |

Integration, end-to-end, and contract validation layers are declared per project
in the table below when they exist.

### Layer boundaries

State explicitly what must **not** be tested at each layer, so the boundary is
enforceable rather than aspirational.

- **Layer 1 must not:** perform network calls, filesystem I/O, subprocess execution, or touch AWS/Supabase/GitHub. All boto3, `requests`, `jwt`, and `subprocess` interactions are patched with `unittest.mock`/`pytest-mock`. A Layer 1 test that reaches a real Secrets Manager, PostgREST, or the GitHub API is misfiled and must move to Layer 2 or higher.
- **Layer 2 must not:** call real external services. Component tests mock AWS (`secretsmanager`), PostgREST (`requests`), the GitHub App token endpoint, and any `git`/`gh`/`pnpm` subprocess. A component test that reimplements the logic of the module it exercises (e.g. re-deriving JWT claims or re-writing the scrub regex) is validating the mock, not the code.
- **Layer 2.5 must not:** mock the data layer. If the database is mocked, the test belongs at Layer 2. If the test hits a live external service over the network, it may belong at E2E or remote integration.
- **E2E must not:** assert on internal state or implementation details. Assertions are on observable user-facing behavior only.
- **Contract validation must not:** test internal business logic. It checks the boundary/interface only.
- **Escalation rule** — when a Layer 1 test needs a real dependency, it moves up
  a layer rather than growing a test double that reimplements the dependency.
  When a Layer 2 test needs a real database, it moves to Layer 2.5.

## CI-vs-local Layer 2.5 gating (#134)

The Layer 2.5 (`integration`) suites talk to a real local Postgres and are
**Docker-gated** by `panel/tests/integration/db.ts` (`probeLocalDb`). The gating
policy differs by environment, controlled by a single env signal
`REQUIRE_LOCAL_DB`:

- **Local (unset).** When the stack is unreachable the suites **skip with a
  recorded reason** — a missing Docker daemon must never redden a developer's
  `make validate`. This is unchanged, long-standing behavior.
- **CI (`REQUIRE_LOCAL_DB=1`).** A probe failure is a hard **failure**, not a
  skip. `probeLocalDb` throws when the stack is unreachable, and because every
  Layer 2.5 suite calls it at module top-level, that throw fails the test file.
  A green CI therefore means the DB-boundary assertions **actually ran** — a
  skip is not evidence. This applies uniformly to every current suite
  (`schema`, `seed-schema`, `reaper`, `queries`, `status-parity`,
  `rls-deny-all`, `dashboard-query`, `runs-by-agent`, `run-detail-queries`,
  `stream-e2e`, `invoke-insert`, `synthetic-agent-form`, `e2e-fixture.smoke`)
  **and to every future one by convention** — a new Layer 2.5 suite inherits the
  gate for free simply by calling `probeLocalDb()`.

The CI workflow (`.github/workflows/ci.yml`, panel job) starts the stack
(`supabase start`), applies `supabase/migrations/` + `supabase/seed.sql`
(`supabase db reset`), exports the local Supabase env, and sets
`REQUIRE_LOCAL_DB=1` before the JS/TS test branch. Runtime impact: the added
stack + browser provisioning is roughly 2–4 minutes on a GitHub Ubuntu runner
(noted, not silently accepted).

**The gates are proven by negative demonstration**, not just by passing: a
broken `effectiveStatus` (inverted comparison) turns `status-parity.test.ts`
red, and a permissive `anon` SELECT policy turns `rls-deny-all.test.ts` red.
Both were demonstrated once and reverted (evidence:
`workstream/s114-negative-demos.md`). A gate never observed failing is not a
proven gate.

## E2E scenario-to-AC traceability (S-114 / #127)

Every scenario asserts through the UI **and** the database only — never through
internal function calls. AgentCore is stubbed at the HTTP boundary, so the real
credential branch selection runs but no AWS call is made.

| Scenario (file) | Asserts | PRD AC / decision |
| --- | --- | --- |
| Scenario 1 (`invoke.spec.ts`) | valid invoke → navigates to `/runs/[id]`; `runs` row is `queued` with all three timeout snapshots non-null | AC12 (D1 / OQ3) |
| Scenario 2 (`live-tail.spec.ts`) | events inserted after the page is open appear with no reload | AC6 (FR12) |
| Scenario 3 (`live-tail.spec.ts`) | drop the SSE connection mid-stream, insert during the gap, reconnect → every event exactly once, in `seq` order, no gap | SD6 |
| Scenario 4 (`stale-and-artifact.spec.ts`) | a `running` run past its threshold reads `timed_out` (banner + pill) with the reaper **off** (read-time `v_runs.effective_status`) | AC10 (SD4) |
| Scenario 5 (`invoke.spec.ts`) | an invalid param submission is blocked; **no** `runs` row is created (server-authoritative) | AC13 |
| Scenario 6 (`density.spec.ts`) | density variant selection survives a reload (S-107 localStorage vocabulary) | AC9 |
| Scenario 7 (`stale-and-artifact.spec.ts`) | a `failed` run still shows its `pull_request` artifact link (https-only, `rel=noopener`) | AC14 |
| Edge cases (`edge-cases.spec.ts`) | empty fleet → dashboard empty state; zero-event run → detail opens with no stream error; two contexts tail the same run | EC-19, robustness |



One row per package. In a single-package repository this table has one row.
A package's language determines its runner and commands — a non-JS package is
described in its own terms, not forced into JavaScript script names.

| Package                                              | Language          | Runner   | Test command                                   | Test environment                          | Coverage tooling                    |
| ---------------------------------------------------- | ----------------- | -------- | ---------------------------------------------- | ----------------------------------------- | ----------------------------------- |
| `dependency-update` (`agents/dependency-update/app/dependencyUpdate/`) | Python `>=3.13` | pytest 8.3.5 | `python -m pytest` (from the package dir; `testpaths=["tests"]`) | Local CPython process, no DB/network; all external I/O mocked | pytest-cov 7.1.0 (branch coverage) — see Coverage §, gate is MEASURED (~90%+ on implemented modules; no `fail_under` floor yet) |
| `agentcore-cdk-app` (`agents/dependency-update/agentcore/cdk/`) | TypeScript | jest 29 (ts-jest) | `pnpm test` / `npm test` (→ `jest`) | Node (jest default); CDK `Template` synth assertions | none configured (no `@vitest/coverage`/`nyc`, no `--coverage` wired) |
| `panel` (`panel/`) | TypeScript (Next.js 15, React 19) | Vitest 3.2.4 + Playwright 1.56.0 | `pnpm --filter panel run test` (→ `vitest run`); `test:e2e` (→ `playwright test`) gated separately; reachable from repo-root `make validate` via the JS/TS branch (E2E excluded — needs a browser) | Node (unit + integration projects) + jsdom (component project); Layer 2.5 `integration` project talks to a **real local Postgres** via the Supabase CLI stack (S-102), Docker-gated (skips with a recorded reason locally; a skip is a **failure** in CI via `REQUIRE_LOCAL_DB=1`, #134). E2E (S-114) drives the browser against the same real stack with AgentCore stubbed at the HTTP boundary | `@vitest/coverage-v8` 3.2.4 (`pnpm --filter panel run test:coverage`) |

> **Scope note.** The `dependency-update` Python package is the active codebase and the subject of this standard. `agentcore-cdk-app` is infrastructure-as-code with a single CDK synth smoke test (`test/cdk.test.ts`); it is listed for completeness and reachability accounting, not as a primary test target. The Next.js frontend (`panel`, Phase 2) **now exists in the repo** as of S-101 (#114) — its JS/TS test package uses Vitest projects (unit/component/integration) + a Playwright E2E config stub, reachable from the repo-root `make validate` JS/TS branch; the scenario suites fill in across later Phase 2 stories.

### Test environment

**`dependency-update` (Python).** Tests run in a plain local CPython interpreter with no database, no network, and no browser. The package has no UI, so no `jsdom`/DOM environment applies. Every external boundary — AWS Secrets Manager (`boto3`), Supabase PostgREST (`requests`), the GitHub App access-token endpoint (`requests`), JWT signing (`jwt`), and `subprocess` — is patched via `unittest.mock.patch`/`pytest-mock`. A `conftest.py` provides temp-dir project fixtures for the `toolchain.py`/`validator.py` tests and auto-applies layer markers by directory; there is no `setupFiles`-style global setup beyond that. Mock lifetimes are scoped by decorator/context-manager, so they auto-restore per test.

**`agentcore-cdk-app` (TypeScript).** Runs under jest's default Node environment; the single test synthesizes a CDK stack and asserts on the CloudFormation template. No DOM environment needed.

### Runtime parity

| Package             | Local                | CI                | Production / runtime          |
| ------------------- | -------------------- | ----------------- | ----------------------------- |
| `dependency-update` | CPython **3.13.0** (dev venv at `.venv`, `pyvenv.cfg`) | **3.13 + 3.14 matrix** (`.github/workflows/ci.yml`) | **PYTHON_3_14** (`agentcore/agentcore.json` → `runtimeVersion`); Docker build base is `python:3.13-slim` (`Dockerfile`) |
| `agentcore-cdk-app` | Node (unpinned locally) | not in CI yet | n/a — build/deploy tooling, not a runtime target |

> **FINDING — runtime parity divergence (`dependency-update`), MITIGATED by CI.** Three Python runtimes are in play: tests are authored locally on **3.13.0**, the container image builds on **python:3.13-slim**, and AgentCore executes as **PYTHON_3_14**. `pyproject.toml` pins only `requires-python = ">=3.13"`. This is now mitigated: `ci.yml` runs the full quality gate on a **3.13 + 3.14 matrix**, so every PR proves the suite passes on the production runtime, not just the dev one (the current 328-test suite passes on both). Remaining lower-priority cleanup: align the Docker base to `python:3.14-slim` to match AgentCore exactly, and consider tightening the `requires-python` floor.

## Commands

### JavaScript / TypeScript default

Canonical script names for JS/TS packages. Prefer `pnpm`.

| Script             | Purpose                                   | Required            |
| ------------------ | ----------------------------------------- | ------------------- |
| `lint`             | Static analysis                           | yes                 |
| `lint:fix`         | Auto-fix lint findings                    | no                  |
| `format`           | Write formatting                          | no                  |
| `format:check`     | Verify formatting                         | yes                 |
| `typecheck`        | Type analysis                             | yes                 |
| `test`             | Aggregate — MUST reach every test package | yes                 |
| `test:unit`        | Layer 1                                   | yes                 |
| `test:integration` | Layer 2.5 — real database integration     | when present        |
| `test:e2e`         | E2E layer — Playwright browser automation | when present        |
| `test:contract`    | Contract validation — `dt verify` family  | when present        |
| `test:coverage`    | Coverage measurement                      | when tooling exists |
| `audit`            | Dependency vulnerability scan             | yes                 |
| `validate`         | Aggregate quality gate                    | yes                 |

### Non-JS packages

Declare each non-JS package's equivalent commands here. The canonical names
above are a JS/TS convention, not a cross-language requirement — what matters is
that every package has a discoverable command per purpose and that the aggregate
test command reaches it.

| Package             | Purpose                       | Command                                                                              |
| ------------------- | ----------------------------- | ------------------------------------------------------------------------------------ |
| `dependency-update` | Install dev deps              | `make install` → `pip install -e '.[dev]'` (pytest, pytest-mock, pytest-cov, ruff, mypy, pip-audit) |
| `dependency-update` | Run all tests                 | `make test` → `python -m pytest` (run from `agents/dependency-update/app/dependencyUpdate/`; `testpaths=["tests"]`) |
| `dependency-update` | Layer 1 only (unit)           | `make test-unit` → `python -m pytest -m unit`                                       |
| `dependency-update` | Layer 2 only (component)      | `make test-component` → `python -m pytest -m component` (~56 component tests across `test_pipeline.py`, `test_pr_creation.py`, `test_fix_agent.py`) |
| `dependency-update` | Lint                          | `make lint` → `ruff check .` (autofix: `make lint-fix`)                              |
| `dependency-update` | Format / format check         | `make format` → `ruff format .`; check-only: `make format-check` → `ruff format --check .` |
| `dependency-update` | Typecheck                     | `make typecheck` → `mypy .`                                                          |
| `dependency-update` | Coverage                      | `make test-cov` → `python -m pytest --cov --cov-report=term-missing` (branch coverage; config in `[tool.coverage]`) |
| `dependency-update` | Audit (dependency vuln scan)  | `make audit` → `pip-audit . --strict` (audits declared runtime deps, not ambient venv tooling) |
| `dependency-update` | **Aggregate gate**            | `make validate` → lint + format-check + typecheck + test-cov + audit (fail-fast)     |

> **RESOLVED (was: no quality toolchain).** As of the `chore/python-quality-toolchain` change, the Python package has a full toolchain, all pinned in `pyproject.toml [dev]`: **ruff 0.16.4** (lint + format), **mypy 2.3.1** (typecheck), **pip-audit 2.10.1** (vuln scan), **pytest-cov 7.1.0** (coverage). Tool config lives in `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`, `[tool.coverage]`). A `Makefile` in the package dir provides the canonical targets and the `validate` aggregate. Current state: `make validate` passes clean (lint ✓, format ✓, typecheck ✓, 328 tests ✓, audit ✓ no known vulns).
>
> **Note on `audit`:** `pip-audit` run bare audits the whole venv and surfaces vulnerabilities in ambient tooling (`pip`, `pytest`) that never ship in the production container. The gate therefore runs `pip-audit .` to scope the scan to the project's declared runtime dependencies. Those are clean.
>
> **RESOLVED — interpreter-robustness (harness finding).** The `Makefile` test targets now invoke **`python -m pytest`** rather than a bare `pytest`. This binds test execution to the active interpreter (the venv/matrix Python) instead of whatever `pytest` shim happens to be first on `PATH`, closing the previously-flagged risk of the suite silently running under the wrong interpreter. Applies to `test`, `test-unit`, `test-component`, and `test-cov`.

### Gate reachability

The aggregate test command MUST reach every package that contains tests, and the
CI and deploy quality gates MUST invoke that aggregate. A correctly named script
that silently omits a package is the failure this section exists to prevent.

- Aggregate quality gate (Python package): **`make validate`** — from the repo root (delegates via root `Makefile`) or from `agents/dependency-update/app/dependencyUpdate/`. Runs lint + format-check + typecheck + test-cov + audit, fail-fast. This is the canonical gate for the active codebase.
- Aggregate quality gate (JS/TS `panel` package): reached from the **same** repo-root `make validate`, which now runs a Python branch (`validate-py`) **and** a JS/TS branch (`validate-js` → `pnpm --filter panel run validate` = lint + format:check + typecheck + test + audit). `make validate` fails if either branch fails (F7 closed — the panel is no longer outside the aggregate gate).
- Aggregate test command (repo-wide): a repo-root `Makefile` delegates the Python package targets (`make validate`/`make test`/etc.) via `-C` and the `panel` package via `pnpm --filter`. The CDK package still uses `pnpm test` in its own dir and is not yet folded into the root aggregate (IaC smoke test, low priority).
- Packages reached: **`dependency-update`** via root `make validate`/`make test`; **`panel`** via root `make validate`/`make test` (JS/TS branch); **`agentcore-cdk-app`** via a manual `pnpm test`.
- CI gate: **`.github/workflows/ci.yml`** runs on every push to `main` and every PR targeting `main`. The **`python-quality`** job executes lint → format-check → typecheck → test+coverage → audit on a **Python 3.13 + 3.14 matrix**; the **`panel-quality`** job (Node 22 + pnpm) executes lint → format:check → typecheck → test:coverage → audit for the `panel` package. No `paths:` filter excludes `panel/`. RESOLVED.
- Deploy gate: **still none.** Deploy is via the AgentCore CLI / CDK (Phase 1) and Fly (Phase 2); neither is wired to invoke the aggregate. A deploy can still proceed without the gate. FINDING remains open (lower risk now that CI enforces on every PR to `main`).

> **RESOLVED (CI) / PARTIALLY OPEN (deploy).** `make validate` exists, works from the repo root, and is now enforced by CI (`ci.yml`) on every push/PR to `main` across both the dev runtime (3.13) and the production runtime (3.14). The remaining open item is a deploy-time gate — `agentcore deploy`/Fly do not yet invoke the suite. Given CI blocks unmerged breakage, this is now a lower-risk gap rather than an unguarded one.

## Coverage

### Thresholds and baseline policy

Coverage percentages alone do not establish confidence — a suite can cover every
line while asserting nothing meaningful. Thresholds are a floor, not a goal.

- Measurement tool per package: **`dependency-update`: pytest-cov 7.1.0** (coverage.py backend), branch coverage on, config in `[tool.coverage.run]` / `[tool.coverage.report]`. `agentcore-cdk-app`: none wired (out of scope — IaC smoke test only).
- Threshold policy: **no hard floor yet (`fail_under` unset).** Coverage is measured and reported on every `make test-cov`/`make validate` run, but a numeric gate is deliberately deferred. Most deterministic pipeline modules (#72–#76) now exist and are tested; a `fail_under` floor should be introduced once the remaining wiring (#77) lands so the number reflects a complete pipeline.
- Baseline: **~90%+ on implemented modules** — `scrubber.py` 100%, `config.py` 100%, `classifier.py` 100%, `eligibility.py` 100%, `credentials.py` 95%, `pull_request.py` 95%, `validator.py` 99%, `toolchain.py` 94%, `fix_agent.py` ~91%, `audit.py` ~87%. `main.py` and `agent_reporter.py` remain coverage-excluded/untested (see gap table). This baseline now describes the bulk of the pipeline logic, not just a narrow slice.
- **Last validated artifact (2026-08-31, issue #94 / PR #96):** `make validate` re-run from `agents/dependency-update/app/dependencyUpdate/` — **362 passed**, TOTAL **94%** (845 stmts / 48 miss / 234 branch / 19 brpart), `pip-audit . --strict` clean. Figures reproduced independently, not taken on report. **Measured scope caveat:** this artifact covers the 11 non-omitted Python modules of the `dependency-update` package only. `main.py` and `agent_reporter.py` are in `[tool.coverage.run] omit`, and the SQL layer (`docs/reference/001_schema.sql`), runbooks, and `workstream/` artifacts are outside the measured tree entirely. It is valid evidence of no Python regression; it is **not** evidence about anything issue #94 changed.
- Regression policy: report coverage on every `validate` run; a drop on any of the tested modules below its current number is a regression to investigate. Formal `fail_under` enforcement lands with the remaining #77 wiring.

> **`coverage_gate: MEASURED (~90%+ on implemented modules; no `fail_under` floor yet)`.** The gate is not SKIPPED — a provider (pytest-cov) is configured and runs in `make validate`. The structural gap analysis below now targets the remaining untested surface (`main.py` orchestrator wiring, `agent_reporter.py`), not the pipeline logic modules, which are covered.

**Structural gap analysis (substitute for coverage, current state):**

| Source file (`dependency-update`) | Tested? | Risk | Note |
| ---------------------------------- | ------- | ---- | ---- |
| `credentials.py`                   | partial | HIGH | GitHub App RS256 JWT auth + Supabase key resolution. Happy paths and staleness covered (**95%**); security-negative cases largely missing (see Security-Negative §). |
| `scrubber.py`                      | yes     | MED  | Secret redaction; 13 tests including boundary/overlap/bytes cases (**100%**). |
| `toolchain.py`                     | yes     | MED  | Package-manager + script-contract detection. Temp-dir project fixtures; **94%** coverage. |
| `validator.py`                     | yes     | MED  | Post-fix validation gating. Same temp-dir fixtures; **99%** coverage. |
| `classifier.py`                    | yes     | MED  | Advisory classification (in_range / major_required / unknown). **100%** coverage. |
| `eligibility.py`                   | yes     | MED  | Semver eligibility policy (D26). **100%** coverage. |
| `audit.py`                         | yes     | MED  | Vulnerability audit runner + JSON parsing. **~87%** coverage. |
| `fix_agent.py`                     | yes     | HIGH | LLM-driven code fix path (`strands-agents`). Layer 1 + Layer 2 tested with the model mocked (**~91%**); no Layer 3 semantic/groundedness eval harness (LLM *output quality* still unevaluated). |
| `pull_request.py`                  | yes     | MED  | Branch naming, idempotency (`gh pr list`), credential-helper push, PR body builder, `open_pr_if_needed`. Unit + component tested (**95%**); side-effecting `git`/`gh` calls mocked. |
| `updater.py`                       | partial | MED  | Apply updates + reconcile lockfile. Exercised via component pipeline tests; no dedicated unit suite. |
| `agent_reporter.py`                | **no**  | MED  | Lifecycle/log reporting SDK (buffering, retries, `seq` ordering). Design doc notes prior manual testing with a fake client; no committed tests. |
| `config.py`                        | yes     | LOW  | Config constants. **100%** coverage. |
| `main.py`                          | **no** (coverage-excluded) | MED | Entrypoint/orchestrator wiring. Listed in `[tool.coverage.run] omit`; guard ordering (req49→req50→open_pr, PR-before-MAJOR_UPDATE_REQUIRED, `pull_request` artifact emission) verified by inspection, not by an automated assertion. |

Source-to-test ratio: **most source modules now have tests** — the deterministic pipeline (`audit`, `classifier`, `eligibility`, `toolchain`, `validator`, `updater`, `pull_request`), the secret scrubber, credentials, and the LLM fix loop are all exercised. The remaining untested surface is `agent_reporter.py` (SDK, no committed tests) and `main.py` (orchestrator, coverage-excluded by convention). Ranked by residual risk: (1) `main.py` orchestration guards (inspection-only), (2) `agent_reporter.py` buffering/retry/`seq` behavior, (3) the **LLM output-quality** dimension of `fix_agent.py` (Layer 3 eval harness absent — the code path is tested, its semantic output is not), and (4) the security-negative auth cases in `credentials.py` (see below).

### Database / reaper layer — structural gap (added issue #94; partly closed S-102/S-103)

> **Update (S-102 / #115 and S-103 / #116).** Two facts this section originally asserted are now
> false and have been corrected. (1) The canonical DDL no longer lives in
> `docs/reference/001_schema.sql` applied by hand through the SQL Editor — the schema moved to the
> Supabase CLI migration `supabase/migrations/20260902200101_initial_schema.sql` (S-102), with
> `reap_stale_runs()` since carried forward by `supabase/migrations/20260903090000_english_reaper_messages.sql`
> (S-103); `docs/reference/001_schema.sql` is now a zero-DDL pointer stub. (2) The reaper contract is
> **no longer coverage-free** — S-102 stood up a Layer 2.5 harness (Vitest `integration` project in
> `panel`, real local Postgres via the Supabase CLI) and S-103 added executable assertions against it.
> The gap table below is retained for the parts that remain open, with per-row status updated.

The stale-run reaper now has **automated Layer 2.5 coverage** (was: "zero automated coverage").
`reap_stale_runs()`, `v_runs.effective_status`, and the explanatory `run_events` contract are defined
in the canonical migrations under `supabase/migrations/` (no longer `docs/reference/001_schema.sql`,
which is a pointer stub) and are applied by the Supabase CLI (`supabase db reset` / `supabase db push`),
not by hand. The Layer 2.5 suite in `panel/tests/integration/` exercises them against a real local
Postgres:

- **`reaper.test.ts` (7 tests, added S-103):** stale `running` → `timed_out` with `RUNTIME_TIMEOUT`;
  stale `queued` → `failed_to_start` with `START_TIMEOUT`; the explanatory event written at
  `seq = max(seq)+1` carrying `reaped_by`/`reason`; open `run_steps` closed as `failed` on the
  `timed_out` branch (the #99 contract); and a safe no-op when a `queued` run has no steps.
- **`seed-schema.test.ts` (4 tests, added S-103):** the seeded `params_schema` top-level structure is
  unchanged, all four properties carry English titles, the whole serialized schema is ASCII (no
  Spanish prose), and the enum/range/default constraint structure survives the label translation.
- **`schema.test.ts` (3 tests, S-102 baseline):** `v_runs` exists, exposes `effective_status`, and
  `reap_stale_runs()` is callable and returns an integer count.

Issue #94 verified the reaper against the live database and the evidence is genuine, and S-103 turned
several of the previously one-shot manual checks into repeatable assertions. Ranked gaps **1, 3, and
4 below are wholly or partly closed** by the Layer 2.5 suite; the residual open items (the full
must-not-reap negative table, deployed-vs-migration drift detection, concurrency, and the
`agent_reporter.py` write side) are noted per-row.

Ranked by residual risk (status updated for S-102/S-103):

| # | Gap | Risk | Why it ranks here | Evidence today |
|---|-----|------|-------------------|----------------|
| 1 | **Reaper "must NOT reap" negative table is only partly ported.** `reaper.test.ts` (S-103) now asserts the positive transitions (`running`→`timed_out`, `queued`→`failed_to_start`) and a safe no-op for a `queued` run with no steps, but the full negative half of the CT-1 contract — within-grace rows stay `running`, `started_at IS NULL` is skipped, future-dated `started_at` is skipped, already-terminal rows are never mutated — is still not all expressed as executable assertions. | **MED** (was HIGH) | The reaper now has a live harness and its positive path is regression-guarded, so an "always reaps" break would be caught. The remaining risk is the *eager*-reap direction (reaping a healthy within-grace run), whose negative cases are catalogued but not all executed. AC5 (the real-run must-not-reap check) is still PENDING, blocked by #98. | **Partly closed (S-103):** `panel/tests/integration/reaper.test.ts` executes the positive transitions + `seq=max+1` event + #99 step-closure + queued-no-steps no-op. EC-1..EC-5/EC-8 negative rows from `workstream/test-plan-issue-94.md` are ported for the covered cases; the remaining within-grace/null/future-dated negatives are the residual. |
| 2 | **Drift between the deployed database and the canonical migration is undetectable.** The Layer 2.5 harness applies the migrations to a *local* Postgres, but there is no checksum or `schema diff` step comparing the deployed (remote) function/view/schedule against `supabase/migrations/`. | **HIGH** | Issue #94 was itself a drift defect of this class — the scheduling block sat commented out while the design docs described a scheduled reaper. The migration move (S-102) removes the "applied by hand" failure mode locally, but nothing yet asserts remote == migration. #100 (control plane must insert the `queued` row) is a second instance: a documented contract that no code or test enforces. | Local-apply is now covered by the Supabase CLI harness; remote-vs-migration drift verified by inspection only. |
| 3 | **Two-layer consistency (CT-2) has no repeatable assertion.** `runs.status == v_runs.effective_status` after the reaper fires, and `effective_status` == eventual `status` before it fires, were each observed once. | **MED** | This is the invariant the Phase 2 Run Detail panel is built on (DESIGN.md §5.3, PRD FR11a). A view-vs-function divergence would surface as the UI showing a terminal run as `running` — quiet, plausible, and wrong. | **Partly closed (S-103):** `schema.test.ts` asserts `v_runs.effective_status` exists as a column and `reaper.test.ts` asserts `runs.status` after the reaper fires; the *pre-fire* `effective_status == eventual status` read-time branch is not yet a committed assertion. |
| 4 | **Event-schema contract (CT-3).** `level='error'`, `data.reaped_by`, `data.reason ∈ {START_TIMEOUT, RUNTIME_TIMEOUT}`, `seq = max(seq)+1`, plus the #99 step-closure. | **LOW** (was MED) | The explanatory event is the *only* source of "why did this run die" (product-context success metric 3). | **Closed (S-103):** `reaper.test.ts` asserts the explanatory event at `seq = max(seq)+1` carrying `reaped_by`/`reason`, and asserts open `run_steps` are closed as `failed` on the `timed_out` branch (the #99 contract) — both now repeatable Layer 2.5 assertions, no longer "asserted by eye". |
| 5 | **Concurrency / idempotency of `for update skip locked` (EC-5, EC-6) unverified.** Two overlapping ticks must transition a row once and write exactly one event. | **MED** | A double-fire produces a `seq` collision that aborts the whole tick, so one bad row stalls reaping for every run. Low likelihood at one tick per minute; high blast radius. | Not executed. |
| 6 | **`agent_reporter.py` is the write side of this same contract and has no committed tests** (buffering, 3-retry backoff, 4xx-not-retried, `seq` assignment, stderr/CloudWatch fallback). | **MED** | It is coverage-omitted, so the 94% figure excludes it entirely. AC6 — the CloudWatch fallback — is PENDING, meaning neither the automated nor the manual path covers it. Follow-up #97 (`unwrap_payload` double-wrap) and #98 (run dies without reporting terminal status) are both failures in this reporting surface. | None (design doc notes prior ad-hoc testing with a fake client). |

**Is this in scope, and what remains?** The Layer 2.5 harness that this section originally called for
**now exists** — the Vitest `integration` project in `panel` running against a real local Postgres via
the Supabase CLI (S-102 / #115), with the reaper and seed-schema contracts asserted against it
(S-103 / #116). The originally-recommended follow-up is therefore **substantially delivered**: gap 4
is closed, gaps 1 and 3 are partly closed, and the migrations apply clean in the harness so a broken
`reap_stale_runs()` fails CI locally. What remains open: the full must-not-reap negative table (gap 1
residual), remote-vs-migration drift detection (gap 2), concurrency/idempotency of
`for update skip locked` (gap 5), and the `agent_reporter.py` write side (gap 6). Gap 6 is closable at
Layer 1/2 with no new dependencies but is a different module and belongs in its own change.

**Recommended follow-up issue (residual scope — hand to the user):**
*"Complete the Layer 2.5 reaper contract: port the remaining must-not-reap negatives and add
remote-vs-migration drift detection."* Scope: port the still-uncovered CT-1 negative rows (within-grace
stays `running`, `started_at IS NULL` skipped, future-dated `started_at` skipped, already-terminal
never mutated) and EC-5/EC-6 concurrency into the existing `panel/tests/integration/` suite; add a
`supabase db diff`-style check comparing the deployed function/view/schedule against
`supabase/migrations/` so remote drift fails CI. The positive transitions, the explanatory-event
schema, and the #99 step-closure are already covered by `reaper.test.ts` (S-103).

**Related open follow-ups from issue #94** (already registered in `docs/technical-guidelines.md` §18,
`docs/adr/ADR-004-schedule-pg-cron-reaper.md`, and the verification runbook — repeated here for their
testing consequences):

| Issue | Testing consequence |
|---|---|
| [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97) — `unwrap_payload()` double-wrap | Payload-shape handling has component tests (`test_pipeline.py::TestInvalidPayloadNoClone`) that assert the *single*-wrap contract only. The defect is a missing case, not a missing suite — closable at Layer 2 with no new deps. |
| [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98) — agent dies mid-`validate` without reporting terminal status | **Blocks AC5**, which is the only planned check of the reaper's must-not-reap-healthy-runs behaviour (ranked gap 1). Also unreachable by any current layer: no test exercises the streaming/idle-timeout interaction with `TEST_TIMEOUT`. |
| [#99](https://github.com/llipe/dev-tasks-agent-fleet/issues/99) — reaper leaves open `run_steps` | Would be caught by ranked gap 4 (event/step schema assertions) once a Layer 2.5 harness exists. Currently detectable only by manual inspection. |
| [#100](https://github.com/llipe/dev-tasks-agent-fleet/issues/100) — control plane must insert the `queued` row | Instance of ranked gap 2: a documented D1 contract with no enforcing code or test. PostgREST returns HTTP 200 on a zero-match UPDATE, so the failure is silent — exactly the shape that needs an integration assertion. |
| [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) — complete issue #94 AC5/AC6 verification | Executes the **manual** half of ranked gaps 1 and 6: AC5's synthetic interlock proof is the first deliberate must-not-reap check (gap 1), and AC6 is the only coverage of the `agent_reporter.py` CloudWatch fallback in either direction (gap 6). Also carries the unobserved `queued`→`failed_to_start` read-time branch of AC4, which is gap 3's missing symmetric case. Closing #101 does not remove the need for the Layer 2.5 harness — it converts one-shot manual observations into recorded ones, not into regression detectors. |



## Panel frontend test surface (Phase 2)

The `panel` package accrues its test surface per story. Each row records the story,
the layer, the test files, and what they assert. This table is additive — a new
story appends rows, it does not rewrite prior ones. Coverage figures are the
per-module `@vitest/coverage-v8` numbers measured on the story's delivery.

| Story | Layer | Test file(s) | Asserts |
|-------|-------|--------------|---------|
| **S-109 (#122)** — run detail `/runs/[id]` | 1 (unit) | `tests/unit/artifact-url.test.ts` (12 tests, incl. RT-1 fuzz) | **Mandatory security-negative #5** — `isSafeArtifactUrl` accepts only well-formed `https:`; rejects `http:`/`javascript:`/`data:`/`vbscript:`/`file:`/`ftp:`/relative/empty/`null`; case-insensitive scheme; TOTAL function that never throws over a 5,000-string fuzz corpus + a curated malformed set. `artifact-url.ts` **100%**. |
| **S-109 (#122)** | 1 (unit) | `tests/unit/log-window.test.ts` (14 tests, incl. RT-3 partition property) | SD11 most-recent-2,000 window selector and `priorWindowRange` load-earlier math; the RT-3 property that the window plus the prior range partition the event stream without gap or overlap. `log-window.ts` **100%**. |
| **S-109 (#122)** | 1 (unit) | `tests/unit/run-detail.test.ts` (19 tests) | `selectBanner` terminal-state selection, `buildLogLines`, `buildSummary` (status derived through the shared `effectiveStatus`; duration fallback). `run-detail.ts` **~97%** (uncovered = the `startedAtMs`/`finishedAtMs` fallback branch — a defensive path). |
| **S-109 (#122)** | 2 (component) | `tests/component/run-detail.test.tsx` (21 tests) | **Mandatory security-negative #6** — a `<script>` and an `<img onerror>` message render as literal inert text with NO real `script`/`img` node created inside the `role="log"` region; the render consequence of #5 (a `javascript:`/`http:` artifact URL renders as inert text, never an `<a>`); AC14 (artifact link renders alongside a red `failed` pill); `rel="noopener noreferrer"` hardening; full 8 KB message not truncated; `aria-live` on the log region; terminal-state banner. |
| **S-109 (#122)** | 2 (component) | `tests/component/run-detail-page-wiring.test.tsx` (3 tests) | Server-component page wiring — the `/runs/[id]` page composes summary + artifacts + log viewer + load-earlier server action from the query layer. |
| **S-109 (#122)** | 2.5 (integration) | `tests/integration/run-detail-queries.test.ts` (5 tests, **ran live** against local Supabase) | `getRunEventsInRange` and the run-detail reads against a **real local Postgres** (Supabase CLI stack); the SD11 bounded read — a seeded 2,500-event run returns exactly the most-recent 2,000 in `seq` order. Docker-gated; ran live for this delivery with the stack up. |
| **S-110 (#123)** — SSE live-tail relay `GET /api/runs/[id]/events/stream` | 1 (unit) | `tests/unit/sse-cursor.test.ts` (incl. RT-1 monotonic-cursor property) | `SeqCursor.admit` / `dedupeAndOrder` — the SD6 dedupe/order reducer: strictly-increasing emitted `seq`, every input `seq > after_seq` exactly once, late/duplicate/regressing `seq` dropped, NaN/negative cursor normalized to 0. `cursor.ts` **100% stmts** (one uncovered branch, line 67 — the `!Number.isFinite(seq)` guard). |
| **S-110 (#123)** | 1 (unit) | `tests/unit/sse-serialize.test.ts` (incl. RT-2 round-trip property) | `serializeFrame` / `parseFrames` — the four event types (`event`/`run`/`heartbeat`/`closed`), newline-safe framing (a JSON payload can never forge the blank-line frame terminator — EC-11/EC-14), and the serialize→parse round-trip oracle. `serialize.ts` **92.85% stmts** (uncovered lines 61–62 — the defensive multi-`data:`-line split for a JSON value containing a raw `\n`, unreachable via `JSON.stringify`). |
| **S-110 (#123)** | 1 (unit) | `tests/unit/autoscroll.test.ts` | `shouldAutoScroll` / `distanceFromBottom` — the DESIGN §6.6 24px follow boundary (inclusive at 24px, pauses at 25px — EC-15). `autoscroll.ts` **100%**. |
| **S-110 (#123)** | 1 (unit) | `tests/unit/after-seq.test.ts` (incl. RT-3 fuzz, recorded seed) | `parseAfterSeq` (exported from the route module) — integer/default-0 contract; coerces malformed/negative/non-parseable `after_seq` to 0, never `NaN`, never negative, never a 500 (CT-2/CT-3). This is the only part of `route.ts` reachable without the Next.js runtime; the module's `GET`/`wrapSupabaseChannel` are not exercised here (see coverage note). |
| **S-110 (#123)** | 2 (component) | `tests/component/stream-route.test.ts` (9 tests, fake clock + fake Realtime channel) | The relay engine `createStreamResponse` (`lib/sse/relay.ts`): backfill-before-subscribe + dedupe (AC2/SD6), the four event types + `closed{reason}` (AC3/CT-5), 15s heartbeat cadence (EC-10), unsubscribe-once on abort + balanced `sse_open`/`sse_close` log pair (AC7/EC-8/SR5), terminal-at-connect never subscribes (EC-3), 200-event burst in seq order (EC-12). `relay.ts` **89.47% stmts** (uncovered lines 135–137, 164–169 — the `cancel()` reader-cancel teardown and a redundant closed-guard branch; the `abort` teardown path IS covered). |
| **S-110 (#123)** | 2 (component) | `tests/component/use-run-stream.test.tsx` (7 tests, injected fake `EventSource`) | `useRunStream` — appends `event` frames with client-side `seq` dedupe (defensive mirror of SD6), tracks highest rendered `seq`, reconnects with it as `after_seq` on an unexpected drop, stops reconnecting on `closed`, forwards raw `run` status. `useRunStream.ts` **100% stmts** (uncovered branches lines 103–105/129 — the `onerror`-with-already-closed short-circuit and the no-`EventSource`/no-factory SSR early return). |
| **S-110 (#123)** | 2 (component) | `tests/component/live-log-viewer.test.tsx` | `LiveLogViewer` + `LiveTailButton` — **AC5** live status derived through the shared `effectiveStatus` (a late `running` push on an expired run still reads `timed_out`, SD4); **AC6** auto-scroll/pause/resume follow state; message rendered by `LogLine` as an inert text node (security guard #6). `LiveLogViewer.tsx` **100% stmts** (uncovered branch line 96 — a defensive null-ref guard); `LiveTailButton.tsx` **100%**. |
| **S-110 (#123)** | 2.5 (integration) | `tests/integration/stream-e2e.test.ts` (1 test, **ran live** against local Supabase Realtime) | SC-11/EC-2 — open the relay, insert `run_events` **after** the stream is open, assert every inserted event arrives exactly once in `seq` order against **real Supabase Realtime** (the backfill→subscribe seam holds against the real stack, not a mock); also drives `getRunEventsAfterSeq` live. Docker-/service-role-/Realtime-gated with recorded skip reasons. **Flake note:** timing-sensitive (1500ms subscribe + 2500ms delivery windows) — observed 1 failure (`expected [] to include 1`, Realtime not yet `SUBSCRIBED`) then 2 passes across full-suite runs; see coverage note. |

> **`coverage_gate` (S-110, MEASURED): PASS.** Measured with `@vitest/coverage-v8` 3.2.4 on the full
> panel suite (`pnpm exec vitest run --coverage`) with the Layer 2.5 `integration` project run **live**
> against the local Supabase stack (`SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` exported from
> `supabase status -o env`). New/changed-module coverage: `autoscroll.ts` **100%**, `cursor.ts`
> **100% stmts** (93.33% branch), `useRunStream.ts` **100% stmts** (88% branch), `LiveLogViewer.tsx`
> **100% stmts**, `LiveTailButton.tsx` **100%**, `serialize.ts` **92.85%**, `relay.ts` **89.47%**,
> `getRunEventsAfterSeq` (in `queries.ts`) exercised live by the Layer 2.5 backfill. Full suite
> reproduced: unit+component **719 passed / 4 skipped**; all-projects with integration live **769 passed
> / 4 skipped**; `make validate` reaches the panel via `validate-js` (F7 intact).
>
> **Route handler is a thin adapter — verified by inference, not covered.**
> `app/api/runs/[id]/events/stream/route.ts` measures **12% stmts** (lines 45–152 uncovered): only the
> exported `parseAfterSeq` is unit-tested. The streaming `GET` and the Supabase-specific
> `wrapSupabaseChannel` are **not** exercised by any test — the component suite drives the pure
> `createStreamResponse` core (relay.ts) with a fake channel, and the Layer 2.5 suite uses its own local
> `wrapSupabaseChannel` copy against real Realtime rather than importing the route. This is the same
> thin-adapter/pure-core split used across prior stories (all engine logic sits in the injected
> `lib/sse/relay.ts` at 89%+); the route's ~35 wiring lines are the accepted non-blocking gap, ranked #1
> below. The residual uncovered lines in `relay.ts` (135–137, 164–169 — `cancel()` reader teardown) and
> `serialize.ts` (61–62 — a `JSON.stringify`-unreachable newline split) are defensive paths, not business
> logic. None of these are a `FAIL`.
>
> **Security-negative / SD2 boundary: covered and intact.** The SSE path adds no browser Supabase client
> and no `NEXT_PUBLIC_SUPABASE*` (grep-confirmed across `app/`, `lib/`, `components/`): the browser holds
> only an `EventSource` to the server route; all Supabase Realtime lives server-side (SD2). The route
> reads Supabase through `createServerClient`, guarded at build time by the `import "server-only"` pragma
> and at lint time by the SD2 `no-restricted-imports` rule (scoped to `app/**` + `components/**`, correctly
> excluding `app/**/route.ts` where server reads are legitimate). The repo-wide security-negative tests
> cover this delivery: `tests/unit/bundle-secrets.test.ts` (RUN_BUNDLE_SECRET_TEST=1 — builds the whole app
> incl. this route and greps `.next/static/**` for the service-role sentinel) and
> `tests/unit/eslint-server-import.test.ts` (proves the SD2 rule fires). Security guard #6 (inert log-line
> render, no `dangerouslySetInnerHTML`) is asserted for the live viewer in `live-log-viewer.test.tsx`.
>
> **Layer 2.5 flake (harness reliability, non-blocking).** `stream-e2e.test.ts` failed once
> (`expected [] to include 1` — the Realtime subscription had not reached `SUBSCRIBED` within the 1500ms
> window before inserts) and passed on two subsequent runs (isolated and full-suite). It is timing-
> sensitive against the shared local stack under load. It is real evidence when green (it did run and pass),
> but it is not deterministically reliable; recorded as a harness-reliability finding for a follow-up
> (widen/await-`SUBSCRIBED` before insert) — not a business-logic defect and not a gate failure.

> **`coverage_gate` (S-109, MEASURED): PASS.** Measured with `@vitest/coverage-v8` 3.2.4 on the
> full panel suite (`pnpm --filter panel run test:coverage`) with the Layer 2.5 `integration` project
> run **live** against the local Supabase stack. New-module coverage: `artifact-url.ts` **100%**,
> `log-window.ts` **100%**, `RunSummary.tsx`/`StateBanner.tsx`/`ArtifactLinks.tsx` **100%**,
> `run-detail.ts` **97.22%**, `LogViewer.tsx` **95.52%**. The two `LogViewer` uncovered lines (55–57)
> are the `priorWindowRange(cursor) === null` defensive early-return, unreachable through the UI while
> the `cursor == null` guard above it holds; the two `run-detail.ts` uncovered lines (172–173) are the
> `startedAtMs`/`finishedAtMs` duration fallback. Both are defensive paths, not business logic —
> reported as an accepted non-blocking gap, not a `FAIL`. Both mandatory security-negative categories
> are present and passing: **#5** (artifact-url `https:`-only scheme, `tests/unit/artifact-url.test.ts`)
> and **#6** (inert `<script>`/`<img>` render, `tests/component/run-detail.test.tsx`). Full suite
> independently reproduced: **711 passed / 4 skipped**; `make validate` exits 0 (Python 452 + panel
> 711). Coverage is not confidence: the Layer 1/2 suites mock the data layer, so the query defects that
> matter are guarded by the Layer 2.5 `run-detail-queries` suite running against a real Postgres — which
> ran live here, not skipped.

| Story | Layer | Test file(s) | Asserts |
|-------|-------|--------------|---------|
| **S-115 (#128)** — `next build` unblock (`parseAfterSeq` move) | 1 (unit) | `tests/unit/after-seq.test.ts` (incl. RT-3 fuzz, recorded seed) | `parseAfterSeq` relocated from the S-110 SSE `route.ts` into `lib/sse/cursor.ts` (behavior unchanged — the App Router route-type validator rejects the non-standard named export, failing `next build`). The test is pointed at `@/lib/sse/cursor` and passes: integer/default-0 contract, malformed/negative/non-parseable → 0, never `NaN`/negative/500 (CT-2/CT-3). `cursor.ts` **100% stmts** (94.44% branch; one uncovered branch, line 85 — the `!Number.isFinite(seq)` guard in `SeqCursor.admit`, a defensive path). _(Retained from S-115; the S-115 privacy-gate rows were superseded by the S-122 auth-gate rows below when `fly-privacy-check.*` / `verify-fly-private.sh` were removed.)_ |
| **S-122 (#161)** — Auth release gate REPLACING the privacy gate (SR2 inversion / PRD AC17) | 1 (unit) | `tests/unit/panel-auth-check.test.ts` (30 tests) | **"Gate observed failing" evidence.** The pure release-gate parser `panel/scripts/panel-auth-check.mjs` (`checkEnvNames`/`checkProtectedRedirect`/`checkSseUnauthorized`/`checkSignupRejected`/`evaluateAuthGate`). A correct-deployment fixture passes; each violation fixture makes the verdict fail — a protected UI path served **200** (gate not enforcing), an SSE path served **200** (reachable anonymously), a **successful signUp** (AC17/R9, the highest-value check — anyone could self-register into the invoke surface), and a **missing auth env-var name**. Fail-closed is asserted directly: non-array/garbage env names, a network error/timeout, a redirect to a NON-`/login` location, a 401-with-HTML body (status is authoritative → still pass), an unrecognized signup shape, and an entirely empty input all fail. The five exported pure functions (the whole gate decision logic, lines 1–218) are **100%** covered; the file reads **87.39% stmts / 91.3% branch** overall because the CLI entrypoint (lines 227–256, 259–260 — `readJsonOrNull`/`mainCli`/`import.meta.url` self-invoke guard) is not attributed in-process (it is spawned by the CLI suite below). This REPLACES the removed S-115 privacy-parser suite (`fly-privacy-check.test.ts`). |
| **S-122 (#161)** — CLI exit-code contract | 1 (unit) | `tests/unit/panel-auth-check-cli.test.ts` (4 tests) | The process-level contract `scripts/verify-panel-auth.sh` turns into "release allowed" vs "release BLOCKED": spawns the real Node CLI and asserts **exit 0** on a correct fixture, **exit 1** on a successful-signup fixture (AC17), **exit 1** on a protected-path-200 fixture, and **exit 1 fail-closed** on garbage/unreadable input. This is the "gate observed failing" evidence end-to-end (violation → non-zero exit), and it is what exercises the CLI entrypoint lines the in-process coverage run cannot attribute. REPLACES the removed `fly-privacy-check-cli.test.ts`. |
| **S-122 (#161)** — CI wiring (static + by-name) | CI (static) | `scripts/verify-panel-auth.sh` (no unit test — shellcheck) | The shell wrapper that collects the four live inputs (`fly secrets list` NAMES only, an unauthenticated protected-UI probe, an unauthenticated SSE probe, and a disposable-address signUp attempt with auto-delete) and hands the verdict to the unit-tested parser (exit 0 boundary-holds / exit 1 any failure, fail-closed). Not unit-tested (it shells out to `curl`/`fly`/`node` and the signup-live-delete path needs a live Supabase); statically checked by the **`Shellcheck the auth-gate script (S-122)`** CI step (`.github/workflows/ci.yml`, `shellcheck scripts/verify-panel-auth.sh`). CI additionally runs the parser suite by name via the **`Auth-gate parser test (S-122)`** step (`pnpm --filter panel exec vitest run --project unit panel-auth-check`) so a gate-parser regression reddens CI independently of the broader suite. |

> **`coverage_gate` (S-122, MEASURED): PASS.** Measured with `@vitest/coverage-v8` 3.2.4 on the panel
> `unit` project (`pnpm --filter panel exec vitest run --project unit panel-auth-check --coverage`,
> `--coverage.include=scripts/panel-auth-check.mjs`), reproduced independently — not taken on report.
> The S-122 surface is pure-parser + a shell wrapper; there is no Layer 2.5/DB component, so the
> Docker-gated `integration` project is not part of this surface.
>
> New/changed-module coverage for the S-122 committable code:
> `panel/scripts/panel-auth-check.mjs` — **87.39% stmts, 91.3% branch, 77.77% funcs** file-total, with
> the **entire pure gate decision logic (all five exported functions, lines 1–218) at 100%** on
> statements, branches, and functions. The 31 uncovered lines are exactly the CLI entrypoint
> (227–256, 259–260) and the two uncovered functions are `readJsonOrNull` + `mainCli`; V8 does not
> attribute the child-process execution of the spawning CLI suite back to the in-process run, so those
> lines read uncovered here even though the 4 CLI tests exercise both exit paths end-to-end. The pure
> logic hitting the stated 100% target IS the coverage gate for this story.
>
> 34 S-122 tests green (30 pure + 4 CLI). Full panel unit suite reproduced independently:
> **658 passed / 4 skipped** (the 4 skips are the `RUN_BUNDLE_SECRET_TEST=1`-gated bundle tests — none
> in the S-122 surface).
>
> **Ranked structural gaps (S-122, accepted / non-blocking).**
> 1. **`panel-auth-check.mjs` CLI entrypoint (lines 227–256, 259–260) — 0% in-process attribution.**
>    `mainCli`, `readJsonOrNull`, and the `import.meta.url === process.argv[1]` self-invoke guard.
>    Risk: **low** — pure `process.argv` parsing, `readFileSync`+`JSON.parse` (already caught to `null`),
>    and `console`/`process.exit` wiring; the decision logic it delegates to (`evaluateAuthGate`) is 100%
>    covered. It is genuinely exercised end-to-end by `panel-auth-check-cli.test.ts` (spawns the real
>    CLI, asserts exit 0/1 both directions) — the gap is a coverage-attribution artifact of spawning a
>    child process, not an untested path.
> 2. **`scripts/verify-panel-auth.sh` — no behavioral test.** Static-only (shellcheck, clean). Its live
>    behavior depends on `curl`/`fly`/a live Supabase project (the disposable-address **signUp
>    attempt + auto-delete** path can only be exercised against a live Auth endpoint), so it is out of
>    scope for automated coverage; the LIVE deploy/probe half is operator-executed per
>    `docs/runbooks/panel-deployment.md`. Suggested future closure: a wrapper test injecting fake
>    `curl`/`fly`/`node` on `PATH` returning fixture JSON to assert the exit-code plumbing.
> 3. **`panel/fly.toml` (banner-only change) — no unit-testable logic**, correctly excluded from the
>    coverage surface. The app remains PRIVATE in this wave (the flip to public is the separate
>    Phase B / S-123).
>
> **Scope note.** The LIVE deploy/probe half of S-122 (running `verify-panel-auth.sh` against the
> deployed app, including the live signup-rejection assertion) is operator-executed
> (`docs/runbooks/panel-deployment.md`) and is out of scope for automated coverage — not counted as a
> gap here.

### When coverage cannot be measured

If no coverage provider is configured, the gate reports
`SKIPPED(<reason>)` — never a pass — and structural gap analysis runs instead:
untested files and exported symbols are enumerated, source-to-test size ratios
are reported per package, and gaps are ranked by size and risk. Absence of
tooling is never reported as absence of gaps.

Existing coverage artifacts are validated before being trusted. A stale report,
or one whose measured scope is narrower than the package it claims to describe,
is reported as misleading rather than used as evidence.

## Fixtures and Mocking

**`dependency-update` (Python).** Test doubles are built with the stdlib `unittest.mock` (`patch`, `MagicMock`) plus `pytest-mock`. External boundaries are patched at the module boundary — `credentials.boto3`, `credentials.requests`, `credentials.jwt`, and `credentials.mint_installation_token` — so the module under test runs its real logic against fake transports. `scrubber.py` tests need no mocks (pure functions over strings and a synthetic `subprocess.CalledProcessError`). The `toolchain.py`/`validator.py` tests use **temp-dir JS project fixtures centralized in `tests/conftest.py`** (`pnpm_project`, `npm_project`, `no_lockfile_project`, `no_test_project`, `minimal_test_project`) that build real `package.json`/lockfile shapes under pytest's `tmp_path` — no mocking of the filesystem, just disposable directories.

Mocks are function/class-scoped via decorators and context managers, so they restore automatically; there is no shared global stub requiring explicit teardown. A **`conftest.py`** now exists and is the single home for shared fixtures: it holds the temp-dir project builders and a `pytest_collection_modifyitems` hook that **auto-applies the `unit`/`component` markers by directory** (`tests/unit/` → `unit`, `tests/component/` → `component`), so the canonical `pytest -m unit`/`-m component` selectors work without per-test marker declarations. Any future token builder or mocked PostgREST/Secrets-Manager client shared across files MUST live here rather than being copy-pasted. The `tests/fixtures/` directory (`.gitkeep` only) remains the intended home for recorded API payloads and golden files.

### Rules

- Shared fixtures and helpers live in one place per package. Duplicating a token
  builder or a client mock across test files is a defect.
- A test double must not reimplement the logic it stands in for. When a mock
  grows a copy of production behavior, the test validates the mock.
- Stubbed globals are restored after each test. Rely on explicit restoration
  rather than on worker isolation.
- Placeholder assertions such as `expect(true)` are prohibited. They report
  health without exercising anything.

### Gold datasets

**None recorded today.** `tests/fixtures/` contains only a `.gitkeep` — no recorded HTTP responses, no golden files, no captured PostgREST/Secrets-Manager/GitHub-API payloads. Layer 2 component tests now exist (`test_pipeline.py`, `test_pr_creation.py`, `test_fix_agent.py`) but they build their inputs inline / via mocks rather than from recorded API-shape fixtures. When recorded-payload fixtures are added, they MUST live under `tests/fixtures/`, and each fixture MUST document how it was captured and how to regenerate it. Until then, this section is a gap, not a satisfied requirement.

## Security-Negative Tests

Required for every authentication and authorization code path. A suite that
only asserts the behavior the implementation happens to have provides no
security evidence.

| Case                        | Required | Covered today?                                                                                     |
| --------------------------- | -------- | -------------------------------------------------------------------------------------------------- |
| Invalid signature rejected  | yes      | **NO** — the RS256 JWT is verified by GitHub's server, which `test_credentials.py` mocks away. No test asserts a bad/tampered assertion is refused. GAP. |
| Expired credential rejected | yes      | **PARTIAL / indirect** — `TokenContext.is_stale()` staleness logic is tested (fresh, boundary, 46-min stale, custom threshold), so client-side re-mint is covered. But GitHub-side JWT `exp` rejection is not exercised (server is mocked). Token-staleness ≠ credential-expiry rejection. GAP for the auth-server case. |
| Wrong issuer or audience    | yes      | **NO** — `mint_installation_token` sets `iss = str(app_id)`; a test asserts the claim value is set, but nothing asserts a wrong-issuer assertion is rejected (again, server-side, mocked). GAP. |
| Tampered claims rejected    | yes      | **NO** — no test tampers with JWT claims and asserts rejection. GAP. |
| Cross-tenant access denied  | yes      | **NO** — `_get_installation` filters by `github_org_slug=eq.{org}&is_enabled=eq.true` and the empty-result path raises `CredentialError('NO_INSTALLATION')` (tested). But there is no test proving a caller cannot resolve credentials for an org it should not access, and no RLS/policy layer is exercised (agent uses the service-role key, which bypasses RLS entirely — see D15/R2). GAP. |

> **FINDING — security-negative coverage is largely absent, and what looks covered is fake-based.** The authentication path in `credentials.py` (GitHub App RS256 JWT minting + Supabase key resolution) is exercised only through mocked transports. Every actual signature/expiry/issuer/tamper *rejection* is performed by GitHub's token endpoint, which the tests replace with a `MagicMock` that returns a valid token unconditionally. Consequently the suite proves the **client assembles the request correctly**, not that **bad credentials are refused**. This is precisely the "fake-based isolation is not evidence that the production policy holds" caveat: asserting against test doubles here yields no security evidence.
>
> Compounding this: the agent authenticates to Supabase with the **service-role key, which bypasses RLS** (D15, accepted risk R2). There is no policy layer to test cross-tenant denial against — isolation rests entirely on the `github_org_slug` query filter in `_get_installation`, and even that is not covered by a negative test.
>
> **What genuinely IS covered (positive-adjacent):** the `NO_INSTALLATION` error when no enabled row matches, and the client-side token-staleness/refresh boundary logic. These are real and useful but are not security-negative rejections.
>
> **Recommended (hand to `developer` — requires no new deps):** add tests that (a) feed a `requests.post` mock returning 401/403 from the token endpoint and assert `mint_installation_token` raises rather than returns a token; (b) assert `_get_installation` never returns a row for a mismatched or disabled org; (c) once a real signature check is reachable (e.g. verifying the assertion with the public key in a component test), assert tampered/expired/wrong-issuer assertions are rejected. Until a real policy or verification layer is exercised, this section MUST remain marked as a gap, not satisfied.
