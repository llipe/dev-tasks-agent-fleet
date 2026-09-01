# Compliance Test Plan — Issue #98: run dies during `validate` step without reporting terminal status

- **Repository:** `llipe/dev-tasks-agent-fleet`
- **Issue:** [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98)
- **Source artifact:** `workstream/issue-98-validate-step-no-terminal-report-refinement.md`
- **Input type:** `story` (refined issue)
- **Mode:** Design (test-first, pre-implementation)
- **Companion:** `workstream/traceability-matrix-issue-98.md`

## Changelog

| Version | Date       | Summary                                                            | Author   |
| ------- | ---------- | ------------------------------------------------------------------ | -------- |
| 1.0     | 2026-08-31 | Initial compliance test plan. Derived from the #98 refinement ACs. | verifier |

## 1. Source Input Summary

The `dependency-update` agent's `@app.entrypoint invoke()` is an async generator that yields **only** at terminal points. During a long-running step (notably `validate` running `pnpm test`), the HTTP response stream is idle and AgentCore reclaims the container at `idleRuntimeSessionTimeout: 300s`, before the agent can write a terminal status. Three timeout clocks are mutually inconsistent (`TEST_TIMEOUT=600 > idleRuntimeSessionTimeout=300`). The fix (Option A) is periodic heartbeat yields to keep the stream alive + reconciling the clocks to the invariant `TOOL_COMMAND_TIMEOUT ≤ TEST_TIMEOUT ≤ container idle/lifetime ≤ reaper threshold (3720s)`, with a best-effort terminal flush and reaper as documented backstop.

## 2. Acceptance Criteria (from refinement)

- **AC1** — Root cause recorded with evidence (CloudWatch clean-silence, `RunReporter.__exit__` always-terminal contract, three-clock inconsistency), referenced from the #94 runbook.
- **AC2** — A `validate` step whose test run exceeds 5 minutes completes without the container being reclaimed.
- **AC3** — An `llm_fix` run exceeding 20 minutes reaches an agent-written terminal status (not a reaper `timed_out`).
- **AC4** — `TEST_TIMEOUT`, `TOOL_COMMAND_TIMEOUT`, `idleRuntimeSessionTimeout`, `maxLifetime`, and Supabase `max_runtime_seconds`/`grace_seconds` are mutually consistent per the ordering invariant and documented.
- **AC5** — Heartbeat chunks are distinguishable from the terminal result payload and do not break consumer-side result parsing; the terminal payload stays last.
- **AC6** — Best-effort terminal flush on SIGKILL where technically possible; otherwise documented that the reaper is the sole backstop.

### Observability note (black-box surfaces)

Because this is an agent-runtime behavior, the "observable behavior" is defined by these external surfaces rather than a UI/HTTP API:

- **The AgentCore HTTP response stream** — sequence of emitted chunks (heartbeats + terminal payload).
- **The Supabase `runs` row** — terminal `status`/`outcome`/`error_code`/`finished_at` and who wrote it (agent vs. reaper `error_code=RUNTIME_TIMEOUT`).
- **The Supabase `run_events` / `run_steps`** — step lifecycle and event stream.
- **CloudWatch container logs** — presence/absence of idle-reclamation and terminal-report lines.
- **The committed config values + docs** — the reconciled clock invariant.

## 3. E2E Scenarios

### SC-1: Long `validate` completes without container reclamation (happy path)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-2 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | Heartbeat + reconciled clocks deployed. A target repo whose `pnpm test` runs 6–8 min. |
| **Steps** | 1. Insert `queued` run (control plane). 2. Invoke the agent. 3. Observe the response stream + CloudWatch during `validate`. |
| **Expected Result** | Heartbeat chunks emitted throughout `validate`; container not reclaimed; run reaches an agent-written terminal `status`. |
| **Pass Criteria** | `runs.finished_at` set with `status ∈ {succeeded, failed}` and `error_code ≠ RUNTIME_TIMEOUT`; CloudWatch shows terminal-report line, no idle-reclamation silence. |

### SC-2: Long `llm_fix` run (>20 min) reaches agent-written terminal status (happy path)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-3 |
| **Type** | happy-path |
| **Severity** | critical |
| **Preconditions** | Deployed fix; a repo whose full `llm_fix` cycle exceeds 20 min. |
| **Steps** | 1. Insert `queued` run. 2. Invoke in `llm_fix` mode. 3. Let it run >20 min. 4. Inspect terminal state + reaper. |
| **Expected Result** | Agent writes the terminal status before the reaper threshold; `run_steps` all closed. |
| **Pass Criteria** | `runs.status` terminal, written by agent (`error_code ≠ RUNTIME_TIMEOUT`); no reaper `run_events` row with `data.reaped_by=reap_stale_runs`. |

### SC-3: Silent-death regression (negative path — the original defect)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-2, AC-3, AC-6 |
| **Type** | negative-path |
| **Severity** | critical |
| **Preconditions** | Mocked long-running `validate` in a component harness (no real model/network). |
| **Steps** | 1. Drive the entrypoint with a `validate` that blocks longer than the heartbeat interval. 2. Capture emitted stream chunks. |
| **Expected Result** | At least one heartbeat chunk is emitted before the terminal payload; the run is never left with no terminal report on a normal exit. |
| **Pass Criteria** | Component test asserts ≥1 heartbeat chunk interleaved AND a terminal payload emitted last. Fails on the pre-fix behavior (zero interim chunks). |

### SC-4: Clock inconsistency is rejected (negative path)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-4 |
| **Type** | negative-path |
| **Severity** | major |
| **Preconditions** | Clock-consistency assertion implemented. |
| **Steps** | 1. Set `TEST_TIMEOUT` greater than the configured container idle bound (fixture/env). 2. Run the consistency check/test. |
| **Expected Result** | The check fails loudly, preventing the inconsistent configuration from shipping. |
| **Pass Criteria** | Unit test fails when `TEST_TIMEOUT > container idle bound`; passes when the invariant holds. |

### SC-5: Consumer parses terminal payload despite heartbeats (happy path)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-5 |
| **Type** | happy-path |
| **Severity** | major |
| **Preconditions** | Heartbeat chunk shape defined. |
| **Steps** | 1. Produce a stream = [heartbeat, heartbeat, terminal]. 2. Run the consumer-side parse (`unwrap_payload` / result reader). |
| **Expected Result** | Heartbeat chunks are ignored; the terminal result payload is read correctly. |
| **Pass Criteria** | Parser returns the terminal payload fields (`status`/`outcome`/`error_code`), unaffected by preceding heartbeat chunks. |

### SC-6: Root-cause evidence is documented (happy path / documentation)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-1 |
| **Type** | happy-path |
| **Severity** | major |
| **Preconditions** | Fix + docs delivered. |
| **Steps** | 1. Review `docs/runbooks/issue-94-reaper-verification.md` and `docs/technical-guidelines.md`. |
| **Expected Result** | The three evidence strands (CloudWatch silence, `__exit__` contract, three-clock inconsistency) are recorded and cross-referenced from the #94 runbook. |
| **Pass Criteria** | Doc review confirms all three strands present + cross-reference link exists. |

### SC-7: SIGKILL best-effort backstop (negative path)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-6 |
| **Type** | negative-path |
| **Severity** | major |
| **Preconditions** | Best-effort flush handler implemented (if technically possible). |
| **Steps** | 1. Simulate an interceptable termination signal (e.g., SIGTERM) mid-run in a harness. 2. Observe whether a terminal report attempt is made. |
| **Expected Result** | On an interceptable signal, a best-effort terminal report is attempted (secrets scrubbed); on true SIGKILL, docs state the reaper is the sole backstop. |
| **Pass Criteria** | Handler invoked on SIGTERM; docs explicitly note reaper-only for SIGKILL. |

## 4. Contract Validation Scenarios

The boundary under contract is the **AgentCore response-stream chunk contract** consumed by the caller and the **terminal result payload** shape.

### CT-1: Heartbeat chunk shape is valid and non-terminal

| Field | Value |
| --- | --- |
| **AC(s)** | AC-5 |
| **Contract type** | provider-driven |
| **Boundary** | AgentCore response stream chunk |
| **Direction** | event-payload |
| **Input** | A heartbeat chunk emitted mid-step |
| **Expected Result** | Chunk is structurally valid, flagged/typed as non-terminal, and carries no result fields that could be mistaken for the terminal payload. |
| **Pass Criteria** | Consumer classifies it as heartbeat (not terminal); no `status`/`outcome` misread. |

### CT-2: Terminal payload unchanged (schema-compat)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-5 |
| **Contract type** | schema-compat |
| **Boundary** | terminal result payload (`build_return_payload` output) |
| **Direction** | response |
| **Input** | Terminal payload after a run with heartbeats |
| **Expected Result** | Same required fields as before this change (`status`, `outcome`, `error_code`, plus metrics) — heartbeat addition does not alter the terminal schema. |
| **Pass Criteria** | Terminal payload validates against the pre-existing shape; it is the final chunk. |

### CT-3: Terminal payload is always last (ordering contract)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-5 |
| **Contract type** | provider-driven |
| **Boundary** | response stream ordering |
| **Direction** | event-payload |
| **Input** | Full stream of a completed run |
| **Expected Result** | Exactly one terminal payload, emitted as the last chunk; no heartbeat after it. |
| **Pass Criteria** | Last chunk is terminal; count of terminal chunks == 1. |

### CT-4: No DB migration / `error_code` remains free-form (schema-compat)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-4, AC-6 |
| **Contract type** | schema-compat |
| **Boundary** | Supabase `runs` table |
| **Direction** | persistence |
| **Input** | Terminal write from agent + reaper write |
| **Expected Result** | No new enum/check on `error_code`; agent-written and reaper-written codes coexist; no migration required. |
| **Pass Criteria** | `001_schema.sql` unchanged for `error_code`; both write paths succeed. |

## 5. Edge-Case Catalog

All 9 categories evaluated.

### EC-1: Test run duration exactly at the idle boundary (Data Boundaries)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-2, AC-4 |
| **Category** | Data Boundaries |
| **Input / Setup** | `validate` whose test run lasts ~ the `idleRuntimeSessionTimeout` value (e.g., 299 s, 300 s, 301 s). |
| **Expected Result** | Heartbeat keeps the stream alive across the boundary; run completes at all three durations. |
| **Risk if Missed** | Off-by-one at the exact idle boundary reintroduces silent death for borderline suites. |

### EC-2: Heartbeat interval ≥ idle timeout (Timing & Concurrency)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-2, AC-4 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | Misconfigure `HEARTBEAT_INTERVAL` ≥ `idleRuntimeSessionTimeout`. |
| **Expected Result** | Consistency check flags it (heartbeat must be safely below idle timeout, e.g. ≤ half). |
| **Risk if Missed** | A heartbeat that fires too late never resets the idle clock — silent death returns despite the "fix". |

### EC-3: `audit_only` short run — no spurious heartbeats (State Transitions)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-5 |
| **Category** | State Transitions |
| **Input / Setup** | `fix_mode=audit_only` run that finishes in seconds. |
| **Expected Result** | Terminal payload emitted; zero or minimal heartbeats; no orphaned heartbeat task after the early `return`. |
| **Risk if Missed** | Heartbeat task leaks past the terminal `return`, emitting a chunk after the terminal payload (violates CT-3). |

### EC-4: Early-return branches during a step (State Transitions)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-5, AC-6 |
| **Category** | State Transitions |
| **Input / Setup** | Runs hitting each `yield ... return` branch: `audit_only`, no-changes update, validation-failed, mandate-violation. |
| **Expected Result** | Each terminal branch stops heartbeats cleanly and emits exactly one terminal payload last. |
| **Risk if Missed** | Double-terminal or heartbeat-after-terminal on the less-travelled branches. |

### EC-5: Exception during a heartbeated step (Failure Modes)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-6 |
| **Category** | Failure Modes |
| **Input / Setup** | Raise an exception mid-`validate` while heartbeats are active. |
| **Expected Result** | Heartbeat stops; `RunReporter.__exit__` still writes `failed` + closes open steps; a terminal payload is yielded. |
| **Risk if Missed** | Heartbeat task interferes with exception propagation, losing the terminal report. |

### EC-6: Heartbeat does not flood logs/stream (Resource Exhaustion)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-2 |
| **Category** | Resource Exhaustion |
| **Input / Setup** | A 30-minute step at the chosen interval. |
| **Expected Result** | Emitted chunk count is bounded and proportional (`≈ duration / interval`), not per-second. |
| **Risk if Missed** | R5 write-volume blowup; noisy stream/logs. |

### EC-7: Secret scrubbing on best-effort flush (Auth & Permissions)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-6 |
| **Category** | Auth & Permissions |
| **Input / Setup** | Trigger the best-effort flush with tokens present in `secrets`. |
| **Expected Result** | Any flushed message/traceback is scrubbed of tokens (reuses `scrub`). |
| **Risk if Missed** | Installation token / service-role key leaked into a terminal report or CloudWatch. |

### EC-8: Heartbeat vs. reaper threshold coherence (Timing & Concurrency)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-3, AC-4 |
| **Category** | Timing & Concurrency |
| **Input / Setup** | A run approaching `maxLifetime` (3600 s) vs. reaper threshold (3720 s). |
| **Expected Result** | Container lifetime and reaper threshold are coherent — the agent gets its full lifetime and the reaper is the outer bound, not a competitor. |
| **Risk if Missed** | Reaper marks `timed_out` while the container is still legitimately working, or the container outlives the reaper window. |

### EC-9: `"0 packages changed"` yet proceeds to `validate` (State Transitions — pre-existing anomaly)

| Field | Value |
| --- | --- |
| **AC(s)** | AC-1 |
| **Category** | State Transitions |
| **Input / Setup** | Reproduce the observed run where `has_changes(workspace)` is truthy despite a logged 0 package-change count. |
| **Expected Result** | The inconsistency is characterized (log vs. change-detection mismatch) and recorded; fixed if trivial, else flagged as a follow-up. |
| **Risk if Missed** | Confusing operator logs persist; masks whether `validate` should have run at all. |

### N/A categories

- **Input Domain** — N/A: this issue changes runtime/streaming behavior, not a user-input field surface (payload validation is covered by #97).
- **Idempotency** — Partially covered by EC-3/EC-4 (single terminal payload); no new idempotent request surface introduced.
- **API Versioning** — N/A: no external API version change; the `agentcore` CLI version interaction is #97's scope.

## 6. Randomized Tactics and Seed Policy

Seed format: `<tactic-type>-<AC-id>-<unix-timestamp>-<hex4>`. Replay: `pytest -k <tactic-id> --seed=<seed>` (or the harness equivalent). Failure triage per the `verifier` Failure Triage Workflow; max 3 non-reproducing retries before `inconclusive`.

### RT-1: Property — a terminal payload always terminates the stream, for any step duration

| Field | Value |
| --- | --- |
| **AC(s)** | AC-2, AC-5 |
| **Tactic type** | property-based |
| **Input surface** | Randomized mocked step durations (0 s … 40 min) across all pipeline branches |
| **Property / Oracle** | For every run: exactly one terminal payload, emitted last; ≥1 heartbeat iff duration > interval; no chunk after terminal. |
| **Iterations** | 200 |
| **Seed** | `prop-AC5-{timestamp}-{hex}` |
| **Replay instruction** | `pytest -k rt1_terminal_last --seed=<seed> --iterations=1` |
| **Shrink strategy** | Reduce step duration to the minimal value that breaks the "terminal-last" invariant. |

### RT-2: Property — heartbeat interval always < idle bound after config load

| Field | Value |
| --- | --- |
| **AC(s)** | AC-4 |
| **Tactic type** | property-based |
| **Input surface** | Randomized env combos of `TEST_TIMEOUT`, `HEARTBEAT_INTERVAL`, container idle bound |
| **Property / Oracle** | Consistency check accepts iff `HEARTBEAT_INTERVAL < idle_bound` AND `TEST_TIMEOUT ≤ idle/lifetime ≤ reaper threshold`; rejects otherwise. |
| **Iterations** | 300 |
| **Seed** | `prop-AC4-{timestamp}-{hex}` |
| **Replay instruction** | `pytest -k rt2_clock_invariant --seed=<seed> --iterations=1` |
| **Shrink strategy** | Binary-search the offending value toward the boundary. |

### RT-3: Fuzz — malformed/interleaved chunks do not fool the consumer parser

| Field | Value |
| --- | --- |
| **AC(s)** | AC-5 |
| **Tactic type** | fuzz |
| **Input surface** | Stream sequences with random counts/orderings of heartbeat-like chunks around one terminal payload |
| **Property / Oracle** | Consumer never returns a heartbeat as the result; always resolves to the single terminal payload; never raises on well-formed heartbeats. |
| **Iterations** | 500 |
| **Seed** | `fuzz-AC5-{timestamp}-{hex}` |
| **Replay instruction** | `pytest -k rt3_parser_fuzz --seed=<seed> --iterations=1` |
| **Shrink strategy** | Delta-debug the chunk sequence to the minimal failing arrangement. |

## 7. Execution Checklist

- [ ] Every AC maps to ≥1 positive and ≥1 negative/edge test (see traceability matrix).
- [ ] Layer 1 (unit): heartbeat scheduler/emitter, terminal-last invariant, clock-consistency assertion, secret-scrub on flush.
- [ ] Layer 2 (component, `test_pipeline.py`): heartbeat interleaving with mocked long `validate`; all early-return branches; consumer parser ignores heartbeats.
- [ ] Randomized tactics RT-1..RT-3 wired with seed capture + replay.
- [ ] Live/manual (deployed AgentCore): SC-1 (>5 min `validate`), SC-2 (>20 min `llm_fix`) with CloudWatch + Supabase evidence attached to the issue/PR.
- [ ] `make validate` (lint + format:check + typecheck + test-cov + audit) passing.
- [ ] Empirical confirmation of `idleRuntimeSessionTimeout` semantics recorded (gates whether heartbeat alone suffices).

## 8. Coverage Status

All 6 ACs covered by at least one positive and one negative/edge scenario. AC2 and AC3 require live execution (deployed AgentCore) for full verification; component-level proxies (SC-3, RT-1) cover them pre-deploy. No AC is uncovered. Status: **covered**.
