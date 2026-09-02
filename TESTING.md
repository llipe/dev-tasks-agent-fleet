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
| 2.5      | Integration               | Real database, real migrations, RLS policies, schema contracts. No mocked data layer. | **not configured — and now a live gap, not a deferred one.** No local Postgres/Supabase harness exists (no pgTAP, no testcontainers, no `docker-compose`, no Supabase CLI directory). As of issue #94 the database is no longer inert reference DDL: `reap_stale_runs()` is scheduled in production via `pg_cron` and `v_runs.effective_status` is a read-time contract the Phase 2 UI will depend on. Both are verified **only** by live operator SQL (`docs/runbooks/issue-94-reaper-verification.md`). See the Database/reaper gap table under Coverage. |
| E2E      | End-to-end                | Playwright CLI — committed browser automation, full-stack, scenario-driven.           | config stub only — `panel/playwright.config.ts` exists (S-101) with the `test:e2e` script wired; the scenario suite lands in S-114 (#127). No committed scenarios yet. |
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

## Packages

One row per package. In a single-package repository this table has one row.
A package's language determines its runner and commands — a non-JS package is
described in its own terms, not forced into JavaScript script names.

| Package                                              | Language          | Runner   | Test command                                   | Test environment                          | Coverage tooling                    |
| ---------------------------------------------------- | ----------------- | -------- | ---------------------------------------------- | ----------------------------------------- | ----------------------------------- |
| `dependency-update` (`agents/dependency-update/app/dependencyUpdate/`) | Python `>=3.13` | pytest 8.3.5 | `python -m pytest` (from the package dir; `testpaths=["tests"]`) | Local CPython process, no DB/network; all external I/O mocked | pytest-cov 7.1.0 (branch coverage) — see Coverage §, gate is MEASURED (~90%+ on implemented modules; no `fail_under` floor yet) |
| `agentcore-cdk-app` (`agents/dependency-update/agentcore/cdk/`) | TypeScript | jest 29 (ts-jest) | `pnpm test` / `npm test` (→ `jest`) | Node (jest default); CDK `Template` synth assertions | none configured (no `@vitest/coverage`/`nyc`, no `--coverage` wired) |
| `panel` (`panel/`) | TypeScript (Next.js 15, React 19) | Vitest 3.2.4 | `pnpm --filter panel run test` (→ `vitest run`); reachable from repo-root `make validate` via the JS/TS branch | Node (unit + integration projects) + jsdom (component project); no real DB in this story — Layer 2.5 integration harness lands in S-102 | `@vitest/coverage-v8` 3.2.4 (`pnpm --filter panel run test:coverage`) |

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

### Database / reaper layer — structural gap (added issue #94)

The stale-run reaper is **production behaviour with zero automated coverage.** `reap_stale_runs()`,
`v_runs.effective_status`, and the explanatory `run_events` contract exist in exactly one file —
`docs/reference/001_schema.sql` — and that file is applied by hand through the Supabase SQL Editor.
A repo-wide search for `reap_stale_runs`, `v_runs`, and `effective_status` across `*.py`, `*.ts`,
`*.sql`, `*.toml`, `*.yml`, and `Makefile` returns hits in that one file and nowhere else. No test,
no migration runner, and no CI step touches it. `coverage_gate` therefore says nothing about this
layer, in either direction.

Issue #94 verified the reaper against the live database and the evidence is genuine — but it is
**one-shot manual evidence, not a regression detector.** The runbook records AC1–AC4 and AC7 as PASS
(`docs/runbooks/issue-94-reaper-verification.md`); AC5 and AC6 are PENDING. Nothing in the repo will
notice if the deployed function, the view, or the cron schedule later drifts from the DDL in
`001_schema.sql`, because nothing compares them.

Ranked by residual risk:

| # | Gap | Risk | Why it ranks here | Evidence today |
|---|-----|------|-------------------|----------------|
| 1 | **Reaper "must NOT reap" behaviour is unverified in both directions.** The negative half of the CT-1 state-transition contract — within-grace rows stay `running`, `started_at IS NULL` is skipped, future-dated `started_at` is skipped, already-terminal rows are never mutated — has no automated test *and* no executed manual check. | **HIGH** | Every executed case was past-threshold, so all observed evidence is of the reaper firing. A regression that reaps too eagerly would kill healthy long runs — the exact failure the D8 grace window exists to prevent — and would be invisible to every check that has run. AC5 (the one check that would have caught it on a real run) is PENDING, blocked by #98. | EC-1..EC-5 and EC-8 are catalogued in `workstream/test-plan-issue-94.md` and mapped in the traceability matrix as negative pairings, but the matrix records no executed result for them. EC-9 (`seq` monotonicity) was confirmed incidentally. |
| 2 | **DDL drift between `001_schema.sql` and the deployed database is undetectable.** The schema file is a reference artifact applied manually; there is no migration runner, no checksum, no `schema diff` step. | **HIGH** | Issue #94 was itself a drift defect of this class — the scheduling block sat commented out while the design docs described a scheduled reaper. The same class of gap will recur silently. #100 (control plane must insert the `queued` row) is a second instance: a documented contract that no code or test enforces. | None. Verified by inspection only. |
| 3 | **Two-layer consistency (CT-2) has no repeatable assertion.** `runs.status == v_runs.effective_status` after the reaper fires, and `effective_status` == eventual `status` before it fires, were each observed once. | **MED** | This is the invariant the Phase 2 Run Detail panel is built on (DESIGN.md §5.3, PRD FR11a). A view-vs-function divergence would surface as the UI showing a terminal run as `running` — quiet, plausible, and wrong. | One synthetic observation + one real-run convergence, both manual. |
| 4 | **Event-schema contract (CT-3) is asserted by eye.** `level='error'`, `data.reaped_by`, `data.reason ∈ {START_TIMEOUT, RUNTIME_TIMEOUT}`, `seq = max(seq)+1`. | **MED** | The explanatory event is the *only* source of "why did this run die" (product-context success metric 3). The related orphan-`run_steps` defect (#99) — where the reaper wrote the event but left open `run_steps` pinned `running` — was fixed in the DDL and verified once against live Supabase (`test-plan-issue-99.md`, 19/19 assertions PASS), but that verification is manual: no committed automated assertion guards either the event schema or the new step-closure behaviour, so a regression in `reap_stale_runs()` would still go unnoticed here. | Real-run event inspected once (`seq=10`, no `uq_run_events_seq` collision); #99 step-closure confirmed once against live Supabase, no repeatable test. |
| 5 | **Concurrency / idempotency of `for update skip locked` (EC-5, EC-6) unverified.** Two overlapping ticks must transition a row once and write exactly one event. | **MED** | A double-fire produces a `seq` collision that aborts the whole tick, so one bad row stalls reaping for every run. Low likelihood at one tick per minute; high blast radius. | Not executed. |
| 6 | **`agent_reporter.py` is the write side of this same contract and has no committed tests** (buffering, 3-retry backoff, 4xx-not-retried, `seq` assignment, stderr/CloudWatch fallback). | **MED** | It is coverage-omitted, so the 94% figure excludes it entirely. AC6 — the CloudWatch fallback — is PENDING, meaning neither the automated nor the manual path covers it. Follow-up #97 (`unwrap_payload` double-wrap) and #98 (run dies without reporting terminal status) are both failures in this reporting surface. | None (design doc notes prior ad-hoc testing with a fake client). |

**Is this in scope to fix now? No.** Closing gaps 1–5 requires a Layer 2.5 harness that does not exist
— a local Postgres with `pg_cron` (testcontainers, `docker-compose`, or the Supabase CLI) plus pgTAP
or a Python DB-integration suite. Standing that up means new dependencies and new CI infrastructure,
which is an approved-task decision, not something to smuggle into an infrastructure-verification PR.
Gap 6 (`agent_reporter.py`) is closable at Layer 1/2 with no new dependencies, but it is a different
module than issue #94 touched and belongs in its own change.

**Recommended follow-up issue (not filed by `qa-engineer` — hand to the user):**
*"Add a Layer 2.5 database harness and pin the reaper contract with automated tests."* Scope: choose a
local Postgres+`pg_cron` runner; port CT-1 (full transition table, **including the must-not-reap
rows**), CT-2, CT-3, and EC-1..EC-6/EC-9 from `workstream/test-plan-issue-94.md` into executable
assertions; apply `001_schema.sql` clean in the harness so DDL drift fails CI; wire the suite into
`make validate` and `ci.yml`. This single issue covers ranked gaps 1–5 and would have caught #99
(orphan `run_steps`) as an assertion rather than a manual observation.

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
