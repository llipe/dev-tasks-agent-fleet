# Compliance Test Plan — Security Analyst Agent

## Changelog

| Version | Date       | Summary         | Author   |
| ------- | ---------- | --------------- | -------- |
| 1.0     | 2026-09-15 | Initial version. Design-mode plan derived from PRD v1.2 (64 numbered requirements, 31 acceptance criteria + AC12a/AC12b), spec v1.2, the 17-story user-stories doc (S-125–S-141), and the implementation task plan. Covers 44 E2E scenarios, 15 contract-validation scenarios, 46 edge cases, and 6 randomized/property tactics. Pre-implementation: no code exists yet at `agents/security-analyst/` as of this writing. | verifier |

---

## 1. Source Input Summary

| Field | Value |
|---|---|
| Mode | Design |
| Repository | `llipe/dev-tasks-agent-fleet` |
| PRD | `docs/requirements/prd-security-analyst-agent.md` v1.2 |
| Spec | `workstream/specification-prd-security-analyst-agent.md` v1.2 |
| Stories | `workstream/user-stories-prd-security-analyst-agent.md` (S-125–S-141) |
| Task plan | `workstream/tasks-prd-security-analyst-agent-plan.md` |
| GitHub Issues | #185–#201 in `llipe/dev-tasks-agent-fleet` |
| Target code location (not yet created) | `agents/security-analyst/app/securityAnalyst/` |

**Scope note.** This is the full 17-story build (no subset). Unlike the sibling `dependency-update` agent, this plan is written **before** any implementation exists, so it is a pure design catalog — there is no "measured coverage" reconciliation section yet (contrast with `test-plan-dep-update-agent.md` §0). That reconciliation is expected as a follow-up Audit Mode pass once implementation lands (see PRD/spec/stories cross-reference §16 "Testing dependency").

---

## 2. Acceptance Criteria Extraction

| AC ID | Description | PRD §13 # | Primary story |
|-------|-------------|-----------|----------------|
| AC-1 | Project scaffolding: `agentcore create` layout, `agentcore validate` passes | 1 | S-125 |
| AC-2 | Deploys: `agentcore deploy` provisions runtime, `agentcore status` ready, seed has `runtime_arn` | 2 | S-125, S-141 |
| AC-3 | Audit-only, clean repo: `succeeded`/`no_findings`, `audit_report` artifact, no branch/PR | 3 | S-135 |
| AC-4 | Audit-only, findings + `fail_on_findings=true`: `failed`/`needs_review`/`AUDIT_FINDINGS`, all buckets present | 4 | S-135 |
| AC-5 | Audit-only, findings + `fail_on_findings=false`: `succeeded`/`needs_review` | 5 | S-135 |
| AC-6 | Fingerprint stability under a small line shift; changes on file/rule difference | 6 | S-127 |
| AC-7 | Cross-tool dedup: same-resource finding from 2 tools merges, names both | 7 | S-133 |
| AC-8 | Dedup does not over-merge: 2 distinct findings (same file, diff line/category) stay separate | 8 | S-133 |
| AC-9 | Classifier: Semgrep native-autofix finding → `mechanical` | 9 | S-134 |
| AC-10 | Classifier: Trivy base-image (non-lockfile) clean version-bump → `mechanical` | 10 | S-134 |
| AC-11 | Classifier: Trivy JS/TS-lockfile finding → `manual`, names `dependency-update` as owner | 11 | S-134 |
| AC-12 | Classifier: unparseable remediation shape → `unscannable`, never guessed, never modified | 12 | S-134 |
| AC-12a | Severity normalization table honored exactly, all 5 tools, both unknown-floor paths, CodeQL dual fallback | 58 | S-126 |
| AC-12b | `min_severity` gates status only, never scan/fix/re-scan scope (audit_only + fix mode) | 62–64 | S-135, S-140 |
| AC-13 | Fix mode happy path, zero LLM tokens: exactly 1 PR, `succeeded`/`fixed`\|`partial`, `metrics.llm_used=false` | 13 | S-140 |
| AC-14 | Re-scan gate blocks unverified fix (targeted finding still present) → `RESCAN_NOT_CLEAN`, no PR | 14 | S-137, S-140 |
| AC-15 | Re-scan gate blocks a regression-introducing fix, unless allow-listed | 15 | S-137, S-140 |
| AC-16 | LLM escape hatch fires only when deterministic fix insufficient; single-finding scope; AI warning in PR | 16 | S-138, S-140 |
| AC-17 | LLM budget per finding, not per run | 17 | S-138 |
| AC-18 | LLM disabled at `max_fix_attempts=0`, zero Bedrock calls | 18 | S-138 |
| AC-19 | Allow-list closed: fix agent receives only the single targeted finding's record | 19 | S-138 |
| AC-20 | Path escape refused by `_safe_path` | 20 | S-138 |
| AC-21 | No-findings no-op in fix mode: `succeeded`/`no_findings`, no branch/PR | 21 | S-140 |
| AC-22 | Idempotency: second `fix` invocation while PR open → `succeeded`/`not_applicable`, no 2nd branch/PR | 22 | S-139 |
| AC-23 | Scanner skip is non-fatal (e.g., Checkov, no IaC files) | 23 | S-131 |
| AC-24 | Scanner failure non-fatal unless total (`ALL_SCANNERS_FAILED`) | 18, 24 | S-135 |
| AC-25 | GitHub App auth via shared `github_installations` row | 25 | S-125 |
| AC-26 | No credential on disk or in logs | 26 | S-125 |
| AC-27 | Secret value never leaks through findings (Gitleaks + cross-cutting redaction) | 27 | S-129 |
| AC-28 | Invalid payload fast-fails `INVALID_PARAMS` without cloning | 28 | S-125 |
| AC-29 | Step stream complete: 7 `run_steps` in order, each terminal | 46 | S-140 |
| AC-30 | Reporting outage survivable | — | S-125 |
| AC-31 | Reaper interlock: `max_runtime_seconds` == `maxLifetime`, hung run reaped | 31, 49–50 | S-141 |

**Ambiguous/untestable-as-stated items flagged (see report to caller for detail):** AC-1/AC-2/AC-31's dynamic half are real-infra/deploy-time verifications, not pure-function-testable — same class as the sibling agent's AC-1/AC-2/AC-36. Requirement 56 (the full-coverage tool combination for a repo outside the JS/TS+Python stack) has **no dedicated numbered AC** — added here as SC-40/EC-41 on this plan's own initiative; flagged to `product-engineer` as a possible AC-catalog gap.

---

## 3. E2E Black-Box Scenarios

Compact form: `ID | AC(s) | Type | Story | Description → Expected result`.

| ID | AC(s) | Type | Story | Scenario |
|----|-------|------|-------|----------|
| SC-1 | AC-1 | happy-path | S-125 | `agentcore create` scaffold exists at `/agents/security-analyst/`; `agentcore validate` passes. |
| SC-2 | AC-2 | happy-path | S-125, S-141 | `agentcore deploy -y` provisions runtime in `us-east-1`; `agentcore status` reports ready; `runtime_arn` recorded in `supabase/seed.sql`. |
| SC-3 | AC-25, AC-26, AC-30 groundwork | happy-path | S-125 | Placeholder pipeline run against a real small repo produces a complete `runs` row with `resolve_credentials`/`checkout` steps and terminal `succeeded`/`no_findings` (no scanners yet). |
| SC-4 | AC-3 | happy-path | S-135 | `audit_only` on a repo with zero findings across all 5 tools → `succeeded`/`no_findings`, `audit_report` artifact lists 0 findings/tool, no branch, no PR. |
| SC-5 | AC-4 | negative-path | S-135 | `audit_only`, repo with findings across ≥3 tools, `fail_on_findings=true` → `failed`/`needs_review`/`AUDIT_FINDINGS`; artifact buckets every finding into mechanical/manual/unscannable. |
| SC-6 | AC-5 | happy-path | S-135 | Same repo, `fail_on_findings=false` → `succeeded`/`needs_review`. |
| SC-7 | AC-12b | boundary | S-135 | `audit_only`, `fail_on_findings=true`, `min_severity=high`, repo with only low/medium findings → `succeeded`/`no_findings` (not failed); artifact still lists every finding. |
| SC-8 | AC-12b | boundary | S-135 | Same repo + one `high` finding → `failed`/`AUDIT_FINDINGS`. |
| SC-9 | AC-12b | boundary | S-140 | `fix` mode, `min_severity=high`, a `low`-severity Semgrep-autofixable finding is still fixed and still appears in the PR's fixed-findings table. |
| SC-10 | AC-6 | boundary | S-127 | A finding is re-scanned after an unrelated edit shifts its line number by < tolerance band → same fingerprint, read as unchanged, not resolved+new. |
| SC-11 | AC-6 | negative-path | S-127 | Same finding, file path or `rule_id` changed → fingerprint changes. |
| SC-12 | AC-7 | happy-path | S-133 | Fixture: Terraform misconfiguration flagged by both Trivy and Checkov at the same resource → one merged finding in `audit_report`, `reported_by=("trivy","checkov")`. |
| SC-13 | AC-8 | negative-path | S-133 | Fixture: two distinct findings, same file, different line, different category → two separate findings. |
| SC-14 | AC-9 | happy-path | S-134 | Semgrep finding whose rule carries a native `--autofix` patch → classified `mechanical`. |
| SC-15 | AC-10 | happy-path | S-134 | Trivy finding on a container base image (not a JS/TS lockfile), clean version-bump remediation → `mechanical`. |
| SC-16 | AC-11 | negative-path | S-134 | Trivy finding whose remediation is a `pnpm-lock.yaml`/`package-lock.json` version bump → `manual`, annotated naming `dependency-update` as owner. |
| SC-17 | req 54 (boundary) | happy-path | S-134 | Trivy finding on `requirements.txt`/`poetry.lock`/`Pipfile.lock` → `mechanical` when otherwise eligible — **not** excluded by the D24 boundary. |
| SC-18 | AC-12 | negative-path | S-134 | Finding with an unparseable remediation shape → `unscannable`, own group in artifact, never modified by any code path. |
| SC-19 | req 27 (major-bump guard) | boundary | S-134 | Major-version bump on a non-lockfile semver artifact (e.g., container base-image tag) → `manual`, reason recorded, named in PR body's major-version-guard section. |
| SC-20 | AC-12a | happy-path | S-126 | Full severity table exercised end-to-end: Semgrep `ERROR`→high; every Gitleaks finding→critical; Checkov no-severity→medium; Trivy `UNKNOWN`→medium; CodeQL `security-severity=9.5`→critical; CodeQL neither signal→medium. |
| SC-21 | AC-13 | happy-path | S-140 | `fix` mode, repo with only cleanly-applying Semgrep-autofixable findings → exactly 1 PR on `security/fix-<timestamp>`, `succeeded`/`fixed`\|`partial`, `metrics.llm_used=false`. |
| SC-22 | AC-14 | negative-path | S-137, S-140 | Fixture: deterministic fix applies but re-scan still shows the targeted finding present → LLM escape hatch invoked; if still unresolved after budget → `failed`/`needs_review`/`RESCAN_NOT_CLEAN`, **no PR**, despite a local working-tree change. |
| SC-23 | AC-15 | negative-path | S-137, S-140 | Fixture: fix removes the targeted finding but re-scan reveals a new, non-allow-listed finding → same outcome as SC-22, no PR. |
| SC-24 | req 34 (allow-list) | happy-path | S-137 | Fixture: fix introduces a new finding matching an enumerated allow-list exception (e.g., Trivy `intermediate-patch-advisory`) → gate passes, does not block the PR. |
| SC-25 | AC-16 | happy-path | S-138, S-140 | Fixture: Semgrep autofix patch fails to apply cleanly → LLM path reached, `metrics.llm_used=true`, tool-call args show only the single finding's record; on success + clean re-scan, PR opens with the AI-modification warning. |
| SC-26 | AC-17 | boundary | S-138 | `max_fix_attempts=1`, two independent LLM-eligible findings, one resolves on attempt 1, the other never resolves → first fixed, second exhausts its own budget; PR (if opened) is `partial`, unresolved one named. |
| SC-27 | AC-18 | negative-path | S-138 | `max_fix_attempts=0`, a finding whose deterministic fix fails to apply cleanly → zero Bedrock invocations, finding reported remaining, not silently dropped. |
| SC-28 | AC-19 | negative-path | S-138 | Direct inspection of the fix agent's tool-call arguments/prompt confirms it never receives the full findings list — structurally cannot touch a `manual`/`unscannable` finding. |
| SC-29 | AC-20 | negative-path | S-138 | `_safe_path`-resolving tool call with a relative path escaping the workspace root → refused. |
| SC-30 | AC-21 | happy-path | S-140 | `fix` mode, repo with zero findings across all 5 tools → `succeeded`/`no_findings`, no branch, no PR. |
| SC-31 | req 37 | happy-path | S-140 | `fix` mode, repo with zero **mechanical** findings but `manual`/`unscannable` findings present → `succeeded`/`needs_review`, no branch/PR. |
| SC-32 | AC-22 | negative-path | S-139 | Second `fix` invocation on a repo while a `security/fix-*` PR is already open → `succeeded`/`not_applicable`, no second branch/PR, existing PR URL recorded as artifact. |
| SC-33 | AC-23 | negative-path | S-131 | Repo with no IaC files present → Checkov `SKIPPED` with a named `run_event`, run completes normally with the other 4 tools. |
| SC-34 | AC-24 (partial) | negative-path | S-132, S-135 | CodeQL deliberately made to crash (unsupported language forced into scope), other 4 tools succeed → run completes, CodeQL failure recorded as `error`-level event, run not failed. |
| SC-35 | AC-24 (full) | negative-path | S-135 | All 5 requested scanners deliberately fail → `failed`/`ALL_SCANNERS_FAILED`. |
| SC-36 | AC-25 | happy-path | S-125 | Run authenticates via the same `github_installations` row (`installation_id 156226839`) the sibling agent uses — no new installation/credential created. |
| SC-37 | AC-26 | negative-path | S-125 | Clone/push path: no credential value appears on disk (post-clone `.git/config` inspection) or in any log output at any verbosity. |
| SC-38 | AC-27 | negative-path | S-129 | Fixture repo/commit with one known dummy secret; Gitleaks finding's `message`, across `run_events`, `audit_report`, and PR body, never contains the literal secret string, including multiple-occurrence redaction. |
| SC-39 | AC-28 | negative-path | S-125 | Payload missing `run_id` / unknown `mode` / empty `scanners` list → `failed`/`INVALID_PARAMS`, terminates **without cloning**. |
| SC-40 | req 56 (no dedicated AC — flagged gap) | boundary | S-128–S-132 | Repo with no JS/TS or Python content → Gitleaks/Trivy(`config`/`image`)/Checkov full coverage, Semgrep partial (`p/security-audit` only), CodeQL `SKIPPED` — not a hard refusal. |
| SC-41 | req 51, 8.9 | happy-path | S-132 | Repo matching **both** JS/TS and Python → CodeQL runs twice (once per language pack), findings merged into one scan pass, no duplicate double-count in metrics. |
| SC-42 | req 17, 51 | negative-path | S-132 | Repo matching **neither** JS/TS nor Python → CodeQL `SKIPPED`, not failed. |
| SC-43 | AC-29 | happy-path | S-140 | Completed `fix` run has all 7 `run_steps` (`resolve_credentials`/`checkout`/`scan`/`classify`/`fix`/`rescan`/`open_pr`) present, in order, each terminal, events correctly associated. |
| SC-44 | AC-30 | negative-path | S-125 | PostgREST unreachable mid-run → pipeline still completes to a terminal state; payload appears on stderr/CloudWatch. |
| SC-45 | AC-31 | boundary | S-141 | `agents.max_runtime_seconds` (5400) in the seed row equals `maxLifetime` in `agentcore.json`; a deliberately hung run is marked `timed_out` by the existing `pg_cron` reaper with no reaper-side change. |
| SC-46 | req 42 (PR body) | happy-path | S-139 | PR body contains every required section: summary table, fixed-findings table, always-present remaining-manual table (even when empty), D24-boundary section (when applicable), major-version-guard section (when applicable), AI-modification warning (when LLM fired), re-scan confirmation line. |
| SC-47 | req 63 (heartbeat under load) | timing | S-140 | Deliberately slow fixture (simulated CodeQL delay) proves the stream stays alive past `IDLE_SESSION_TIMEOUT` under `heartbeat.run_with_heartbeat(...)` wrapping the `scan`/`rescan` steps. |
| SC-48 (manual) | task 17.10 | happy-path | S-141 | Real `audit_only` invocation against a real (small, known-content) target repo — evidence attached to closing PR. |
| SC-49 (manual) | task 17.11 | happy-path | S-141 | Real `fix` invocation against a fixture repo seeded with a Semgrep-autofixable finding — confirms a real, reviewable PR opens. |

---

## 4. Contract Validation Scenarios

| ID | Contract | AC/Req | Scenario |
|----|----------|--------|----------|
| CT-1 | Invocation payload — required fields | req 7, 9 | Missing `run_id`/`repository_org`/`repository_name` → `INVALID_PARAMS`. |
| CT-2 | Invocation payload — `prompt`-wrapping | req 8 | Payload wrapped as a JSON string inside `prompt`, up to `_MAX_UNWRAP_DEPTH=16`, unwrapped transparently; depth 17 rejected/handled per sibling precedent. |
| CT-3 | Parameter defaults | req 10, spec §6.1 | Omitted `params` object → `mode=audit_only`, `fail_on_findings=true`, `min_severity=low`, `max_fix_attempts=3`, `scanners=`all five. |
| CT-4 | `max_fix_attempts` clamping | req 10 | Values outside `0..5` are clamped (`max(0, min(5, n))`), not rejected — verify against spec §6.1's `apply_defaults()`. |
| CT-5 | `scanners` list validation | req 11 | Empty list or a value outside the 5-tool enum → `INVALID_PARAMS`. |
| CT-6 | `min_severity` enum validation | req 10, §7.4b | Value outside `{low,medium,high,critical}` → `INVALID_PARAMS`. |
| CT-7 | `Finding`/`Remediation` schema | spec §8.1 | Every normalizer's output conforms to the frozen-dataclass field set exactly (`tool`, `rule_id`, `severity`, `file_path`, `line_start`, `line_end`, `message`, `cwe_or_category`, `remediation`, `raw_ref`). |
| CT-8 | `ScanResult`/`ScanStatus` contract | spec §8.5 | Every scanner module returns `ScanResult(tool, status, findings, reason)`; `reason` populated iff `status` is `SKIPPED`/`FAILED`. |
| CT-9 | Return payload contract | spec §6.2 | `build_return_payload()` output carries all fields listed in req 47 (`status`, `outcome`, `error_code`, `pr_url`, before/after counts by bucket, `findings_fixed`, `fix_attempts_deterministic`/`_llm`, `llm_used`). |
| CT-10 | `runs.metrics` contract | req 47, spec §9.1 | `build_metrics()` output carries `llm_used`, `fix_attempts_deterministic`, `fix_attempts_llm`, finding counts, `scanners_run`/`skipped`/`failed`, per-step durations. |
| CT-11 | `run_steps` contract | req 46 | Exactly the 7 named keys, correct mode applicability (`resolve_credentials`/`checkout`/`scan`/`classify` = both; `fix`/`rescan`/`open_pr` = `fix` only). |
| CT-12 | Seed `params_schema` ↔ invocation contract parity | spec §5.2, §6.1 | `supabase/seed.sql`'s JSON Schema `enum`/`default`/`minItems` values match `_VALID_MODES`/`_VALID_SCANNERS`/`_VALID_SEVERITIES` exactly; `additionalProperties: false` rejects an unrecognized extra param. |
| CT-13 | PR body section contract | req 42 | `build_pr_body()` always emits summary/fixed/remaining-manual sections; conditionally emits D24-boundary, major-version-guard, and AI-warning sections; always emits the re-scan confirmation line. |
| CT-14 | Clock invariant chain | spec §9.2 | `FIX_COMMAND_TIMEOUT(180) <= SCANNER_TIMEOUT(600) <= IDLE_SESSION_TIMEOUT(900) <= MAX_LIFETIME(5400) <= REAPER_THRESHOLD_SECONDS(5520)`; `0 < HEARTBEAT_INTERVAL(120) <= IDLE_SESSION_TIMEOUT/2`. |
| CT-15 | `error_code` enum contract | spec §13.1 | Only `INVALID_PARAMS`/`NO_INSTALLATION`/`ALL_SCANNERS_FAILED`/`RESCAN_NOT_CLEAN`/`CLONE_FAILED`/`GITHUB_AUTH_FAILED`/exception-class-name values ever appear on a `failed` run. |

---

## 5. Edge-Case Catalog

Organized by the required category set.

### Input domain

| ID | Edge case | AC/Req |
|----|-----------|--------|
| EC-1 | Missing `run_id` | req 9, AC-28 |
| EC-2 | Missing `repository_org`/`repository_name` | req 9, AC-28 |
| EC-3 | Unknown `mode` value (not `audit_only`/`fix`) | req 9, AC-28 |
| EC-4 | Unknown `min_severity` value | req 10, AC-28 |
| EC-5 | Empty `scanners` list | req 11, AC-28 |
| EC-6 | `scanners` list containing an unrecognized tool name | req 11, AC-28 |
| EC-7 | `max_fix_attempts` outside `0..5` (negative, > 5, non-integer) | req 10 |
| EC-8 | Payload `prompt`-wrapped beyond `_MAX_UNWRAP_DEPTH=16` | req 8 |
| EC-9 | Payload wrapped once as a JSON string inside `prompt` (normal case) | req 8 |

### State transition

| ID | Edge case | AC/Req |
|----|-----------|--------|
| EC-10 | `audit_only` mode never transitions to fix/branch/PR states regardless of finding volume | req 26 |
| EC-11 | `fix` mode with an already-open PR short-circuits before `fix`/`rescan` steps even run | AC-22 |
| EC-12 | `fix` mode loops `rescan → llm_fix → rescan` correctly for multiple attempts before reaching `open_pr` | spec §8.8 |
| EC-13 | Gate not clean, budget exhausted mid-loop → terminal `RESCAN_NOT_CLEAN`, no further step transitions attempted | req 36 |

### Timing

| ID | Edge case | AC/Req |
|----|-----------|--------|
| EC-14 | An individual scanner exceeds `SCANNER_TIMEOUT` (600s) → that tool `FAILED`, others continue independently | req 19 |
| EC-15 | CodeQL's database-build phase is the long pole; heartbeat keeps the stream alive past `IDLE_SESSION_TIMEOUT` | spec §9.2 |
| EC-16 | Overall run approaches `MAX_LIFETIME` (5400s) → hard kill by AgentCore; reaper marks `timed_out` | AC-31 |
| EC-17 | An individual LLM fix-agent shell command exceeds `FIX_COMMAND_TIMEOUT` (180s) | spec §9.2 |

### Idempotency

| ID | Edge case | AC/Req |
|----|-----------|--------|
| EC-18 | Second `audit_only` invocation on the same repo is an independent run — no cross-run dedup expected | req 15 |
| EC-19 | Second `fix` invocation, same repo, first PR still open → `not_applicable`, no duplicate branch | AC-22 |
| EC-20 | `fix` invocation replayed after the prior `security/fix-*` PR is merged/closed → new branch/PR created, not blocked | req 41 |

### Failure modes

| ID | Edge case | AC/Req |
|----|-----------|--------|
| EC-21 | Individual scanner crash / unparseable output → non-fatal, `error`-level event, findings excluded | req 18 |
| EC-22 | All 5 scanners fail → `ALL_SCANNERS_FAILED` | req 18, AC-24 |
| EC-23 | Semgrep autofix patch fails to apply cleanly (merge conflict) → escalates to LLM fix agent | req 29 |
| EC-24 | Trivy version bump requires a source edit beyond the version string → escalates to LLM fix agent | req 29 |
| EC-25 | Clone failure / GitHub auth failure → `CLONE_FAILED` / `GITHUB_AUTH_FAILED` | spec §13.1 |
| EC-26 | No matching `github_installations` row → `NO_INSTALLATION` | spec §8.1 table |
| EC-27 | Unhandled exception mid-pipeline → `failed`/`needs_review`/exception-class-name, step closed | spec §8.1 table |
| EC-28 | PostgREST unreachable mid-run → pipeline completes, stderr fallback | AC-30 |

### Auth / permissions

| ID | Edge case | AC/Req |
|----|-----------|--------|
| EC-29 | GitHub App installation token nears the 45-min re-mint threshold mid-run → re-minted transparently | req 13 |
| EC-30 | Fix agent's mocked tool surface is exercised for unexpected network egress beyond clone/scan needs — asserted absent | req 14 |
| EC-31 | `_safe_path`: relative path with `../` escaping the workspace root → refused | AC-20 |
| EC-32 | `_safe_path`: absolute path outside the workspace root → refused | AC-20 |
| EC-33 | `_safe_path`: symlink escaping the workspace (if the filesystem under test supports it) → refused | AC-20 |

### Data boundaries

| ID | Edge case | AC/Req |
|----|-----------|--------|
| EC-34 | Fingerprint line shift **exactly at** the tolerance-band boundary (3 lines) — explicit inclusive/exclusive assertion | AC-6, D18 |
| EC-35 | Fingerprint with an empty `rule_id` falls back to `cwe_or_category` | spec §8.2 |
| EC-36 | Dedup: three-way overlap (3 tools, same location) → single merged record naming all three | req 22 |
| EC-37 | Dedup: overlapping line ranges but different category → not merged | req 22, AC-8 |
| EC-38 | Classifier: `lockfile_managed=True` **and** major-bump simultaneously → lockfile branch wins (checked first per spec §8.4's branch order) | S-134 task 10.10 |
| EC-39 | Re-scan gate: near-miss allow-list pattern (partially matching but not exact) → **not** treated as an allowed exception, gate fails | req 34, S-137 task 13.6 |
| EC-40 | `min_severity=critical`, repo's only findings are `high` → `succeeded`/`no_findings`; all findings still in the artifact | AC-12b |
| EC-41 | Checkov's absent severity **and** a CodeQL result with neither `security-severity` nor a usable `level` both occur in the same run — both independently fall to the shared `medium` floor | D30 |

### Resource exhaustion

| ID | Edge case | AC/Req |
|----|-----------|--------|
| EC-42 | Large repo, hundreds of findings across all 5 tools — pipeline completes within timeout/memory envelope (manual/perf note, not unit-testable) | spec §11 |
| EC-43 | `max_fix_attempts=5` (upper bound) across 10 LLM-eligible findings — budget respected per finding, no cross-finding starvation | D26, AC-17 |

### API / schema versioning

| ID | Edge case | AC/Req |
|----|-----------|--------|
| EC-44 | `params_schema`'s `additionalProperties: false` rejects an unrecognized extra invocation param | spec §5.2 |
| EC-45 | Seed `params_schema` enum sets and `main.py`'s `_VALID_*` sets are drift-checked against each other (same test also covers CT-12) | spec §5.2, §6.1 |
| EC-46 | A repo containing no JS/TS or Python content still legitimately receives partial coverage (Semgrep `p/security-audit` only, CodeQL `SKIPPED`) rather than a hard refusal | req 56 (flagged gap, see §2) |

---

## 6. Randomized & Property-Based Tactics

> **Design note on adoption.** The sibling agent (`dependency-update`) evaluated and **declined** to adopt `hypothesis`/property-based fuzzing during implementation (`test-plan-dep-update-agent.md` v1.1), judging its already-dense table-driven unit coverage sufficient and citing PRD-adjacent reasoning that applies here too (PRD §16: "a large share of the criteria... are unit-testable against pure functions over recorded scanner-output fixtures"). The tactics below are retained as the **designed** randomized catalog per this skill's requirement, but `developer`/`qa-engineer` should make the same build-vs-skip call for this agent during implementation and record the decision in this file's changelog (mirroring the sibling's v1.1 reconciliation), rather than silently skipping without a recorded rationale.

| ID | Property | Function under test | Seed policy |
|----|----------|----------------------|-------------|
| RT-1 | `fingerprint(f) == fingerprint(f')` whenever only `line_start` shifts by less than `_LINE_TOLERANCE_BAND` (3) and `file_path`/`rule_id` are unchanged | `fingerprint.py::fingerprint` | Fixed seed `20260915`; randomized line deltas in `[-2, 2]` and `[3, 6]` (boundary + beyond); captured seed + minimized delta logged on failure. |
| RT-2 | `len(dedupe(findings)) <= len(findings)`; every input `Finding` is represented in exactly one `MergedFinding.reported_by` | `dedupe.py::dedupe` | Fixed seed; randomized synthetic `Finding` sets varying file/line/category/tool combinations. |
| RT-3 | `classify()` always returns a value in `{MECHANICAL, MANUAL, UNSCANNABLE}` for any well-formed `Finding`/`Remediation` combination, including fuzzed `remediation.kind`/`lockfile_managed`/`target_version` shapes | `classifier.py::classify` | Fixed seed; structured fuzzing over the documented `Remediation` field domain only (no arbitrary bytes — the schema is closed per spec §8.1). |
| RT-4 | Every `severity_from_*` function is total (never raises) across its tool's full native-value input space, including out-of-table values, falling to the documented floor | `severity.py::severity_from_*` | Fixed seed; exhaustive enumeration where the domain is finite (Semgrep/Trivy/Checkov), randomized floats for CodeQL's `security-severity`. **Flagged discrepancy:** spec §8.1a's `severity_from_semgrep` uses direct dict indexing (`{"ERROR": ...}[raw_severity]`), not the `.get(..., floor)` pattern the other four functions use — an out-of-table Semgrep value will raise `KeyError` rather than fall to the floor. RT-4 is designed to surface this; see report to caller. |
| RT-5 | `rescan_gate(...).clean == True` iff `still_present` is empty **and** `unexplained_new` is empty | `rescan.py::rescan_gate` | Fixed seed; randomized before/after `MergedFinding` set pairs, including allow-listed and non-allow-listed new-finding cases. |
| RT-6 | `_at_or_above_floor()` is monotonic — raising `min_severity` never increases the gated-finding-set size | `main.py::_at_or_above_floor` | Fixed seed; randomized finding-severity distributions crossed with all 4 floor values. |

All randomized cases **MUST** capture and log their seed on failure and be re-runnable deterministically from that seed (replay instructions: re-invoke the same test function with `--seed <captured>` or the project's fixed-seed constant, per the repo's existing convention).

---

## 7. Execution Checklist

1. **Pre-implementation blockers** (must resolve before scenarios needing them can run for real, not just against mocks):
   - [ ] PRD/spec OQ5 — CodeQL ARM64 CLI availability confirmed for `javascript-typescript`/`python` packs at the pinned version (blocks SC-41/SC-42 real execution; task 8.0.1 is itself a blocking pre-check).
   - [ ] Spec open question 2 — IAM grant synthesis mechanism verified against a real `agentcore deploy` (blocks SC-2 full verification).
   - [ ] Trivy `image` mode target ambiguity ("built or a representative base image") resolved to a concrete implementation choice (affects SC-15, SC-19 fixture design).
2. Build the fixture corpus first (PRD §16 "Testing dependency"): clean + findings-bearing raw output per tool (Semgrep/Gitleaks/Trivy `fs`(npm)/`fs`(Python)/`config`/`image`/Checkov/CodeQL SARIF JS+Python), plus two purpose-built fixture repos for re-scan-gate manufacture (SC-22, SC-23).
3. Run unit-layer scenarios (fingerprint, dedupe, classifier, severity, rescan-gate, safe-path, clock-invariant, payload-contract) first — they are pure-function and unblock everything downstream.
4. Run component-layer scenarios (mocked subprocess scanners, mocked `Agent`, mocked `gh pr list`) next.
5. Run E2E scenarios requiring a real (small) target repo (SC-3, SC-48, SC-49) only after unit/component layers are green — these are the manual/deploy-verification items.
6. Run randomized tactics (§6) with the fixed seed policy; log and triage any failure per the standard failure-triage workflow (capture → isolate → minimize → classify → report; 3-retry cap on non-reproducing failures).
7. Cross-check every AC row in the traceability matrix has ≥1 positive and ≥1 negative/edge case before declaring Design Mode complete.

---

## 8. Test Layer Mapping (designed)

| Layer | Scope | Scenario IDs (representative) |
|---|---|---|
| Unit (Layer 1) | Pure functions: fingerprint, dedupe, classifier, severity, rescan-gate comparison, `_safe_path`, `_assert_diff_confined_to`, `_at_or_above_floor`, clock invariant, payload validate/defaults | SC-10, SC-11, SC-12, SC-13, SC-14–SC-19, SC-20, SC-24, SC-28, SC-29, SC-39, EC-1–EC-9, EC-31–EC-41, EC-44, EC-45, RT-1–RT-6, CT-1–CT-8 |
| Component (Layer 2) | Mocked subprocess scanner calls, mocked `Agent`, mocked `gh pr list`/branch/push, full pipeline with all 5 scanners mocked | SC-21–SC-27, SC-30–SC-38, SC-43, SC-46, SC-47, EC-14, EC-17, EC-21–EC-30, CT-9–CT-11, CT-13–CT-15 |
| E2E (real infra, manual/runbook) | `agentcore create`/`deploy`/`validate`, real repo audit/fix runs, reaper interlock | SC-1, SC-2, SC-3, SC-45, SC-48, SC-49, EC-16, EC-42 |
| Randomized / property | Fingerprint tolerance, dedup invariants, classifier totality, severity totality, gate correctness, floor monotonicity | RT-1–RT-6 |
