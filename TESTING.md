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
— the `dependency-update` agent (the original, and still active, codebase) —
`agents/security-analyst/app/securityAnalyst` — the `security-analyst`
agent (S-125–S-141), which mirrors the sibling's layout, Makefile, and
`pyproject.toml` conventions — `agents/code-review/app/codeReview` — the
`code-review` agent (S-204 onward), which mirrors `security-analyst` — and
`agents/bug-fix/app/bugFix` — the `bug-fix` agent (scaffold since S-180),
which mirrors the same conventions.

Root `package.json` (`private: true`, `packageManager: pnpm@10.11.0`,
`engines.node: ">=24 <27"`) declares thin aggregate scripts that all delegate
via `pnpm --filter panel run ...` — see Commands below. The repo-root
`Makefile` is the actual cross-language aggregate: it runs a Python branch
(`*-py`, looping over every agent package dir in `AGENT_DIRS`) and a JS/TS
branch (`*-js`, delegating into `panel` via the pnpm workspace) and fails if
either fails.

## Test Layers

| Layer    | Name                      | Scope                                                                                                                             | Status |
| -------- | ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------ |
| 1        | Deterministic foundations | Unit tests and schema/contract assertions with no network, database, or wall-clock dependency.                                    | configured — `dependency-update`, `security-analyst`, and `code-review` `tests/unit/` (pytest `unit` marker); `panel` Vitest `unit` project (`panel/tests/unit/`). |
| 2        | Constrained model/tool    | CLI, filesystem, subprocess, component, and fixture tests with external providers replaced by deterministic fixtures or stubs. | configured — `dependency-update` and `security-analyst` `tests/component/` (pytest `component` marker; `security-analyst`'s mock `subprocess.run` for all five scanners and drive `main.invoke()` end to end); `code-review` `tests/integration/` (pytest `integration` marker; drives `main.invoke()` against a reporter sink with the `requests` transport stubbed, and context assembly — `context/diff.py` from S-206, `context/issues.py` and `context/spec.py` from S-207, and the S-209 prompt built on top of them — through the real `GitHubClient` over recorded fixtures (`sample-pr` with a hand-written golden diff; `issue-315` with the #315 issue shape and the webhook-triggers spec), and from S-213 the whole pipeline through `tests/helpers/pipeline_run.py` with `FakeConverse`); `panel` Vitest `component` project (`panel/tests/component/`, jsdom, mocked externals). |
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
| `security-analyst` (`agents/security-analyst/app/securityAnalyst/`)     | Python `>=3.13`                  | pytest 8.x                            | `python -m pytest` (`testpaths=["tests"]`); via `make test` from the package dir or `make test-py` from repo root | Local CPython process, no DB/network; scanner binaries (`semgrep`, `gitleaks`, `trivy`, `checkov`, `codeql`) are NEVER invoked — every runner mocks `subprocess.run` against checked-in JSON/SARIF fixtures in `tests/fixtures/`; `boto3`/`requests`/`jwt` mocked as in the sibling | pytest-cov, branch coverage on; `[tool.coverage]` config with **`fail_under = 90`** (set at PRD close; measured 97%) |
| `code-review` (`agents/code-review/app/codeReview/`)                   | Python `>=3.13`                  | pytest 8.x                            | `python -m pytest` (`testpaths=["tests"]`); via `make test` from the package dir or `make test-py` from repo root | Local CPython process, no DB/network. `tests/unit/` (Layer 1, `unit` marker) and `tests/integration/` (Layer 2, `integration` marker: `invoke` against a reporter sink that replaces only the vendored reporter's HTTP layer, `requests` transport stubbed to refuse every call; context-assembly tests drive the real `GitHubClient` over `StubTransport` and compare against a checked-in golden file such as `tests/fixtures/github/sample-pr/expanded_diff.golden`). `tests/fixtures/params_cases.json` is shared with the panel (CT-01). GitHub calls are stubbed by `tests/helpers/github_stub.py` (`StubTransport`, recorded `tests/fixtures/github/`) | pytest-cov, branch coverage on; **`fail_under = 90`** from the first story (`main.py` is not omitted) |
| `bug-fix` (`agents/bug-fix/app/bugFix/`)     | Python `>=3.13`                  | pytest 8.x + hypothesis (property tests)                           | `python -m pytest` (`testpaths=["tests"]`); via `make test` from the package dir or `make test-py` from repo root | Local CPython process, no DB/network; Supabase faked at `agent_reporter._SupabaseClient`, `boto3`/`requests`/`jwt` mocked as in the siblings; GitHub REST and GraphQL faked at the `requests.Session` boundary by `tests/component/fake_github.py` (S-186, extended in S-185 with issue facts, open pulls, the closing-reference query and fault injection, and in S-188 with comment deletion; no extra HTTP-mock dependency; real `Link` header parsing covered at L1 by `tests/unit/test_github_client.py`); Supabase `v_runs` reads faked by a PostgREST double in `tests/component/test_refusal.py` (reused by `test_claim.py`); marker grammar pinned by golden bodies in `tests/fixtures/contract/markers/`. S-189: real `git` at Layer 2 on fixture repos in `tests/fixtures/repos/`, served from a local bare remote by `tests/component/repo_fixtures.py`, whose `SpawnSpy` checks the production `setpriv` prefix on every `fixer` spawn and runs it as the current user; `StubSandbox` for gate/install argv, `LocalSandbox` for real offline `npm ci`/`pnpm install --frozen-lockfile`/`make` (skipped when the binary is missing). Layer 2 process checks: `tests/component/test_sandbox_proc.py` runs `sandbox.py`'s real command chain with real processes (exec-through `setpriv`/`srt` shims, sweep scoped to a per-test marker). Layer 2 image checks: `make image-smoke` (Docker, ARM64) runs `scripts/image-smoke.sh` against the built image | pytest-cov, branch coverage on; `[tool.coverage]` config with **`fail_under = 90`** from the first story (S-180 measured 97%) |
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
| `security-analyst`  | CPython 3.13.x (dev venv)                                | **3.13 + 3.14 matrix** (same job; `agent` matrix axis added at PRD close) | AgentCore container built from `python:3.13-slim` (Dockerfile pins CodeQL 2.27.0, Gitleaks 8.30.1, Trivy 0.74.0, Node 22, `semgrep` 1.180.0 in an isolated venv at `/opt/semgrep` (#360), `checkov` via `pyproject.toml`) |
| `code-review`       | CPython 3.13.x (dev venv)                                | **3.13 + 3.14 matrix** (same job; added at S-204) | AgentCore container built from `python:3.13-slim` with no system toolchains (runtime lands with S-214) |
| `panel`             | Node `>=24 <27` per `package.json` `engines`; the pnpm-managed install **hard-rejects** an ambient Node outside that range (`ERR_PNPM_UNSUPPORTED_ENGINE` reproduced live against Node 26 — see Harness defects) | Node **22** pinned (`actions/setup-node@v4`, `panel-quality` job) | Fly.io deploy (pre-deploy scaffold; see `docs/technical-guidelines.md` §13) |
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
| `security-analyst`  | All of the above              | Identical `Makefile` targets (`make test`, `test-unit`, `test-component`, `lint`, `format-check`, `typecheck`, `test-cov`, `audit`, `validate`) run from `agents/security-analyst/app/securityAnalyst/` |
| `code-review`       | All of the above              | Same targets run from `agents/code-review/app/codeReview/`, with `test-integration` (`python -m pytest -m integration`) in place of `test-component`; `make audit` is plain `pip-audit . --strict` (no exception) |
| `security-analyst`  | Audit                         | `make audit` → `pip-audit . --strict`, no ignored vulnerabilities. `semgrep` is installed in its own venv in the Dockerfile, not in `pyproject.toml`, so its exact `mcp`/`opentelemetry-api` pins stay out of the audited tree (#360). `tests/unit/test_semgrep_isolation.py` pins this |
| `bug-fix`           | All of the above              | Identical `Makefile` targets run from `agents/bug-fix/app/bugFix/`; `make audit` → `pip-audit . --strict` |
| `bug-fix`           | Image (Layer 2, Docker)       | `make image` → `docker build --platform linux/arm64 -t bug-fix:local .`; `make image-smoke` → build, then `scripts/image-smoke.sh` (privilege checks under `--security-opt no-new-privileges` to emulate AgentCore; toolchain versions incl. pinned `claude`/`srt`; the D-110 root wrapper and `setpriv` drop: default user root, no `sudo`, uid/gid 10002 with no groups, no capabilities and `NoNewPrivs` 1, no way back to root, root `/proc/<pid>/environ`/`mem` unreadable, `fixer_exec.py` env and root refusal, `Sandbox().sweep()`; `localhost` through nss-myhostname, `127.0.0.1` first, with an empty read-only `/etc/hosts` mounted (D-111); dir owners; managed-policy and `srt-settings.json` ownership; S-189: git `--attr-source`, `safe_git` end to end as root under `no_new_privs`, fixer-owned materialized files, planted hooks never run in the wrapper's capture, `/work/wrapper/repo/.git/config` unreadable as `fixer`; S-189 fix round: `fs.protected_hardlinks` and `fs.protected_symlinks` are 1, the image's tar is GNU tar, the clone's `fsckObjects` refuses a symlink-plus-directory tree, and with fsck off `materialize` writes nothing through the link). Not part of `validate`: it needs Docker |
| `agentcore-cdk-app` | Run test / build / format     | `pnpm test` (→ `jest`) / `pnpm run build` (→ `tsc`) / `pnpm run format:check` (from its own package dir) |

### Repo-root aggregate (`Makefile`)

The repo-root `Makefile` runs both branches: `make install|lint|format-check|typecheck|test|audit|validate`
each fan out to a `-py` target (loops `make -C <dir>` over every agent package dir in `AGENT_DIRS`, fail-fast)
and a `-js` target (delegates via `pnpm --filter panel run ...`), and the
aggregate fails if either branch fails. `make validate` = `validate-py` +
`validate-js`.

### Gate reachability

- **Aggregate test command:** `make test` (repo root) reaches `dependency-update`, `security-analyst`, `code-review`, and `bug-fix` (Python) and `panel` (JS/TS, all three Vitest projects). It does not reach `agentcore-cdk-app` (tested via its own `pnpm test`, not folded into the root aggregate).
- **CI gate:** `.github/workflows/ci.yml` runs two jobs on every push/PR to `main` and to `integration/**` branches: `python-quality` (one entry per agent — `dependency-update`, `security-analyst`, `code-review`, `bug-fix` — on a 3.13 + 3.14 matrix — lint → format-check → typecheck → `pytest --cov` → `make audit`, so each agent's Makefile is the single source of its `pip-audit` flags; the `bug-fix` legs also install pnpm 10.11.0 with `pnpm/action-setup`, so its real `pnpm install --frozen-lockfile` test runs instead of skipping, DF-189-09) and `panel-quality` (Node 22 — boots the Supabase stack with `REQUIRE_LOCAL_DB=1`, lint → format:check → typecheck → the S-122 auth-gate parser test + shellcheck → `test:coverage` (incl. gated Layer 2.5) → Playwright E2E → audit). Neither job has a `paths:` filter excluding its package.
- **Deploy gate:** none. `panel` deploys to Fly.io as a documented operator runbook (`docs/technical-guidelines.md` §13, `docs/runbooks/panel-deployment.md`); `dependency-update`, `security-analyst`, and `bug-fix` deploy via the AgentCore CLI/CDK (`bug-fix` since S-181, `docs/runbooks/bug-fix-agent.md`); `code-review` is not deployed yet (its runtime lands with S-214). None invokes the aggregate gate automatically.

## Coverage

### Thresholds and baseline policy

- **`security-analyst`:** pytest-cov, branch coverage on, `fail_under = 90` enforced by `make test-cov`/`make validate` and CI (set at PRD close, 2026-09-17, after porting the sibling's `credentials`/`signal_backstop`/`scrubber` tests; measured 97%, 712 tests). `main.py` and `agent_reporter.py` are coverage-omitted as in the sibling.
- **`code-review`:** pytest-cov, branch coverage on, `fail_under = 90` enforced by `make test-cov`/`make validate` and CI from the scaffold story (S-204). Only `agent_reporter.py` (vendored, byte-identical to the sibling) is coverage-omitted; `main.py` is measured. Baseline at S-204: **98%** (356 tests, 2 skipped until `agentcore.json` lands with S-214). Wave A PRD-level gate (2026-10-23, `integration/code-review-agent` @ `9e1d73e` plus `tests/integration/test_cross_story_joins.py`): **99.51%** (4,104 statements, 1,154 branches; 3,115 passed, 2 skipped, 2 strict xfails pinning QA-PRD-01/02). After the Wave A QA fix (`fix/S-213-wave-a-qa`): **99.64%**, 3,160 passed, 2 skipped, 0 xfails; every module 100% except `pipeline.py` 97% and `main.py` 98% (defensive failure-path branches). Detail: `workstream/coverage-report-prd-code-review-agent.md`.
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
`workstream/archive/coverage-report-prd-agent-fleet-panel-v3-ui-depth.md`.

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

**`code-review`.** `GitHubClient` takes an injected transport: tests use
`tests/helpers/github_stub.py` (`StubTransport`, which records every call and
answers from a route table) and the recorded fixtures under
`tests/fixtures/github/<sample>/` (`routes.json` plus GitHub-shaped bodies,
loaded with `load_fixture("sample-pr")` or `load_fixture("issue-315")`; no real tokens, accounts, or SHAs).
Fidelity-report inputs for the Layer 1 verifier parser (S-208) live in
`tests/fixtures/reports/` (a byte copy of `workstream/fidelity-report-S-170.md`
plus synthetic AC-7, no-heading, numbered-heading, empty, and bullet-list
reports, described in that directory's `README.md`) and are loaded with
`tests/helpers/reports.py::report_text(<file name>)`, which decodes the bytes so
line endings are exactly the ones on disk.
The budget and prompt tests (S-209) build the readers' outputs directly with
`tests/helpers/prompt_inputs.py` (`inputs()`, `diff_ctx()`, `issue()`,
`candidate()`, and friends; no GitHub) and read a rendered prompt back with
`parse_blocks(user, nonce)`, an independent splitter on the run's nonce that
fails on an unclosed block or a stray end marker. Inject `nonce=` (16 lowercase
hex) and, for forced collisions, `nonce_factory=`; never assert on a random
nonce. `tests/integration/test_prompt_sample_pr.py::render_sample_prompt()`
renders the `sample-pr` prompt with a fixed nonce through the real readers.
Bedrock is never called: `tests/fixtures/bedrock.py::FakeConverse` (S-210,
reused by S-213) stands in for the `bedrock-runtime` client, records a deep
copy of every request so tests assert exact Converse shapes, answers from a
script of responses (`tool_use_response`, `text_response`), botocore errors
(`validation_error`, `tool_choice_rejected`, `context_length_rejected`,
`access_denied`, `throttled`, ...: the modeled `ClientError` subclasses the real
client raises, with full `ResponseMetadata`), or callables, and fails on a call
past the end of its script. `tests/helpers/bedrock_run.py::run()` drives
`bedrock_adapter.review` with a counter nonce factory, a stepping `Clock`, and
a `Recorder` for `warn` events and sink prompts; it passes the fake as `client=`,
or, with `client_factory=`, exercises the per-call client sizing that
production uses (`client_factory=make_client`). `FakeConverse`
does not run botocore, so `tests/unit/test_bedrock_hostile.py` (S-210 QA) adds
two wire-level checks: a real `bedrock-runtime` client behind
`botocore.stub.Stubber` validates the adapter's requests and the fixture's
responses against the Converse service model, and a real client made by
`make_client` with `botocore.httpsession.URLLib3Session.send` patched (scripted
HTTP answers, a virtual clock advanced by read timeouts and by the patched
`time.sleep` of botocore's backoff) measures botocore's own retry attempts and
the wall time against the run deadline. Credentials are dummy environment
values and config files point at an empty `tmp_path`; no socket is opened.
The validation and verdict tests (S-211) need no fake: `validate.validate` is pure, so they pass a `changed_ranges` mapping and `context.verifier.Candidate` tuples directly, and `validate_result` takes any object with `findings` and `context.shown_candidates`/`dropped_candidates` (a `SimpleNamespace` in tests) plus a real `DiffContext`. The comment renderer tests (S-212) build `Validation`, `ContextData`, `DiffContext` and `VerifierContext` directly with `tests/helpers/render_inputs.py` (`finding()`, `status()`, `context_data()`, and the `blocking_fixture()`/`clear_fixture()` snapshot inputs). Snapshots are plain files in `tests/unit/__snapshots__/` compared byte for byte (no snapshot library); after an intended layout change, regenerate them with `UPDATE_SNAPSHOTS=1` and review the diff, which is part of the PR review. `test_neutralize_hostile_body_renders_as_inert_markdown` parses a hostile body with `markdown-it-py`, a transitive dev dependency (through `pip-audit`), and is skipped with `pytest.importorskip` if it is absent. `tests/unit/test_render_hostile.py` (qa-engineer, S-212 gate) attacks the comment guarantees against GitHub's renderer rather than CommonMark: a line-start allowlist proves no content begins a line, and a `markdown-it-py` token walk applies GitHub's mention, issue-reference and autolink filters to text nodes only. Every wall-clock bound in the `code-review` linear-time tests goes through `tests/helpers/perf.py::perf_bound`, which multiplies it by `PERF_BOUND_SCALE` (default 5 when `CI` is set, 1 locally); the inputs are sized so a quadratic implementation misses the scaled bound by orders of magnitude. Its tactics use seeds 414002–414004 (`tactic_seed(414, 2..4)`). The renderer defects QA pinned there (QA-212-D1–D3) are fixed and their `xfail(strict=True)` markers removed; 0 xfails remain. The pipeline tests (S-213: `tests/unit/test_outcomes.py`, `tests/unit/test_deadline.py`, `tests/integration/test_pipeline_e2e.py`, `test_pipeline_prompt_capture.py`, `test_pipeline_edges.py`, plus `test_cross_story_joins.py` and `tests/unit/test_scrub_invisible.py` from the Wave A PRD-level gate) drive `main.invoke` end to end with `tests/helpers/pipeline_run.py::Harness`: a `ReporterSink` replacing only the vendored reporter's HTTP layer, the recorded `StubTransport` shared by every `GitHubClient` the pipeline builds, `FakeConverse` behind a recording client factory (the production `client_factory` path), a `ManualClock`, a list as the prompt sink, and a heartbeat spy, all injected through a monkeypatched `main.pipeline_deps`. `set_pull`, `set_files`, `set_content` and `set_issue` add routes rather than editing the fixture files. The error-code property uses seed 415001 (`tactic_seed(415, 1)`). Two deliberate exceptions: the cases that test the real-time deadline bound (`bounded`, a stuck phase, heartbeat chunks) use short real sleeps (at most 1 s), the only exception to the no-sleep rule that follows; and `test_sigterm_during_post_is_recorded_by_the_backstop` sends a real SIGTERM to the pytest process with the real backstop installed and `signal.raise_signal` patched to raise instead of exiting, restoring the previous handler afterwards. `tests/integration/test_pipeline_hostile.py` (qa-engineer, S-213 gate) attacks the pipeline guarantees on the same harness: an exception (no `.code`, secret-bearing `str`/`repr`, unprintable, `KeyboardInterrupt`, `SystemExit`) injected at every step and sub-call, inside the failure path and after the review `POST`; the deadline at every step including mid-`POST`; workers abandoned at the deadline (proved by recording, inside the worker, what had been written when it unblocked, since `asyncio.run` joins the executor); heartbeats in each long phase; and a real SIGTERM at every step under the same patched backstop. Its invariants (one terminal write, a §13 code, every §5.3 key, at most one review comment and one failure comment, no edit, refs pinned to the captured head or merge base, no secret in any output) run on every case and in a seeded fault property, seed 415002 (`tactic_seed(415, 2)`). Its real sleeps are at most 0.4 s. Pipeline defects are pinned there with `pytest.mark.xfail(strict=True)` and a reproducer (QA-213-01 to QA-213-07), under the same rule as QA-212. All seven are fixed and 0 xfails remain; the post-phase timeouts (QA residual 2) are pinned in `tests/unit/test_deadline.py`. Retry waits and clocks are injected, so no test sleeps. Property tactics use
the seeded `tests/helpers/prng.py` (`Tactic.from_env(<issue> x 1000 + k, n)`,
replayable with `PRNG_SEED`/`PRNG_ITER`). `credentials.boto3`/`requests`/`jwt`
are patched at the module boundary as in the siblings. Because `StubTransport`
sees the URL the client hands over, not the one `requests` sends, the guard's
wire-level checks (`tests/unit/test_github_client_guard_hardening.py`) drive the
client through a real `requests.Session` with a capturing adapter mounted for
`http://`/`https://` and `trust_env = False`, and assert on the
`PreparedRequest`; no socket is opened. A known defect pinned by a test is
marked `xfail(strict=True)` with the defect in `reason`, so the fix turns it red
and the marker is removed in the same change.
Hostile-input suites for repository-controlled text (S-208:
`tests/unit/test_verifier_hostile.py`, `tests/unit/test_repo_conventions_hostile.py`;
S-209: `tests/unit/test_prompt.py::test_hostile_content_builds_quickly` and
`tests/unit/test_prompt_hostile.py::test_megabyte_hostile_inputs_build_in_linear_time`)
are the one sanctioned Layer 1 use of `time.perf_counter`: a regex-cost or
quadratic-scan test may assert an elapsed bound on a 100k+ line input. The bound
must hold with at least 3x margin under `make test-cov` (coverage tracing), and
the input must be large enough that a quadratic implementation misses the bound
by an order of magnitude, so the test cannot flake either way.
The S-209 completion-gate suites `tests/unit/test_budget_hostile.py` (budget
invariant at and around `I + D`, the 20,000 minimum at every reader's contract
maximum, multi-byte/CR/CRLF/empty text, `include_full_files=False`; property
tactic `tactic_seed(411, 3)`) and `tests/unit/test_prompt_hostile.py` (the real
nonce forged through every `ContextInputs` field, near-miss markers, hostile
paths under `str.splitlines`, the retry loop, failure paths and the sink,
`rubric.md` from a copied package dir run with `python -I`, schema key order;
property tactic `tactic_seed(411, 4)`) build on the same helpers.

**`bug-fix`.** GitHub REST is faked at the `requests.Session` boundary by
`tests/component/fake_github.py` (see the Packages row). Property tactics run
at the test plan's budgets in the default profile, with no Hypothesis profile
switch: RT-02 (`tests/unit/test_markers_property.py`) at 1000 examples per
property, RT-12 (`tests/unit/test_neutralize_property.py`) at 2000 examples
with inputs of 0–20,000 characters (long inputs repeat drawn pieces and are
cut at 20,000, which avoids Hypothesis' buffer limit), RT-15 at 1000 (disposition
and refusal bodies), and RT-13 (`tests/component/test_label_invariance.py`) at
200. The shared GitHub client's retry waits never sleep in tests: an autouse
fixture in `tests/conftest.py` replaces `github_client._sleep` and
`github_client._monotonic` with one `FakeClock` that a wait advances, so the
per-operation wait budget (120 s) runs for real with no real sleep. The tests
that assert the waits or the budget pass their own `sleep` and `clock`
(`tests.conftest.FakeClock`). `fake_github.py` records the `allow_redirects`
each request sent and can answer a 3xx (`redirect()`); the `v_runs` double
records it too. CT-34's agent side (claims resolved by
`v_runs.effective_status`: active, terminal, missing, unknown) runs against the
PostgREST double in `tests/component/test_refusal.py`; the real-database read
at L2.5 is not covered yet.
Raising them added about 13 s to `make test` (S-186 fix round, DF-186-03;
the whole local suite went from 43 s to 60 s with that round's other tests), so
a profile is only worth adding if that grows past about 60 s.
`test_neutralize.py::test_a_long_glued_chain_is_linear_not_quadratic` is a
sanctioned `time.perf_counter` bound (2 s on a 65,536-character chain that
took 14 s when quadratic). The SIGTERM-backstop tests in
`tests/component/test_s186_security_negative.py` send a real SIGTERM to the
pytest process with `signal.raise_signal` patched and the previous handler
restored, so the handler runs on the suspended main thread as in production.

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

1. **Local/CI Node major-version mismatch (`panel`).** `panel/package.json` declares `engines.node: ">=24 <27"`; an ambient Node outside that range (e.g. 26) makes `pnpm install --frozen-lockfile` hard-fail with `ERR_PNPM_UNSUPPORTED_ENGINE` before any test can run — reproduced live during the 2026-09-15 PRD rollup. Expected state: a repo-root `.nvmrc`/Volta/mise pin, or a pre-flight check, so an ad-hoc contributor shell does not silently fail on the `panel` workspace.
2. **`dependency-update` — `main.py` and `agent_reporter.py` remain untested/coverage-excluded.** See `docs/technical-guidelines.md` §11/§18 for the ranked gap detail; unchanged by this pass.
3. **`dependency-update` — security-negative server-side rejection cases remain a gap** (see above); unchanged by this pass.
4. **`security-analyst` — mocked-subprocess tests cannot see real scanner output shapes.** Eight defects shipped through a green suite and were caught only by real AgentCore invocations during S-141 (wrong CodeQL `--language` id, `/dev/stdout` data loss for CodeQL SARIF and Gitleaks reports, empty/missing-key outputs from Gitleaks/Trivy, absolute vs relative `file_path`, `CWE-079` vs `CWE-79`). Recommended follow-up (from the PRD-close QA rollup): an opt-in `tests/smoke/` layer marked `real_binaries`, run in CI inside the built Docker image against a checked-in fixture repo, asserting per runner that the output file materializes, ≥1 normalized finding has `severity`/`cwe` populated, and `file_path` is repo-relative — plus a clean-repo case per runner. Est. ~200 lines of tests + ~40 lines of CI; would have caught 7 of the 8.
4. **`panel` — 0/11 planned E2E scenarios for the S-142–S-148 batch were delivered** against `workstream/test-plan-prd-agent-fleet-panel-v3-ui-depth.md` §3 (see Coverage § above). Routed to `product-engineer`/`developer`, not fixed here.
5. **`panel` — no aggregate `panel`-wide numeric coverage baseline has been recorded in this file.** Per-story figures exist in individual fidelity reports; a consolidated number has never been pulled and committed here.
6. **`agentcore-cdk-app` is not reached by the repo-root aggregate `test`/`validate` targets.** Tested via its own `pnpm test`; low priority (single synth smoke test, IaC-only).
7. **Story PRs into an integration branch get no CI (`code-review`, any planner run).** `.github/workflows/ci.yml` triggers on `push` to `main` and `pull_request` to `main` only, so story PRs that target `integration/<feature>` (for example S-204–S-213 into `integration/code-review-agent`) never run the `python-quality` job; their gates are local runs only, and CI first sees the code on the consolidated PR to `main`. Expected state: `pull_request` also matches `integration/**` (or the planner records that CI is deferred to the consolidated PR). Found at the code-review Wave A PRD-level gate (2026-10-23).
8. **The root Python aggregate is fail-fast in `AGENT_DIRS` order.** `make test-py`/`validate-py` stop at the first failing package, and `code-review` is last, so a sibling failure (the pre-existing `security-analyst` audit CVE, S-204 D8) or a missing sibling venv means root `make validate` never reaches `code-review`. CI is not affected (one matrix job per agent, `fail-fast: false`). Expected state: the loop runs every package and fails at the end, or the report records which packages were not reached.
