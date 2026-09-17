# Implementation Plan - Security Analyst Agent

> Source: [`user-stories-prd-security-analyst-agent.md`](user-stories-prd-security-analyst-agent.md) (17 stories, S-125–S-141) · [`prd-security-analyst-agent.md`](../docs/requirements/prd-security-analyst-agent.md) v1.2 · [`specification-prd-security-analyst-agent.md`](specification-prd-security-analyst-agent.md) v1.2 · GitHub issues [#185–#201](https://github.com/llipe/dev-tasks-agent-fleet/issues/185) in `llipe/dev-tasks-agent-fleet`.
> Scope: all 17 stories (the full agent build — no subset selected). No separate Task 0 project-setup block: Story S-125 already **is** the greenfield-component setup (project scaffolding, reporting, credentials) per the stories doc, so a duplicate Task 0 would just restate it.
> Commands throughout are this project's own `make` targets (`agents/security-analyst/app/securityAnalyst/Makefile`), not `pnpm` — this is a Python agent project with no JS/TS toolchain, exactly as `agents/dependency-update/` is.

## Relevant Files

- `agents/security-analyst/agentcore/agentcore.json`, `aws-targets.json` - AgentCore runtime/deploy config
- `agents/security-analyst/app/securityAnalyst/main.py` - Orchestrator: payload contract, state machine, `determine_outcome()`
- `agents/security-analyst/app/securityAnalyst/config.py` - Env constants, `assert_clock_invariant()`
- `agents/security-analyst/app/securityAnalyst/credentials.py` - GitHub App JWT/token (ported from `dependency-update`, unmodified)
- `agents/security-analyst/app/securityAnalyst/scrubber.py` - Secret redaction (ported, unmodified)
- `agents/security-analyst/app/securityAnalyst/heartbeat.py` - Long-step keep-alive (ported, unmodified)
- `agents/security-analyst/app/securityAnalyst/signal_backstop.py` - SIGTERM backstop (ported, unmodified)
- `agents/security-analyst/app/securityAnalyst/agent_reporter.py` - `RunReporter` SDK (byte-identical copy)
- `agents/security-analyst/app/securityAnalyst/severity.py` - Per-tool severity normalization (D28-D30)
- `agents/security-analyst/app/securityAnalyst/normalize.py` - `Finding`/`Remediation` schema
- `agents/security-analyst/app/securityAnalyst/fingerprint.py` - Fingerprinting (D20)
- `agents/security-analyst/app/securityAnalyst/scanners/semgrep_runner.py` - Semgrep scan + normalize
- `agents/security-analyst/app/securityAnalyst/scanners/gitleaks_runner.py` - Gitleaks scan + normalize + redaction
- `agents/security-analyst/app/securityAnalyst/scanners/trivy_runner.py` - Trivy scan + normalize + D24/req-54 boundary
- `agents/security-analyst/app/securityAnalyst/scanners/checkov_runner.py` - Checkov scan + normalize
- `agents/security-analyst/app/securityAnalyst/scanners/codeql_runner.py` - CodeQL scan + normalize (JS/TS + Python only)
- `agents/security-analyst/app/securityAnalyst/dedupe.py` - Cross-tool deduplication (D21)
- `agents/security-analyst/app/securityAnalyst/classifier.py` - mechanical/manual/unscannable classification (D22/D24)
- `agents/security-analyst/app/securityAnalyst/fixers/semgrep_autofix.py` - Semgrep autofix application
- `agents/security-analyst/app/securityAnalyst/fixers/trivy_bump.py` - Trivy version-bump application
- `agents/security-analyst/app/securityAnalyst/rescan.py` - Re-scan gate (D25)
- `agents/security-analyst/app/securityAnalyst/fix_agent.py` - Per-finding LLM escape hatch (D22/D26)
- `agents/security-analyst/app/securityAnalyst/pull_request.py` - Branch/idempotency/push/PR body
- `agents/security-analyst/app/securityAnalyst/Dockerfile` - ARM64 image, 5 scanner toolchains, 2 CodeQL packs
- `agents/security-analyst/app/securityAnalyst/pyproject.toml`, `Makefile` - Deps, quality-gate targets
- `agents/security-analyst/app/securityAnalyst/tests/fixtures/*` - Per-tool raw output fixtures (JSON/SARIF)
- `agents/security-analyst/app/securityAnalyst/tests/unit/*` - Layer 1 tests (pure functions)
- `agents/security-analyst/app/securityAnalyst/tests/component/*` - Layer 2 tests (mocked external services)
- `agents/security-analyst/README.md` - Deployment runbook, timeout-coupling documentation
- `supabase/seed.sql` - Agent row (NOT `docs/reference/002_seed.sql`, which is a stub)

## Tasks

- [ ] 1.0 Implement Story S-125: Project scaffolding, reporting, and credential reuse (deployable no-op) — [Issue #185](https://github.com/llipe/dev-tasks-agent-fleet/issues/185)

  > Note: First story, no dependencies. Proves the pipe (deploy → credentials → reporting → a real `runs` row) before any scanner logic exists — same bring-up order the sibling `dependency-update` agent proved first.

  - [x] 1.1 `agentcore create security-analyst --build Container --entrypoint main.py --code-location app/securityAnalyst/ --protocol HTTP` (scaffolded via `agentcore create --no-agent` + `agentcore add agent --type byo`, then renamed `securityanalyst/` → `security-analyst/`; `--project-name` only accepts alphanumeric chars)
  - [x] 1.2 Copy `agent_reporter.py`, `credentials.py`, `scrubber.py`, `heartbeat.py`, `signal_backstop.py` from `agents/dependency-update/app/dependencyUpdate/` unmodified (`diff`-verified byte-identical)
  - [x] 1.3 Write `config.py` with this agent's own timeout constants (`SCANNER_TIMEOUT=600`, `FIX_COMMAND_TIMEOUT=180`, `IDLE_SESSION_TIMEOUT=900`, `MAX_LIFETIME=5400`, `HEARTBEAT_INTERVAL=120`) and `assert_clock_invariant()`
  - [x] 1.4 Implement `main.py`'s payload unwrap/validate/apply_defaults (including `min_severity`, `scanners` list validation)
  - [x] 1.5 Implement a placeholder pipeline that goes straight to `succeeded`/`no_findings` (no scanners run yet)
  - [x] 1.6 `agentcore deploy -y`; record `runtime_arn` for use in Story S-141 — deployed by planner (direct user confirmation) after `infra-engineer` routing found no AWS AgentCore Runtime change-kind in its framework. `runtime_arn`: `arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/securityanalyst_security_analyst-w6CpbYHRE0`
  - [x] 1.7 Write `pyproject.toml` (reuse `agent_reporter.py`'s ruff/mypy path-exclusion pattern) and `Makefile` targets (`install/lint/format-check/typecheck/test-unit/test-component/test-cov/audit/validate`)
  - [ ] 1.8 Run once against a real (small) target repo; confirm a complete `runs` row with `resolve_credentials`/`checkout` steps and a terminal status — **DEFERRED to S-141** (task 17.10 already plans this exact real invocation). Inserting a `queued` `runs` row requires an `agents.slug='security-analyst'` row, which only S-141's seed migration creates — no such row exists anywhere yet (confirmed no stub in `docs/reference/002_seed.sql` either). User confirmed: defer rather than do a one-off manual insert into the shared prod `agents` table.
  - [x] 1.9 Verify Acceptance Criterion: `/agents/security-analyst/` scaffolded by `agentcore create`, `agentcore validate` passes (PRD AC1)
  - [x] 1.10 Verify Acceptance Criterion: `agentcore deploy` provisions the runtime, `agentcore status` reports ready (PRD AC2) — confirmed: `agentcore status` reports `security_analyst: Deployed - Runtime: READY`
  - [x] 1.11 Verify Acceptance Criterion: invalid payload (missing field, unknown `mode`/`min_severity`, empty `scanners`) terminates `failed`/`INVALID_PARAMS` without cloning (PRD AC28)
  - [ ] 1.12 Verify Acceptance Criterion: credential resolution/token minting/scrubbing works against the shared `github_installations` row (PRD AC25, AC26) — code reused unmodified (unit-covered by the sibling's own untouched test suite); live execution **DEFERRED to S-141** alongside 1.8 (same `agents` row dependency)
  - [x] 1.13 Verify Acceptance Criterion: `assert_clock_invariant()` runs at entrypoint start and fails fast on a deliberately misordered constant (PRD AC31 groundwork)
  - [ ] 1.14 Verify Acceptance Criterion: PostgREST outage does not crash the pipeline; payload appears on stderr/CloudWatch (PRD AC30) — inherited from unmodified `agent_reporter.py`'s stderr fallback; live verification **DEFERRED to S-141** alongside 1.8
  - [x] 1.15 Run Tests: `tests/unit/test_clock_invariant.py`, `tests/unit/test_payload_contract.py` — `make test-unit` (36/36 passed)
  - [x] 1.16 Run Tests: full quality gate — `make validate` (lint/format-check/typecheck/test-cov/audit all pass)

- [x] 2.0 Implement Story S-126: Severity normalization (`severity.py`) — [Issue #186](https://github.com/llipe/dev-tasks-agent-fleet/issues/186)

  > Note: Pure functions, no I/O — implements the fixed per-tool severity table from PRD §7.4b (D28-D30). Depends on S-125 only for the project skeleton to add a module to.

  - [x] 2.1 Add `Severity` enum (`CRITICAL`/`HIGH`/`MEDIUM`/`LOW`) and `_UNKNOWN_SEVERITY_FLOOR = Severity.MEDIUM`
  - [x] 2.2 Implement `severity_from_semgrep()` (`ERROR→high`, `WARNING→medium`, `INFO→low`)
  - [x] 2.3 Implement `severity_from_gitleaks()` (unconditional `critical`)
  - [x] 2.4 Implement `severity_from_trivy()` (direct pass-through 4 levels, `UNKNOWN→medium`)
  - [x] 2.5 Implement `severity_from_checkov()` (pass-through when present, `medium` when absent)
  - [x] 2.6 Implement `severity_from_codeql()` (`security-severity` thresholds → SARIF `level` fallback → `medium`)
  - [x] 2.7 Verify Acceptance Criterion: all five tools' mappings match PRD §7.4b's table exactly, including both unknown-severity-floor paths and CodeQL's dual fallback (PRD AC12a)
  - [x] 2.8 Verify Acceptance Criterion: no function inspects free-text rule metadata beyond the named fields (requirement 61)
  - [x] 2.9 Run Tests: one parametrized unit case per table row, per tool — `make test-unit`

- [x] 3.0 Implement Story S-127: Finding schema, fingerprinting — [Issue #187](https://github.com/llipe/dev-tasks-agent-fleet/issues/187)

  > Note: Foundation for every scanner normalizer, dedup, classification, and the re-scan gate. Depends on S-126 for the `Severity` enum.

  - [x] 3.1 Define `Finding`/`Remediation` frozen dataclasses per spec §8.1
  - [x] 3.2 Implement `fingerprint()` with `_LINE_TOLERANCE_BAND = 3` per spec §8.2
  - [x] 3.3 Verify Acceptance Criterion: `Finding`/`Remediation` fields match spec §8.1 exactly
  - [x] 3.4 Verify Acceptance Criterion: fingerprint stable under a small line shift; changes on file/rule difference (PRD AC6)
  - [x] 3.5 Run Tests: `tests/unit/test_fingerprint.py` (stability, change-on-difference, boundary-of-tolerance-band, empty-`rule_id`-fallback cases) — `make test-unit` (20/20 passed; 105/105 full unit suite)

- [x] 4.0 Implement Story S-128: Semgrep scanner integration — [Issue #188](https://github.com/llipe/dev-tasks-agent-fleet/issues/188)

  > Note: First concrete scanner — establishes the `ScanStatus`/`ScanResult` pattern every later scanner story follows. Pins the PRD §7.4a/§7.4b ruleset scope (no `--config auto`). Depends on S-127, S-126.

  - [x] 4.1 Add `RULESET` constant: `p/javascript p/typescript p/python p/security-audit`
  - [x] 4.2 Implement `run_semgrep()` (`--json`, own `SCANNER_TIMEOUT`, crash/timeout → non-fatal `ScanStatus.FAILED`)
  - [x] 4.3 Implement `normalize_semgrep()` (sets `remediation.kind = "semgrep_autofix"` when the rule carries a native patch)
  - [x] 4.4 Build fixture corpus: `semgrep_clean.json`, `semgrep_findings.json` (with and without an autofix-carrying rule)
  - [x] 4.5 Verify Acceptance Criterion: pinned rulesets used, not `--config auto` (PRD requirement 52)
  - [x] 4.6 Verify Acceptance Criterion: independent `SCANNER_TIMEOUT`; crash/unparseable-output is non-fatal to the run (PRD requirement 18, 19)
  - [x] 4.7 Run Tests: `tests/unit/test_semgrep_runner.py` (normalize against fixtures) — `make test-unit` (22/22 passed; 127/127 full unit suite)
  - [x] 4.8 Run Tests: `tests/component/test_semgrep_runner_subprocess.py` (mocked subprocess: zero findings, unparseable JSON, timeout) — `make test-component` (10/10 passed; 137/137 full suite incl. unit)

- [x] 5.0 Implement Story S-129: Gitleaks scanner integration + secret redaction — [Issue #189](https://github.com/llipe/dev-tasks-agent-fleet/issues/189)

  > Note: Secret-value redaction (PRD §9.3/§12, R14) is bundled in, not deferred — a Gitleaks integration without redaction is unsafe to merge. Depends on S-127, S-126.

  - [x] 5.1 Implement `run_gitleaks()` (`--report-format json`, own `SCANNER_TIMEOUT`)
  - [x] 5.2 Implement `normalize_gitleaks()` (severity always `critical` via S-126; `remediation = None` always)
  - [x] 5.3 Implement/extend redaction pass (reuse `scrubber.py`'s utility) so `Finding.message` never carries the raw matched secret
  - [x] 5.4 Build a fixture repo/commit containing one known dummy secret
  - [x] 5.5 Verify Acceptance Criterion: `Finding.message` carries only location/rule, never the raw secret string, at every reporting surface (`run_events`, artifact, log output) (PRD AC27)
  - [x] 5.6 Verify Acceptance Criterion: crash/timeout non-fatal, same pattern as S-128
  - [x] 5.7 Run Tests: `tests/unit/test_gitleaks_runner.py`, `tests/unit/test_gitleaks_redaction.py` (asserting the dummy secret's literal value is absent from every output surface, including multiple-occurrence redaction) — `make test-unit`
  - [x] 5.8 Run Tests: `tests/component/test_gitleaks_runner.py` (mocked subprocess) — `make test-component`

- [x] 6.0 Implement Story S-130: Trivy scanner integration (fs/config/image + D24/req 54 boundary) — [Issue #190](https://github.com/llipe/dev-tasks-agent-fleet/issues/190)

  > Note: The single most consequential normalizer — decides `lockfile_managed`, which drives the entire classifier split in S-134. Depends on S-127, S-126.

  - [x] 6.1 Implement `run_trivy()` three-mode dispatch: `fs` (npm/pnpm **and** Python manifests), `config`, conditional `image` (when a Dockerfile is present, against a representative base image)
  - [x] 6.2 Implement `normalize_trivy()`, including the `lockfile_managed` decision — `True` **only** for `package-lock.json`/`pnpm-lock.yaml` targets (`_JS_LOCKFILES`), `False` for Python manifest targets
  - [x] 6.3 Set `remediation.kind = "version_bump"` with `target_version` for both npm/pnpm and Python findings alike (boundary applied later, at classification — not here)
  - [x] 6.4 Build fixture JSON for all four target-file cases: `fs`(npm), `fs`(Python), `config`, `image`
  - [x] 6.5 Verify Acceptance Criterion: `fs` mode covers both npm/pnpm and Python manifests (PRD requirement 53)
  - [x] 6.6 Verify Acceptance Criterion: `lockfile_managed` correctly `True`/`False` per target-file case (PRD requirement 54)
  - [x] 6.7 Verify Acceptance Criterion: `image` mode skipped (not failed) when no Dockerfile present (PRD requirement 17)
  - [x] 6.8 Run Tests: `tests/unit/test_trivy_runner.py::test_lockfile_managed_boundary` and general normalize tests — `make test-unit`
  - [x] 6.9 Run Tests: `tests/component/test_trivy_runner.py` (three-mode dispatch mocked) — `make test-component`

- [x] 7.0 Implement Story S-131: Checkov scanner integration — [Issue #191](https://github.com/llipe/dev-tasks-agent-fleet/issues/191)

  > Note: Where the `medium` unknown-severity floor (S-126) first gets exercised against real tool output — Checkov's OSS checks commonly carry no native severity. Depends on S-127, S-126.

  - [x] 7.1 Implement IaC-file detection (skip condition when no Terraform/CloudFormation/K8s/Dockerfile present)
  - [x] 7.2 Implement `run_checkov()` (`--output json`, own `SCANNER_TIMEOUT`)
  - [x] 7.3 Implement `normalize_checkov()` (severity via `severity_from_checkov()`; `remediation.kind = "structural"` always — never mechanical)
  - [x] 7.4 Build fixture JSON with and without a native `severity` field
  - [x] 7.5 Verify Acceptance Criterion: skipped with a named `run_event` when no IaC files present, not a failure (PRD AC23)
  - [x] 7.6 Verify Acceptance Criterion: `medium` fallback correctly applied on the common no-severity case
  - [x] 7.7 Run Tests: `tests/unit/test_checkov_runner.py` — `make test-unit`
  - [x] 7.8 Run Tests: `tests/component/test_checkov_runner.py::test_skip_no_iac` and mocked-subprocess cases — `make test-component`

- [x] 8.0 Implement Story S-132: CodeQL scanner integration (JS/TS + Python only) — [Issue #192](https://github.com/llipe/dev-tasks-agent-fleet/issues/192)

  > Note: **Blocking pre-check before any code:** confirm CodeQL CLI ARM64 availability for the `javascript-typescript` and `python` query packs at the pinned version (PRD OQ5, spec §15.2) — AgentCore Runtime has no x86_64 fallback. Depends on S-127, S-126.

  - [x] 8.0.1 **[BLOCKING]** Confirm CodeQL CLI ships ARM64 Linux builds for both `javascript-typescript` and `python` query packs at the version to be pinned; record the confirmed version before proceeding — **Confirmed via the public GitHub Releases API**: `github/codeql-cli-binaries` release `v2.27.0` ships `codeql-linux-arm64.zip` (393,167,447 bytes) alongside `codeql-linux64.zip`; `github/codeql-action`'s matching `codeql-bundle-v2.27.0` tag ships `codeql-bundle-linux-arm64.tar.gz`/`.tar.zst` alongside the linux64/osx64/win64 variants. Both query packs (`codeql/javascript-typescript-queries`, `codeql/python-queries`) are pure QL source packs with no platform-specific binaries. **Pinned version: CodeQL CLI v2.27.0.** — **Note (CORRECTED in S-141, same finding as 8.1 below):** the JS/TS package name quoted here (`codeql/javascript-typescript-queries`) was never real; the actual name is `codeql/javascript-queries`. Left as originally recorded since this task's ARM64-availability conclusion (both packs are pure QL source, no platform binaries) is unaffected by the name error — see 8.1 for the fix.
  - [x] 8.1 Add the two query packs to the Dockerfile (`codeql pack download codeql/javascript-typescript-queries codeql/python-queries`) — no compiled-language toolchain (no JDK/Go/C++ compiler) — **CORRECTED in S-141**: `codeql/javascript-typescript-queries` is not a real published package (confirmed via `gh api orgs/codeql/packages`); the actual name is `codeql/javascript-queries`. This was undetected until the S-141 redeploy attempt because CodeBuild's `codeql pack download` failure surfaced as a misleading 403 (anonymous requests to a nonexistent package), not a clear "package not found." Fixed in `Dockerfile` and `scanners/codeql_runner.py`'s `_QUERY_PACKS` dict.
  - [x] 8.2 Implement language-detection trigger logic (JS/TS: `.js`/`.ts`/`.jsx`/`.tsx`/`package.json`; Python: `.py`/`pyproject.toml`/`requirements.txt`; both; neither)
  - [x] 8.3 Implement `run_codeql()` two-phase call (`codeql database create --language=<lang>` → `codeql database analyze --format sarif-latest`), per-language dispatch, merged findings when both languages present
  - [x] 8.4 Implement `normalize_codeql()` (severity via `severity_from_codeql()`)
  - [x] 8.5 Build SARIF fixtures for JS/TS and Python separately, including a result with neither `security-severity` nor a usable `level`
  - [x] 8.6 Verify Acceptance Criterion: container ships exactly two query packs, no compiled-language pack (PRD requirement 51)
  - [x] 8.7 Verify Acceptance Criterion: neither pack triggers a compiled build step (PRD requirement 14)
  - [x] 8.8 Verify Acceptance Criterion: a repo matching neither language is `SKIPPED`, not failed (PRD requirement 17, AC24 groundwork)
  - [x] 8.9 Verify Acceptance Criterion: a repo matching both languages runs CodeQL twice, findings merged
  - [x] 8.10 Run Tests: `tests/unit/test_codeql_runner.py` (normalize, 4-way trigger-condition matrix) — `make test-unit`
  - [x] 8.11 Run Tests: `tests/component/test_codeql_runner.py` (two-phase call mocked, skip path) — `make test-component`

- [x] 9.0 Implement Story S-133: Cross-tool deduplication (`dedupe.py`) — [Issue #193](https://github.com/llipe/dev-tasks-agent-fleet/issues/193)

  > Note: Conservative merge (file+line overlap AND category match) so a real second issue is never hidden under an over-eager merge. Formally depends only on S-127's schema.

  - [x] 9.1 Implement `dedupe()`/`_merge_overlapping_by_line()`/`MergedFinding` per spec §8.3
  - [x] 9.2 Representative record in a merge uses the highest-severity contributor; both tool identifiers retained
  - [x] 9.3 Verify Acceptance Criterion: same-resource finding from two tools merges into one record naming both tools (PRD AC7)
  - [x] 9.4 Verify Acceptance Criterion: two distinct findings (same file, different line, different category) stay separate (PRD AC8)
  - [x] 9.5 Run Tests: `tests/unit/test_dedupe.py` (merge case, no-merge case, three-way overlap, overlapping-lines-different-category) against synthetic `Finding` records — `make test-unit`

- [x] 10.0 Implement Story S-134: Classifier — mechanical/manual/unscannable — [Issue #194](https://github.com/llipe/dev-tasks-agent-fleet/issues/194)

  > Note: The single most product-defining logic in the agent — where D22/D24/requirement 54's boundary and requirement 27's major-version guard take effect. Depends on S-130 (`lockfile_managed`), S-133 (`MergedFinding`).

  - [x] 10.1 Implement `classify()` per spec §8.4 (four branches: `semgrep_autofix`→mechanical; `version_bump`+`lockfile_managed`→manual; `version_bump`+major-bump-on-non-lockfile→manual; else eligible `version_bump`→mechanical; everything else→manual; `remediation is None`→unscannable)
  - [x] 10.2 Implement `_is_major_bump()`/`_is_semver()` helpers
  - [x] 10.3 Verify Acceptance Criterion: Semgrep finding with native autofix patch → `mechanical` (PRD AC9)
  - [x] 10.4 Verify Acceptance Criterion: Trivy finding on a container base image (non-lockfile) with clean version-bump → `mechanical` (PRD AC10)
  - [x] 10.5 Verify Acceptance Criterion: Trivy finding on `package-lock.json`/`pnpm-lock.yaml` → `manual`, annotated naming `dependency-update` as owner (PRD AC11, requirement 24)
  - [x] 10.6 Verify Acceptance Criterion: Trivy finding on `requirements.txt`/`poetry.lock`/`Pipfile.lock` → `mechanical` when otherwise eligible — **not** excluded (PRD requirement 54)
  - [x] 10.7 Verify Acceptance Criterion: major-version bump on a non-lockfile semver artifact → `manual` with reason recorded (PRD requirement 27)
  - [x] 10.8 Verify Acceptance Criterion: unparseable remediation shape → `unscannable`, never guessed (PRD AC12)
  - [x] 10.9 Verify Acceptance Criterion: classification is deterministic parsing only, no LLM call (PRD requirement 25)
  - [x] 10.10 Run Tests: `tests/unit/test_classifier.py` — every branch, including the JS/TS-excluded vs. Python-not-excluded boundary side by side, and the `lockfile_managed=True` + major-bump simultaneous case — `make test-unit`

- [x] 11.0 Implement Story S-135: `audit_only` mode end-to-end, including `min_severity` gating — [Issue #195](https://github.com/llipe/dev-tasks-agent-fleet/issues/195)

  > Note: First fully usable mode — everything from S-126–S-134 converges here. Depends on S-128–S-134 (all scanners, dedup, classifier), S-125 (scaffold/reporting).

  - [x] 11.1 Wire `main.py`'s `scan` step to call `run_scanners()` across the requested tools, wrapped in `heartbeat.run_with_heartbeat(...)`
  - [x] 11.2 Wire `classify` step (dedupe → classify)
  - [x] 11.3 Implement `audit_report` artifact construction (findings grouped by bucket/tool/severity)
  - [x] 11.4 Implement `determine_outcome()`'s `audit_only` branch with `_at_or_above_floor()` `min_severity` gating (spec §8.10)
  - [x] 11.5 Verify Acceptance Criterion: clean repo → `succeeded`/`no_findings`, `audit_report` artifact, no branch/PR (PRD AC3)
  - [x] 11.6 Verify Acceptance Criterion: findings + `fail_on_findings=true` → `failed`/`AUDIT_FINDINGS` (PRD AC4)
  - [x] 11.7 Verify Acceptance Criterion: findings + `fail_on_findings=false` → `succeeded`/`needs_review` (PRD AC5)
  - [x] 11.8 Verify Acceptance Criterion: `min_severity=high` with only low/medium findings → `succeeded`/`no_findings`, but all findings still fully listed in the artifact (PRD AC12b)
  - [x] 11.9 Verify Acceptance Criterion: same repo + one `high` finding → `failed`/`AUDIT_FINDINGS`
  - [x] 11.10 Verify Acceptance Criterion: all scanners failing → `failed`/`ALL_SCANNERS_FAILED`; one of five failing → run continues normally (PRD AC24)
  - [x] 11.11 Run Tests: `tests/unit/test_determine_outcome.py` (parametrized over PRD §8.1 `audit_only` rows + `min_severity` crossing) — `make test-unit`
  - [x] 11.12 Run Tests: `tests/component/test_audit_only_pipeline.py` (all five scanners mocked; full-failure and one-of-five-failure cases) — `make test-component`

- [x] 12.0 Implement Story S-136: Mechanical fix application (Semgrep autofix, Trivy version bump) — [Issue #196](https://github.com/llipe/dev-tasks-agent-fleet/issues/196)

  > Note: First half of `fix` mode's write path, built and tested before the re-scan gate so "does the fixer apply the right patch to the right finding" is provable in isolation. Depends on S-135, S-134.

  - [x] 12.1 Implement `fixers/semgrep_autofix.py` (`semgrep --autofix --config <RULESET>`, applied-fingerprints tracking)
  - [x] 12.2 Implement `fixers/trivy_bump.py` (targets lowest closing version; lockfile reconciliation after a Python manifest bump)
  - [x] 12.3 Verify Acceptance Criterion: Semgrep autofix applied for every `mechanical` Semgrep finding (PRD requirement 27)
  - [x] 12.4 Verify Acceptance Criterion: Trivy version bump applied for every `mechanical` Trivy finding (PRD requirement 27)
  - [x] 12.5 Verify Acceptance Criterion: `manual`/`unscannable` findings never touched by any code path (PRD requirement 28) — assert via diff inspection, not just by absence of a call
  - [x] 12.6 Verify Acceptance Criterion: lockfile reconciliation runs after a Python manifest bump
  - [x] 12.7 Run Tests: `tests/unit` — Trivy bump target-version selection as a pure function — `make test-unit`
  - [x] 12.8 Run Tests: `tests/component/test_mechanical_fixers.py` (mocked subprocess; zero-mechanical-findings no-op; autofix-fails-to-apply-cleanly handoff case) — `make test-component`

- [x] 13.0 Implement Story S-137: The re-scan gate (`rescan.py`) — [Issue #197](https://github.com/llipe/dev-tasks-agent-fleet/issues/197)

  > Note: The agent's defining trust mechanism (D23/D25) — no analog in the sibling agent. Built and proven standalone before S-140 wires it into the full orchestrator loop. Depends on S-136, S-135.

  - [x] 13.1 Implement `rescan_gate()` and the `_ALLOWED_NEW_FINDING_EXCEPTIONS` enumerated table per spec §8.7
  - [x] 13.2 Verify Acceptance Criterion: deterministic-fix-applies-but-finding-still-present → `clean=False`, `still_present` names it (PRD AC14 groundwork)
  - [x] 13.3 Verify Acceptance Criterion: fix-removes-target-but-introduces-new-finding → `clean=False`, `unexplained_new` names it, unless allow-listed (PRD AC15 groundwork)
  - [x] 13.4 Verify Acceptance Criterion: an enumerated allow-list exception does not fail the gate
  - [x] 13.5 Verify Acceptance Criterion: the gate never infers an exception — only the fixed table (PRD requirement 34)
  - [x] 13.6 Run Tests: `tests/unit/test_rescan_gate.py` — all four still-present/new-finding combinations, plus the allow-list path, plus a near-miss (partially matching but not exact) allow-list pattern — `make test-unit`

- [x] 14.0 Implement Story S-138: LLM fix agent — per-finding escape hatch — [Issue #198](https://github.com/llipe/dev-tasks-agent-fleet/issues/198)

  > Note: The one genuinely new design point vs. the sibling agent — per-finding invocation and per-finding budgeting (D22/D26), not per-run. Depends on S-137 (re-invokes the gate per attempt), S-136 (invoked only when the deterministic fixer is insufficient).

  - [x] 14.1 Port `_safe_path` workspace-confinement resolver and the 5-tool surface (shell/read/write/find/grep) from `dependency-update`'s `fix_agent.py`
  - [x] 14.2 Implement `run_fix_loop_for_finding()` — single-finding prompt construction, never the full findings list
  - [x] 14.3 Implement `_assert_diff_confined_to()` post-fix check (mandate-violation-equivalent enforcement)
  - [x] 14.4 Verify Acceptance Criterion: fix agent receives only the single targeted finding's record (PRD AC19, requirement 31) — assert via tool-call argument inspection
  - [x] 14.5 Verify Acceptance Criterion: `_safe_path` refuses a path escaping the workspace, tested directly (PRD AC20)
  - [x] 14.6 Verify Acceptance Criterion: `max_fix_attempts` budget applies per finding, not per run (PRD AC17)
  - [x] 14.7 Verify Acceptance Criterion: `max_fix_attempts=0` disables the LLM entirely, zero Bedrock calls (PRD AC18)
  - [x] 14.8 Verify Acceptance Criterion: a diff touching a file outside the finding's own path is caught and the finding reported unresolved, not trusted (spec §12)
  - [x] 14.9 Run Tests: `tests/unit/test_safe_path.py`, `tests/unit/test_diff_confinement.py` — `make test-unit`
  - [x] 14.10 Run Tests: `tests/component/test_fix_agent.py` with `patch("fix_agent.Agent")` — zero-Bedrock-call, per-finding-budget, tool-call-argument-scoping cases (PRD AC16, AC17, AC18) — `make test-component`

- [x] 15.0 Implement Story S-139: Pull request builder — branch, idempotency, body sections — [Issue #199](https://github.com/llipe/dev-tasks-agent-fleet/issues/199)

  > Note: Reuses the sibling agent's branch/idempotency/push mechanics near-verbatim; the new work is entirely the body's content structure. Depends on S-134 (classifier output feeds the body), S-137 (re-scan confirmation line).

  - [x] 15.1 Port branch/idempotency/push mechanics from `dependency-update`'s `pull_request.py`
  - [x] 15.2 Implement `build_pr_body()` section builders: summary table, fixed-findings table, remaining-manual table (always present, even empty), D24-boundary section, major-version-guard section, AI-modification warning, re-scan confirmation line
  - [x] 15.3 Verify Acceptance Criterion: branch `security/fix-<UTC timestamp>`, commit `fix(security): automated mechanical security fixes` (PRD requirements 38-39)
  - [x] 15.4 Verify Acceptance Criterion: already-open `security/fix-*` PR short-circuits to `succeeded`/`not_applicable`, no second branch/PR (PRD AC22)
  - [x] 15.5 Verify Acceptance Criterion: body contains every required section per requirement 42, including the always-present-even-if-empty remaining-manual table (PRD AC15)
  - [x] 15.6 Verify Acceptance Criterion: body passed via `--body-file`, never inline (PRD AC17 groundwork)
  - [x] 15.7 Run Tests: `tests/unit/test_pr_body.py` (synthetic `PipelineState` fixtures: no-LLM, LLM-used, D24-boundary present, major-version-guard present, zero-remaining, all-sections-simultaneously) — `make test-unit`
  - [x] 15.8 Run Tests: `tests/component/test_pr_creation.py` (idempotency via mocked `gh pr list`, branch/push mocked) — `make test-component`

- [x] 16.0 Implement Story S-140: `fix` mode end-to-end wiring — [Issue #200](https://github.com/llipe/dev-tasks-agent-fleet/issues/200)

  > Note: Capstone integration — wires S-136 through S-139 into the full `scan → classify → fix → rescan → open_pr` loop. Depends on S-136, S-137, S-138, S-139 (every piece of the write path).

  - [x] 16.1 Wire `fix`/`rescan`/`open_pr` steps into `main.py`, completing the state machine begun in S-135
  - [x] 16.2 Wrap `scan`/`rescan` in `heartbeat.run_with_heartbeat(...)`
  - [x] 16.3 Implement full `run_steps` emission (7 keys: `resolve_credentials`/`checkout`/`scan`/`classify`/`fix`/`rescan`/`open_pr`) and `build_metrics()`
  - [x] 16.4 Verify Acceptance Criterion: full state machine matches spec §8.8's diagram exactly
  - [x] 16.5 Verify Acceptance Criterion: happy path zero-LLM — exactly one PR, `succeeded`/`fixed` or `partial`, `metrics.llm_used=false` (PRD AC13)
  - [x] 16.6 Verify Acceptance Criterion: re-scan gate blocks an unverified fix even after LLM budget exhausted — `failed`/`RESCAN_NOT_CLEAN`, **no PR**, despite a local working-tree change (PRD AC14, full end-to-end)
  - [x] 16.7 Verify Acceptance Criterion: re-scan gate blocks a regression-introducing fix the same way, unless allow-listed (PRD AC15, full end-to-end)
  - [x] 16.8 Verify Acceptance Criterion: no mechanical findings at all → `no_findings`/`needs_review` per remaining findings, no branch/PR (PRD AC21)
  - [x] 16.9 Verify Acceptance Criterion: a deliberately slow fixture (simulated CodeQL delay) proves the stream stays alive past `IDLE_SESSION_TIMEOUT` under heartbeat wrapping
  - [x] 16.10 Verify Acceptance Criterion: all 7 `run_steps` present, in order, each terminal (PRD AC29)
  - [x] 16.11 Verify Acceptance Criterion: `runs.metrics` includes `fix_attempts_deterministic`, `fix_attempts_llm`, finding counts, `scanners_run/skipped/failed` (PRD requirement 47)
  - [x] 16.12 Run Tests: `tests/unit/test_determine_outcome.py` extended for `fix` mode, parametrized over every PRD §8.1 `fix`-mode row — `make test-unit`
  - [x] 16.13 Run Tests: `tests/component/test_fix_mode_pipeline.py` (happy path; LLM-escape-hatch success; `RESCAN_NOT_CLEAN`; no-mechanical-findings no-op; idempotency; multi-tool-simultaneous-findings) — `make test-component`
  - [x] 16.14 Run Tests: full coverage gate — `make test-cov`, `make validate`

- [ ] 17.0 Implement Story S-141: Seed configuration, deployment, and real-repo verification — [Issue #201](https://github.com/llipe/dev-tasks-agent-fleet/issues/201)

  > Note: Closes out the build. Corrects the one thing the codebase research surfaced: the seed row goes in `supabase/seed.sql`, **not** `docs/reference/002_seed.sql` (a stub). Depends on S-140, S-135 (both modes complete).

  - [x] 17.1 `agentcore deploy -y`; capture `runtime_arn` — already done during S-125 (deployed `arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/securityanalyst_security_analyst-w6CpbYHRE0`; re-run only if the runtime needs redeploying by this point). S-125 tasks 1.8/1.12/1.14 (real `audit_only` invocation, live AC25/AC26/AC30 verification) were deferred here — fold that evidence into 17.10.
  - [x] 17.2 **[MIGRATION — create artifact]** Append the `security-analyst` block to `supabase/seed.sql` (idempotent `on conflict (slug) do update`), per spec §5.2 exactly — never `docs/reference/002_seed.sql`
  - [x] 17.3 **[MIGRATION — document rollback/impact]** Record that rollback is deleting/disabling the seed row; no data-loss risk (agent has no other persisted state) — documented in `agents/security-analyst/README.md` ("Seed migration — rollback and impact (S-141)")
  - [x] 17.4 **[MIGRATION — confirmation gate]** Request explicit user confirmation before applying the seed against anything other than a local/dev Supabase stack — user explicitly confirmed applying against the linked remote (shared) Supabase project, 2026-09-16
  - [x] 17.5 **[MIGRATION — apply]** Apply `supabase/seed.sql` after confirmation — applied via `supabase db query --linked --file supabase/seed.sql` against the linked remote project (`dev-tasks-agent-fleet`, ref `hegxeycmbmjfgzqpdiik`)
  - [x] 17.6 **[MIGRATION — verify]** Run the seed's own Block 4 `count(*)` verification query — confirmed `agents` count = 2 (`dependency-update`, `security-analyst`); direct row query confirmed `security-analyst` row present with `max_runtime_seconds=5400`, `is_enabled=true`, correct `runtime_arn`
  - [x] 17.7 Document the `max_runtime_seconds`/`maxLifetime` manual-sync coupling in `agents/security-analyst/README.md`
  - [x] 17.8 Verify Acceptance Criterion: `max_runtime_seconds=5400` in the seed row equals `maxLifetime` in `agentcore.json` (PRD AC31) — statically confirmed: `agentcore.json` `lifecycleConfiguration.maxLifetime = 5400`, `seed.sql` Block 4 `max_runtime_seconds = 5400` (values not yet applied to a live DB, but the committed artifacts agree)
  - [x] 17.9 Verify Acceptance Criterion: a deliberately hung run is marked `timed_out` by the existing `pg_cron` reaper, no reaper-side change needed (PRD AC31) — confirmed by reading `reap_stale_runs()` (`supabase/migrations/20260902200101_initial_schema.sql`): it is generic, keyed on the per-run snapshot columns `runs.max_runtime_seconds`/`runs.grace_seconds` (D8), no `agent_id`/slug branch or hardcoded threshold; see ADR-004
  - [x] 17.10 Run manual verification: one real `audit_only` invocation against a real (small, known-content) target repo — attach evidence to the closing PR — **VERIFIED 2026-09-17** against `llipe/memo-cli` — definitive post-PR-#240 evidence: run `6b61ca49-1ea8-4730-ae59-0a54ed19fca0` (panel-invoked, 13:40Z), `audit_report` artifact `file_path`s are repo-relative (`workstream/specification-prd-001-mvp.md`, no ephemeral `/tmp/…` prefix). Earlier same-day run `3958c93c-ea87-488b-95c5-41c4efcc37c4` first proved the pipeline end-to-end but predates #240 (its artifact carried absolute paths). Both runs: `resolve_credentials → checkout → scan → classify` all `succeeded`; `Scan complete: run=['codeql', 'gitleaks', 'semgrep', 'trivy'] skipped=['checkov'] failed=[]`; terminal `status=failed / outcome=needs_review / error_code=AUDIT_FINDINGS` with `finished_at` set (not stuck) — the spec §8.10 path for `fail_on_findings=true` + 2 findings ≥ `min_severity=low`; `audit_report` artifact persisted with both Gitleaks `generic-api-key` findings bucketed `unscannable`, messages carrying no raw secret (AC-27 on real data). Getting here required six real-invocation fix PRs (#235–#240) for defects no mocked-subprocess test could see — see `planner-state-security-analyst-agent.md` "S-141 Real-Invocation Hardening". Note: the two prior "succeeded/no_findings" runs on 2026-09-16 were false negatives caused by the Gitleaks `/dev/stdout` data-loss bug (PR #239); the 2 findings are SHA256 example hashes in memo-cli's `workstream/specification-prd-001-mvp.md` (repo-side `.gitleaksignore` candidate, not an agent defect).
  - [x] 17.11 Run manual verification: one real `fix` invocation against a fixture repo seeded with a Semgrep-autofixable finding — confirm a real, reviewable PR opens — attach evidence to the closing PR — **VERIFIED 2026-09-17** against `llipe/security-analyst-fixture` (created for this task, user-approved; seeded with 2 Semgrep-autofixable + 3 non-autofixable findings, verified with the real binaries). Definitive run `3ecaf839-c021-4e84-b88e-bbaf13a8a4cc` (panel-invoked, runtime v9): all 7 steps `succeeded`; `findings_before {mechanical: 2, manual: 1, unscannable: 1}` → `findings_fixed: 2` (deterministic, `llm_used: false`) → re-scan gate clean → real PR opened (llipe/security-analyst-fixture#2, branch `security/fix-*`, diff = exactly `verify=False→True` and `shell=True→False`, body with Summary/Fixed/Remaining tables and the re-scan confirmation) → outcome `succeeded / partial`; `audit_report` (before/after) + `pull_request` artifacts recorded; the CodeQL+Semgrep XSS on `src/hash.js:15` merged into one finding (`reported_by: [codeql, semgrep]`, `CWE-79`). The first attempt (run `362f526e…`, PR #1, later closed) exposed the CWE-spelling dedupe bug fixed in PR #246. AC14/15/17/22 and requirements 27/34/41/43 observed live.

## Coverage Cross-Check

Every task above maps 1:1 to its source story's Implementation Steps, Acceptance Criteria, and Testing Requirements sections — no story content was dropped in conversion. See [`user-stories-prd-security-analyst-agent.md`](user-stories-prd-security-analyst-agent.md)'s own Coverage Validation section for the PRD-requirement-level mapping this task list inherits.
