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
| 1        | Deterministic foundations | Unit tests, schema validation. No I/O, no network, no real database.                  | active — `tests/unit/` (pytest `unit` marker); 25 tests covering `scrubber.py` and `credentials.py`. |
| 2        | Constrained model/tool    | Backend component tests, mocked APIs, fixtures and gold datasets.                     | scaffolded, empty — `tests/component/` and `tests/fixtures/` exist but hold no tests (`component` marker declared, unused). Finding: no component coverage yet. |
| 2.5      | Integration               | Real database, real migrations, RLS policies, schema contracts. No mocked data layer. | not configured — no local Postgres/Supabase harness present. Belongs to Phase 2 / DB work; not applicable to the current agent package. |
| E2E      | End-to-end                | Playwright CLI — committed browser automation, full-stack, scenario-driven.           | not configured — no frontend in repo (Next.js is Phase 2). No Playwright config. |
| Contract | Contract validation       | API spec drift, breaking-change detection, consumer impact. `dt verify` family.       | not configured — no OpenAPI/AsyncAPI spec in repo; `dt` not wired. |
| 3        | Product evaluation        | Semantic, tone, groundedness, hallucination evals. Only for LLM features.             | not configured — the agent uses an LLM (`strands-agents`) in `fix_agent.py`, but no eval harness exists. Finding: LLM fix path is untested. |
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
| `dependency-update` (`agents/dependency-update/app/dependencyUpdate/`) | Python `>=3.13` | pytest 8.3.5 | `pytest` (from the package dir; `testpaths=["tests"]`) | Local CPython process, no DB/network; all external I/O mocked | none configured — see Coverage §, gate is SKIPPED |
| `agentcore-cdk-app` (`agents/dependency-update/agentcore/cdk/`) | TypeScript | jest 29 (ts-jest) | `pnpm test` / `npm test` (→ `jest`) | Node (jest default); CDK `Template` synth assertions | none configured (no `@vitest/coverage`/`nyc`, no `--coverage` wired) |

> **Scope note.** The `dependency-update` Python package is the active codebase and the subject of this standard. `agentcore-cdk-app` is infrastructure-as-code with a single CDK synth smoke test (`test/cdk.test.ts`); it is listed for completeness and reachability accounting, not as a primary test target. The Next.js frontend (Phase 2) is **not** in the repo — no JS/TS application test package exists yet.

### Test environment

**`dependency-update` (Python).** Tests run in a plain local CPython interpreter with no database, no network, and no browser. The package has no UI, so no `jsdom`/DOM environment applies. Every external boundary — AWS Secrets Manager (`boto3`), Supabase PostgREST (`requests`), the GitHub App access-token endpoint (`requests`), JWT signing (`jwt`), and `subprocess` — is patched via `unittest.mock.patch`/`pytest-mock`. There is no `conftest.py` and no `setupFiles` equivalent; pytest defaults apply. Mock lifetimes are scoped by decorator/context-manager, so they auto-restore per test.

**`agentcore-cdk-app` (TypeScript).** Runs under jest's default Node environment; the single test synthesizes a CDK stack and asserts on the CloudFormation template. No DOM environment needed.

### Runtime parity

| Package             | Local                | CI                | Production / runtime          |
| ------------------- | -------------------- | ----------------- | ----------------------------- |
| `dependency-update` | CPython **3.13.0** (dev venv at `.venv`, `pyvenv.cfg`) | **3.13 + 3.14 matrix** (`.github/workflows/ci.yml`) | **PYTHON_3_14** (`agentcore/agentcore.json` → `runtimeVersion`); Docker build base is `python:3.13-slim` (`Dockerfile`) |
| `agentcore-cdk-app` | Node (unpinned locally) | not in CI yet | n/a — build/deploy tooling, not a runtime target |

> **FINDING — runtime parity divergence (`dependency-update`), MITIGATED by CI.** Three Python runtimes are in play: tests are authored locally on **3.13.0**, the container image builds on **python:3.13-slim**, and AgentCore executes as **PYTHON_3_14**. `pyproject.toml` pins only `requires-python = ">=3.13"`. This is now mitigated: `ci.yml` runs the full quality gate on a **3.13 + 3.14 matrix**, so every PR proves the suite passes on the production runtime, not just the dev one (verified: 25 tests pass on 3.14). Remaining lower-priority cleanup: align the Docker base to `python:3.14-slim` to match AgentCore exactly, and consider tightening the `requires-python` floor.

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
| `dependency-update` | Run all tests                 | `make test` → `pytest` (run from `agents/dependency-update/app/dependencyUpdate/`; `testpaths=["tests"]`) |
| `dependency-update` | Layer 1 only (unit)           | `make test-unit` → `pytest -m unit`                                                  |
| `dependency-update` | Layer 2 only (component)      | `make test-component` → `pytest -m component` (currently selects 0 tests — no component tests authored yet) |
| `dependency-update` | Lint                          | `make lint` → `ruff check .` (autofix: `make lint-fix`)                              |
| `dependency-update` | Format / format check         | `make format` → `ruff format .`; check-only: `make format-check` → `ruff format --check .` |
| `dependency-update` | Typecheck                     | `make typecheck` → `mypy .`                                                          |
| `dependency-update` | Coverage                      | `make test-cov` → `pytest --cov --cov-report=term-missing` (branch coverage; config in `[tool.coverage]`) |
| `dependency-update` | Audit (dependency vuln scan)  | `make audit` → `pip-audit . --strict` (audits declared runtime deps, not ambient venv tooling) |
| `dependency-update` | **Aggregate gate**            | `make validate` → lint + format-check + typecheck + test-cov + audit (fail-fast)     |

> **RESOLVED (was: no quality toolchain).** As of the `chore/python-quality-toolchain` change, the Python package has a full toolchain, all pinned in `pyproject.toml [dev]`: **ruff 0.16.4** (lint + format), **mypy 2.3.1** (typecheck), **pip-audit 2.10.1** (vuln scan), **pytest-cov 7.1.0** (coverage). Tool config lives in `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`, `[tool.coverage]`). A `Makefile` in the package dir provides the canonical targets and the `validate` aggregate. Current state: `make validate` passes clean (lint ✓, format ✓, typecheck ✓, 25 tests ✓, audit ✓ no known vulns).
>
> **Note on `audit`:** `pip-audit` run bare audits the whole venv and surfaces vulnerabilities in ambient tooling (`pip`, `pytest`) that never ship in the production container. The gate therefore runs `pip-audit .` to scope the scan to the project's declared runtime dependencies. Those are clean.

### Gate reachability

The aggregate test command MUST reach every package that contains tests, and the
CI and deploy quality gates MUST invoke that aggregate. A correctly named script
that silently omits a package is the failure this section exists to prevent.

- Aggregate quality gate (Python package): **`make validate`** — from the repo root (delegates via root `Makefile`) or from `agents/dependency-update/app/dependencyUpdate/`. Runs lint + format-check + typecheck + test-cov + audit, fail-fast. This is the canonical gate for the active codebase.
- Aggregate test command (repo-wide): a repo-root `Makefile` delegates the Python package targets (`make validate`/`make test`/etc.) via `-C`. The CDK package still uses `pnpm test` in its own dir and is not yet folded into the root aggregate (IaC smoke test, low priority).
- Packages reached: **`dependency-update`** via root `make validate`/`make test`. **`agentcore-cdk-app`** via a manual `pnpm test`.
- CI gate: **`.github/workflows/ci.yml`** runs on every push to `main` and every PR targeting `main`. It executes lint → format-check → typecheck → test+coverage → audit as explicit steps (same commands as `make validate`) on a **Python 3.13 + 3.14 matrix**. RESOLVED.
- Deploy gate: **still none.** Deploy is via the AgentCore CLI / CDK (Phase 1) and Fly (Phase 2); neither is wired to invoke the aggregate. A deploy can still proceed without the gate. FINDING remains open (lower risk now that CI enforces on every PR to `main`).

> **RESOLVED (CI) / PARTIALLY OPEN (deploy).** `make validate` exists, works from the repo root, and is now enforced by CI (`ci.yml`) on every push/PR to `main` across both the dev runtime (3.13) and the production runtime (3.14). The remaining open item is a deploy-time gate — `agentcore deploy`/Fly do not yet invoke the suite. Given CI blocks unmerged breakage, this is now a lower-risk gap rather than an unguarded one.

## Coverage

### Thresholds and baseline policy

Coverage percentages alone do not establish confidence — a suite can cover every
line while asserting nothing meaningful. Thresholds are a floor, not a goal.

- Measurement tool per package: **`dependency-update`: pytest-cov 7.1.0** (coverage.py backend), branch coverage on, config in `[tool.coverage.run]` / `[tool.coverage.report]`. `agentcore-cdk-app`: none wired (out of scope — IaC smoke test only).
- Threshold policy: **no hard floor yet (`fail_under` unset).** Coverage is measured and reported on every `make test-cov`/`make validate` run, but a numeric gate is deliberately deferred until the deterministic pipeline modules (#72–#77) exist — enforcing a floor against a codebase that is ~85% empty stubs would be meaningless. Raise `fail_under` once the pipeline modules are implemented and their tests land.
- Baseline: **97% on implemented modules** (`credentials.py` 95%, `scrubber.py` 100%, `config.py` 100%) as of the toolchain change; the remaining modules are empty stubs reporting 100% trivially (0 statements). This baseline is honest but narrow — it describes only the two modules with logic.
- Regression policy: report coverage on every `validate` run; a drop on `credentials.py`/`scrubber.py` below their current numbers is a regression to investigate. Formal `fail_under` enforcement lands with the pipeline modules.

> **`coverage_gate: MEASURED (97% on implemented modules; no `fail_under` floor yet)`.** The gate is no longer SKIPPED — a provider (pytest-cov) is configured and runs in `make validate`. The structural gap analysis below remains the correct lens for the *unimplemented* modules: 100% "coverage" on an empty stub is not evidence of anything.

**Structural gap analysis (substitute for coverage, current state):**

| Source file (`dependency-update`) | Tested? | Risk | Note |
| ---------------------------------- | ------- | ---- | ---- |
| `credentials.py`                   | partial | HIGH | GitHub App RS256 JWT auth + Supabase key resolution. Happy paths and staleness covered; security-negative cases largely missing (see Security-Negative §). |
| `scrubber.py`                      | yes     | MED  | Secret redaction; 13 tests including boundary/overlap/bytes cases. |
| `fix_agent.py`                     | **no**  | HIGH | LLM-driven code fix path (`strands-agents`). Untested and no eval harness (Layer 3 absent). |
| `audit.py`                         | **no**  | HIGH | Vulnerability audit parsing — core agent function, no tests. |
| `pull_request.py`                  | **no**  | HIGH | Opens PRs via `gh`/GitHub API — side-effecting, no tests. |
| `updater.py`, `toolchain.py`, `validator.py`, `classifier.py`, `eligibility.py` | **no** | MED–HIGH | Dependency resolution, toolchain invocation, validation, classification, eligibility gating — all untested. |
| `agent_reporter.py`                | **no**  | MED  | Lifecycle/log reporting SDK (buffering, retries, `seq` ordering). Design doc notes prior manual testing with a fake client; no committed tests. |
| `config.py`, `main.py`             | **no**  | LOW–MED | Config constants and entrypoint wiring. |

Source-to-test ratio: **2 of ~14 source modules** have any tests. The tested modules are the two lowest-side-effect ones (pure-ish string scrubbing and credential resolution). The highest-risk behavior — the LLM fix path, audit parsing, and PR creation — has **zero** coverage. Ranked by risk, the top gaps are `fix_agent.py`, `audit.py`, and `pull_request.py`.

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

**`dependency-update` (Python).** Test doubles are built with the stdlib `unittest.mock` (`patch`, `MagicMock`) plus `pytest-mock`. External boundaries are patched at the module boundary — `credentials.boto3`, `credentials.requests`, `credentials.jwt`, and `credentials.mint_installation_token` — so the module under test runs its real logic against fake transports. `scrubber.py` tests need no mocks (pure functions over strings and a synthetic `subprocess.CalledProcessError`).

Mocks are function/class-scoped via decorators and context managers, so they restore automatically; there is no shared global stub requiring explicit teardown. There is currently **no `conftest.py`** and **no shared fixture module** — acceptable at today's scale (2 test files), but the moment a token builder or a mocked PostgREST/Secrets-Manager client is needed in more than one file, it MUST live in a single shared helper (a `conftest.py` fixture) rather than being copy-pasted. The `tests/fixtures/` directory exists (`.gitkeep` only) as the intended home for that shared material.

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

**None recorded today.** `tests/fixtures/` contains only a `.gitkeep` — no recorded HTTP responses, no golden files, no captured PostgREST/Secrets-Manager/GitHub-API payloads. Component tests (Layer 2) that record real API shapes do not yet exist. When they are added, recorded responses and golden files MUST live under `tests/fixtures/`, and each fixture MUST document how it was captured and how to regenerate it. Until then, this section is a gap, not a satisfied requirement.

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
