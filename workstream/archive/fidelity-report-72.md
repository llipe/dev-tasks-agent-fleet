# Fidelity Report — Issue #72: Toolchain Detection and Validation Runner

## 1. Header / Verdict

| Field | Value |
| --- | --- |
| **Overall fidelity** | **High** |
| **Highest drift impact** | **Minor** |
| **Scope** | Issue #72 — `feat(agent): toolchain detection and validation runner` |
| **PR / branch** | PR #82 (draft, base `main`) / `issue/72-toolchain-detection` |
| **Mode** | Audit (grey-box) |
| **Sources cross-checked** | Codebase (`toolchain.py`, `validator.py`, tests), `/workstream` artifacts (tasks, test plan), test suite (83 pass), PRD §7.4 (reqs 21-24, D19/D20) + spec §8.1/§8.2 |
| **Verdict statement** | Delivered implementation faithfully realizes every acceptance criterion in scope for this task. The one systematic gap — no `warn`-event emission for absent optional scripts — is **intended, documented, and spec-consistent**: emission is the orchestrator's job (`main.py`, Issue #74), and this task correctly surfaces the data via `ScriptContract.missing_optional`. No unintended drift found. |

> Drift is non-blocking to PR/issue completion. This audit is additive and does not replace the `test` / `lint` / `format:check` / `typecheck` / `audit` quality gates.

---

## 2. Human-Readable Summary — "What Changed and Why"

This task teaches the dependency-update agent two things before it ever touches a repository's code: **which package manager the repo uses**, and **which quality scripts it can run**.

For package-manager detection, the agent follows a strict order of evidence: it first trusts an explicit `packageManager` field in `package.json`, then falls back to a `pnpm-lock.yaml` file (meaning pnpm), then a `package-lock.json` file (meaning npm). If none of those exist, it refuses to proceed and reports a clear `NO_PACKAGE_MANAGER` error naming exactly what it looked for — the agent will not guess at a repo it cannot understand. For pnpm specifically, it figures out which major version the project expects (from the version string or the lockfile format) and installs that version if the container's default is different.

For scripts, the agent is deliberately "opinionated with margin." A **test** script is mandatory — without it, the agent cannot verify that an update is safe, so it stops with `NO_TEST_SCRIPT`. But **lint, format, and typecheck are optional**: if they're missing, the agent notes their absence and keeps going rather than failing over cosmetics. It also recognizes common naming variants (e.g. `format:check`, `type-check`, `lint:fix`).

The validation runner then executes the available checks in a fixed order (lint → format → typecheck → test). If lint or format fails and a corresponding auto-fix script exists (`lint:fix`, `format:fix`), it runs the fix once and re-checks before declaring failure. Missing optional checks are marked "skipped" and never cause the run to fail. Every check's outcome is captured in a structured result object so a later step can render it in the pull-request body.

**One deliberate boundary:** the requirement says every absent optional script must produce a visible warning in the panel. That warning is *not* emitted here — it is emitted by the orchestrator (`main.py`, a separate future task, Issue #74). This task's job is to make the information available, which it does through a `missing_optional` list on the script contract. The agent's own tests and comments state this hand-off explicitly, and it matches the system design where the orchestrator owns the run-event stream. This is a correct division of labor, not a missed requirement.

---

## 3. Per-AC Result Table

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| --- | --- | --- | --- | --- | --- |
| AC-1 | Detects pnpm from `packageManager` field or `pnpm-lock.yaml` | `detect_package_manager` — field check (`_SUPPORTED`) then `_LOCKFILES` precedence | Task 2.1; PRD req 21 / D19 | `test_detects_pnpm_from_package_manager_field`, `test_detects_pnpm_from_lockfile`, `test_ac_pnpm_project_detected` | **Pass** |
| AC-2 | Detects npm from `package-lock.json` | `_LOCKFILES` second entry `("npm", "package-lock.json")` | Task 2.1; PRD req 21 | `test_detects_npm_from_lockfile`, `test_ac_npm_project_detected` | **Pass** |
| AC-3 | Fails with `NO_PACKAGE_MANAGER` when no lockfile matches | `ToolchainError("NO_PACKAGE_MANAGER", …)` with searched-list message | Task 2.11; PRD req 21; test plan SC-18/AC-27 | `test_no_lockfile_raises…`, `test_missing_package_json…`, `test_error_message_names_what_was_searched`, `test_ac_no_package_manager_on_empty_fixture` | **Pass** |
| AC-4 | Matches pnpm major from `packageManager` field or `lockfileVersion` | `detect_pnpm_version` + `_LOCKFILE_TO_PNPM_MAJOR` (9→9, 6→8, 5→7) | Task 2.2; PRD req 22 | `test_from_package_manager_field`, `test_from_lockfile_version_9/6/5`, `test_package_manager_field_wins_over_lockfile`, unquoted + unknown-version cases | **Pass** |
| AC-5 | Installs correct pnpm major when container default differs | `ensure_pnpm_version` → `npm install -g pnpm@<major>` only on mismatch | Task 2.3; PRD req 22 | `test_installs_when_major_differs`, `test_no_install_when_version_matches`, `test_noop_when…undeterminable`, `test_installs_when_current_unknown` | **Pass** |
| AC-6 | `test` required; fails with `NO_TEST_SCRIPT` if absent | `detect_scripts` raises `NO_TEST_SCRIPT` when `"test" not in scripts` | Task 2.12; PRD req 23 / D20; test plan SC-19/AC-24 | `test_missing_test_raises…`, `test_no_scripts_at_all…`, `test_ac_no_test_script_fixture` | **Pass** |
| AC-7 | `lint`/`format`/`typecheck` optional; emits warn event per absent script | `ScriptContract.missing_optional` populated; **warn emission deferred to orchestrator (#74)** | Task 2.13; PRD req 23; test plan SC-20/AC-25 | `test_missing_optional_scripts_listed`, `test_ac_absent_optional_scripts_surfaced_for_warnings` | **Pass (with Minor drift — see D-1)** |
| AC-8 | Detects `lint:fix`, `format:fix`, `format:check`, `type-check` variants | `_OPTIONAL_SCRIPT_VARIANTS` + `_FIX_SCRIPT_VARIANTS` + `_resolve_variant` | Task 2.4; PRD req 23/24 | `test_detects_lint_fix_variant`, `test_detects_format_check_variant`, `test_detects_format_fix_variant`, `test_detects_type_check_hyphen_variant`, `test_canonical_name_preferred_over_variant` | **Pass** |
| AC-9 | `run_validation()` runs lint → format → typecheck → test in order | `run_validation` calls runners in that fixed order; no early exit | Task 2.7; PRD req 23; spec §8.2 | `test_order_lint_format_typecheck_test`, `test_all_pass` | **Pass** |
| AC-10 | When lint fails and `lint:fix` exists, runs fix once and re-checks | `_run_fixable_check` — single fix pass then one re-check | Task 2.6; PRD req 24 | `test_run_lint_fix_and_retry_success`, `test_run_lint_fails_when_no_fix_variant`, `test_run_lint_fails_when_fix_does_not_help`, `test_run_format_fix_and_retry` | **Pass** |
| AC-11 | Returns structured `ValidationResult` with per-check status | `ValidationResult` dataclass, `CheckStatus` enum, `record`/`passed` | Task 2.5; PRD req 23 | `TestValidationResultDataclass` (4 tests), `test_per_check_status_recorded`, `test_optional_absent_are_skipped_run_continues` | **Pass** |

**AC coverage: 11 of 11 covered.** Every AC maps to at least one positive and one negative/edge test.

---

## 4. Drift Catalog

### D-1 — `warn`-event emission for absent optional scripts is not in `toolchain.py`

| Attribute | Value |
| --- | --- |
| **Description** | PRD req 23 states: "Every absent optional script **MUST** produce a `warn`-level `run_event` naming it." The AC-7 wording ("emits warn event per absent script") reads as if this task emits the event. The delivered `toolchain.py` does **not** emit run events — it records absent scripts in `ScriptContract.missing_optional` and leaves emission to the caller. |
| **Impact class** | **Minor** |
| **Intent class** | **Intended** |
| **Evidence sources** | Codebase: `detect_scripts` docstring ("recorded in `missing_optional` so the caller can emit warn events"); test `test_ac_absent_optional_scripts_surfaced_for_warnings` asserts the contract exposes the data "so the orchestrator can emit a warn event per missing script". Spec §8.2: orchestrator step `detect_toolchain` returns `(pm, scripts)`; run-event emission lives inside `RunReporter` steps in `main.py`. Test plan: SC-20/AC-25 ("3 warn-level events … PR body marks them skipped") is classified as an **E2E** scenario (§ test-strategy table: `SC-18–SC-23` run under `pytest -m e2e --run-e2e`, manual), i.e. it validates the *orchestrator* path, not this unit-scoped task. Known context confirms emission is Issue #74. |
| **Spec-consistency check (requested)** | **Consistent.** The spec's module decomposition (§8.1) assigns `toolchain.py` the responsibility "Package manager detection, pnpm version matching, script contract" — not run-event emission. The orchestrator (§8.2) owns `RunReporter` and the run-event stream. `run_events` are written by the reporter within `run.step(...)` blocks in `main.py`. Surfacing `missing_optional` on the contract is precisely the seam the orchestrator needs. Deferring emission to #74 therefore honors the module boundary rather than violating it. The end-to-end requirement (req 23) will be satisfied when #74 consumes `missing_optional`; SC-20 is the E2E test that will verify it at that layer. |
| **Non-blocking note** | This drift does **not** block PR #82 or Issue #72 completion. |
| **Recommendation** | See §6, R-1. |

### D-2 — `tests/fixtures/` directory named in task 2.8 vs. fixtures delivered via `conftest.py`

| Attribute | Value |
| --- | --- |
| **Description** | Task 2.8 says "Create `tests/fixtures/` with temp dir fixtures (pnpm project, npm project, no lockfile, no test script)". The delivered fixtures are implemented as pytest fixtures in `tests/conftest.py` (`pnpm_project`, `npm_project`, `no_lockfile_project`, `no_test_project`, `minimal_test_project`) that build project shapes under each test's `tmp_path`, rather than as static files under a `tests/fixtures/` directory. |
| **Impact class** | **Minor** |
| **Intent class** | **Intended** |
| **Evidence sources** | Codebase: `tests/conftest.py` provides all five fixtures with the exact shapes the task lists, plus a `minimal_test_project` for optional-absent coverage. Task list 3.10 reserves `tests/fixtures/` for real audit JSON corpora (Issue #73), so the directory has a distinct future purpose. All 5 fixture cases are exercised by `TestAcceptanceCriteria`. |
| **Spec-consistency check** | Consistent with spec §12 test strategy intent (temp-dir project shapes for detection tests). Using `tmp_path`-backed fixtures is the idiomatic pytest approach and provides better isolation than checked-in fixture directories. Functional coverage is complete. |
| **Non-blocking note** | Does not block completion. |
| **Recommendation** | See §6, R-2. |

**No Critical or Major drift identified. No Unintended or Undetermined drift identified.**

---

## 5. Edge-Case, Coverage, and Quality-Gate Outcomes

Independently reproduced during this audit (not merely reported):

| Check | Result |
| --- | --- |
| `pytest -m unit test_toolchain.py test_validator.py` | **58 passed** |
| Full agent suite (`pytest tests/`) | **83 passed** |
| `toolchain.py` coverage | **94%** (uncovered: `_current_pnpm_major` non-digit/OS-error branches, `_run` helper) |
| `validator.py` coverage | **99%** (uncovered: line 67, `_combined_output` empty branch) |
| PR #82 state | OPEN, draft, base `main`, head `issue/72-toolchain-detection` |

Notable positive edge coverage beyond the strict ACs:
- Unrecognized `packageManager` field (e.g. `yarn@4`) correctly falls back to lockfile evidence (`test_unrecognized_package_manager_field_falls_back_to_lockfile`).
- Malformed `package.json` degrades gracefully to lockfile detection (`test_malformed_package_json_falls_back_to_lockfile`).
- Unknown/unmapped `lockfileVersion` (e.g. `3.0`) returns `None` rather than guessing (`test_unknown_lockfile_version_returns_none`).
- Canonical script name preferred over variant when both exist (`test_canonical_name_preferred_over_variant`).
- Subprocess **timeout** on test/lint runs is recorded as `FAILED`, not propagated as a crash (`test_run_tests_timeout_marks_failed`, `test_run_lint_timeout_marks_failed`) — validator uses `TEST_TIMEOUT` (600s) for tests and `TOOL_COMMAND_TIMEOUT` (180s) for tool commands, matching the issue's technical note.
- npm/pnpm command parity verified at the runner level (`test_command_uses_npm_run`, `test_command_uses_pnpm`).

No randomized/fuzz tests are in scope for this task (RT-* scenarios are assigned to later modules); no failure-triage entries required.

---

## 6. Recommendations

| ID | Finding | Suggested next step | Owner |
| --- | --- | --- | --- |
| R-1 | D-1 — warn-event emission deferred to orchestrator | **No action needed for #72.** Ensure Issue #74 (`main.py` orchestrator) consumes `ScriptContract.missing_optional` and emits one `warn`-level `run_event` per entry, and that E2E scenario SC-20/AC-25 is executed at that layer to close PRD req 23 end-to-end. Recommend a traceability note on #74 linking back to this contract seam. | `developer` (on #74) |
| R-2 | D-2 — fixtures via `conftest.py` vs. `tests/fixtures/` dir | **No action needed** (functional parity achieved). Optionally reconcile the task-list wording of 2.8 to reflect that project-shape fixtures live in `conftest.py` while `tests/fixtures/` holds data corpora (#73), to prevent future confusion. This is a documentation-alignment nicety, routed through `product-engineer` drift-reconciliation if desired. | `product-engineer` (optional) |

Neither recommendation blocks completion of Issue #72. Both drift items are Minor and Intended; routing to `product-engineer`'s `activity-drift-reconciliation` is optional and at the caller's discretion.

---

## 7. Output Contract

- **Mode / phase:** Audit Mode / Phase 4 (Reporting & Publication)
- **Source artifacts used:** GitHub Issue #72; PRD `docs/requirements/prd-dependency-update-agent.md` §7.4 (reqs 21-24, D19/D20); spec `workstream/specification-prd-dependency-update-agent.md` §8.1/§8.2; test plan `workstream/test-plan-dep-update-agent.md` (SC-18/19/20, AC-24/25/27); task list `workstream/tasks-prd-dependency-update-agent-plan.md` task 2.0
- **Delivered artifacts inspected:** `agents/dependency-update/app/dependencyUpdate/toolchain.py`, `validator.py`, `config.py`, `tests/unit/test_toolchain.py`, `tests/unit/test_validator.py`, `tests/conftest.py`
- **Output file:** `workstream/fidelity-report-72.md`
- **AC coverage status:** 11/11 covered
- **Overall fidelity verdict:** High
- **Highest drift impact:** Minor
- **Blocking gaps:** None
