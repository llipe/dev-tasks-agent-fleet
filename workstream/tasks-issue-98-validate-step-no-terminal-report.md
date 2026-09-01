# Implementation Plan - Issue #98: run dies during `validate` step without reporting terminal status

- **Repository:** `llipe/dev-tasks-agent-fleet`
- **Issue:** [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98)
- **Refinement:** `workstream/issue-98-validate-step-no-terminal-report-refinement.md`
- **Type:** existing codebase (Python agent) · no Task 0 (deps already installed)

## Relevant Files

- `agents/dependency-update/app/dependencyUpdate/main.py` - `@app.entrypoint invoke()` async generator; add periodic heartbeat yields around long-running steps and a best-effort terminal flush.
- `agents/dependency-update/app/dependencyUpdate/config.py` - Timeout constants (`TEST_TIMEOUT`, `TOOL_COMMAND_TIMEOUT`); add heartbeat interval + any clock-consistency constants.
- `agents/dependency-update/agentcore/agentcore.json` - `idleRuntimeSessionTimeout` / `maxLifetime` lifecycle values to reconcile (operator redeploy).
- `agents/dependency-update/app/dependencyUpdate/validator.py` - `run_validation` / `run_tests` (the long `validate` operation being kept alive); no functional change expected, referenced for interval sizing.
- `agents/dependency-update/app/dependencyUpdate/tests/unit/` - New Layer 1 tests: heartbeat scheduler/generator, clock-consistency assertion, best-effort flush.
- `agents/dependency-update/app/dependencyUpdate/tests/component/test_pipeline.py` - New Layer 2 tests: heartbeat interleaving with a mocked long `validate`, terminal payload stays last, consumer-side parsing ignores heartbeat chunks.
- `docs/technical-guidelines.md` - Document the reconciled three-clock ordering invariant (single source of truth) and the SIGKILL/reaper backstop.
- `docs/runbooks/issue-94-reaper-verification.md` - Cross-reference the #98 root cause from Known limitations §1.
- `workstream/pending-manual-config-dependency-update-agent.md` - Record the AgentCore redeploy step for changed lifecycle values.

## Tasks

- [ ] 1.0 Implement Issue #98 - https://github.com/llipe/dev-tasks-agent-fleet/issues/98: run dies during `validate` step without reporting terminal status

  > Note: Root cause confirmed as AgentCore output-idle timeout reclaiming the container mid-`validate` (async generator yields only at terminal points; stream idle > `idleRuntimeSessionTimeout: 300`). Chosen direction (Option A): heartbeat keep-alive + reconcile the three clocks. OOM is a documented contingency only. No DB migration anticipated.

  ### Investigation / confirmation

  - [ ] 1.1 Confirm AgentCore `idleRuntimeSessionTimeout` semantics empirically (invocation-idle vs. stream-output-idle): run a short live invocation that yields a heartbeat chunk mid-flight and observe whether the idle clock resets. Record the finding. (Resolves the §9 open question; gates whether heartbeat alone suffices or the timeout value must also be raised.)
  - [ ] 1.2 Record the root-cause evidence bundle in the code/docs: CloudWatch clean-silence finding (run `f63ac9f3-…`), the `RunReporter.__exit__` always-terminal contract, and the three-clock inconsistency table.

  ### Heartbeat keep-alive (entrypoint)

  - [ ] 1.3 Add a heartbeat interval constant to `config.py` (env-overridable, default well below 300 s — e.g. 60–120 s), with a clear name (e.g. `HEARTBEAT_INTERVAL`).
  - [ ] 1.4 Implement a heartbeat mechanism in `main.py` that emits lightweight stream chunks on the configured interval while a blocking step (`install` / `audit` / `update` / `validate` / `llm_fix`) is in progress, using the existing async-generator mechanism (no new external dependency).
  - [ ] 1.5 Ensure heartbeat chunks are structurally distinguishable from the terminal result payload, and that the terminal result payload is always the final chunk emitted.
  - [ ] 1.6 Ensure heartbeat logic lives in the entrypoint/orchestration layer, NOT in the byte-identical copied `agent_reporter.py` (preserve D13; do not diverge the copied SDK).
  - [ ] 1.7 Verify heartbeat interacts safely with the `audit_only` early-return path and every terminal `yield ... return` branch (no double-terminal, no orphaned heartbeat task).

  ### Clock reconciliation

  - [ ] 1.8 Update `agentcore/agentcore.json` `idleRuntimeSessionTimeout` (and confirm `maxLifetime`) per the §1.1 finding so the container is not reclaimed during a bounded `TEST_TIMEOUT` run.
  - [ ] 1.9 Reconcile values to the ordering invariant `TOOL_COMMAND_TIMEOUT ≤ TEST_TIMEOUT ≤ container idle/lifetime ≤ reaper threshold (max_runtime_seconds + grace_seconds = 3720 s)`; adjust any value that violates it.
  - [ ] 1.10 Add a unit-level clock-consistency assertion (a test that FAILS if `TEST_TIMEOUT` > the configured container idle bound) so the inconsistency cannot silently regress.

  ### Container-kill backstop

  - [ ] 1.11 Add a best-effort terminal flush on abrupt termination where technically possible (e.g. signal handler / `atexit` that attempts a terminal report), scrubbing secrets; where a SIGKILL genuinely cannot be intercepted, document that the pg_cron reaper is the sole backstop.

  ### Documentation

  - [ ] 1.12 Document the reconciled three-clock ordering invariant as a single source of truth in `docs/technical-guidelines.md` (and/or the agent README), plus the SIGKILL/reaper backstop note.
  - [ ] 1.13 Cross-reference the #98 root cause from `docs/runbooks/issue-94-reaper-verification.md` (Known limitations §1).
  - [ ] 1.14 Record the AgentCore runtime redeploy step (changed lifecycle values are an operator/manual action) in `workstream/pending-manual-config-dependency-update-agent.md`.

  ### Edge cases

  - [ ] 1.15 Investigate and record the `"Update applied: 0 packages changed"`-yet-proceeded-to-`validate` inconsistency (`has_changes(workspace)` returned truthy despite a zero package-change count). Fix only if trivially in-scope; otherwise document and flag for a follow-up issue.
  - [ ] 1.16 Verify heartbeat frequency does not flood the stream/logs (interacts with R5 verbose-execution write volume) — assert a sane upper bound on emitted chunks for a given step duration.

  ### Tests

  - [ ] 1.17 Layer 1 (unit, `pytest`): heartbeat scheduler/generator emits at the configured interval and stops at step boundaries; terminal payload is always the final chunk; clock-consistency assertion (task 1.10); best-effort flush unit (if implemented in 1.11).
  - [ ] 1.18 Layer 2 (component, `pytest`, `test_pipeline.py`): entrypoint driven with a mocked long-running `validate` — heartbeat chunks are interleaved AND a terminal report is still produced; consumer-side parsing (`unwrap_payload` / result parsing) ignores heartbeat chunks and reads the terminal payload correctly (AC5).
  - [ ] 1.19 Run the aggregate gate: `make validate` (lint + format:check + typecheck + test-cov + audit) — all passing. Confirm no coverage regression on `main.py`-adjacent surfaces that are testable.

  ### Acceptance-criteria verification

  - [ ] 1.20 Verify AC1: root cause recorded with evidence (CloudWatch + `__exit__` contract + three-clock inconsistency), referenced from the #94 runbook. (Mapped: tasks 1.2, 1.13; validation = doc review.)
  - [ ] 1.21 Verify AC2: a `validate` step whose test run exceeds 5 minutes completes without container reclamation. (Mapped: manual live run + component test 1.18; validation = live CloudWatch capture confirming no idle reclamation + terminal DB status.)
  - [ ] 1.22 Verify AC3: an `llm_fix` run exceeding 20 minutes reaches an agent-written terminal status (not a reaper `timed_out`). (Mapped: manual live run; validation = Supabase `runs` row terminal status written by agent, `error_code` not `RUNTIME_TIMEOUT`.)
  - [ ] 1.23 Verify AC4: `TEST_TIMEOUT`, `TOOL_COMMAND_TIMEOUT`, `idleRuntimeSessionTimeout`, `maxLifetime`, `max_runtime_seconds`/`grace_seconds` mutually consistent per the ordering invariant and documented. (Mapped: tasks 1.8, 1.9, 1.10, 1.12; validation = unit clock-consistency test + doc review.)
  - [ ] 1.24 Verify AC5: heartbeat chunks distinguishable from terminal result payload and do not break consumer-side result parsing; terminal payload stays last. (Mapped: tasks 1.5, 1.18; validation = component test.)
  - [ ] 1.25 Verify AC6: best-effort terminal flush on SIGKILL where technically possible; otherwise documented that the reaper is the sole backstop. (Mapped: tasks 1.11, 1.12; validation = doc review + best-effort-flush unit if implemented.)

  ### Manual / live verification (requires deployed AgentCore — ties to #77)

  - [ ] 1.26 Deploy the updated AgentCore runtime (operator step per 1.14) and run one real invocation with a >5 min test suite (AC2) and one `llm_fix` run >20 min (AC3); capture CloudWatch + Supabase `runs`/`run_events` evidence and attach to the issue/PR.
