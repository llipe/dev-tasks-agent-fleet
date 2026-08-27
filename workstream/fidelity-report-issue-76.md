# Fidelity Report — Issue #76: PR creation & PR body builder

## Verdict

- **Overall fidelity:** **High**
- **Highest drift impact present:** **Minor**
- **Scope:** issue #76 (`feat(agent): pull request creation and PR body builder`) — branch `issue/76-pr-creation-body-builder`, Draft PR #86, repo `llipe/dev-tasks-agent-fleet`
- **Mode:** Audit (grey-box). Drift findings below are **non-blocking** for PR readiness.

---

## Human-readable summary — what changed and why

This change gives the dependency-update agent its final step: after it has updated packages and confirmed the test suite still passes, it now opens a pull request so a human can review and merge the fix.

The work does exactly what was asked, and the behavior is well covered by tests:

- It creates a dated branch (`deps/update-<timestamp>`) and commits with a fixed, conventional message. It never commits to or pushes the project's main branch.
- If a dependency-update PR is already open, it does not open a second one — it stops cleanly and points at the existing PR. This keeps repeated runs from piling up duplicate PRs.
- The PR description is built from the run's real results (vulnerabilities before/after, which advisories were fixed, which still need a manual major-version upgrade, package changes, and test results). If an AI helper touched the code, the PR says so plainly so reviewers know to look harder.
- Security handling is careful: the GitHub token is never written into a URL or the git config, is scrubbed out of any error messages, and is refreshed if the run has been going long enough (over 45 minutes) that it might expire before the push.
- Importantly, when a fix is only partial because some advisories need a major upgrade, the PR for the part that *was* fixed is still opened before the run reports the "major update required" outcome — so the reviewer always gets the safe subset in hand.

The only gaps worth noting are documentation/verification hygiene, not behavior defects: the new PR-failure error codes aren't listed in the spec's error-code table, and the top-level `open_pr` orchestration in `main.py` is verified by inspection rather than an automated end-to-end test (a pre-existing, documented project convention). Neither affects the delivered behavior.

---

## Per-AC result table

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
|---|---|---|---|---|---|
| AC-1 | Branch name `deps/update-YYYYMMDD-HHMMSS` | `pull_request.branch_name()` uses `%Y%m%d-%H%M%S` + prefix `deps/update-` | spec §8.9, PRD req 53 | `test_pr_body.py::TestBranchName` (exact format + prefix) | **Pass** |
| AC-2 | Commit message `chore(deps): automated dependency update` | `_COMMIT_MESSAGE` constant; used in `create_pr` | PRD req 53 | `test_pr_creation.py::test_commit_message_is_conventional` | **Pass** |
| AC-3 | Never pushes to default branch | `create_pr` checks out a new `deps/update-*` branch and pushes only that branch | PRD req 53, spec §8.10 | `test_pr_creation.py::test_never_pushes_to_default_branch` | **Pass** |
| AC-4 | Idempotency: existing `deps/update-*` PR → `succeeded / not_applicable` | `existing_pr()` + `open_pr_if_needed()` short-circuit; `determine_outcome(pr_existed=True)` → `succeeded/not_applicable` | spec §8.10 (`open_pr → SUCCEEDED_NOT_APPLICABLE`), PRD req 54 | `test_pr_creation.py::TestExistingPr`, `::TestOpenPrIfNeeded::test_existing_pr_short_circuits`, `test_outcome_mapping.py::test_pr_existed` | **Pass** |
| AC-5 | PR body via `--body-file`, never inline | `create_pr` writes temp file, passes `--body-file`; `_write_body_file` | spec §8.9, PRD req 55, repo git invariant | `test_pr_creation.py::test_uses_body_file_never_inline`, `::test_body_file_written_with_content` | **Pass** |
| AC-6 | PR body sections (security, fixed, major_required, unknown, non-semver, pkg changes capped 30, validation, AI warning) | `build_pr_body` assembles sections 1–8; cap `_PACKAGE_CHANGES_CAP=30` | spec §8.9 (section-by-section match) | `test_pr_body.py` (all-sections, omitted-sections, cap-at-30, AI-warning, validation table) | **Pass** |
| AC-7 | PR recorded as `run_artifacts` type `pull_request` | `main.py` `run.artifact("pull_request", url=..., metadata={...})` for both new and existing PRs | PRD req 57 | Inspection-only (in `main.py`, coverage-excluded); no automated assertion | **Pass (inspection)** |
| AC-8 | Token refresh before push if >45 min | `refresh_token_if_stale` gated on `TokenContext.is_stale()`; `TOKEN_STALE_THRESHOLD_MINUTES = 45.0` | spec §7.2 ("Re-minted if >45 minutes"), PRD req 58 | `test_pipeline.py::TestRefreshTokenIfStale` (not-stale → same ctx; stale → re-mint + secret tracked) | **Pass** |
| AC-9 | Token via ephemeral credential helper, not in remote URL | `_push_with_credential_helper` uses inline `-c credential.helper=` snippet; `gh` via `GH_TOKEN` env | spec §7.2, PRD req 58 | `test_pr_creation.py::test_credential_helper_no_token_in_remote`, `::test_gh_token_passed_via_env_not_argv` | **Pass** |
| AC-10 | PR opened BEFORE MAJOR_UPDATE_REQUIRED terminates run (D25/req 43) | `main.py` opens PR in `open_pr` step, then calls `determine_outcome(has_pr=..., )`; `determine_outcome` returns `failed/needs_review/MAJOR_UPDATE_REQUIRED` only after PR context established (PR kept) | spec §8.10 (`open_pr → check_major_after_pr → FAILED_MAJOR_REQUIRED (PR kept)`), PRD req 43 | `test_outcome_mapping.py::test_pr_opened_with_major`, `::test_major_beats_fixed_in_llm_fix`; sequencing itself inspection-only in `main.py` | **Pass (tested outcome + inspection sequencing)** |

**AC coverage: 10/10 covered.** 8 fully implemented+tested; AC-7 and the ordering half of AC-10 rest on inspection of coverage-excluded `main.py` (documented project convention).

---

## Drift catalog

All drift below is **non-blocking** for PR readiness (Audit Mode is additive and does not gate completion).

| ID | Description | Impact | Intent | Evidence source(s) |
|---|---|---|---|---|
| DRIFT-1 | New PR-failure error codes `PR_LIST_FAILED`, `PUSH_FAILED`, `PR_CREATE_FAILED`, `GIT_FAILED` (raised by `PullRequestError` in `pull_request.py`) are absent from the spec §13.1 error-code table. | Minor | Undetermined | `pull_request.py` (raises the codes) vs. spec §13.1 (lists only pipeline-level codes through `MANDATE_VIOLATION`) |
| DRIFT-2 | AC-7 (`run_artifacts` type `pull_request`) and the *sequencing* half of AC-10 (PR opened before terminal MAJOR_UPDATE_REQUIRED) live in `main.py`, which is coverage-excluded by project convention; verified by inspection, no automated assertion that `run.artifact("pull_request", ...)` fires or that the artifact call precedes the terminal report. | Minor | Intended | `main.py` open_pr step; `TESTING.md` convention (main.py orchestrator coverage-excluded, guard ordering verified by inspection) |
| DRIFT-3 | Spec §8.9 signature types `non_semver_changes`/`upgraded` as `list[dict]`; implementation uses `list[PackageChange]` dataclasses. Functionally equivalent and stronger-typed, but a literal signature divergence from the spec snippet. | Minor | Intended | `pull_request.build_pr_body` signature vs. spec §8.9 code block |
| DRIFT-4 | PR failure paths in `pull_request.py` raise `PullRequestError`, but there is no test asserting how `main.py`'s `open_pr` step maps that exception to a run outcome/error_code (only lower-level scrubbing is tested). The generic `except Exception` in `main.py` would catch it as `UNHANDLED_ERROR`. | Minor | Undetermined | `pull_request.py` (raises) + `main.py` (no dedicated `except PullRequestError`); test suite has no assertion for this mapping |

No Critical or Major drift found.

---

## Edge-case & randomized test outcomes

No prior Design-Mode test plan exists for this scope, so this section reports observed edge coverage rather than a planned matrix. Notable edge cases exercised by the delivered suite:

- Package-changes table boundary: exactly 30 (no overflow note), 45 (overflow "and 15 more"), under-cap all-shown — `test_pr_body.py::TestPackageChangesCap`.
- Markdown injection safety: pipe and newline in advisory titles escaped/flattened — `test_pr_body.py::TestMarkdownEscaping`.
- Idempotency negatives: no `deps/update-*` PR present, empty `gh` output, non-matching head branches — `test_pr_creation.py::TestExistingPr`.
- Token-leak negatives: push failure, list failure — token scrubbed from raised error; token never on argv — `test_pr_creation.py`.
- Optional-section omission when inputs empty — `test_pr_body.py::TestOmittedSections`.

No randomized/property/fuzz tests are present in this scope; none were required by the ACs. No failure triage was needed (all 325 suite tests pass).

---

## Verification performed during this audit

- `pytest tests/unit/test_pr_body.py tests/component/test_pr_creation.py tests/unit/test_outcome_mapping.py tests/component/test_pipeline.py` → **82 passed**.
- Full suite `pytest -q` → **325 passed** (matches recorded gate).
- `pull_request.py` coverage → **95%** (uncovered lines are defensive/empty-input branches: 122–123, 239–241, 261–263, 444), matches recorded gate.
- Confirmed `TOKEN_STALE_THRESHOLD_MINUTES = 45.0` in `config.py` backs the >45-min refresh AC.
- Did not independently re-run lint/format:check/typecheck/audit; relied on recorded gate results (all PASS) and qa-engineer `coverage_gate = PASS`.

---

## Recommendations (no changes applied)

| Drift | Suggested next step | Owner |
|---|---|---|
| DRIFT-1 | Add `PR_LIST_FAILED`, `PUSH_FAILED`, `PR_CREATE_FAILED`, `GIT_FAILED` to spec §13.1 error-code table (or fold under a single `PR_FAILED`). Spec-alignment write-back. | `product-engineer` (spec changelog via `activity-drift-reconciliation`) |
| DRIFT-2 | No action needed if the coverage-exclusion convention stands; optionally add a thin `main.py` integration test asserting the `run.artifact("pull_request", ...)` call and its ordering relative to the terminal report. | `no action needed` / optional `developer` |
| DRIFT-3 | Update spec §8.9 signature to `list[PackageChange]` to match the stronger-typed implementation. | `product-engineer` (spec touch-up) |
| DRIFT-4 | Consider a dedicated `except PullRequestError` in `main.py`'s `open_pr` step mapping to a defined error_code, plus a test — so a push/create failure yields a meaningful outcome rather than `UNHANDLED_ERROR`. | `developer` (follow-up, non-blocking) |

---

## Output contract

- **Mode / phase:** Audit / Phase 4 (Reporting & Publication)
- **Source artifacts:** issue #76 body; spec §8.9/§8.10/§13; PRD §7.7 (reqs 53–58) + req 43; branch `issue/76-pr-creation-body-builder` / PR #86
- **Files produced:** `workstream/fidelity-report-issue-76.md`
- **AC coverage:** 10/10 covered (8 implemented+tested, 2 partly inspection-only)
- **Overall fidelity verdict:** High | **Highest drift impact:** Minor
- **Blocking gaps:** none (drift is non-blocking)
- **GitHub publication:** pending — post this report's Verdict + Human-readable summary to issue #76 / PR #86 (delegate to `github-ops`, `--body-file`)
