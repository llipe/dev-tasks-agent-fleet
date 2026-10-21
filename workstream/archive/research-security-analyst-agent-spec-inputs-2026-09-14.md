# Research — security-analyst Agent: Reusable Patterns from `dependency-update`

## Changelog

| Version | Date       | Summary          | Author     |
| ------- | ---------- | ----------------- | ---------- |
| 1.0     | 2026-09-14 | Initial research artifact scoping `dependency-update`'s implementation for the `security-analyst` spec author. | researcher |

## Provenance

- **Repository:** `dev-tasks-agent-fleet` (local working tree, branch `main`)
- **Base branch / commit:** `main` at commit `ecf8ef4` ("chore: updates dev-tasks") — see `git log` at investigation time. Working tree also had uncommitted changes to `.dev-tasks/manifest.json`, `DESIGN.md`, `TESTING.md` unrelated to this research.
- **Invoking context:** direct user request (standalone research), to inform a forthcoming PRD-to-spec translation for `security-analyst`.
- **Multi-repo detection:** no `component.json` found; this is a single-repo project. Direct filesystem scanning used throughout (`find`, `Read`, `grep`).
- **Research question:** Document concrete, reusable implementation patterns in `agents/dependency-update/` that a spec-writer for `security-analyst` needs to replicate or deviate from.
- **Staleness:** treat as current only against the commit above; `agents/dependency-update/app/dependencyUpdate/*.py` and `supabase/seed.sql` are the fastest-moving files in this repo and should be re-checked if HEAD has advanced.

---

## Answer first

`dependency-update` at `/agents/dependency-update/` is an `agentcore create`-scaffolded Container project (Python 3.13, ARM64, HTTP protocol) with a hand-written pipeline under `app/dependencyUpdate/`. Its `main.py` entrypoint (`@app.entrypoint`, `BedrockAgentCoreApp`) drives a deterministic `resolve_credentials → checkout → detect_toolchain → install → audit → [update → validate → llm_fix → open_pr]` pipeline, reporting through a byte-identical copy of `docs/reference/agent_reporter.py` used as a context manager. Credentials flow: Secrets Manager (Supabase key, then GitHub App PEM) → PostgREST lookup of `github_installations` → RS256 JWT (PyJWT) → GitHub installation-token mint, all wrapped in `TokenContext` with a 45-min staleness re-mint. Every secret is appended to a `secrets: list[str]` that `scrubber.scrub()` / `scrub_process_error()` redact from any error text before it can leak. The pipeline is decomposed into single-purpose modules (`audit.py`, `classifier.py`, `eligibility.py`, `updater.py`, `toolchain.py`, `validator.py`, `pull_request.py`) each independently unit-testable with pure functions plus thin subprocess wrappers; the LLM (`fix_agent.py`, Strands `Agent` + Bedrock) sits on exactly one edge — invoked only when deterministic validation fails — with 5 fixed tools, a workspace-confining path resolver, and a deterministic post-hoc "mandate check" backstop. Tests are pytest with `unit`/`component` markers auto-applied by directory (`tests/conftest.py`), fixture JSON files for audit output, and `unittest.mock.patch("fix_agent.Agent")` to fully stub the LLM in component tests — zero real Bedrock calls in the test suite. The seed row lives in `supabase/seed.sql` (NOT `docs/reference/002_seed.sql`, which is now a stub/redirect stub — the PRD's own reference is stale). CDK (`agentcore/cdk/lib/cdk-stack.ts`) is 100% `agentcore create` boilerplate (generic payments/MCP wiring) with zero dependency-update-specific IAM/container code — confirming the PRD's claim that `agentcore deploy` needs no hand-written stack.

For `security-analyst`, nearly everything in credential resolution, checkout, reporting, PR mechanics (branch/idempotency/`--body-file`), token scrubbing, heartbeat/signal-backstop, and Dockerfile base-layer conventions is reusable close to verbatim. What needs new design: the finding schema/fingerprint (`classifier.py`/`eligibility.py`'s advisory-bucket shape is JS/TS-audit-specific and must be replaced by a five-tool-normalized schema), a `scan`/`rescan` module pair (no analog exists — `audit.py` runs one command, not five with per-tool skip/fail semantics), cross-tool deduplication (no analog), and the fix-agent's *scope* (per-finding invocation vs. `dependency-update`'s whole-validation-failure invocation) though the *tool/prompt/safety pattern* is directly reusable.

---

## Relevance-ranked file map

| # | Path | Why it matters |
|---|------|-----------------|
| 1 | `agents/dependency-update/app/dependencyUpdate/main.py` | Entrypoint orchestrator — step sequencing, payload unwrap/validate, outcome-mapping pure function, reporter lifecycle |
| 2 | `agents/dependency-update/app/dependencyUpdate/agent_reporter.py` | Vendored copy of the reporting SDK — must stay byte-identical to `docs/reference/agent_reporter.py` |
| 3 | `agents/dependency-update/app/dependencyUpdate/credentials.py` | GitHub App JWT + installation token minting, Supabase key fetch, `TokenContext` staleness |
| 4 | `agents/dependency-update/app/dependencyUpdate/scrubber.py` | Secret scrubbing pattern (`scrub`, `scrub_process_error`) |
| 5 | `agents/dependency-update/app/dependencyUpdate/fix_agent.py` | LLM escape-hatch pattern: 5 tools, `_safe_path`, system prompt, bounded loop, mandate check |
| 6 | `agents/dependency-update/app/dependencyUpdate/pull_request.py` | Branch naming, idempotency check, ephemeral credential-helper push, `--body-file`, PR body builder |
| 7 | `agents/dependency-update/app/dependencyUpdate/classifier.py` | Bucket classification pattern (pure function, dataclass result) — schema itself is JS/TS-specific |
| 8 | `agents/dependency-update/app/dependencyUpdate/eligibility.py` | Semver eligibility pure function — pattern for a version-bump lane check |
| 9 | `agents/dependency-update/app/dependencyUpdate/audit.py` | Single-tool run + normalize + diff/count pattern — closest analog to a per-scanner module |
| 10 | `agents/dependency-update/app/dependencyUpdate/toolchain.py` | Detection-with-precedence + `ToolchainError` pattern |
| 11 | `agents/dependency-update/app/dependencyUpdate/validator.py` | Multi-check runner with skip/fail semantics — closest analog to running 5 scanners with per-tool skip |
| 12 | `agents/dependency-update/app/dependencyUpdate/updater.py` | Subprocess-wrapper + typed-error pattern |
| 13 | `agents/dependency-update/app/dependencyUpdate/heartbeat.py` | Long-step keep-alive chunk pattern (issue #98) — needed for a 5-scanner run under AgentCore's idle timeout |
| 14 | `agents/dependency-update/app/dependencyUpdate/signal_backstop.py` | SIGTERM best-effort terminal-report pattern |
| 15 | `agents/dependency-update/app/dependencyUpdate/config.py` | Env-var constants + `assert_clock_invariant()` cross-check pattern |
| 16 | `agents/dependency-update/app/dependencyUpdate/Dockerfile` | ARM64 multi-stage build, ECR Public base images (Docker Hub 429 workaround), CA-cert build arg |
| 17 | `agents/dependency-update/app/dependencyUpdate/pyproject.toml` | Pinned deps, ruff/mypy/coverage config, `agent_reporter.py` exclusions |
| 18 | `agents/dependency-update/app/dependencyUpdate/Makefile` | Canonical `install/lint/typecheck/test/validate` targets |
| 19 | `agents/dependency-update/agentcore/agentcore.json` | Runtime config shape: `Container` build, `runtimeVersion`, `envVars`, `lifecycleConfiguration` |
| 20 | `agents/dependency-update/agentcore/aws-targets.json` | Deploy target account/region |
| 21 | `agents/dependency-update/agentcore/cdk/lib/cdk-stack.ts` | Confirms: 100% `agentcore create` boilerplate, zero agent-specific CDK code |
| 22 | `agents/dependency-update/app/dependencyUpdate/tests/conftest.py` | Auto-marker-by-directory, shared tmp-dir fixtures |
| 23 | `agents/dependency-update/app/dependencyUpdate/tests/unit/test_classifier.py` | Unit-test style for pure classification functions |
| 24 | `agents/dependency-update/app/dependencyUpdate/tests/component/test_fix_agent.py` | `@patch("fix_agent.Agent")` mocking pattern for the LLM |
| 25 | `supabase/seed.sql` (lines ~43-118) | **Canonical** seed location (NOT `docs/reference/002_seed.sql`, which is a stub) — row shape, `params_schema`, timeouts |
| 26 | `docs/reference/002_seed.sql` | Now a redirect stub pointing to `supabase/seed.sql` — the PRD's own reference (§4, req 49) is stale and should be corrected in the spec |
| 27 | `agents/dependency-update/README.md` | Deployment/invocation runbook conventions, env var table, testing commands |
| 28 | `workstream/specification-prd-dependency-update-agent.md` | The sibling **spec** (not PRD) — section structure, mermaid diagrams, code-snippet density to mirror |
| 29 | `docs/technical-guidelines.md` | Fleet-wide conventions (§7 data guidelines, §8 integration/timeouts) referenced by `config.py` comments |
| 30 | `docs/requirements/prd-security-analyst-agent.md` | The PRD this spec must translate — not investigated as "existing implementation" but is the spec's other primary input |

**Not investigated in depth** (budget): `agentcore/.llm-context/*`, `agentcore/cdk/test/cdk.test.ts`, `.mypy_cache`, `.venv` contents, full `tests/unit/test_updater.py`/`test_toolchain.py`/`test_pr_body.py` bodies (only patterns sampled via adjacent files), `docs/adr/ADR-006-long-step-keepalive-and-clock-invariant.md` (referenced but not opened — relevant to heartbeat/clock-invariant reuse for security-analyst's longer `maxLifetime`).

---

## Slice findings

### S1 — Components / modules

`app/dependencyUpdate/` is a flat package (18 top-level `.py` files, no subpackages) with strict single-responsibility boundaries documented in the module docstrings and the README's layout table (`agents/dependency-update/README.md:5-36`). Each module owns exactly one concern: `config.py` (env + clock invariant), `credentials.py` (auth), `scrubber.py` (redaction), `toolchain.py` (PM/script detection), `audit.py` (run + normalize + diff one tool's output), `eligibility.py`/`classifier.py` (pure classification), `updater.py` (apply + reconcile), `validator.py` (multi-check runner), `fix_agent.py` (LLM), `pull_request.py` (git/gh + PR body), `heartbeat.py`/`signal_backstop.py` (AgentCore-lifecycle plumbing added later for issue #98), and `main.py` (orchestration only — imports everything, contains almost no business logic itself beyond payload handling and outcome-mapping pure functions).

### S2 — APIs / contracts

Invocation contract: `main.py:74-186` (`_REQUIRED_FIELDS`, `unwrap_payload`, `validate_payload`, `apply_defaults`). Payload unwrap tolerates single- and double-`prompt`-wrapping (issue #97) up to `_MAX_UNWRAP_DEPTH = 16`. Return payload: `build_return_payload()` (`main.py:317-345`) — flat dict with `status`, `outcome`, `error_code`, `pr_url`, plus domain-specific counters; `build_metrics()` (`main.py:362-372`) projects a fixed subset into `runs.metrics`. `RunReporter` public surface (`agent_reporter.py`): `from_env()` classmethod reading `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY`/`RUN_ID`/`RUN_PARAMS`; context-manager `__enter__`/`__exit__`; `.step(key, title=None)` returns a `_Step` context manager; `.log/.info/.warn/.error/.debug`; `.artifact(type_, url=None, title=None, storage_path=None, **metadata)`; `.succeed(outcome, result=None, metrics=None)`; `.fail(error_code, error_message, outcome=None, traceback_text=None, metrics=None)`.

### S3 — UI surfaces

None — confirmed no-UI agent (`agents/dependency-update` has no frontend code). The PR body (`pull_request.py:279-341`, `build_pr_body()`) is the sole human-facing surface, built from ordered conditional Markdown sections (always: security summary, package changes, validation results; conditional: fixed advisories, major-required, unknown, non-semver, AI warning).

### S4 — Tests

`tests/unit/` (14 files) covers pure functions with no I/O: `test_classifier.py`, `test_eligibility.py`, `test_audit.py`, `test_safe_path.py`, `test_scrubber.py`, `test_outcome_mapping.py`, `test_clock_invariant.py`, `test_mandate_check.py`, `test_toolchain.py`, `test_updater.py`, `test_validator.py`, `test_pr_body.py`, `test_heartbeat.py`, `test_credentials.py`, `test_payload_contract_fixture.py`, `test_agent_reporter_start.py`. `tests/component/` (3 files) covers mocked-external-service paths: `test_fix_agent.py` (mocks `fix_agent.Agent` via `unittest.mock.patch`, verifying zero-LLM-call at `max_attempts=0`, retry-budget respect, `llm_used`/`fix_attempts` bookkeeping), `test_pipeline.py`, `test_pr_creation.py`. `tests/conftest.py` auto-applies `unit`/`component` pytest markers based on directory path (`tests/unit/` / `tests/component/`) — no per-test marker decoration needed — and defines shared tmp-dir project fixtures (`pnpm_project`, `npm_project`, `no_lockfile_project`, `no_test_project`, `minimal_test_project`) that write real `package.json`/lockfile files under `tmp_path`. `tests/fixtures/` holds raw audit JSON (`audit_npm_clean.json`, `audit_npm_vulns.json`, `audit_pnpm_before.json`/`_after.json`/`_clean.json`/`_vulns.json`, `list_npm.json`, `list_pnpm.json`, `list_pnpm_monorepo.json`) consumed by `test_audit.py` and similar. `pyproject.toml` marker declarations: `unit: unit tests (no I/O, no network)`, `component: component tests (mocked external services)`. Coverage config excludes `main.py` and `agent_reporter.py`; no `fail_under` set yet.

### S5 — Data model

No new tables — reuses `runs`, `run_steps`, `run_events`, `run_artifacts`, `github_installations` (per PRD §9 and `technical-guidelines.md`). `RunReporter` writes rows directly via raw PostgREST HTTP calls (stdlib `urllib.request`, no ORM), with retry/backoff (`HTTP_RETRIES=3`, exponential backoff, 4xx-except-429 short-circuits retry) and a fallback to `stderr`/CloudWatch on total failure — reporting never raises upward (`agent_reporter.py:94-158`). `update_expect_rows()` (`agent_reporter.py:126-158`) uses `Prefer: return=headers-only,count=exact` and parses the `Content-Range` header to detect a zero-row `start()` PATCH (issue #100 loud-warning pattern) — directly reusable, unchanged file.

### S6 — Config / env / CI

`agentcore.json` (`agentcore/agentcore.json:1-42`): `build: "Container"`, `entrypoint: "main.py"`, `codeLocation: "app/dependencyUpdate/"`, `runtimeVersion: "PYTHON_3_14"` (note: this is the *AgentCore-declared* runtime version, distinct from the Dockerfile's actual `python:3.13-slim` base and `pyproject.toml`'s `requires-python = ">=3.13"` — a real discrepancy worth flagging, not resolving, for the new agent's spec), `networkMode: "PUBLIC"`, `protocol: "HTTP"`, `envVars` (3: `SUPABASE_URL`, `SUPABASE_KEY_SECRET_ID`, `MODEL_ID`), `lifecycleConfiguration.idleRuntimeSessionTimeout = 900`, `maxLifetime = 3600`. `aws-targets.json`: single target, account `755641879575`, region `us-east-1`. `Makefile` targets mirror `TESTING.md`'s command contract exactly: `install`, `lint`, `lint-fix`, `format`, `format-check`, `typecheck`, `test`, `test-unit`, `test-component`, `test-cov`, `audit`, `validate` (aggregate, fail-fast ordered: lint → format-check → typecheck → test-cov → audit). `config.py`'s `assert_clock_invariant()` (`config.py:69-134`) enforces `TOOL_COMMAND_TIMEOUT <= TEST_TIMEOUT <= IDLE_SESSION_TIMEOUT <= MAX_LIFETIME <= REAPER_THRESHOLD_SECONDS` and a heartbeat-interval bound — called unconditionally at entrypoint start (`main.py:507`) and fails fast on drift.

### S7 — Relationships

`main.py` imports from every pipeline module. `fix_agent.py` imports `validator.run_validation` (re-validates after each LLM attempt) and `toolchain.ScriptContract`. `pull_request.py` imports `audit.PackageChange`, `classifier.ClassifiedAdvisory`, `scrubber.scrub_process_error`, `validator.CheckStatus`/`ValidationResult`. `classifier.py` imports `eligibility.parse_semver` explicitly to avoid rule drift (module docstring: "no drift — req 37"). `credentials.py` and `pull_request.py` both depend on `scrubber.py` for redaction at every subprocess/HTTP failure boundary. `agent_reporter.py` has **zero** imports from sibling modules (stdlib-only, per its own docstring) — this is the byte-identical-copy invariant (D13/D24) the spec must preserve for `security-analyst` too.

### S8 — Prior history

Numerous inline comments cite issue numbers as the provenance for non-obvious code (#90 advisory-ID-diff fix, #97 double-wrap unwrap, #98 heartbeat/clock-invariant, #100 zero-row PATCH warning, #106/#108 credential-error classification, #77 lockfile-conflict fix, #94 reaper verification). `docs/reference/002_seed.sql` itself documents its own supersession by `supabase/seed.sql` as of "Story S-102 (issue #115)" — the `security-analyst` PRD's own affected-repos table (line 102) still cites `docs/reference/002_seed.sql` as the file to update, which is now stale; the spec should target `supabase/seed.sql`.

---

## Relationships (diagrammatic summary)

```
main.py (orchestrator)
 ├─ credentials.py ──uses──> config.py (SUPABASE_KEY_SECRET_ID, TOKEN_STALE_THRESHOLD_MINUTES)
 ├─ scrubber.py ──used by──> credentials.py (raise paths), pull_request.py, main.py (unhandled exc)
 ├─ toolchain.py ──used by──> validator.py, fix_agent.py (ScriptContract)
 ├─ audit.py ──feeds──> classifier.py (via classify_advisories() in main.py)
 ├─ classifier.py ──imports──> eligibility.py (parse_semver, shared rules)
 ├─ updater.py ──feeds──> validator.py (post-update validation)
 ├─ validator.py ──feeds──> fix_agent.py (initial_result) and main.py (determine_outcome)
 ├─ fix_agent.py ──re-invokes──> validator.run_validation (per attempt)
 ├─ pull_request.py ──imports──> audit.PackageChange, classifier.ClassifiedAdvisory, validator.ValidationResult
 ├─ heartbeat.py + signal_backstop.py ──wrap──> long steps (validate, llm_fix) and SIGTERM
 └─ agent_reporter.py ──standalone, stdlib-only──> RunReporter (context manager wraps entire pipeline)
```

---

## Risks and gotchas (for the spec author, not the PRD author)

1. **Seed file location drift.** The PRD (and even `docs/reference/002_seed.sql`'s own historical name) points at `docs/reference/002_seed.sql`; the actual, applied file is `supabase/seed.sql`. The `security-analyst` spec's Data Requirements / Deployment sections must target `supabase/seed.sql`.
2. **`agentcore.json` `runtimeVersion` vs. Dockerfile Python version mismatch already exists in the sibling agent** (`PYTHON_3_14` declared vs. `python:3.13-slim` actually built). Not a security-analyst-specific issue, but the spec author should not assume these two values are kept in lockstep by convention — verify at implementation time rather than copying blindly.
3. **CDK stack is fully generic** (`cdk-stack.ts`) — it contains no agent-specific IAM statements beyond the AgentCore-CDK-managed payments/MCP wiring. This confirms PRD requirement "no separate hand-written CDK stack" but also means the security-analyst spec should not describe custom IAM policy authorship inside `cdk-stack.ts` — the execution-role grants (`secretsmanager:GetSecretValue`, `bedrock:InvokeModel`) are presumably synthesized by `agentcore create`/`deploy` from `agentcore.json`, not hand-added here. This mechanism was not directly located in this investigation (out of budget) — flag as unverified rather than asserted.
4. **The clock-invariant pattern (`assert_clock_invariant`) is directly reusable** but its five-clock ordering must be recomputed for security-analyst's higher `maxLifetime` (5400s per PRD §12.3) — the spec should show the recomputed invariant chain explicitly, mirroring `config.py:69-134`, not just reference it.
5. **Heartbeat is per-long-step, not automatic.** `main.py` explicitly wraps `validate` and `llm_fix` in `run_with_heartbeat(...)` generators (`main.py:698-747`). For security-analyst, every scanner run (especially CodeQL database builds) and the rescan step will need the same explicit heartbeat wrapping — this is not free by just reusing `heartbeat.py`; each blocking call site must be wired individually.
6. **The LLM fix agent's tool surface pattern is directly reusable, but its *invocation granularity* is not.** `dependency-update`'s `run_fix_loop` is invoked once per *run* (after `validate` fails as a whole) and is given the full failure description across all checks. The PRD explicitly requires `security-analyst`'s escape hatch to be invoked *per finding* (D22, req 29-32) — this is a new design point, not a copy of `run_fix_loop`'s signature; the spec needs a new `run_fix_loop`-equivalent whose loop boundary is a single finding, with `max_fix_attempts` budgeted per-finding (D26) rather than per-run.
7. **Test-mocking convention for the LLM is `unittest.mock.patch("fix_agent.Agent")`** (`tests/component/test_fix_agent.py:76`) — the equivalent security-analyst fix-agent module should follow the same patch target naming (`patch("<module>.Agent")`) so component tests never call Bedrock.
8. **`agent_reporter.py` must remain byte-identical** — `pyproject.toml` explicitly excludes it from ruff/mypy scanning by path, with a documented mypy `exit-return` override specifically because of this constraint (`pyproject.toml:46-51,68-83`). The security-analyst spec should reuse this exact suppression rather than re-deriving it.
9. **Scanner-analog gap.** `audit.py` runs exactly one command (`pnpm audit` / `npm audit`) with a two-branch dispatch. `security-analyst` needs five scanners with independent timeouts, independent skip/fail semantics (req 17-19), and SARIF/JSON parsing per tool — there is no existing five-way dispatcher to copy; `validator.py`'s multi-check pattern (`run_lint`/`run_format`/`run_typecheck`/`run_tests`, each recording `PASSED`/`FAILED`/`SKIPPED` into one `ValidationResult`) is the closest structural analog and should be cited as the pattern to generalize, not `audit.py`.

---

## External sources

None consulted — codebase-only research per scope.

---

## Not investigated

- `agents/dependency-update/agentcore/.llm-context/*` (agentcore-generated context files) — likely irrelevant to spec authorship.
- `agentcore/cdk/test/cdk.test.ts` — CDK unit test, low relevance given the stack is boilerplate.
- Full bodies of `tests/unit/test_updater.py`, `tests/unit/test_toolchain.py`, `tests/unit/test_pr_body.py`, `tests/unit/test_payload_contract_fixture.py`, `tests/unit/test_agent_reporter_start.py`, `tests/component/test_pipeline.py`, `tests/component/test_pr_creation.py` — sampled adjacent files instead; same conventions apply per `tests/conftest.py`'s auto-marking and the Makefile's test targets.
- `docs/adr/ADR-006-long-step-keepalive-and-clock-invariant.md` — referenced by the README but not opened; likely directly relevant to security-analyst's heavier `maxLifetime` (5400s) and should be read by the spec author before writing the timeout section.
- The actual AgentCore CDK L3 construct internals (`@aws/agentcore-cdk` package) that presumably synthesize the IAM role grants — out of repo, out of budget; the spec should describe the *desired* IAM grants (per PRD §12.5) without asserting how `agentcore create`/`deploy` wires them, since this repo's own stack file provided no evidence either way.
- `docs/technical-guidelines.md` full text (655 lines; only section headings and cross-referenced §7/§8 context sampled via `config.py`/README citations, due to single-read token budget).

---

## Confidence

**High** on: entrypoint contract, reporter usage, credential/token/scrubbing mechanics, PR mechanics, test-layer conventions, module decomposition, seed-file location drift, Dockerfile conventions — all read directly from source with line-level citations.

**Medium** on: exact IAM-grant synthesis mechanism (not located in-repo, inferred from PRD text only) and the `agentcore.json`/Dockerfile Python-version relationship (observed but not root-caused).

**Low / not assessed**: CDK L3 construct behavior outside this repo, ADR-006 content, and any runtime behavior not observable from static source (e.g., actual AgentCore Container resource limits, CodeQL ARM64 support — both explicitly flagged as open questions in the PRD itself, §18 OQ5/OQ6).
