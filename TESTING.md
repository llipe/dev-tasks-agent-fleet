---
version: 1.1
name: Testing Standard
description: Canonical testing contract for dev-tasks-agent-fleet — declares test layers, runners, commands, fixtures, and coverage policy across every package in the pnpm workspace.
status: filled
owner: qa-engineer
---

<!--
FILLED by qa-engineer from repository inspection; kept current by
technical-writer whenever a documentation-drift pass finds this file has
fallen behind the actual workspace. This file is the canonical testing
contract for this repository. Findings recorded below are gaps, not satisfied
requirements — absence of tooling is never reported as a pass.

Correction (2026-09-15, planner drift pass): a prior "adds Claude support for
dev-tasks" commit (9f8cbad) silently overwrote this file with a generic
single-package scaffold, dropping ~400 lines of accumulated per-story history
and the entire `panel` package section. That overwrite is corrected here. The
full pre-overwrite history remains recoverable from git (`git show
1e76e61:TESTING.md`) and from the per-story `workstream/fidelity-report-*.md`
files if a future pass wants to restore narrative detail; this version
prioritizes an accurate, current-state description of every package over
reproducing the full incremental history inline.
-->

## Workspace shape

This is a **pnpm workspace with two declared packages** (`pnpm-workspace.yaml`):

- `panel` — the Next.js 15 / React 19 Agent Fleet Control Panel (App Router,
  Supabase-backed). This is the active, most-tested package in the repo and
  the subject of every Phase 2 UI story (S-101 onward, including the v3 "UI
  Depth" batch, S-142–S-148).
- `agents/dependency-update/agentcore/cdk` — a small CDK infrastructure-as-code
  package with a single synth smoke test.

A third package sits outside the pnpm workspace (it is a separate Python
project, not a Node package): `agents/dependency-update/app/dependencyUpdate`
— the `dependency-update` agent (the original, and still active, codebase).

Root `package.json` (`private: true`, `packageManager: pnpm@10.11.0`,
`engines.node: ">=22 <25"`) declares thin aggregate scripts that all delegate
via `pnpm --filter panel run ...` — see Commands below. The repo-root
`Makefile` is the actual cross-language aggregate: it runs a Python branch
(`*-py`, delegating into the `dependency-update` package dir) and a JS/TS
branch (`*-js`, delegating into `panel` via the pnpm workspace) and fails if
either fails.

## Test Layers

| Layer    | Name                      | Scope                                                                                                                             | Status |
| -------- | ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------ |
| 1        | Deterministic foundations | Unit tests and schema/contract assertions with no network, database, or wall-clock dependency.                                    | configured — `dependency-update` `tests/unit/` (pytest `unit` marker); `panel` Vitest `unit` project (`panel/tests/unit/`). |
| 2        | Constrained model/tool    | CLI, filesystem, subprocess, component, and fixture tests with external providers replaced by deterministic fixtures or stubs. | configured — `dependency-update` `tests/component/` (pytest `component` marker); `panel` Vitest `component` project (`panel/tests/component/`, jsdom, mocked externals). |
| 2.5      | Integration               | Real database, migrations, RLS, and schema contracts without a mocked data layer.                                                 | **configured** — `panel` Vitest `integration` project (`panel/tests/integration/`), against a real local Postgres brought up by the Supabase CLI (`supabase start` / `supabase db reset`). Docker-gated via `panel/tests/integration/db.ts` (`probeLocalDb`); see CI-vs-local gating below. Not applicable to `dependency-update` (no owned database) or the CDK package. |
| E2E      | End-to-end                | Playwright full-stack browser scenarios.                                                                                          | **configured** — `panel/playwright.config.ts` + `panel/tests/e2e/` (retries 0, one worker, headless in CI, `webServer` = `next dev`), driving the browser against the real local Supabase stack with AgentCore stubbed at the HTTP boundary. |
| Contract | Contract validation       | `dt verify` API-spec diff, impact, and drift checks.                                                                              | not configured; no repository API spec (`panel` has no OpenAPI surface yet). |
| 3        | Product evaluation        | Semantic or groundedness evaluation for LLM features.                                                                             | not configured — `dependency-update`'s `fix_agent.py` uses an LLM (`strands-agents`); the code path is tested (mocked model), output quality is not evaluated. Not applicable to `panel`. |
| 4        | Human evaluation          | Human review and safeguard gates.                                                                                                 | manual only — PR review is the enforcement backstop. |

### Layer boundaries

- **Layer 1 must not:** open sockets or database connections, invoke real external services, read the wall clock without injection, depend on test order, or assert internal call counts as a proxy for behavior.
- **Layer 2 must not:** replace the system under test at its own public entry point, reimplement production filtering or persistence in a fake, or claim provider behavior that was only tested against a double.
- **Layer 2.5 must not:** mock the data layer or use application-level filtering as evidence of database/RLS policy.
- **E2E must not:** assert on internal state or implementation details; it must assert observable user-facing behavior.
- **Contract validation must not:** test internal business logic; it checks the boundary/interface only.
- **Escalation:** when a Layer 1 test needs a real dependency, move it to Layer 2 instead of growing a behavior-reimplementing double; when a Layer 2 test needs a real database, move it to Layer 2.5.

## CI-vs-local Layer 2.5 gating

`panel`'s Layer 2.5 (`integration` project) suites are **Docker-gated** by
`panel/tests/integration/db.ts` (`probeLocalDb`), controlled by
`REQUIRE_LOCAL_DB`:

- **Local (unset).** An unreachable stack makes the suites **skip with a
  recorded reason** — a missing Docker daemon must never redden a developer's
  `pnpm --filter panel run validate`.
- **CI (`REQUIRE_LOCAL_DB=1`).** A probe failure is a hard **failure**, not a
  skip, because every Layer 2.5 suite calls `probeLocalDb()` at module
  top-level. This applies uniformly across the current integration suites
  (`schema`, `seed-schema`, `reaper`, `queries`, `status-parity`,
  `rls-deny-all`, `dashboard-query`, `runs-by-agent`, `run-detail-queries`,
  `stream-e2e`, `invoke-insert`, `synthetic-agent-form`, `e2e-fixture.smoke`,
  `filtered-runs`, `pull-request-artifacts`, `repository-mutations`, `auth-login`)
  and to every future one by convention.

`.github/workflows/ci.yml`'s `panel-quality` job sets `REQUIRE_LOCAL_DB=1`,
starts the stack (`supabase start` + `db reset`), exports the local Supabase
env, warms Realtime, runs `pnpm --filter panel run test:coverage`, installs
Chromium, and runs `pnpm --filter panel run test:e2e` — so a Layer 2.5 skip
can no longer pass CI vacuously.

## Packages

| Package                | Language                          | Runner                              | Test command                                                                                          | Test environment                                                                                                                        | Coverage tooling                                                                                          |
| ---------------------- | --------------------------------- | ------------------------------------ | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| `dependency-update` (`agents/dependency-update/app/dependencyUpdate/`) | Python `>=3.13`                  | pytest 8.x                            | `python -m pytest` (`testpaths=["tests"]`); via `make test` from the package dir or `make test-py` from repo root | Local CPython process, no DB/network; all external I/O (boto3, `requests`, `jwt`, `subprocess`) mocked                                    | pytest-cov 7.1.0, branch coverage on; `[tool.coverage]` config; `coverage_gate` MEASURED (no `fail_under` floor yet) |
| `agentcore-cdk-app` (`agents/dependency-update/agentcore/cdk/`)        | TypeScript                        | jest 29 (ts-jest)                    | `pnpm test` (→ `jest`), run from the package dir; not reached by the repo-root aggregate                  | Node (jest default); CDK `Template` synth assertions                                                                                       | none configured                                                                                              |
| `panel` (`panel/`)     | TypeScript (Next.js 15, React 19) | Vitest 3.2.x (`unit`/`component`/`integration` projects) + Playwright | `pnpm --filter panel run test` (→ `vitest run`, all three projects); `test:unit` / `test:integration` (`--passWithNoTests`) run one project; `test:e2e` (→ `playwright test`) gated separately; reachable from repo-root `make validate`/`pnpm run validate` | Node (unit + integration), jsdom (component, `setupFiles: tests/setup.ts`); `integration` project pinned `singleFork`/sequential (shared local Postgres — avoids the cross-file `reap_stale_runs()` race) | `@vitest/coverage-v8` (`pnpm --filter panel run test:coverage`) |

Tests for `panel` live under `panel/tests/` in four directories:
`unit/` (Layer 1, ~45 files), `component/` (Layer 2, jsdom, ~36 files),
`integration/` (Layer 2.5, real local Postgres, ~19 files), and `e2e/`
(Playwright specs + fixtures + `global-setup.ts`/`global-teardown.ts`).
`tests/stubs/` holds test-only module replacements (e.g. neutralizing the
`server-only` import guard so server modules can run under the Vitest `node`
environment; the real guard still fires in `next build`). `tests/helpers/`
holds shared test utilities.

Tests for `dependency-update` live in `tests/unit/` and `tests/component/`
(pytest markers), with shared fixtures centralized in `tests/conftest.py`;
`tests/fixtures/` (`.gitkeep` only) is the intended, currently-empty home for
recorded API payloads.

### Test environment

**`dependency-update`.** Plain local CPython, no database/network/browser.
Every external boundary is patched via `unittest.mock`/`pytest-mock`.

**`panel`.** `panel/vitest.config.ts` declares three Vitest `projects` mirroring
this file's layer taxonomy (see the config's own header comment): `unit`
(node), `component` (jsdom), `integration` (node, real local Postgres via the
Supabase CLI stack, `singleFork`). `panel/playwright.config.ts` drives a real
browser against the same real stack for E2E, with AgentCore stubbed at the
HTTP boundary (`AWS_ENDPOINT_URL_BEDROCK_AGENTCORE`) so the credential branch
runs but no AWS call is made.

### Runtime parity

| Package             | Local                                                   | CI                                                | Production / runtime |
| -------------------- | -------------------------------------------------------- | ---------------------------------------------------- | ----------------------- |
| `dependency-update` | CPython 3.13.x (dev venv)                                | **3.13 + 3.14 matrix** (`.github/workflows/ci.yml`, `python-quality` job) | `PYTHON_3_14` (AgentCore); Docker build base `python:3.13-slim` |
| `panel`             | Node `>=22 <25` per `package.json` `engines`; the pnpm-managed install **hard-rejects** an ambient Node outside that range (`ERR_PNPM_UNSUPPORTED_ENGINE` reproduced live against Node 26 — see Harness defects) | Node **22** pinned (`actions/setup-node@v4`, `panel-quality` job) | Fly.io deploy (pre-deploy scaffold; see `docs/technical-guidelines.md` §13) |
| `agentcore-cdk-app` | Node (unpinned locally)                                  | not in CI yet                                        | n/a — build/deploy tooling |

## Commands

### JavaScript / TypeScript canonical scripts (`panel`)

| Script             | Purpose                                                                | Status  |
| ------------------ | ----------------------------------------------------------------------- | ------- |
| `lint`             | ESLint static analysis                                                 | present |
| `lint:fix`         | ESLint auto-fix                                                        | present |
| `format`           | Prettier write                                                         | present |
| `format:check`     | Prettier verification                                                  | present |
| `typecheck`        | `tsc --noEmit`                                                         | present |
| `test`             | Aggregate Vitest run — all three projects (unit/component/integration) | present |
| `test:unit`        | Vitest `unit` project only                                             | present |
| `test:integration` | Vitest `integration` project only (`--passWithNoTests`)                | present |
| `test:e2e`         | Playwright (`playwright test`)                                          | present |
| `test:coverage`    | `vitest run --coverage` (`@vitest/coverage-v8`, all three projects)     | present |
| `audit`            | `node scripts/audit.mjs` — resilient `pnpm audit` wrapper (retries a network-unreachable advisory registry, soft-passes with a warning; a real high/critical advisory fails) | present |
| `validate`         | `lint && format:check && typecheck && test && audit`                   | present |

Root `package.json` mirrors every one of these (minus `lint:fix`/`format`) as
thin `pnpm --filter panel run <script>` wrappers, so `pnpm run test` /
`pnpm run validate` from the repo root reach `panel` directly.

### Non-JS packages

| Package             | Purpose                      | Command                                                                              |
| -------------------- | ------------------------------ | ---------------------------------------------------------------------------------------- |
| `dependency-update` | Install dev deps              | `make install` → `pip install -e '.[dev]'`                                              |
| `dependency-update` | Run all tests                 | `make test` → `python -m pytest`                                                        |
| `dependency-update` | Layer 1 only (unit)           | `make test-unit` → `python -m pytest -m unit`                                           |
| `dependency-update` | Layer 2 only (component)      | `make test-component` → `python -m pytest -m component`                                 |
| `dependency-update` | Lint / format / typecheck     | `make lint` (`ruff check .`) / `make format-check` (`ruff format --check .`) / `make typecheck` (`mypy .`) |
| `dependency-update` | Coverage                      | `make test-cov` → `python -m pytest --cov --cov-report=term-missing`                     |
| `dependency-update` | Audit                         | `make audit` → `pip-audit . --strict`                                                    |
| `dependency-update` | **Aggregate gate**            | `make validate` → lint + format-check + typecheck + test-cov + audit (fail-fast)          |
| `agentcore-cdk-app` | Run test / build / format     | `pnpm test` (→ `jest`) / `pnpm run build` (→ `tsc`) / `pnpm run format:check` (from its own package dir) |

### Repo-root aggregate (`Makefile`)

The repo-root `Makefile` runs both branches: `make install|lint|format-check|typecheck|test|audit|validate`
each fan out to a `-py` target (delegates via `make -C agents/dependency-update/app/dependencyUpdate`)
and a `-js` target (delegates via `pnpm --filter panel run ...`), and the
aggregate fails if either branch fails. `make validate` = `validate-py` +
`validate-js`.

### Gate reachability

- **Aggregate test command:** `make test` (repo root) reaches both `dependency-update` (Python) and `panel` (JS/TS, all three Vitest projects). It does not reach `agentcore-cdk-app` (tested via its own `pnpm test`, not folded into the root aggregate).
- **CI gate:** `.github/workflows/ci.yml` runs two jobs on every push/PR to `main`: `python-quality` (3.13 + 3.14 matrix — lint → format-check → typecheck → `pytest --cov` → `pip-audit`) and `panel-quality` (Node 22 — boots the Supabase stack with `REQUIRE_LOCAL_DB=1`, lint → format:check → typecheck → the S-122 auth-gate parser test + shellcheck → `test:coverage` (incl. gated Layer 2.5) → Playwright E2E → audit). Neither job has a `paths:` filter excluding its package.
- **Deploy gate:** none. `panel` deploys to Fly.io as a documented operator runbook (`docs/technical-guidelines.md` §13, `docs/runbooks/panel-deployment.md`); `dependency-update` deploys via the AgentCore CLI/CDK. Neither invokes the aggregate gate automatically.

## Coverage

### Thresholds and baseline policy

- **`dependency-update`:** pytest-cov 7.1.0, branch coverage on, config in `pyproject.toml`. No hard `fail_under` floor yet — coverage is measured and reported on every `make test-cov`/`make validate` run. Baseline: high (~90%+) on the implemented pipeline modules; `credentials.py` **100%** (as of #106/#108/#109); `main.py` and `agent_reporter.py` remain coverage-excluded/untested (see gap table in `docs/technical-guidelines.md` §11/§18 and the archived per-issue fidelity reports for the full per-module figures).
- **`panel`:** `@vitest/coverage-v8` is configured (`vitest.config.ts` declares the provider; `test:coverage` is a real, runnable script) and reachable from CI (`panel-quality` job runs `test:coverage`, not just `test`). **No repo-level numeric coverage baseline has been recorded for `panel` as a whole** — individual stories have recorded per-module coverage figures in their own fidelity reports (see `workstream/fidelity-report-S-*.md`), but no aggregate `panel`-wide percentage has been captured and committed here. This is a tracked gap, not a `SKIPPED` provider situation — the tooling exists and runs; only the aggregate number has never been pulled and recorded in this file.
- **`agentcore-cdk-app`:** no coverage tooling configured (out of scope — IaC synth smoke test only).

### Ground-truth run (2026-09-15, PRD-scope rollup for the "UI Depth" batch, S-142–S-148)

`pnpm --filter panel run validate` executed live against a real local Supabase
stack (Node 22.23.2, pnpm 10.11.0, `REQUIRE_LOCAL_DB=1`): lint/format:check/
typecheck/audit PASS; `test` — **100 test files passed, 1 skipped (101 total);
1205 tests passed, 4 skipped (1209 total)**. Every `tests/integration/*`
file printed its local-Postgres-reachable line and ran for real, including the
Layer 2.5 files this batch added/extended: `filtered-runs.test.ts` (14 tests,
S-143/S-144/S-146), `repository-mutations.test.ts` (15 tests, S-147/S-148),
and `pull-request-artifacts.test.ts` (6 tests, S-144). The 4 skips are all in
`tests/unit/bundle-secrets.test.ts`, gated behind `RUN_BUNDLE_SECRET_TEST=1`
(pre-existing, CI-only, unrelated to this batch). Full detail:
`workstream/coverage-report-prd-agent-fleet-panel-v3-ui-depth.md`.

**Known gap carried forward from that rollup, not fixed here (routed to
`product-engineer`/`developer`):** `workstream/test-plan-prd-agent-fleet-panel-v3-ui-depth.md`
§3 specified 11 new E2E scenarios (E2E-1…E2E-11, four new spec files) for this
batch; `panel/tests/e2e/` contains only the pre-existing specs
(`auth`, `density`, `edge-cases`, `invoke`, `live-tail`, `stale-and-artifact`) —
0 of the 11 planned scenarios were added. Layer 1/2/2.5 coverage for the batch
is strong (see above); the E2E layer for this batch's new screens (`/runs`,
`/repositories`, the run-detail steps panel filter, the run-history filter
bar) is a real, named gap against the pre-implementation test plan, not a
silent one.

### When coverage cannot be measured

If no coverage provider is configured for a package, the gate reports
`SKIPPED(<reason>)` — never a pass — and structural gap analysis runs instead.
Absence of tooling is never reported as absence of gaps.

## Fixtures and Mocking

**`dependency-update`.** Test doubles use `unittest.mock`/`pytest-mock`,
patched at the module boundary (`credentials.boto3`, `credentials.requests`,
`credentials.jwt`). `tests/conftest.py` centralizes temp-dir project fixtures
and auto-applies `unit`/`component` markers by directory. `tests/fixtures/`
remains empty (`.gitkeep` only) — no recorded API payloads yet.

**`panel`.** Component tests (jsdom) mock external providers (Supabase client,
`EventSource`, fetch) at the module boundary; integration tests use a real
local Postgres with no mocked data layer. `tests/stubs/server-only.ts`
neutralizes the `server-only` import guard for unit-testing server modules
under Node (the real guard still fires in `next build`). E2E stubs AgentCore
only at the HTTP boundary (`tests/e2e/fixtures/agentcore-stub.ts`), never the
database.

### Rules

- Shared fixtures and helpers live in one place per package. Duplicating a token builder or a client mock across test files is a defect.
- A test double must not reimplement the logic it stands in for.
- Stubbed globals are restored after each test.
- Placeholder assertions such as `expect(true)` are prohibited.

## Security-Negative Tests

Required for every authentication and authorization code path.

**`dependency-update` — `credentials.py` (GitHub App RS256 JWT + Supabase key resolution).**
The client-side transport/secret-store failure classification is covered and
**100%** (`SUPABASE_UNREACHABLE`/`GITHUB_UNREACHABLE`/`SUPABASE_KEY_UNAVAILABLE`/
`PEM_UNAVAILABLE`, #106/#108/#109). The server-side *rejection* cases (invalid
signature, expired credential, wrong issuer/audience, tampered claims) remain a
**GAP** — GitHub's token endpoint is mocked, so no test proves a bad assertion
is refused. Cross-tenant access is filtered by `github_org_slug` in
`_get_installation` (tested for the empty-result path) but the agent
authenticates with the **service-role key, which bypasses RLS** (accepted risk,
`docs/technical-guidelines.md` §5/§8) — there is no policy layer to test denial
against.

**`panel` — auth release gate (S-122, replacing the S-115 privacy gate).**
`panel/scripts/panel-auth-check.mjs` is unit-tested (`tests/unit/panel-auth-check.test.ts`,
30 tests) with all five exported decision functions at 100% coverage: a
protected UI path served 200, an SSE path served 200, a successful signup
(AC17), and a missing auth env-var name all make the verdict fail;
non-array/garbage input, a network error/timeout, a non-`/login` redirect, and
empty input all fail closed. The CLI exit-code contract
(`tests/unit/panel-auth-check-cli.test.ts`, 4 tests) proves the process-level
"gate observed failing" behavior end to end. CI runs both the parser suite by
name and `shellcheck` on the wrapper script independently of the broader
suite. RLS is asserted deny-all for the anon role in
`tests/integration/rls-deny-all.test.ts` against the real local Postgres.

## Harness defects to track

1. **Local/CI Node major-version mismatch (`panel`).** `panel/package.json` declares `engines.node: ">=22 <25"`; an ambient Node outside that range (e.g. 26) makes `pnpm install --frozen-lockfile` hard-fail with `ERR_PNPM_UNSUPPORTED_ENGINE` before any test can run — reproduced live during the 2026-09-15 PRD rollup. Expected state: a repo-root `.nvmrc`/Volta/mise pin, or a pre-flight check, so an ad-hoc contributor shell does not silently fail on the `panel` workspace.
2. **`dependency-update` — `main.py` and `agent_reporter.py` remain untested/coverage-excluded.** See `docs/technical-guidelines.md` §11/§18 for the ranked gap detail; unchanged by this pass.
3. **`dependency-update` — security-negative server-side rejection cases remain a gap** (see above); unchanged by this pass.
4. **`panel` — 0/11 planned E2E scenarios for the S-142–S-148 batch were delivered** against `workstream/test-plan-prd-agent-fleet-panel-v3-ui-depth.md` §3 (see Coverage § above). Routed to `product-engineer`/`developer`, not fixed here.
5. **`panel` — no aggregate `panel`-wide numeric coverage baseline has been recorded in this file.** Per-story figures exist in individual fidelity reports; a consolidated number has never been pulled and committed here.
6. **`agentcore-cdk-app` is not reached by the repo-root aggregate `test`/`validate` targets.** Tested via its own `pnpm test`; low priority (single synth smoke test, IaC-only).
