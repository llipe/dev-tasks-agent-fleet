# User Stories — Dependency Update Agent

## Changelog

| Version | Date       | Summary         | Author           |
| ------- | ---------- | --------------- | ------------------ |
| 1.0     | 2026-08-26 | Initial version. 8 stories covering the full Phase 1 agent implementation from scaffolding through E2E validation. | product-engineer |

---

## Summary

8 stories, ordered by dependency. Each fits a single PR. Total estimated effort: ~10-14 days.

| ID | Title | Priority | Size | Dependencies |
|----|-------|----------|------|--------------|
| S-001 | Project scaffolding and container image | Critical | M | None |
| S-002 | Credential resolution and GitHub App auth | Critical | M | S-001 |
| S-003 | Toolchain detection and validation runner | High | S | S-001 |
| S-004 | Audit, version eligibility, and advisory classification | High | L | S-003 |
| S-005 | Deterministic pipeline orchestrator | Critical | L | S-002, S-003, S-004 |
| S-006 | LLM fix agent escape hatch | High | M | S-005 |
| S-007 | Pull request creation and PR body builder | High | M | S-005 |
| S-008 | Seed update, deployment, and E2E validation | Critical | M | S-005, S-006, S-007 |

---

### Story S-001: Project Scaffolding and Container Image

**Priority:** Critical
**Estimated Size:** M
**Dependencies:** None

#### User Story

As an operator,
I want the agent project scaffolded at `/agents/dependency-update/` using the AgentCore CLI,
So that the canonical layout exists for `agentcore deploy` and sets the convention for future agents.

#### Context

D16 places all agents under `/agents/<name>/`. D22 requires using `agentcore create` rather than hand-authoring. The Container build type is required for system-level deps (Node, pnpm, npm, git, gh CLI). This is the foundation everything else builds on.

#### Acceptance Criteria

- [ ] `/agents/dependency-update/` exists with `agentcore/agentcore.json`, `agentcore/aws-targets.json`, `agentcore/cdk/`, and `app/dependencyUpdate/`
- [ ] `agentcore validate` passes without errors
- [ ] `agentcore.json` specifies Container build, HTTP protocol, PYTHON_3_14 runtime, `maxLifetime: 3600`, `idleRuntimeSessionTimeout: 300`
- [ ] `aws-targets.json` targets `us-east-1`
- [ ] Dockerfile builds successfully for ARM64 and includes Node 26, pnpm, npm, git, gh CLI, Python 3.13+
- [ ] `agent_reporter.py` is copied from `docs/reference/agent_reporter.py` and is byte-identical
- [ ] `pyproject.toml` declares all Python dependencies with pinned versions
- [ ] `main.py` exists with a minimal `BedrockAgentCoreApp` entrypoint that responds to `/ping`
- [ ] `agentcore dev` starts the local server and `/ping` responds

#### Business Rules

- D22: scaffold with CLI, don't hand-author
- D16: monorepo layout under `/agents/`
- D24: `agent_reporter.py` byte-identical to reference

#### Technical Notes

- Use `agentcore create --name dependency-update --build Container --framework Strands --model-provider Bedrock --protocol HTTP --memory none --network-mode PUBLIC --max-lifetime 3600 --idle-timeout 300 --skip-git --skip-python-setup --output-dir agents/dependency-update`
- Customize the generated Dockerfile (spec §15.2) to add Node 26, pnpm, npm, gh CLI
- Set `runtimeVersion: PYTHON_3_14` in agentcore.json
- The entrypoint module structure follows spec §8.1

#### Testing Requirements

- **Unit Tests:** None (scaffolding story)
- **Integration Tests:** `agentcore validate` passes; Docker build succeeds on ARM64
- **Manual Testing:** `agentcore dev` → `curl localhost:8080/ping` returns 200
- **Edge-Case Matrix:** N/A
- **Execution Commands:** `cd agents/dependency-update && agentcore validate && agentcore dev`

#### Implementation Steps

1. Run `agentcore create` with the flags above
2. Edit `agentcore.json`: set runtimeVersion, lifecycle config, code location
3. Set `aws-targets.json` to us-east-1 with account ID
4. Author `Dockerfile` per spec §15.2 (multi-stage: Python 3.13 slim + Node 26 + pnpm + npm + gh)
5. Author `pyproject.toml` with pinned dependencies (spec §16.1)
6. Copy `docs/reference/agent_reporter.py` → `app/dependencyUpdate/agent_reporter.py`
7. Create minimal `main.py` with `BedrockAgentCoreApp` + `@app.entrypoint` returning `{"status": "ok"}`
8. Create module stubs: `config.py`, `credentials.py`, `toolchain.py`, `audit.py`, `classifier.py`, `eligibility.py`, `updater.py`, `validator.py`, `fix_agent.py`, `pull_request.py`, `scrubber.py`
9. Verify `agentcore validate` and `agentcore dev` + `/ping`
10. Add README documenting the layout and the `max_runtime_seconds` ↔ `maxLifetime` coupling (req 65)

#### Files to Create/Modify

- `agents/dependency-update/agentcore/agentcore.json` - Runtime config
- `agents/dependency-update/agentcore/aws-targets.json` - Region/account
- `agents/dependency-update/app/dependencyUpdate/main.py` - Entrypoint stub
- `agents/dependency-update/app/dependencyUpdate/agent_reporter.py` - SDK copy
- `agents/dependency-update/app/dependencyUpdate/config.py` - Constants
- `agents/dependency-update/app/dependencyUpdate/Dockerfile` - Container image
- `agents/dependency-update/app/dependencyUpdate/pyproject.toml` - Dependencies
- `agents/dependency-update/README.md` - Documentation

#### Definition of Done Checklist

- [ ] `agentcore validate` passes
- [ ] Docker image builds for ARM64
- [ ] `agentcore dev` + `/ping` responds 200
- [ ] `agent_reporter.py` byte-identical to reference (verified by diff)
- [ ] PR created and merged

---

### Story S-002: Credential Resolution and GitHub App Auth

**Priority:** Critical
**Estimated Size:** M
**Dependencies:** S-001

#### User Story

As an operator,
I want the agent to authenticate via a GitHub App installation token resolved from the database,
So that repository access is scoped, auditable, and doesn't depend on my personal credentials.

#### Context

D18 (option A): credentials resolved from `github_installations` via PostgREST, not from a naming convention. The agent reads the Supabase service role key from Secrets Manager (D15/D24), then uses it to query PostgREST for the installation row, fetches the PEM, signs a JWT, and exchanges it for an installation token. Token scrubbing (req 19) is implemented here because it's required from the moment the token exists.

#### Acceptance Criteria

- [ ] `fetch_supabase_key()` reads from Secrets Manager using the configured secret ID
- [ ] Secret ID is overridable via `SUPABASE_KEY_SECRET_ID` env var (req 14)
- [ ] `resolve_github_credentials(org)` queries PostgREST for `github_org_slug = org` (req 15)
- [ ] Returns `NO_INSTALLATION` error when no enabled row matches (req 16)
- [ ] Mints RS256 JWT with `iss=app_id`, `exp=now()+9min` (req 17)
- [ ] Exchanges JWT for installation token at GitHub API (req 17)
- [ ] `TokenContext.is_stale()` returns true after 45 minutes (req 20)
- [ ] `refresh_if_stale()` re-mints when stale
- [ ] `scrub()` removes token from any string it appears in (req 19)
- [ ] `scrub_process_error()` cleans cmd, stdout, and stderr of CalledProcessError

#### Business Rules

- Never construct Secrets Manager path from org name (D18-A)
- Token never appears in run_events, stderr, or return payload
- Installation must be `is_enabled = true`

#### Technical Notes

- Modules: `credentials.py`, `scrubber.py`, `config.py`
- Uses `boto3` for Secrets Manager, `PyJWT` + `cryptography` for RS256, `requests` for GitHub API
- PostgREST query: `GET {SUPABASE_URL}/rest/v1/github_installations?github_org_slug=eq.{org}&is_enabled=eq.true&select=app_id,installation_id,private_key_secret_arn`

#### Testing Requirements

- **Unit Tests:** `test_credentials.py` — mock boto3 + mock HTTP for PostgREST and GitHub API
  - Happy path: key fetch → PostgREST query → JWT sign → token exchange
  - No installation row → raises with NO_INSTALLATION
  - Secrets Manager failure → descriptive error
  - Token staleness at 44min (not stale) and 46min (stale)
- **Unit Tests:** `test_scrubber.py`
  - Token in middle of string → replaced with ***
  - Token in CalledProcessError.cmd (list and string forms)
  - Multiple secrets scrubbed
  - Empty/None secrets handled gracefully
- **Execution Commands:** `pytest -m unit tests/unit/test_credentials.py tests/unit/test_scrubber.py`

#### Implementation Steps

1. Implement `config.py`: env var reads, secret IDs, SUPABASE_URL
2. Implement `scrubber.py`: `scrub()` and `scrub_process_error()` (spec §8.6)
3. Implement `credentials.py`: `fetch_supabase_key()`, `resolve_github_credentials()`, `mint_installation_token()`, `refresh_if_stale()`, `TokenContext` dataclass (spec §8.5)
4. Write unit tests with mocked AWS + HTTP
5. Verify all acceptance criteria pass

#### Files to Create/Modify

- `agents/dependency-update/app/dependencyUpdate/config.py` - Env var reads
- `agents/dependency-update/app/dependencyUpdate/credentials.py` - Auth logic
- `agents/dependency-update/app/dependencyUpdate/scrubber.py` - Token scrubbing
- `agents/dependency-update/tests/unit/test_credentials.py` - Unit tests
- `agents/dependency-update/tests/unit/test_scrubber.py` - Unit tests

#### Definition of Done Checklist

- [ ] Unit tests passing
- [ ] No credential value appears in any test output or logged string
- [ ] Code follows spec §8.5, §8.6
- [ ] PR created and merged

---

### Story S-003: Toolchain Detection and Validation Runner

**Priority:** High
**Estimated Size:** S
**Dependencies:** S-001

#### User Story

As an operator,
I want the agent to detect the package manager and validate the repository's script contract,
So that the agent refuses to work on repos it cannot verify, and reports missing optional scripts as visible warnings.

#### Context

D19: pnpm and npm from lockfile evidence. D20: `test` required, rest reported. The agent is opinionated — a missing `test` script is a hard failure, but missing lint/format/typecheck just emit warn events and continue.

#### Acceptance Criteria

- [ ] Detects pnpm from `packageManager` field or `pnpm-lock.yaml` (req 21)
- [ ] Detects npm from `package-lock.json` (req 21)
- [ ] Fails with `NO_PACKAGE_MANAGER` when no lockfile matches (req 21)
- [ ] Matches pnpm major version from `packageManager` field or lockfileVersion (req 22)
- [ ] Installs correct pnpm major when container default differs (req 22)
- [ ] Identifies `test` script as required; fails with `NO_TEST_SCRIPT` if absent (req 23)
- [ ] Identifies `lint`, `format`, `typecheck` as optional; emits warn event per absent script (req 23)
- [ ] Detects `lint:fix`, `format:fix`, `format:check`, `type-check` variants (req 23-24)
- [ ] `run_validation()` runs lint → format → typecheck → test in order
- [ ] When lint fails and `lint:fix` exists, runs fix once and re-checks (req 24)
- [ ] Same for format/format:fix (req 24)
- [ ] Returns structured `ValidationResult` with per-check status (passed/failed/skipped)

#### Business Rules

- Detection precedence: `packageManager` field → `pnpm-lock.yaml` → `package-lock.json` → fail
- `test` absent = hard failure before any update
- Optional script absent = warn-level event, continues

#### Technical Notes

- Modules: `toolchain.py`, `validator.py`
- Uses subprocess for pnpm/npm commands
- `TEST_TIMEOUT` env var (default 600s) caps test run duration
- Individual command timeout: 180s for non-test, 600s for test

#### Testing Requirements

- **Unit Tests:** `test_toolchain.py`
  - Fixture with pnpm-lock.yaml → detects pnpm
  - Fixture with package-lock.json → detects npm
  - Fixture with both → pnpm wins (packageManager field)
  - Fixture with neither → NO_PACKAGE_MANAGER
  - Fixture with no `test` script → NO_TEST_SCRIPT
  - Fixture with `test` only → lint/format/typecheck reported skipped
  - pnpm version detection from lockfileVersion values (9.x, 6.x, 5.x)
- **Unit Tests:** `test_validator.py`
  - Mock subprocess: all pass → ValidationResult all passed
  - lint fails, lint:fix exists → fix runs, re-check
  - test fails → result.passed = False, output captured
- **Execution Commands:** `pytest -m unit tests/unit/test_toolchain.py tests/unit/test_validator.py`

#### Implementation Steps

1. Implement `toolchain.py`: `detect_package_manager()`, `detect_pnpm_version()`, `ensure_pnpm_version()`, `detect_scripts()` (spec §8.1 references)
2. Implement `validator.py`: `run_validation()`, `run_lint()`, `run_format()`, `run_typecheck()`, `run_tests()`, `ValidationResult` dataclass (spec §8.1)
3. Write unit tests with filesystem fixtures (temp dirs with package.json + lockfiles)
4. Verify all acceptance criteria pass

#### Files to Create/Modify

- `agents/dependency-update/app/dependencyUpdate/toolchain.py` - Detection logic
- `agents/dependency-update/app/dependencyUpdate/validator.py` - Validation runner
- `agents/dependency-update/tests/unit/test_toolchain.py` - Unit tests
- `agents/dependency-update/tests/unit/test_validator.py` - Unit tests

#### Definition of Done Checklist

- [ ] Unit tests passing
- [ ] All detection cases covered
- [ ] PR created and merged

---

### Story S-004: Audit, Version Eligibility, and Advisory Classification

**Priority:** High
**Estimated Size:** L
**Dependencies:** S-003

#### User Story

As an operator,
I want the agent to classify every advisory into `in_range`, `major_required`, or `unknown` and decide version eligibility per D26,
So that the agent can report exactly which vulnerabilities it cannot fix and which version changes it accepts.

#### Context

D25: major-only advisories are a named failure. D26: semver patch/minor accepted, 0.x minor treated as major-equivalent, non-semver accepted outright with the test suite as gate. The classifier uses naive major extraction (PRD OQ#4 option A) and the same eligibility rules as the version guard, so they cannot drift apart (req 37).

#### Acceptance Criteria

- [ ] `parse_semver()` correctly parses `1.2.3`, `0.1.2`, `1.2.3-beta.1`, returns None for non-semver
- [ ] `is_eligible("1.2.3", "1.3.0")` → eligible (patch/minor)
- [ ] `is_eligible("1.2.3", "2.0.0")` → ineligible (major increase)
- [ ] `is_eligible("0.1.2", "0.2.0")` → ineligible (0.x minor = major-equivalent)
- [ ] `is_eligible("abc123", "def456")` → eligible (both non-semver, req 33)
- [ ] `is_eligible("abc123", "2.0.0")` with installed=`1.0.0` context → ineligible (req 34)
- [ ] `classify_advisory()` with patched `>=5.0.0`, installed `4.x` → `major_required`
- [ ] `classify_advisory()` with patched `>=4.17.21`, installed `4.17.0` → `in_range`
- [ ] `classify_advisory()` with empty patched range → `unknown`
- [ ] `classify_advisory()` with non-semver installed → `unknown` (req 38)
- [ ] `_extract_lowest_version(">=5.0.0")` → `"5.0.0"`
- [ ] `_extract_lowest_version("<0.21.0 || >=0.21.1")` → `"0.21.0"` or `"0.21.1"` (lowest bound)
- [ ] `run_audit()` parses pnpm audit JSON and npm audit JSON
- [ ] `snapshot_packages()` returns {name: version} dict from lockfile
- [ ] `diff_packages()` computes changes between before/after snapshots
- [ ] `count_vulns()` sums vulnerability counts from audit metadata
- [ ] Non-semver version changes are flagged with `warn` event (req 35)

#### Business Rules

- Eligibility and classification use identical rules (req 37)
- Unknown never triggers MAJOR_UPDATE_REQUIRED (req 38)
- Non-semver acceptance is never a route around the major guard (req 34)

#### Technical Notes

- Modules: `eligibility.py`, `classifier.py`, `audit.py`
- Spec §8.3 (eligibility), §8.4 (classifier)
- Fixture corpus of real pnpm and npm audit JSON needed for testing
- The `_extract_lowest_version()` is naive: regex for `>=X.Y.Z` patterns, falls back to first version-like string, returns None on failure → `unknown` bucket

#### Testing Requirements

- **Unit Tests:** `test_eligibility.py` — all 4 rows of req 32 table + req 34 anti-loophole case
- **Unit Tests:** `test_classifier.py` — fixture corpus:
  - Real pnpm audit JSON with known advisories
  - Real npm audit JSON with known advisories
  - Advisory with complex range `<0.21.0 || >=0.21.1`
  - Advisory with `>=4.17.21 <5.0.0` range
  - Advisory with no patched versions field
  - Advisory for package with non-semver resolved version
  - 0.x package with 0.x+1 patch → major_required
- **Unit Tests:** `test_audit.py` — parse pnpm/npm audit JSON, snapshot, diff
- **Execution Commands:** `pytest -m unit tests/unit/test_eligibility.py tests/unit/test_classifier.py tests/unit/test_audit.py`

#### Implementation Steps

1. Implement `eligibility.py`: `parse_semver()`, `is_eligible()` (spec §8.3)
2. Implement `classifier.py`: `classify_advisory()`, `_extract_lowest_version()`, `ClassifiedAdvisory` dataclass (spec §8.4)
3. Implement `audit.py`: `run_audit()`, `count_vulns()`, `extract_advisories()`, `snapshot_lockfile_packages()`, `diff_packages()`
4. Collect real audit JSON fixtures from pnpm and npm repos
5. Write comprehensive unit tests for all cases
6. Verify all acceptance criteria pass

#### Files to Create/Modify

- `agents/dependency-update/app/dependencyUpdate/eligibility.py` - Version guard
- `agents/dependency-update/app/dependencyUpdate/classifier.py` - Advisory classifier
- `agents/dependency-update/app/dependencyUpdate/audit.py` - Audit runner + parsing
- `agents/dependency-update/tests/unit/test_eligibility.py` - Unit tests
- `agents/dependency-update/tests/unit/test_classifier.py` - Unit tests
- `agents/dependency-update/tests/unit/test_audit.py` - Unit tests
- `agents/dependency-update/tests/fixtures/` - Audit JSON fixtures

#### Definition of Done Checklist

- [ ] All eligibility table rows unit-tested
- [ ] Classifier tested against fixture corpus from both package managers
- [ ] Anti-loophole case (req 34) tested
- [ ] 0.x minor treated as major-equivalent tested
- [ ] Non-semver → unknown tested
- [ ] PR created and merged

---

### Story S-005: Deterministic Pipeline Orchestrator

**Priority:** Critical
**Estimated Size:** L
**Dependencies:** S-002, S-003, S-004

#### User Story

As an operator,
I want the full deterministic pipeline wired together with proper step reporting and outcome mapping,
So that a single invocation clones, audits, classifies, updates, validates, and reports its lifecycle correctly to Supabase.

#### Context

This is the main `main.py` orchestrator (spec §8.2). It wires S-002 (credentials), S-003 (toolchain + validation), and S-004 (audit + classification) into the pipeline shape from PRD §2.1. The LLM escape hatch (S-006) and PR creation (S-007) plug in later — this story handles the deterministic path including the `audit_only` mode and the `no_changes` early exit.

#### Acceptance Criteria

- [ ] Payload unwrapping handles `prompt` wrapper (req 9)
- [ ] Payload validation rejects invalid payloads with `INVALID_PARAMS` (req 10)
- [ ] Defaults applied: `fix_mode=audit_only`, `fail_on_findings=true`, `max_fix_attempts=3` (req 11)
- [ ] `max_fix_attempts` constrained to 0..5 (req 11)
- [ ] Clone URL constructed as `https://github.com/{org}/{name}.git` (req 12)
- [ ] Token scrubbed from `.git/config` after clone (req 18)
- [ ] Git identity configured for commits
- [ ] All 9 step keys emitted in correct order (req 61)
- [ ] `audit_only` mode: no working-tree modification, audit_report artifact created (req 28)
- [ ] `audit_only` + no findings → `succeeded / no_vulnerabilities`
- [ ] `audit_only` + findings + `fail_on_findings=true` → `failed / needs_review / AUDIT_FINDINGS`
- [ ] `audit_only` + findings + `fail_on_findings=false` → `succeeded / needs_review`
- [ ] `audit_only` + `major_required` findings + `fail_on_findings=true` → `failed / MAJOR_UPDATE_REQUIRED`
- [ ] `audit_only` + `major_required` + `fail_on_findings=false` → `succeeded` (req 42 precedence)
- [ ] `llm_fix` + no working-tree change → `succeeded / no_vulnerabilities` (req 31)
- [ ] `llm_fix` + no change + major_required → `failed / MAJOR_UPDATE_REQUIRED` (req 31+38)
- [ ] Supabase key injected into env before `RunReporter.from_env()` (D24)
- [ ] Unhandled exception → `failed` with traceback, open step closed (req 59)
- [ ] Return payload matches spec §6.2 structure (req 63)
- [ ] `error`-level events emitted per major_required advisory (req 40)
- [ ] Summary event with count and highest severity (req 40)
- [ ] `warn` events for absent optional scripts, non-semver changes (req 23, 35)

#### Business Rules

- Precedence: VALIDATION_FAILING > MAJOR_UPDATE_REQUIRED > succeeded (req 42)
- `fail_on_findings=false` overrides MAJOR_UPDATE_REQUIRED in audit_only mode (req 42)
- Clone URL never from caller — always constructed (req 12)
- Reporting failures don't kill the pipeline (req 62)

#### Technical Notes

- Module: `main.py` (spec §8.2 pseudocode)
- Integrates all other modules
- The `updater.py` module (simple `pnpm update` / `npm update` + reconcile) is implemented inline here

#### Testing Requirements

- **Component Tests:** `test_pipeline.py` — mock all external calls (Secrets Manager, PostgREST, GitHub, filesystem)
  - audit_only happy path (clean audit)
  - audit_only with findings, failing
  - audit_only with findings, tolerant
  - audit_only with major_required, both fail_on settings
  - llm_fix no-change path
  - llm_fix no-change with major_required
  - Invalid payload fast-fail
  - Unhandled exception → proper cleanup
- **Unit Tests:** `test_outcome_mapping.py` — pure function testing the §8.1 table for every row
- **Execution Commands:** `pytest -m "unit or component" tests/`

#### Implementation Steps

1. Implement `updater.py`: `update_packages()`, `has_changes()`, `reconcile_lockfile()`, `install_deps()`
2. Implement payload validation and unwrapping in `main.py`
3. Wire the orchestrator per spec §8.2 pseudocode
4. Implement outcome determination logic as a pure function (testable separately)
5. Implement clone + token scrub + git identity setup
6. Wire `RunReporter` lifecycle (context manager, step emission)
7. Implement return payload assembly
8. Write component tests mocking external dependencies
9. Write unit tests for outcome mapping (all rows of §8.1 table)

#### Files to Create/Modify

- `agents/dependency-update/app/dependencyUpdate/main.py` - Full orchestrator
- `agents/dependency-update/app/dependencyUpdate/updater.py` - Update + install logic
- `agents/dependency-update/tests/unit/test_outcome_mapping.py` - Outcome logic tests
- `agents/dependency-update/tests/component/test_pipeline.py` - Integration with mocks

#### Definition of Done Checklist

- [ ] All outcome mapping rows unit-tested
- [ ] Component tests cover audit_only and llm_fix-no-change paths
- [ ] Payload validation tested
- [ ] Step emission order verified
- [ ] PR created and merged

---

### Story S-006: LLM Fix Agent Escape Hatch

**Priority:** High
**Estimated Size:** M
**Dependencies:** S-005

#### User Story

As an operator,
I want the agent to invoke Claude Sonnet to fix test breakage after a dependency update,
So that routine breaking changes don't require my manual intervention.

#### Context

D17: the model is reachable only on one edge ("validation failed after update"). The fix agent has 5 tools, a strict system prompt (req 47), and a retry budget (req 48). After fixes, the mandate violation check (req 50) ensures the model didn't widen ranges or bump majors. The test suite must pass after the fix — if not, no PR.

#### Acceptance Criteria

- [ ] Fix agent created with Strands framework, model `us.anthropic.claude-sonnet-4-6` (req 7, D23)
- [ ] Model ID overridable via `MODEL_ID` env var
- [ ] Exactly 5 tools: shell, read_file, write_file, find_files, grep_code (req 45)
- [ ] `_safe_path()` rejects paths escaping the workspace (req 46)
- [ ] `_safe_path("../../../etc/passwd")` → raises ValueError
- [ ] `_safe_path("node_modules/../../../etc/passwd")` → raises ValueError
- [ ] System prompt includes all constraints from req 47
- [ ] Fix loop bounded by `max_fix_attempts`; re-runs validation after each attempt (req 48)
- [ ] After fix success, re-runs lint + format + typecheck (req 49)
- [ ] `verify_no_mandate_violation()` compares package.json specifiers pre/post (req 50)
- [ ] Widened range detected → `MANDATE_VIOLATION` error, no PR (req 50)
- [ ] Budget exhausted → `failed / VALIDATION_FAILING`, test output as artifact (req 51)
- [ ] `max_fix_attempts=0` → no Bedrock invocation at all (req 11)
- [ ] `runs.metrics` records `llm_used` and `fix_attempts` (req 52)

#### Business Rules

- Never invoked on happy path (D17)
- Never invoked for audit classification, version selection, or PR body (req 44)
- Model cannot escape workspace (req 46)
- Model cannot weaken tests, roll back versions, or widen ranges (req 47) — enforced by comparison (req 50)

#### Technical Notes

- Module: `fix_agent.py` (spec §8.7, §8.8)
- Uses `from strands import Agent, tool`
- Shell tool has 180s timeout; output capped at 3000 chars stdout + 1500 stderr
- read_file output capped at 8000 chars
- The mandate violation check is separate from the fix agent — it runs deterministically after

#### Testing Requirements

- **Unit Tests:** `test_safe_path.py` — path traversal attempts (symlinks, `..`, absolute)
- **Unit Tests:** `test_mandate_check.py` — pre/post package.json diffs:
  - No change → passes
  - Range widened (`^1.0.0` → `^2.0.0`) → raises MandateViolationError
  - New dep added → raises
  - Version pinned differently (`1.2.3` → `1.2.4`) → this is fine (package manager did it)
- **Component Tests:** `test_fix_agent.py` — mock Bedrock responses, verify tool calls executed, retry loop works
- **Execution Commands:** `pytest -m unit tests/unit/test_safe_path.py tests/unit/test_mandate_check.py`

#### Implementation Steps

1. Implement `fix_agent.py`: tools (`shell`, `read_file`, `write_file`, `find_files`, `grep_code`), `_safe_path()`, system prompt, `FIX_AGENT_SYSTEM_PROMPT`
2. Implement `run_fix_loop()`: create Strands Agent, iterate up to `max_fix_attempts`, re-validate
3. Implement `verify_no_mandate_violation()` in `main.py` or a utility module (spec §8.8)
4. Write unit tests for `_safe_path` and mandate check
5. Write component test mocking Bedrock API responses

#### Files to Create/Modify

- `agents/dependency-update/app/dependencyUpdate/fix_agent.py` - LLM tools + agent setup
- `agents/dependency-update/tests/unit/test_safe_path.py` - Path safety tests
- `agents/dependency-update/tests/unit/test_mandate_check.py` - Mandate violation tests
- `agents/dependency-update/tests/component/test_fix_agent.py` - Agent with mocked Bedrock

#### Definition of Done Checklist

- [ ] Path escape tests passing (multiple traversal vectors)
- [ ] Mandate violation detection tested with real package.json diffs
- [ ] Fix loop respects budget
- [ ] `max_fix_attempts=0` produces zero Bedrock calls
- [ ] PR created and merged

---

### Story S-007: Pull Request Creation and PR Body Builder

**Priority:** High
**Estimated Size:** M
**Dependencies:** S-005

#### User Story

As an operator,
I want the agent to open a well-structured pull request with security diff, package changes, and validation results,
So that I can review the update in one screenful without reconstructing the diff myself.

#### Context

The PR body is the agent's primary human interface (PRD §11). It must contain: security summary, closed advisories, major_required section, unknown section, non-semver section, package changes, validation results, and the AI warning. The `--body-file` requirement comes from the repo's git invariants. Idempotency (D21) prevents duplicate PRs.

#### Acceptance Criteria

- [ ] Branch name: `deps/update-YYYYMMDD-HHMMSS` (req 53)
- [ ] Commit message: `chore(deps): automated dependency update` (req 54)
- [ ] Never pushes to default branch (req 55)
- [ ] Idempotency: checks for existing `deps/update-*` PR before creating (req 56)
- [ ] Existing PR → `succeeded / not_applicable`, records URL as artifact (req 56)
- [ ] PR body passed via `--body-file`, never inline (req 57)
- [ ] PR body contains security summary table (req 57)
- [ ] PR body contains closed advisories table (req 57)
- [ ] PR body contains `major_required` section when applicable (req 57)
- [ ] PR body contains `unknown` section when applicable (req 57)
- [ ] PR body contains non-semver section when applicable (req 57)
- [ ] PR body contains package changes table, capped at 30 rows (req 57)
- [ ] PR body contains validation results table (passed/failed/skipped per check) (req 57)
- [ ] PR body contains AI warning when `llm_used=true` (req 57)
- [ ] PR recorded as `run_artifacts` row of type `pull_request` (req 58)
- [ ] Token refresh before push if >45min elapsed (req 20)
- [ ] Token supplied via ephemeral credential helper, not in remote URL (req 18)
- [ ] Token scrubbed from all error messages on push failure

#### Business Rules

- PR opened BEFORE MAJOR_UPDATE_REQUIRED terminates the run (req 43, D25)
- `--body-file` always, never inline (git invariant)
- Conventional Commits commit message (git invariant)
- Never merge — only open

#### Technical Notes

- Module: `pull_request.py` (spec §8.9)
- Uses `gh pr list --json` for idempotency check, `gh pr create --body-file` for creation
- `GH_TOKEN` supplied per-call as env var
- Credential helper pattern from the reference implementation for `git push`

#### Testing Requirements

- **Unit Tests:** `test_pr_body.py` — PR body builder with all section combinations:
  - All sections present (full run)
  - No major_required, no unknown → those sections omitted
  - No LLM used → AI warning omitted
  - 35 packages → capped at 30 + "N more" note
  - Empty advisories → "No advisories closed" text
- **Component Tests:** `test_pr_creation.py` — mock `gh` CLI and `git` commands:
  - Happy path: branch, commit, push, PR
  - Existing PR → short-circuit
  - Push failure → token scrubbed from error
- **Execution Commands:** `pytest -m "unit or component" tests/unit/test_pr_body.py tests/component/test_pr_creation.py`

#### Implementation Steps

1. Implement `pull_request.py`: `build_pr_body()`, `create_pr()`, `existing_pr()`, `_push_with_credential_helper()`
2. Implement each PR body section as a helper function (spec §8.9)
3. Wire into main.py's `open_pr` step
4. Write unit tests for body builder
5. Write component tests mocking git/gh CLI

#### Files to Create/Modify

- `agents/dependency-update/app/dependencyUpdate/pull_request.py` - PR logic + body builder
- `agents/dependency-update/tests/unit/test_pr_body.py` - Body builder tests
- `agents/dependency-update/tests/component/test_pr_creation.py` - PR creation with mocked CLI

#### Definition of Done Checklist

- [ ] PR body builder tested with all section combinations
- [ ] Idempotency check verified
- [ ] Token never appears in test output
- [ ] `--body-file` used, never inline
- [ ] PR created and merged

---

### Story S-008: Seed Update, Deployment, and E2E Validation

**Priority:** Critical
**Estimated Size:** M
**Dependencies:** S-005, S-006, S-007

#### User Story

As an operator,
I want the agent deployed to AgentCore and the seed SQL updated,
So that I can invoke the agent from the AWS CLI against a real repository and verify the control plane end-to-end.

#### Context

This is the integration story. It deploys the agent, updates `002_seed.sql` with the resulting `runtime_arn` and the `params_schema`, then runs real invocations to verify acceptance criteria from the PRD. Satisfies parent PRD Phase 1 acceptance criterion #2.

#### Acceptance Criteria

- [ ] `agentcore deploy` succeeds; `agentcore status` reports runtime ready (AC #2)
- [ ] `002_seed.sql` updated with `runtime_arn`, `params_schema`, `max_runtime_seconds=3600`, `grace_seconds=120`, `start_timeout_seconds=300` (req 64)
- [ ] `agentcore invoke` with `fix_mode=audit_only` on a clean repo → `succeeded / no_vulnerabilities` (AC #3)
- [ ] Lifecycle written to Supabase: `runs` row transitions, `run_steps` populated, `run_events` present
- [ ] `audit_report` artifact exists in `run_artifacts`
- [ ] `agentcore invoke` with `fix_mode=llm_fix` on a repo with available updates → PR opened (AC #12)
- [ ] Second invoke while PR open → `succeeded / not_applicable` (AC #19)
- [ ] Invalid payload → `failed / INVALID_PARAMS` immediately (AC #31)
- [ ] `metrics` field populated with `llm_used`, `fix_attempts`, counts
- [ ] Agent README documents the `max_runtime_seconds` ↔ `maxLifetime` coupling

#### Business Rules

- `agents.max_runtime_seconds` must equal `agentcore.json` `maxLifetime` (req 65)
- Seed is idempotent (ON CONFLICT)

#### Technical Notes

- Uses `agentcore deploy -y` for non-interactive deployment
- After deploy, run `agentcore status` to get the runtime ARN
- Seed SQL uses `ON CONFLICT (slug) DO UPDATE`
- E2E tests run against real infrastructure — not CI-gated, manually triggered

#### Testing Requirements

- **E2E Tests:** Manual invocations via `agentcore invoke`:
  1. Clean audit repo → audit_only → verify Supabase writes
  2. Repo with available updates → llm_fix → verify PR opened
  3. Double invoke → verify idempotency
  4. Bad payload → verify fast-fail
- **Verification:** Query Supabase directly to confirm runs/steps/events/artifacts
- **Execution Commands:** `cd agents/dependency-update && agentcore deploy -y && agentcore status`

#### Implementation Steps

1. Run `agentcore deploy -y` from `agents/dependency-update/`
2. Record `runtime_arn` from `agentcore status`
3. Update `docs/reference/002_seed.sql` with the new agent row
4. Apply seed to Supabase
5. Run E2E invocations and verify results
6. Document results in the PR description

#### Files to Create/Modify

- `docs/reference/002_seed.sql` - Updated agent row
- `agents/dependency-update/README.md` - Deployment docs, coupling notes

#### Definition of Done Checklist

- [ ] `agentcore status` shows runtime ready
- [ ] Seed applied to Supabase
- [ ] At least one successful real invocation with lifecycle in Supabase
- [ ] PR created and merged

---

## Coverage Validation

### Summary

- **Total PRD Requirements:** 65
- **Total User Stories:** 8
- **Coverage:** 100%
- **Status:** Complete

### Requirement Mapping

| PRD Req Range | Story ID(s) | Status |
|---|---|---|
| 1-7 (Project structure) | S-001 | Covered |
| 8-13 (Invocation contract) | S-005 | Covered |
| 14-20 (Credentials) | S-002 | Covered |
| 21-24 (Toolchain) | S-003 | Covered |
| 25-31 (Audit, update) | S-004, S-005 | Covered |
| 32-35 (Version eligibility) | S-004 | Covered |
| 36-43 (Advisory classification) | S-004, S-005 | Covered |
| 44-52 (LLM escape hatch) | S-006 | Covered |
| 53-58 (Pull request) | S-007 | Covered |
| 59-63 (Reporting) | S-005 | Covered |
| 64-65 (Seed) | S-008 | Covered |

### Non-Goals Validation

- [x] Major-version bumps — NOT in any story (agent detects and reports, never performs)
- [x] Python/pip support — NOT in any story
- [x] Yarn — NOT in any story
- [x] Merging PRs — NOT in any story
- [x] Scheduled invocation — NOT in any story
- [x] Cancellation — NOT in any story
- [x] Cross-repo fan-out — NOT in any story
- [x] Monorepo workspace filtering — NOT in any story
- [x] Phase 2 panel UI — NOT in any story (aware of DESIGN.md but not implementing it)
