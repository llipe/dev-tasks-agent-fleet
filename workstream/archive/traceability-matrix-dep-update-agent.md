# Traceability Matrix — Dependency Update Agent

## Changelog

| Version | Date       | Summary         | Author   |
| ------- | ---------- | --------------- | -------- |
| 1.0     | 2026-08-26 | Initial version. Maps all 36 ACs to test cases across 4 layers (E2E, contract, edge-case, randomized). Every AC has ≥1 positive and ≥1 negative/edge test. | verifier |
| 1.1     | 2026-09-11 | **Reconciled against the shipped suite (issue #78).** v1.0 mapped ACs to the *designed* SC/CT/EC/RT case IDs; this revision re-points every row at the **real, runnable test** that asserts it (named `tests/unit/**::test_*` / `tests/component/**::test_*`) or the **operator runbook** step that exercises it. The v1.0 "100% / no gaps" summary counted designed cases; the measured result is **30/36 ACs automated (unit/component), 6 real-infra deferred-to-runbook (listed + accepted), 0 unaccounted**. The `hypothesis`/fuzz layer (RT-*) was **not adopted** and the `-m e2e` harness was **not built** (decisions taken with the user, 2026-09-11); the SC-*/RT-* IDs below are retained as design references. Companion write-backs: `test-plan-dep-update-agent.md` v1.1, `TESTING.md`. | developer |

---

## AC → Real Test Mapping (v1.1 — measured, authoritative)

> Each row cites the **shipped** test(s) that assert the AC, or the runbook step for real-infra ACs.
> Module paths are under `agents/dependency-update/app/dependencyUpdate/`. Class = **(a)** automated
> today · **(c)** real-infra, deferred-to-runbook (accepted). The original design mapping (SC/CT/EC/RT
> IDs) is preserved further below as a reference.

| AC | Real coverage (test name or runbook) | Class |
|----|--------------------------------------|-------|
| AC-1 | Scaffold — `agentcore validate`; deployment verification | (c) runbook |
| AC-2 | Deploy — `agentcore deploy`/`status`; `issue-77-deployment-e2e.md` | (c) runbook |
| AC-3 | `tests/unit/test_outcome_mapping.py::test_clean_no_findings`; `tests/unit/test_audit.py::test_pnpm_clean`, `::test_npm_clean` | (a) |
| AC-4 | `test_outcome_mapping.py::test_findings_fail_on_true_no_major` | (a) |
| AC-5 | `test_outcome_mapping.py::test_findings_fail_on_false` | (a) |
| AC-6 | `test_outcome_mapping.py::test_findings_fail_on_true_with_major`; `test_classifier.py::test_major_increase`, `::test_major_skip` | (a) |
| AC-7 | `test_outcome_mapping.py::test_major_with_fail_on_false` | (a) |
| AC-8 | `test_classifier.py::test_unparseable_patched_range`, `::test_patched_version_not_semver`, `::test_empty_patched_range` | (a) |
| AC-9 | `test_eligibility.py::test_row1_patch_minor_eligible`, `::test_row2_major_increase_ineligible`, `::test_row3_zero_minor_increase_ineligible`, `::test_row4_both_non_semver` (+30 more) | (a) |
| AC-10 | `test_eligibility.py::test_installed_non_semver_target_semver_accept`, `::test_target_non_semver_installed_semver_accept` | (a) |
| AC-11 | `test_eligibility.py::test_zero_to_one_major_increase`, `::test_v_prefix_major_increase`; `test_classifier.py::test_major_increase` | (a) |
| AC-12 | `test_fix_agent.py::test_zero_attempts_no_agent_call`, `::test_marks_llm_used`; `test_pipeline.py::test_extracts_metric_fields`. Live PR + zero-token CloudTrail check → runbook | (a) logic / (c) live half |
| AC-13 | `test_outcome_mapping.py::test_pr_opened_with_major`. Live PR → runbook | (a) logic / (c) live half |
| AC-14 | `test_outcome_mapping.py::test_no_changes_with_major`, `::test_major_beats_fixed_in_llm_fix` | (a) |
| AC-15 | `test_pr_body.py::test_major_section_appears_when_present` | (a) |
| AC-16 | `test_outcome_mapping.py::test_validation_failing_beats_major`, `::test_validation_failing_beats_all` | (a) |
| AC-17 | `test_pr_body.py::test_all_sections_present`, `::test_always_present_sections`, `::test_footer_present` | (a) |
| AC-18 | `test_outcome_mapping.py::test_no_changes_no_major` | (a) |
| AC-19 | `test_pr_creation.py::test_existing_pr_short_circuits`, `::test_returns_url_when_deps_branch_pr_exists`; `test_outcome_mapping.py::test_pr_existed` | (a) |
| AC-20 | `test_fix_agent.py::test_marks_llm_used`, `::test_tools_passed_to_agent`, `::test_system_prompt_passed` | (a) |
| AC-21 | `test_fix_agent.py::test_exhausts_budget`, `::test_stops_early_on_success` | (a) |
| AC-22 | `test_fix_agent.py::test_zero_attempts_no_agent_call` | (a) |
| AC-23 | `test_mandate_check.py::test_caret_major_bump`, `::test_new_dep_added`, `::test_dep_removed` (+10); `test_fix_agent.py::test_violation_detected_after_model_changes` | (a) |
| AC-24 | `test_toolchain.py::test_missing_test_raises_no_test_script`, `::test_no_scripts_at_all_raises_no_test_script`, `::test_ac_no_test_script_fixture` | (a) |
| AC-25 | `test_toolchain.py::test_missing_optional_scripts_listed`, `::test_ac_absent_optional_scripts_surfaced_for_warnings`; `test_validator.py::test_optional_absent_are_skipped_run_continues` | (a) |
| AC-26 | `test_updater.py::test_npm_frozen_uses_ci`, `::test_npm_update`; `test_validator.py::test_command_uses_npm_run`; `test_audit.py::test_npm_*` | (a) |
| AC-27 | `test_toolchain.py::test_no_lockfile_raises_no_package_manager`, `::test_missing_package_json_raises_no_package_manager`, `::test_error_message_names_what_was_searched` | (a) |
| AC-28 | `test_credentials.py::test_reads_pem_from_secrets_manager`, `::test_returns_first_row`; `test_pr_creation.py::test_gh_token_passed_via_env_not_argv`, `::test_credential_helper_no_token_in_remote`. Live JWT→token exchange → runbook | (a) logic / (c) live half |
| AC-29 | `test_credentials.py::test_raises_no_installation_when_empty` | (a) |
| AC-30 | `test_scrubber.py::*` (13); `test_pr_creation.py::test_push_error_scrubs_token`, `::test_list_failure_raises_scrubbed`; `test_signal_backstop.py::test_scrubs_secrets_from_message` | (a) |
| AC-31 | `test_pipeline.py::test_missing_run_id`, `::test_missing_repository_org`, `::test_invalid_payload_returns_invalid_params`, `::test_clamps_max_fix_attempts_upper`, `::test_invalid_max_fix_attempts_type`; `test_payload_contract_fixture.py::*` (covers CT-3–CT-6) | (a) |
| AC-32 | `test_fix_tools.py::test_rejects_traversal`, `::test_rejects_absolute` (read + write); `test_safe_path.py` | (a) |
| AC-33 | Step-status closure asserted (`test_signal_backstop.py`, `test_pipeline.py::test_pull_request_error_carries_code`); **full 9-step ordering in `main.py` is coverage-excluded → verified by inspection + runbook** | (a) partial / (c) sequencing |
| AC-34 | `test_credentials.py::test_transport_failure_raises_credential_error`, `::test_non_connection_request_exception_is_classified`; `test_agent_reporter_start.py::test_*_never_raises*`. Full stderr→CloudWatch fallback → runbook | (a) partial / (c) live half |
| AC-35 | `test_pipeline.py::test_pull_request_error_carries_code`, `::test_handler_payload_shape_for_pr_error`; `test_signal_backstop.py::test_marks_run_failed_with_signal_error_code` | (a) |
| AC-36 | Reaper interlock — **verified 2026-09-01 in `docs/runbooks/issue-94-reaper-verification.md` §4** (static half: `max_runtime_seconds` 3600 = `maxLifetime`; dynamic half: synthetic interlock proof under #101) | (c) runbook — done |

**Measured totals:** 30/36 automated (a); 6 real-infra deferred-to-runbook (AC-1, AC-2, AC-12 live,
AC-28 live, AC-33 sequencing, AC-36 — AC-36 already verified); 0 unaccounted.

---

## AC → Designed-Case Mapping (v1.0 — design reference, retained)

> The original v1.0 mapping to the designed SC/CT/EC/RT case IDs. Retained for design traceability;
> the **authoritative** coverage statement is the measured table above. Note the RT-* (randomized)
> and the `-m e2e` references describe cases that were **not** implemented (see Changelog v1.1).

| AC ID | Description | Positive Tests | Negative/Edge Tests | Layer |
|-------|-------------|---------------|--------------------:|-------|
| AC-1 | Project scaffolding | (Deployment verification — not a runtime test) | — | Manual |
| AC-2 | Deploys successfully | (Deployment verification) | — | Manual |
| AC-3 | audit_only clean | SC-1 | EC-4, EC-24, RT-1 | E2E, Unit, Fuzz |
| AC-4 | audit_only + findings + fail_on | SC-2 | EC-4, EC-7 | E2E, Unit |
| AC-5 | audit_only + findings + !fail_on | SC-3 | EC-9 | E2E, Unit |
| AC-6 | Major-only advisory detected | SC-4 | EC-7, EC-9, EC-20, RT-2 | E2E, Unit, Fuzz |
| AC-7 | fail_on_findings=false wins | SC-5 | SC-4 (contrast) | E2E |
| AC-8 | Unparseable → unknown | SC-6 | EC-9, RT-2 | E2E, Unit, Fuzz |
| AC-9 | Version eligibility table | SC-31, RT-3, RT-4 | SC-33, EC-10, RT-4 | Unit, Fuzz |
| AC-10 | Non-semver accepted + reported | SC-32 | SC-33 | E2E, Unit |
| AC-11 | Non-semver not a loophole | SC-33 | — (itself is negative) | Unit |
| AC-12 | llm_fix happy path | SC-7 | EC-5, EC-8, EC-21, EC-25 | E2E, Unit |
| AC-13 | Major-only + work to land | SC-13 | SC-15 (precedence) | E2E |
| AC-14 | Major-only, nothing to land | SC-14 | — | E2E |
| AC-15 | PR body names gap | SC-35 | EC-27 | E2E, Unit |
| AC-16 | Precedence: VALIDATION > MAJOR | SC-15 | — (itself is negative) | E2E |
| AC-17 | PR body completeness | SC-34 | EC-27 | E2E, Unit |
| AC-18 | No-change no-op | SC-8 | EC-8 | E2E |
| AC-19 | Idempotency | SC-9 | EC-6 | E2E |
| AC-20 | LLM fires | SC-10 | SC-11, SC-12, EC-15, EC-16 | E2E, Unit |
| AC-21 | LLM budget respected | SC-11 | — (itself is negative) | E2E |
| AC-22 | LLM disabled | SC-12 | — (itself is negative) | E2E |
| AC-23 | Mandate violation caught | SC-25 | — (itself is negative) | Unit, Component |
| AC-24 | Test script required | SC-19 | — (itself is negative) | E2E |
| AC-25 | Optional scripts reported | SC-20 | — | E2E |
| AC-26 | npm parity | SC-21 | EC-3, EC-10, EC-18 | E2E, Unit |
| AC-27 | Unknown toolchain | SC-18 | EC-1, EC-2 | E2E, Unit |
| AC-28 | GitHub App auth | SC-29, CT-7, CT-11, CT-12 | EC-12, EC-22 | E2E, Contract |
| AC-29 | Unknown org | SC-17 | — (itself is negative) | E2E, Component |
| AC-30 | No credential in logs | SC-22, SC-23, RT-6 | EC-11 | E2E, Fuzz |
| AC-31 | Invalid payload fast-fail | SC-16, CT-3–CT-6 | EC-23, EC-24, RT-1 | E2E, Contract, Fuzz |
| AC-32 | Path escape refused | SC-24 | EC-16, EC-19 | Unit |
| AC-33 | Step stream complete | SC-26, CT-8, CT-9 | EC-14, EC-28 | E2E, Contract, Unit |
| AC-34 | Reporting outage survivable | SC-27 | EC-13 | E2E, Component |
| AC-35 | Unhandled failure recorded | SC-28 | — (itself is negative) | Component |
| AC-36 | Reaper interlock | SC-36 | — | E2E (manual) — **fully exercised.** Static half: #77 task 7.13 (`max_runtime_seconds` 3600 = `maxLifetime` 3600). Dynamic half: verified 2026-09-01 under [#101](https://github.com/llipe/dev-tasks-agent-fleet/issues/101) via the runbook §4.4 synthetic interlock proof — a `running` row with real thresholds (3600/120) stayed un-reaped with zero `reaped_by` events across several cron ticks while healthy, then reaped to `timed_out` once `started_at` was backdated past the 3720 s boundary (threshold-driven, not indiscriminate). Cold-start gap measured ≈ 4.2 s ≪ `grace_seconds=120` (§4.1 `date -u` method), resolving PRD open question 8. The real 20+ min `llm_fix` framing (blocked by [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98)) was superseded by the synthetic proof. See `docs/runbooks/issue-94-reaper-verification.md` §4. |

---

## Coverage Summary (v1.1 — measured)

> The v1.0 table below counted **designed** cases. The measured, authoritative figures are:

| Metric | Value |
|---|---|
| Total ACs | 36 |
| ACs with real automated (unit/component) coverage | **30 (83%)** |
| ACs real-infra, deferred-to-runbook (listed + accepted) | **6** — AC-1, AC-2, AC-12 (live), AC-28 (live), AC-33 (9-step sequencing), AC-36 (already verified) |
| ACs unaccounted | **0** |
| Shipped tests (collected) | 460 (450 test functions), 18 unit + 3 component modules |
| Runnable markers | `unit`, `component` (no `e2e`, no `fuzz`; `hypothesis` not a dependency) |

### v1.0 designed-case counts (reference only — not implemented as marked layers)

| Metric | Value |
|---|---|
| Total designed E2E scenarios | 36 (→ operator runbook, not a pytest layer) |
| Total designed contract scenarios | 12 (covered as unit/component) |
| Total designed edge cases | 28 (automatable subset covered; real-infra subset → runbook) |
| Total designed randomized tactics | 6 (**not adopted**) |

---

## Gap Analysis (v1.1 — measured)

**No unaccounted gaps. Six ACs are real-infra and deliberately deferred to the operator runbook**,
each listed with rationale — this is an *accepted, documented* deferral, not a silent gap:

- **AC-1, AC-2** — scaffolding/deployment provisioning; verified via `agentcore validate`/`deploy`/`status` and `issue-77-deployment-e2e.md`. Not runtime behavior; automating them would require a live AgentCore deploy.
- **AC-12 (live half), AC-28 (live half)** — the *logic* is unit/component tested (zero-token metrics; installation-token flow, token-in-env-not-argv, credential-helper). The *live* halves (a real PR appearing in a repo; a real JWT→installation-token exchange against GitHub; CloudTrail `bedrock:InvokeModel` absence) need real AWS/Supabase/GitHub → runbook.
- **AC-33 (sequencing half)** — step-status *closure* is tested; the full 9-step ordering lives in `main.py`, which is `coverage`-excluded (`pyproject.toml [tool.coverage.run] omit = ["main.py"]`), so ordering is verified by inspection + runbook. Tracked as a known gap in `TESTING.md`.
- **AC-36** — reaper interlock; **already verified** 2026-09-01 in `issue-94-reaper-verification.md` §4 (static + synthetic-dynamic proof under #101).

**Why the randomized layer (RT-1–RT-6) was not built (#78 decision):** the invariants those tactics
target are already covered by dense table-driven unit tests — `test_eligibility.py` (34), `test_classifier.py`
(27), `test_scrubber.py` (13) — and `test_heartbeat.py` already contains property-style/fuzz-style tests
(`test_terminal_signal_always_terminates_for_random_durations`, `test_fuzz_random_heartbeat_arrangements_never_mislead_parser`)
without adding `hypothesis`. Adding `hypothesis` is a new dev dependency that must keep `pip-audit --strict`
green, for marginal gain over the existing coverage.

---

## Coverage Summary (v1.0 — original, superseded by v1.1 above)

| Metric | Value |
|---|---|
| Total ACs | 36 |
| ACs with ≥1 positive test | 36 (100%) |
| ACs with ≥1 negative/edge test | 36 (100%) |
| Total E2E scenarios | 36 |
| Total contract scenarios | 12 |
| Total edge cases | 28 |
| Total randomized tactics | 6 |
| **Overall coverage** | **100%** |

---

## Gap Analysis (v1.0 — original, superseded by v1.1 above)

**No gaps identified.** Every acceptance criterion maps to at least one positive and one negative/edge-case test. Two ACs (AC-1, AC-2) are deployment-verification criteria tested manually via `agentcore validate` / `agentcore deploy` + `agentcore status` rather than automated runtime tests — this is appropriate for their nature (infrastructure provisioning, not runtime behavior).

---

## Non-Goals Verification

The following PRD non-goals are confirmed NOT tested (scope respected):

- [ ] Major-version bumps — no test attempts a major bump
- [ ] Python/pip support — no test uses pip/uv
- [ ] Yarn — no test uses yarn
- [ ] Merging PRs — no test merges
- [ ] Scheduled invocation — no test uses a schedule
- [ ] Cancellation — no test cancels a running agent
- [ ] Cross-repo fan-out — each test targets one repo
- [ ] Monorepo workspace filtering — no test uses `--filter`
- [ ] Phase 2 panel UI — no browser/UI tests
