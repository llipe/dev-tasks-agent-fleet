# Compliance Test Plan — Dependency Update Agent

## Changelog

| Version | Date       | Summary         | Author   |
| ------- | ---------- | --------------- | -------- |
| 1.0     | 2026-08-26 | Initial version. Derived from PRD v1.2 (65 requirements, 36 acceptance criteria) and spec v1.0. Covers E2E scenarios (36), contract tests (12), edge cases (28), and randomized tactics (6). | verifier |

---

## 1. Source Input Summary

| Field | Value |
|---|---|
| Mode | Design |
| Repository | `llipe/dev-tasks-agent-fleet` |
| PRD | `docs/requirements/prd-dependency-update-agent.md` v1.2 |
| Spec | `workstream/specification-prd-dependency-update-agent.md` v1.0 |
| Stories | `workstream/user-stories-prd-dependency-update-agent.md` (S-001 through S-008) |
| GitHub Issues | #70–#77 |

---

## 2. Acceptance Criteria Extraction

| AC ID | Description | PRD §13 # |
|-------|-------------|-----------|
| AC-1 | Project scaffolding: layout exists, `agentcore validate` passes | 1 |
| AC-2 | Deploys: `agentcore deploy` succeeds, status ready, seed has runtime_arn | 2 |
| AC-3 | audit_only clean: succeeded/no_vulnerabilities, audit_report artifact, no PR | 3 |
| AC-4 | audit_only findings + fail_on: failed/needs_review/AUDIT_FINDINGS | 4 |
| AC-5 | audit_only findings + !fail_on: succeeded/needs_review | 5 |
| AC-6 | Major-only advisory in audit_only + fail_on: failed/MAJOR_UPDATE_REQUIRED + error events + artifact | 6 |
| AC-7 | fail_on_findings=false wins over major_required: succeeded + events still present | 7 |
| AC-8 | Unparseable patched range → unknown, not major_required | 8 |
| AC-9 | Version eligibility table honored: 4 rows + anti-loophole | 9 |
| AC-10 | Non-semver change accepted and reported (warn + PR section) | 10 |
| AC-11 | Non-semver not a loophole: semver target with higher major stays ineligible | 11 |
| AC-12 | llm_fix happy path: PR opened, zero tokens, metrics correct | 12 |
| AC-13 | Major-only + work to land: PR opened first, then failed/MAJOR_UPDATE_REQUIRED | 13 |
| AC-14 | Major-only with nothing to land: failed/MAJOR_UPDATE_REQUIRED, no PR | 14 |
| AC-15 | PR body names the major gap (prominent section) | 15 |
| AC-16 | Precedence: VALIDATION_FAILING outranks MAJOR_UPDATE_REQUIRED | 16 |
| AC-17 | PR body completeness (all sections of req 57) | 17 |
| AC-18 | No-change no-op: succeeded/no_vulnerabilities, no branch/PR | 18 |
| AC-19 | Idempotency: second invoke → succeeded/not_applicable, no second PR | 19 |
| AC-20 | LLM fires: llm_fix step reached, llm_used=true, AI warning in PR | 20 |
| AC-21 | LLM budget: max_fix_attempts=1, exactly 1 attempt, failed/VALIDATION_FAILING | 21 |
| AC-22 | LLM disabled: max_fix_attempts=0, zero Bedrock calls | 22 |
| AC-23 | Mandate violation: widened range detected, failed/MANDATE_VIOLATION, no PR | 23 |
| AC-24 | Test script required: failed/NO_TEST_SCRIPT before update | 24 |
| AC-25 | Optional scripts: warn events, skipped in PR, run completes | 25 |
| AC-26 | npm parity: full path using npm commands | 26 |
| AC-27 | Unknown toolchain: failed/NO_PACKAGE_MANAGER | 27 |
| AC-28 | GitHub App auth: installation token from DB row, no PAT | 28 |
| AC-29 | Unknown org: failed/NO_INSTALLATION | 29 |
| AC-30 | No credential on disk or in logs | 30 |
| AC-31 | Invalid payload: failed/INVALID_PARAMS without clone | 31 |
| AC-32 | Path escape refused by fix agent tools | 32 |
| AC-33 | Step stream complete: 9 steps in order, each terminal | 33 |
| AC-34 | Reporting outage survivable: pipeline completes, stderr has payloads | 34 |
| AC-35 | Unhandled failure: failed + traceback, step closed | 35 |
| AC-36 | Reaper interlock: max_runtime_seconds = maxLifetime, hung run reaped | 36 |

---

## 3. E2E Black-Box Scenarios

### SC-1: Audit-only on clean repository

| Field | Value |
|---|---|
| **AC(s)** | AC-3 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | Repository exists with no audit vulnerabilities; `github_installations` row configured |
| **Steps** | 1. Invoke agent with `fix_mode=audit_only` on the clean repo. 2. Wait for terminal status. |
| **Expected Result** | `status=succeeded`, `outcome=no_vulnerabilities`, `audit_report` artifact exists, no branch created, no PR opened, `metrics.llm_used=false` |
| **Pass Criteria** | Supabase `runs` row matches expected fields; `run_artifacts` has type `audit_report`; no `deps/update-*` branch in repo |

### SC-2: Audit-only with in-range findings, fail_on_findings=true

| Field | Value |
|---|---|
| **AC(s)** | AC-4 |
| **Type** | negative-path |
| **Severity** | critical |
| **Preconditions** | Repository has known in-range-fixable vulnerabilities |
| **Steps** | 1. Invoke with `fix_mode=audit_only`, `fail_on_findings=true`. |
| **Expected Result** | `status=failed`, `outcome=needs_review`, `error_code=AUDIT_FINDINGS`, no PR |
| **Pass Criteria** | Run terminates failed; audit_report artifact present; no branch in repo |

### SC-3: Audit-only with findings, fail_on_findings=false

| Field | Value |
|---|---|
| **AC(s)** | AC-5 |
| **Type** | happy-path |
| **Severity** | major |
| **Preconditions** | Same repo as SC-2 |
| **Steps** | 1. Invoke with `fix_mode=audit_only`, `fail_on_findings=false`. |
| **Expected Result** | `status=succeeded`, `outcome=needs_review` |
| **Pass Criteria** | Run succeeded despite findings; audit_report artifact present |

### SC-4: Audit-only with major-only advisory, fail_on=true

| Field | Value |
|---|---|
| **AC(s)** | AC-6 |
| **Type** | negative-path |
| **Severity** | critical |
| **Preconditions** | Repository pinned to range where only a higher major carries the patch |
| **Steps** | 1. Invoke with `fix_mode=audit_only`, `fail_on_findings=true`. |
| **Expected Result** | `status=failed`, `outcome=needs_review`, `error_code=MAJOR_UPDATE_REQUIRED`. Error-level events per package (6 fields each). audit_report artifact groups under `major_required` |
| **Pass Criteria** | error_code matches; run_events with level=error exist for affected package; audit_report metadata has `major_required` group |

### SC-5: fail_on_findings=false overrides MAJOR_UPDATE_REQUIRED

| Field | Value |
|---|---|
| **AC(s)** | AC-7 |
| **Type** | happy-path |
| **Severity** | major |
| **Preconditions** | Same repo as SC-4 |
| **Steps** | 1. Invoke with `fix_mode=audit_only`, `fail_on_findings=false`. |
| **Expected Result** | `status=succeeded`, `outcome=needs_review`. Error events still present. |
| **Pass Criteria** | Run succeeded; error events exist (information not lost); no PR |

### SC-6: Unparseable patched range → unknown

| Field | Value |
|---|---|
| **AC(s)** | AC-8 |
| **Type** | negative-path |
| **Severity** | major |
| **Preconditions** | Advisory whose patched_versions field cannot be parsed |
| **Steps** | 1. Invoke audit_only on repo with that advisory. |
| **Expected Result** | Advisory classified `unknown` in artifact; does NOT produce MAJOR_UPDATE_REQUIRED |
| **Pass Criteria** | audit_report metadata shows advisory in `unknown` group; run does not have error_code=MAJOR_UPDATE_REQUIRED (given no other major advisory) |

### SC-7: llm_fix happy path — zero tokens

| Field | Value |
|---|---|
| **AC(s)** | AC-12 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | Repository with available patch/minor updates; test suite passes after update |
| **Steps** | 1. Invoke with `fix_mode=llm_fix`. 2. Wait for terminal status. |
| **Expected Result** | One PR on `deps/update-*` branch; `status=succeeded`; `metrics.llm_used=false`; `metrics.fix_attempts=0`; no Bedrock invocation |
| **Pass Criteria** | PR exists in repo; runs row has correct status/outcome; metrics fields match; no bedrock:InvokeModel in CloudTrail for this run |

### SC-8: llm_fix no-change no-op

| Field | Value |
|---|---|
| **AC(s)** | AC-18 |
| **Type** | happy-path |
| **Severity** | major |
| **Preconditions** | Repository fully up-to-date, no available updates |
| **Steps** | 1. Invoke with `fix_mode=llm_fix`. |
| **Expected Result** | `status=succeeded`, `outcome=no_vulnerabilities`, no branch, no PR |
| **Pass Criteria** | No `deps/update-*` branch in repo; runs row shows no_vulnerabilities |

### SC-9: Idempotency — second invoke while PR open

| Field | Value |
|---|---|
| **AC(s)** | AC-19 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | Prior successful run left an open `deps/update-*` PR |
| **Steps** | 1. Invoke again with `fix_mode=llm_fix` on same repo. |
| **Expected Result** | `status=succeeded`, `outcome=not_applicable`, existing PR URL as artifact, no second branch/PR |
| **Pass Criteria** | Only one `deps/update-*` PR exists; artifact points to existing URL |

### SC-10: LLM escape hatch fires and succeeds

| Field | Value |
|---|---|
| **AC(s)** | AC-20 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | Repository with a dep bump that breaks a test assertion (seeded fixture) |
| **Steps** | 1. Invoke with `fix_mode=llm_fix`, `max_fix_attempts=3`. |
| **Expected Result** | Run reaches `llm_fix` step; `metrics.llm_used=true`; PR body contains AI modification warning; PR opened |
| **Pass Criteria** | run_steps includes key=`llm_fix`; metrics.fix_attempts≥1; PR body has "AI agent modified source files" text |

### SC-11: LLM budget exhausted

| Field | Value |
|---|---|
| **AC(s)** | AC-21 |
| **Type** | negative-path |
| **Severity** | major |
| **Preconditions** | Unfixable breakage (no fix within 1 attempt) |
| **Steps** | 1. Invoke with `max_fix_attempts=1`. |
| **Expected Result** | `status=failed`, `outcome=needs_review`, `error_code=VALIDATION_FAILING`, no PR, test output tail as artifact |
| **Pass Criteria** | Exactly 1 Bedrock invocation; no PR; artifact of type `file` with test output |

### SC-12: LLM disabled (max_fix_attempts=0)

| Field | Value |
|---|---|
| **AC(s)** | AC-22 |
| **Type** | negative-path |
| **Severity** | major |
| **Preconditions** | Failing test suite after update |
| **Steps** | 1. Invoke with `max_fix_attempts=0`. |
| **Expected Result** | `status=failed`, no Bedrock calls, no PR |
| **Pass Criteria** | Zero bedrock:InvokeModel calls; metrics.llm_used=false |

### SC-13: Major-only advisory in fix mode with work to land

| Field | Value |
|---|---|
| **AC(s)** | AC-13 |
| **Type** | negative-path |
| **Severity** | critical |
| **Preconditions** | Repo with both an in-range advisory (fixable) and a major-only advisory |
| **Steps** | 1. Invoke with `fix_mode=llm_fix`. |
| **Expected Result** | PR opened (closing the in-range advisory), then run terminates `failed/needs_review/MAJOR_UPDATE_REQUIRED`. PR artifact exists with live URL. |
| **Pass Criteria** | PR exists and is valid; run status=failed; error_code=MAJOR_UPDATE_REQUIRED; pull_request artifact present |

### SC-14: Major-only advisory, nothing to land

| Field | Value |
|---|---|
| **AC(s)** | AC-14 |
| **Type** | negative-path |
| **Severity** | major |
| **Preconditions** | Only advisory is major-only; no other updates available |
| **Steps** | 1. Invoke with `fix_mode=llm_fix`. |
| **Expected Result** | `status=failed`, `error_code=MAJOR_UPDATE_REQUIRED`, no branch, no PR |
| **Pass Criteria** | No branch or PR in repo; runs row matches |

### SC-15: Precedence — VALIDATION_FAILING outranks MAJOR_UPDATE_REQUIRED

| Field | Value |
|---|---|
| **AC(s)** | AC-16 |
| **Type** | negative-path |
| **Severity** | major |
| **Preconditions** | Repo with major-only advisory AND unfixable test breakage |
| **Steps** | 1. Invoke with `fix_mode=llm_fix`, `max_fix_attempts=1`. |
| **Expected Result** | `error_code=VALIDATION_FAILING`, NOT `MAJOR_UPDATE_REQUIRED`, no PR |
| **Pass Criteria** | error_code is VALIDATION_FAILING |

### SC-16: Invalid payload — fast fail

| Field | Value |
|---|---|
| **AC(s)** | AC-31 |
| **Type** | negative-path |
| **Severity** | critical |
| **Preconditions** | Agent running |
| **Steps** | 1. Invoke with payload missing `run_id`. 2. Invoke with `fix_mode="invalid_value"`. |
| **Expected Result** | `status=failed`, `error_code=INVALID_PARAMS`, no clone occurs |
| **Pass Criteria** | No git clone in logs; fast termination; correct error_code |

### SC-17: Unknown org — no github_installations row

| Field | Value |
|---|---|
| **AC(s)** | AC-29 |
| **Type** | negative-path |
| **Severity** | major |
| **Preconditions** | No `github_installations` row for `nonexistent-org` |
| **Steps** | 1. Invoke with `repository_org=nonexistent-org`. |
| **Expected Result** | `status=failed`, `error_code=NO_INSTALLATION` |
| **Pass Criteria** | error_code matches; no clone attempted |

### SC-18: No package manager detected

| Field | Value |
|---|---|
| **AC(s)** | AC-27 |
| **Type** | negative-path |
| **Severity** | major |
| **Preconditions** | Repository with no pnpm-lock.yaml, no package-lock.json, no packageManager field |
| **Steps** | 1. Invoke with `fix_mode=audit_only`. |
| **Expected Result** | `status=failed`, `error_code=NO_PACKAGE_MANAGER`, message names what was searched |
| **Pass Criteria** | error_code and error_message match |

### SC-19: No test script

| Field | Value |
|---|---|
| **AC(s)** | AC-24 |
| **Type** | negative-path |
| **Severity** | major |
| **Preconditions** | Repository has lockfile but no `test` in package.json scripts |
| **Steps** | 1. Invoke with `fix_mode=llm_fix`. |
| **Expected Result** | `status=failed`, `error_code=NO_TEST_SCRIPT`, before any update |
| **Pass Criteria** | error_code matches; working tree unmodified |

### SC-20: Optional scripts absent — run continues

| Field | Value |
|---|---|
| **AC(s)** | AC-25 |
| **Type** | happy-path |
| **Severity** | minor |
| **Preconditions** | Repo has `test` but no `lint`, `format`, `typecheck` |
| **Steps** | 1. Invoke with `fix_mode=llm_fix`. |
| **Expected Result** | Run completes; warn events for each absent script; PR body marks them `skipped` |
| **Pass Criteria** | 3 warn-level events naming absent scripts; PR body has "skipped" for each |

### SC-21: npm parity — full path

| Field | Value |
|---|---|
| **AC(s)** | AC-26 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | npm-only repository (package-lock.json, no pnpm-lock.yaml) with available updates |
| **Steps** | 1. Invoke with `fix_mode=llm_fix`. |
| **Expected Result** | Full pipeline completes using npm commands; PR opened |
| **Pass Criteria** | run_events show npm commands (not pnpm); PR exists |

### SC-22: Credential scrubbing — no token in logs

| Field | Value |
|---|---|
| **AC(s)** | AC-30 |
| **Type** | abuse-case |
| **Severity** | critical |
| **Preconditions** | Successful run (any mode) |
| **Steps** | 1. Complete a run. 2. Query all run_events for the run. 3. Check `.git/config` in workspace (if accessible). 4. Check return payload. |
| **Expected Result** | No event message, artifact, or return value contains the installation token or PEM |
| **Pass Criteria** | grep for token substring across all events returns 0 matches; git config has no token |

### SC-23: Credential scrubbing under push failure

| Field | Value |
|---|---|
| **AC(s)** | AC-30 |
| **Type** | abuse-case |
| **Severity** | critical |
| **Preconditions** | Simulated git push failure (e.g., revoked token mid-run) |
| **Steps** | 1. Invoke in a way that push fails. 2. Check error_message and run_events. |
| **Expected Result** | Error messages contain `***` not the actual token |
| **Pass Criteria** | Token not present in any logged string |

### SC-24: Path escape — fix agent tools

| Field | Value |
|---|---|
| **AC(s)** | AC-32 |
| **Type** | abuse-case |
| **Severity** | critical |
| **Preconditions** | Fix agent tools available (validation failed) |
| **Steps** | 1. Call `read_file("../../../etc/passwd")` directly (unit test). 2. Call `write_file("../../outside.txt", "pwned")`. |
| **Expected Result** | ValueError raised; no file read or written outside workspace |
| **Pass Criteria** | Exception raised for every traversal attempt |

### SC-25: Mandate violation — fix agent widens range

| Field | Value |
|---|---|
| **AC(s)** | AC-23 |
| **Type** | negative-path |
| **Severity** | critical |
| **Preconditions** | Fix agent modifies package.json to widen a range (simulated) |
| **Steps** | 1. Pre-fix: record package.json. 2. Simulate fix that changes `^1.0.0` to `^2.0.0`. 3. Run mandate check. |
| **Expected Result** | `MANDATE_VIOLATION` detected; no PR opened |
| **Pass Criteria** | MandateViolationError raised; run terminates failed |

### SC-26: Step stream completeness

| Field | Value |
|---|---|
| **AC(s)** | AC-33 |
| **Type** | happy-path |
| **Severity** | major |
| **Preconditions** | Completed llm_fix run (any outcome) |
| **Steps** | 1. Query run_steps for the run, ordered by seq. |
| **Expected Result** | Steps match req 61 keys in order; each has terminal status; events associated to correct step_id |
| **Pass Criteria** | Exact key sequence matches; no step left `running` |

### SC-27: Reporting outage — pipeline survives

| Field | Value |
|---|---|
| **AC(s)** | AC-34 |
| **Type** | negative-path |
| **Severity** | major |
| **Preconditions** | PostgREST unreachable (simulated via network block or wrong URL) |
| **Steps** | 1. Invoke with SUPABASE_URL pointing to unreachable host. |
| **Expected Result** | Pipeline completes; PR opened; payloads appear on stderr (→ CloudWatch) |
| **Pass Criteria** | Return payload has status; PR exists; stderr contains JSON payloads |

### SC-28: Unhandled exception — graceful degradation

| Field | Value |
|---|---|
| **AC(s)** | AC-35 |
| **Type** | negative-path |
| **Severity** | major |
| **Preconditions** | Injected exception (e.g., division by zero in a step) |
| **Steps** | 1. Trigger unhandled exception mid-pipeline. |
| **Expected Result** | `status=failed`, traceback in events, open step closed as failed |
| **Pass Criteria** | runs.status=failed; run_events has traceback; open step status=failed |

### SC-29: GitHub App auth — no PAT

| Field | Value |
|---|---|
| **AC(s)** | AC-28 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | github_installations row configured; no PAT in env |
| **Steps** | 1. Complete a successful run. 2. Verify auth flow in events. |
| **Expected Result** | Events show "installation token" flow; no `GITHUB_TOKEN` or PAT env var used |
| **Pass Criteria** | No PAT in configuration; auth via JWT→installation token |

### SC-30: Token refresh before push (>45min elapsed)

| Field | Value |
|---|---|
| **AC(s)** | AC-12 (implied by req 20) |
| **Type** | happy-path |
| **Severity** | minor |
| **Preconditions** | Simulated long run where >45min passes (mock time) |
| **Steps** | 1. Set token issued_at to 46 minutes ago. 2. Attempt push. |
| **Expected Result** | Token is re-minted before push |
| **Pass Criteria** | `mint_installation_token` called a second time; push uses fresh token |

### SC-31: Version eligibility — semver cases

| Field | Value |
|---|---|
| **AC(s)** | AC-9 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | Unit test environment |
| **Steps** | 1. `is_eligible("1.2.3", "1.3.0")` 2. `is_eligible("1.2.3", "2.0.0")` 3. `is_eligible("0.1.2", "0.2.0")` 4. `is_eligible("abc", "def")` |
| **Expected Result** | 1→eligible, 2→ineligible, 3→ineligible, 4→eligible |
| **Pass Criteria** | All 4 assertions pass |

### SC-32: Non-semver accepted and reported

| Field | Value |
|---|---|
| **AC(s)** | AC-10 |
| **Type** | happy-path |
| **Severity** | major |
| **Preconditions** | Dependency with non-semver resolved version changes |
| **Steps** | 1. Run pipeline. 2. Check events and PR body. |
| **Expected Result** | Change applied; warn event names package; PR body has non-semver section |
| **Pass Criteria** | warn event exists; PR body section present |

### SC-33: Non-semver not a loophole

| Field | Value |
|---|---|
| **AC(s)** | AC-11 |
| **Type** | negative-path |
| **Severity** | major |
| **Preconditions** | Installed non-semver, target semver with higher major |
| **Steps** | 1. `is_eligible("abc123", "2.0.0")` where context shows installed was previously `1.x` |
| **Expected Result** | Ineligible — target semver with major increase wins |
| **Pass Criteria** | is_eligible returns False with reason "major_increase" |

### SC-34: PR body completeness

| Field | Value |
|---|---|
| **AC(s)** | AC-17 |
| **Type** | happy-path |
| **Severity** | major |
| **Preconditions** | Run with all conditions triggering all PR sections (fixed advisories, major_required remaining, non-semver, LLM used) |
| **Steps** | 1. Complete run. 2. Read PR body. |
| **Expected Result** | All 7 sections present (security summary, fixed advisories, major_required, unknown, non-semver, packages, validation, AI warning) |
| **Pass Criteria** | Each section header found in PR body markdown |

### SC-35: PR body names the major gap

| Field | Value |
|---|---|
| **AC(s)** | AC-15 |
| **Type** | happy-path |
| **Severity** | major |
| **Preconditions** | Run with a major_required advisory remaining AND a PR opened |
| **Steps** | 1. Read PR body's major_required section. |
| **Expected Result** | Lists package, resolved version, declared range, minimum closing version, severity, advisory ref + explicit statement |
| **Pass Criteria** | All 6 data fields present; explicit "does not resolve" statement present |

### SC-36: Reaper interlock

| Field | Value |
|---|---|
| **AC(s)** | AC-36 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | `agents.max_runtime_seconds=3600` matches `agentcore.json maxLifetime=3600`; agent artificially hung |
| **Steps** | 1. Start run that hangs indefinitely. 2. Wait for `max_runtime_seconds + grace_seconds + 60s`. 3. Query run status. |
| **Expected Result** | Run marked `timed_out` by reaper |
| **Pass Criteria** | runs.status=timed_out; run_events has reaper event |

---

## 4. Contract Test Scenarios

### CT-1: Valid invocation payload accepted

| Field | Value |
|---|---|
| **AC(s)** | AC-31, AC-3 |
| **Contract type** | consumer-driven |
| **Boundary** | AgentCore `/invocations` endpoint |
| **Direction** | request |
| **Input** | `{"run_id":"uuid","repository_org":"llipe","repository_name":"repo","params":{"fix_mode":"audit_only","fail_on_findings":true,"max_fix_attempts":3}}` |
| **Expected Result** | Agent processes payload successfully |
| **Pass Criteria** | No INVALID_PARAMS; run proceeds to resolve_credentials step |

### CT-2: Payload wrapped in `prompt` key

| Field | Value |
|---|---|
| **AC(s)** | AC-31 (req 9) |
| **Contract type** | consumer-driven |
| **Boundary** | AgentCore `/invocations` |
| **Direction** | request |
| **Input** | `{"prompt":"{\"run_id\":\"uuid\",\"repository_org\":\"llipe\",\"repository_name\":\"repo\",\"params\":{}}"}` |
| **Expected Result** | Unwrapped and processed identically to CT-1 |
| **Pass Criteria** | No INVALID_PARAMS; JSON string inside prompt parsed correctly |

### CT-3: Missing required field — run_id

| Field | Value |
|---|---|
| **AC(s)** | AC-31 |
| **Contract type** | consumer-driven |
| **Boundary** | AgentCore `/invocations` |
| **Direction** | request |
| **Input** | `{"repository_org":"llipe","repository_name":"repo"}` |
| **Expected Result** | `INVALID_PARAMS` immediately |
| **Pass Criteria** | error_code=INVALID_PARAMS; no side effects |

### CT-4: Type mismatch — max_fix_attempts as string

| Field | Value |
|---|---|
| **AC(s)** | AC-31 |
| **Contract type** | consumer-driven |
| **Boundary** | AgentCore `/invocations` |
| **Direction** | request |
| **Input** | `{"run_id":"uuid","repository_org":"llipe","repository_name":"repo","params":{"max_fix_attempts":"three"}}` |
| **Expected Result** | `INVALID_PARAMS` |
| **Pass Criteria** | error_code=INVALID_PARAMS |

### CT-5: max_fix_attempts out of range (6)

| Field | Value |
|---|---|
| **AC(s)** | AC-31 |
| **Contract type** | consumer-driven |
| **Boundary** | AgentCore `/invocations` |
| **Direction** | request |
| **Input** | `{"run_id":"uuid","repository_org":"llipe","repository_name":"repo","params":{"max_fix_attempts":6}}` |
| **Expected Result** | `INVALID_PARAMS` (constrained 0..5) |
| **Pass Criteria** | error_code=INVALID_PARAMS |

### CT-6: Unknown fix_mode value

| Field | Value |
|---|---|
| **AC(s)** | AC-31 |
| **Contract type** | consumer-driven |
| **Boundary** | AgentCore `/invocations` |
| **Direction** | request |
| **Input** | `{"run_id":"uuid","repository_org":"llipe","repository_name":"repo","params":{"fix_mode":"full_auto"}}` |
| **Expected Result** | `INVALID_PARAMS` |
| **Pass Criteria** | error_code=INVALID_PARAMS |

### CT-7: PostgREST contract — github_installations query

| Field | Value |
|---|---|
| **AC(s)** | AC-28, AC-29 |
| **Contract type** | consumer-driven |
| **Boundary** | `GET /rest/v1/github_installations?github_org_slug=eq.{org}&is_enabled=eq.true` |
| **Direction** | response |
| **Input** | Valid org slug |
| **Expected Result** | Response contains `app_id` (integer), `installation_id` (integer), `private_key_secret_arn` (string) |
| **Pass Criteria** | All three fields present and correctly typed |

### CT-8: PostgREST contract — run update

| Field | Value |
|---|---|
| **AC(s)** | AC-33 |
| **Contract type** | provider-driven |
| **Boundary** | `PATCH /rest/v1/runs?id=eq.{run_id}` |
| **Direction** | request |
| **Input** | `{"status":"running","started_at":"2026-08-26T14:02:00Z"}` |
| **Expected Result** | HTTP 204 (Prefer: return=minimal) |
| **Pass Criteria** | Status 2xx; row updated in database |

### CT-9: PostgREST contract — run_events batch insert

| Field | Value |
|---|---|
| **AC(s)** | AC-33 |
| **Contract type** | provider-driven |
| **Boundary** | `POST /rest/v1/run_events` |
| **Direction** | request |
| **Input** | Array of event objects with `run_id`, `seq`, `ts`, `level`, `message` |
| **Expected Result** | HTTP 201 |
| **Pass Criteria** | Events inserted; seq values preserved |

### CT-10: Return payload schema

| Field | Value |
|---|---|
| **AC(s)** | AC-3, AC-12 |
| **Contract type** | provider-driven |
| **Boundary** | Agent return value |
| **Direction** | response |
| **Input** | Successful run completion |
| **Expected Result** | JSON contains: status, outcome, error_code, pr_url, vulnerabilities_before, vulnerabilities_after, advisories_fixed, advisories_major_required, advisories_unknown, packages_changed, fix_attempts, llm_used |
| **Pass Criteria** | All 12 fields present with correct types |

### CT-11: Secrets Manager contract — SUPABASE_SERVICE_ROLE_KEY

| Field | Value |
|---|---|
| **AC(s)** | AC-28 |
| **Contract type** | consumer-driven |
| **Boundary** | `secretsmanager:GetSecretValue` |
| **Direction** | response |
| **Input** | SecretId = configured ID |
| **Expected Result** | `SecretString` is a plain string (the key), not JSON |
| **Pass Criteria** | Value usable directly as apikey header |

### CT-12: GitHub API contract — installation token exchange

| Field | Value |
|---|---|
| **AC(s)** | AC-28 |
| **Contract type** | consumer-driven |
| **Boundary** | `POST /app/installations/{id}/access_tokens` |
| **Direction** | response |
| **Input** | Valid RS256 JWT |
| **Expected Result** | `{"token":"ghs_...","expires_at":"..."}` |
| **Pass Criteria** | `token` field present and starts with expected prefix |

---

## 5. Edge-Case Catalog

### EC-1: Empty repository (no package.json)

| Field | Value |
|---|---|
| **AC(s)** | AC-27 |
| **Category** | Input Domain |
| **Input / Setup** | Repository exists but contains no package.json at root |
| **Expected Result** | `NO_PACKAGE_MANAGER` (or earlier error if package.json read fails) |
| **Risk if Missed** | Agent crashes with unhandled exception instead of clean error |

### EC-2: package.json with syntax error

| Field | Value |
|---|---|
| **AC(s)** | AC-27 |
| **Category** | Input Domain |
| **Input / Setup** | Malformed JSON in package.json |
| **Expected Result** | Clean failure with descriptive error, not a JSON parse traceback to the user |
| **Risk if Missed** | Internal traceback exposed; unclear error message |

### EC-3: Repository with both pnpm-lock.yaml and package-lock.json

| Field | Value |
|---|---|
| **AC(s)** | AC-26, AC-27 |
| **Category** | Input Domain |
| **Input / Setup** | Both lockfiles present |
| **Expected Result** | pnpm wins (precedence table: pnpm-lock.yaml before package-lock.json) |
| **Risk if Missed** | Wrong package manager used; lockfile corruption |

### EC-4: pnpm audit returns non-JSON output

| Field | Value |
|---|---|
| **AC(s)** | AC-3, AC-4 |
| **Category** | Failure Modes |
| **Input / Setup** | pnpm audit --json produces stderr warning mixed with JSON |
| **Expected Result** | Parser handles gracefully; falls back to `parse_failed` |
| **Risk if Missed** | Unhandled JSONDecodeError crashes the pipeline |

### EC-5: Installation token expires exactly at push time

| Field | Value |
|---|---|
| **AC(s)** | AC-12 (req 20) |
| **Category** | Timing & Concurrency |
| **Input / Setup** | Token issued 59 minutes ago; push takes >1 minute |
| **Expected Result** | Token refreshed at 45-min check before push; push succeeds |
| **Risk if Missed** | 401 from GitHub on push; validated work lost |

### EC-6: Concurrent invocations on same repo

| Field | Value |
|---|---|
| **AC(s)** | AC-19 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | Two invocations dispatched simultaneously for the same repo |
| **Expected Result** | One creates PR, the other finds it via idempotency check and returns not_applicable |
| **Risk if Missed** | Duplicate PRs; branch name collision |

### EC-7: Advisory with no CVE, no URL

| Field | Value |
|---|---|
| **AC(s)** | AC-6 |
| **Category** | Input Domain |
| **Input / Setup** | Advisory record with empty `cves` and empty `url` fields |
| **Expected Result** | Classified correctly; error event still emitted with available fields; no KeyError |
| **Risk if Missed** | Pipeline crashes on missing field access |

### EC-8: 0-vulnerability audit (clean) with available updates

| Field | Value |
|---|---|
| **AC(s)** | AC-12, AC-18 |
| **Category** | State Transitions |
| **Input / Setup** | Audit is clean (no advisories) but packages have minor updates available |
| **Expected Result** | In llm_fix mode: updates applied, PR opened with outcome=needs_review (packages moved, no advisory to close) |
| **Risk if Missed** | Confusion between "no vulnerabilities" and "no updates available" |

### EC-9: All advisories are `unknown` classification

| Field | Value |
|---|---|
| **AC(s)** | AC-8 |
| **Category** | Data Boundaries |
| **Input / Setup** | Multiple advisories, all with unparseable patched ranges |
| **Expected Result** | None triggers MAJOR_UPDATE_REQUIRED; all in `unknown` group; run can succeed |
| **Risk if Missed** | False MAJOR_UPDATE_REQUIRED from fallback logic |

### EC-10: pnpm version mismatch — lockfileVersion 5

| Field | Value |
|---|---|
| **AC(s)** | AC-26 |
| **Category** | Input Domain |
| **Input / Setup** | Old repo with lockfileVersion 5.x (pnpm 7 era) |
| **Expected Result** | Agent detects pnpm 7, installs it, proceeds normally |
| **Risk if Missed** | Frozen install fails; agent crashes |

### EC-11: git clone failure — repo doesn't exist

| Field | Value |
|---|---|
| **AC(s)** | AC-31 |
| **Category** | Failure Modes |
| **Input / Setup** | `repository_name` points to non-existent repo |
| **Expected Result** | `failed` with `error_code=CLONE_FAILED`, descriptive message, token scrubbed |
| **Risk if Missed** | Token leaked in git error output |

### EC-12: Secrets Manager unavailable at startup

| Field | Value |
|---|---|
| **AC(s)** | AC-28 |
| **Category** | Failure Modes |
| **Input / Setup** | Secrets Manager returns 500 or times out |
| **Expected Result** | Run fails with descriptive error at `resolve_credentials` step |
| **Risk if Missed** | Agent hangs or produces unclear error |

### EC-13: PostgREST returns 429 (rate limited)

| Field | Value |
|---|---|
| **AC(s)** | AC-34 |
| **Category** | Resource Exhaustion |
| **Input / Setup** | PostgREST responds 429 to event insert |
| **Expected Result** | SDK retries (429 is transient per the retry policy); if exhausted, payload to stderr |
| **Risk if Missed** | Events silently dropped without fallback |

### EC-14: run_events message exceeds 8KB

| Field | Value |
|---|---|
| **AC(s)** | AC-33 |
| **Category** | Data Boundaries |
| **Input / Setup** | Test output > 8KB flows into a log event |
| **Expected Result** | Truncated to 8KB with `…[truncado]` marker (per agent_reporter.py) |
| **Risk if Missed** | PostgREST rejects oversized row; event lost |

### EC-15: Fix agent produces empty file

| Field | Value |
|---|---|
| **AC(s)** | AC-20 |
| **Category** | Input Domain |
| **Input / Setup** | Fix agent calls write_file with empty content |
| **Expected Result** | File created with 0 bytes; no crash |
| **Risk if Missed** | Exception on empty write |

### EC-16: Fix agent path with spaces

| Field | Value |
|---|---|
| **AC(s)** | AC-32 |
| **Category** | Input Domain |
| **Input / Setup** | `read_file("src/my file.ts")` |
| **Expected Result** | Path resolved correctly; file read if it exists |
| **Risk if Missed** | Path splitting causes file-not-found or path traversal |

### EC-17: Repository with only devDependencies (no dependencies)

| Field | Value |
|---|---|
| **AC(s)** | AC-12 |
| **Category** | Data Boundaries |
| **Input / Setup** | package.json has no `dependencies` key, only `devDependencies` |
| **Expected Result** | Audit and update still work; snapshot captures devDependencies |
| **Risk if Missed** | KeyError on missing `dependencies`; incomplete snapshot |

### EC-18: npm audit JSON format differs from pnpm

| Field | Value |
|---|---|
| **AC(s)** | AC-26 |
| **Category** | Input Domain |
| **Input / Setup** | npm audit --json returns v2 format (different structure than pnpm) |
| **Expected Result** | Parser handles both formats correctly |
| **Risk if Missed** | Classification fails on npm repos; false unknown bucket |

### EC-19: Symlink in repository points outside

| Field | Value |
|---|---|
| **AC(s)** | AC-32 |
| **Category** | Auth & Permissions |
| **Input / Setup** | Repo contains symlink `src/link → /etc/passwd` |
| **Expected Result** | `_safe_path` resolves the real path and rejects it |
| **Risk if Missed** | Fix agent reads sensitive files outside workspace |

### EC-20: Multiple advisories for same package

| Field | Value |
|---|---|
| **AC(s)** | AC-6, AC-8 |
| **Category** | Data Boundaries |
| **Input / Setup** | Package has 3 advisories: one in_range, one major_required, one unknown |
| **Expected Result** | All three classified independently; major_required triggers the failure |
| **Risk if Missed** | Only first advisory processed; rest missed |

### EC-21: pnpm update produces lockfile config mismatch

| Field | Value |
|---|---|
| **AC(s)** | AC-12 |
| **Category** | State Transitions |
| **Input / Setup** | After `pnpm update`, lockfile has stale `pnpm.overrides` hash |
| **Expected Result** | `reconcile_lockfile()` runs `pnpm install --no-frozen-lockfile` to fix it |
| **Risk if Missed** | CI's `--frozen-lockfile` fails on the PR branch |

### EC-22: GitHub API returns 403 on token exchange

| Field | Value |
|---|---|
| **AC(s)** | AC-28 |
| **Category** | Failure Modes |
| **Input / Setup** | App not installed, or wrong installation_id |
| **Expected Result** | `failed` with `error_code=GITHUB_AUTH_FAILED`, descriptive message |
| **Risk if Missed** | Unclear 403 error; no guidance on fix |

### EC-23: Payload with extra unknown fields

| Field | Value |
|---|---|
| **AC(s)** | AC-31 |
| **Category** | Input Domain |
| **Input / Setup** | `{"run_id":"uuid","repository_org":"x","repository_name":"y","extra_field":true}` |
| **Expected Result** | Either rejected (strict) or ignored (tolerant) — per schema's additionalProperties:false → rejected |
| **Pass Criteria** | INVALID_PARAMS (schema says additionalProperties:false) |
| **Risk if Missed** | Unknown fields silently accepted; drift between schema and behavior |

### EC-24: params.fix_mode missing (uses default)

| Field | Value |
|---|---|
| **AC(s)** | AC-3 |
| **Category** | Input Domain |
| **Input / Setup** | `{"run_id":"uuid","repository_org":"x","repository_name":"y"}` (no params) |
| **Expected Result** | Defaults applied: fix_mode=audit_only, fail_on_findings=true, max_fix_attempts=3 |
| **Risk if Missed** | Crash on missing params key |

### EC-25: git push timeout

| Field | Value |
|---|---|
| **AC(s)** | AC-12 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | Network slow; push exceeds command timeout |
| **Expected Result** | TimeoutExpired caught; run fails with descriptive error; token scrubbed |
| **Risk if Missed** | Agent hangs until container killed; run stuck as "running" |

### EC-26: Test suite outputs ANSI color codes

| Field | Value |
|---|---|
| **AC(s)** | AC-33 |
| **Category** | Input Domain |
| **Input / Setup** | Test runner produces colored output with ANSI escape sequences |
| **Expected Result** | Stored as-is in run_events; log viewer in Phase 2 handles or strips them |
| **Risk if Missed** | Events contain garbled escape sequences; 8KB truncation hits mid-sequence |

### EC-27: PR body exceeds GitHub's size limit (65535 chars)

| Field | Value |
|---|---|
| **AC(s)** | AC-17 |
| **Category** | Data Boundaries |
| **Input / Setup** | Massive package diff (100+ packages) + many advisories |
| **Expected Result** | Body capped (package table at 30 rows); stays under limit |
| **Risk if Missed** | GitHub rejects PR creation; validated work lost |

### EC-28: Agent invoked with run_id that doesn't exist in runs table

| Field | Value |
|---|---|
| **AC(s)** | AC-33 |
| **Category** | State Transitions |
| **Input / Setup** | run_id points to non-existent row (caller didn't pre-create it) |
| **Expected Result** | First PATCH to runs returns 404/0-rows-affected; SDK logs to stderr; pipeline continues or fails gracefully |
| **Risk if Missed** | Silent write failures; no lifecycle recorded anywhere |

---

## 6. Randomized Test Tactics

### RT-1: Fuzz invocation payload

| Field | Value |
|---|---|
| **AC(s)** | AC-31 |
| **Tactic type** | fuzz |
| **Input surface** | Invocation payload JSON |
| **Property / Oracle** | Agent never returns 5xx/crash; always returns structured JSON with `status` field; INVALID_PARAMS for malformed inputs |
| **Iterations** | 200 |
| **Seed** | `fuzz-AC31-{timestamp}-{hex}` |
| **Replay instruction** | `pytest tests/fuzz/test_payload_fuzz.py --seed=<seed> --iterations=1` |
| **Shrink strategy** | Remove one field at a time; binary search on string length for oversized values |

**Mutation corpus:** null values, empty strings, integers where strings expected, nested objects 10 levels deep, Unicode injection (`\u0000`, RTL marks), 1MB string in repository_name, negative max_fix_attempts, float fix_attempts, array instead of object for params.

### RT-2: Fuzz patched-version range parsing

| Field | Value |
|---|---|
| **AC(s)** | AC-8 |
| **Tactic type** | fuzz |
| **Input surface** | `patched_versions` field of advisory objects |
| **Property / Oracle** | `_extract_lowest_version()` never raises; returns `str | None`; `classify_advisory()` never raises; always returns a valid ClassifiedAdvisory with bucket in {in_range, major_required, unknown} |
| **Iterations** | 500 |
| **Seed** | `fuzz-AC8-{timestamp}-{hex}` |
| **Replay instruction** | `pytest tests/fuzz/test_classifier_fuzz.py --seed=<seed> --iterations=1` |
| **Shrink strategy** | Character-level deletion to find minimal crashing input |

**Mutation corpus:** empty string, `"<0.0.0"`, `">= 5.0.0"` (space), `">=5.0.0 <6.0.0"`, `"<0.21.0 || >=0.21.1"`, `"*"`, `"^2.0.0"`, random alphanumeric, `">=a.b.c"`, null bytes, 10KB string.

### RT-3: Property — eligibility is reflexive for patch/minor

| Field | Value |
|---|---|
| **AC(s)** | AC-9 |
| **Tactic type** | property-based |
| **Input surface** | Random semver pairs where major is unchanged and minor/patch vary |
| **Property / Oracle** | `is_eligible(a, b)` returns `(True, "patch_or_minor")` for all such pairs |
| **Iterations** | 1000 |
| **Seed** | `prop-AC9-{timestamp}-{hex}` |
| **Replay instruction** | `pytest tests/fuzz/test_eligibility_prop.py --seed=<seed> --iterations=1` |
| **Shrink strategy** | Reduce minor/patch to boundary values (0, 1, MAX_INT) |

### RT-4: Property — eligible changes never cross major boundary

| Field | Value |
|---|---|
| **AC(s)** | AC-9 |
| **Tactic type** | property-based |
| **Input surface** | Random semver pairs |
| **Property / Oracle** | If `is_eligible(a, b)` returns True AND both parse as semver, then `major(a) == major(b)` (except when major==0 and minor unchanged) |
| **Iterations** | 1000 |
| **Seed** | `prop-AC9b-{timestamp}-{hex}` |
| **Replay instruction** | `pytest tests/fuzz/test_eligibility_prop.py --seed=<seed> --tactic=RT-4 --iterations=1` |
| **Shrink strategy** | Binary search on version components |

### RT-5: Stateful random walk — pipeline mode combinations

| Field | Value |
|---|---|
| **AC(s)** | AC-3, AC-4, AC-5, AC-12, AC-18, AC-19 |
| **Tactic type** | stateful-random-walk |
| **Input surface** | Sequence of invocations with random params against a fixture repo |
| **Property / Oracle** | Every invocation returns a valid (status, outcome, error_code) triple from the §8.1 table; no unexpected status values; idempotency holds |
| **Iterations** | 50 (sequences of 3-5 invocations each) |
| **Seed** | `walk-multi-{timestamp}-{hex}` |
| **Replay instruction** | `pytest tests/fuzz/test_pipeline_walk.py --seed=<seed> --iterations=1` |
| **Shrink strategy** | Remove invocations from sequence to find minimal failing sequence |

### RT-6: Fuzz scrubber with random token positions

| Field | Value |
|---|---|
| **AC(s)** | AC-30 |
| **Tactic type** | fuzz |
| **Input surface** | Strings containing a known token at random positions, with random surrounding text |
| **Property / Oracle** | After `scrub(text, [token])`, the token substring NEVER appears in the result |
| **Iterations** | 300 |
| **Seed** | `fuzz-AC30-{timestamp}-{hex}` |
| **Replay instruction** | `pytest tests/fuzz/test_scrubber_fuzz.py --seed=<seed> --iterations=1` |
| **Shrink strategy** | Reduce surrounding text length to find minimal context where scrub fails |

---

## 7. Execution Checklist

- [ ] All 36 ACs mapped to ≥1 positive + ≥1 negative/edge test
- [ ] E2E scenarios executable against real infrastructure (manual E2E gate)
- [ ] Contract tests executable as unit/component tests with mocked HTTP
- [ ] Edge cases executable as unit tests with fixtures
- [ ] Randomized tactics executable with seed capture
- [ ] Fixture repositories created (clean audit, breaking bump, major-only advisory, npm-only)
- [ ] Audit JSON fixture corpus collected from real pnpm and npm
- [ ] Test commands documented per story issue

---

## 8. Test Layer Mapping

| Layer | Test IDs | Framework | Trigger |
|---|---|---|---|
| Unit (Layer 1) | SC-24, SC-25, SC-31, SC-32, SC-33, EC-1–EC-28, RT-2–RT-4, RT-6 | pytest | `pytest -m unit` |
| Component (Layer 2) | SC-16, SC-17, SC-27, SC-28, CT-1–CT-12 | pytest + moto + responses | `pytest -m component` |
| E2E | SC-1–SC-15, SC-18–SC-23, SC-26, SC-29, SC-34–SC-36 | pytest + real infra | `pytest -m e2e --run-e2e` (manual) |
| Randomized | RT-1–RT-6 | pytest + hypothesis | `pytest -m fuzz` |
