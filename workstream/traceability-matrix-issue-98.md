# Traceability Matrix — Issue #98: run dies during `validate` step without reporting terminal status

- **Repository:** `llipe/dev-tasks-agent-fleet`
- **Issue:** [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98)
- **Test plan:** `workstream/test-plan-issue-98.md`
- **Source artifact:** `workstream/issue-98-validate-step-no-terminal-report-refinement.md`

## Changelog

| Version | Date       | Summary                                                                                       | Author   |
| ------- | ---------- | --------------------------------------------------------------------------------------------- | -------- |
| 1.0     | 2026-08-31 | Initial AC-to-test mapping for all 6 ACs.                                                     | verifier |
| 1.1     | 2026-09-01 | Audit Mode: populated Observed-Result / Pass·Fail·Drift for all 6 ACs against PR #103 delivery. | verifier |

## AC → Test Case Mapping

Every AC has ≥1 positive and ≥1 negative/edge test. `Observed-Result` and `Pass/Fail/Drift` are populated during Audit Mode after implementation.

| AC | Positive test(s) | Negative / edge test(s) | Test level | Observed-Result | Pass/Fail/Drift |
| --- | --- | --- | --- | --- | --- |
| **AC1** — root cause recorded w/ evidence | SC-6 (doc review) | EC-9 (`0 packages changed` anomaly) | Doc review + manual | All three evidence strands present: CloudWatch clean-silence on run `f63ac9f3-…` (tech-guidelines §8 + runbook §3/Known-limitations §1), the `RunReporter.__exit__` always-terminal contract (tech-guidelines §8 "Abrupt-termination backstop"), and the four-clock inconsistency table (tech-guidelines §8). Cross-referenced from `issue-94-reaper-verification.md` Known-limitations §1. EC-9 characterized: `main.py` `update` step log clarified to explain working-tree-vs-lockfile mismatch, citing "issue #98 EC-9". | **Pass** |
| **AC2** — long `validate` survives | SC-1 (live >5 min) | SC-3 (silent-death regression), EC-1 (boundary), EC-2 (interval ≥ idle), EC-6 (no flood), RT-1 | Component + live + property | Pre-deploy proxies **Pass**: `validate` runs under `run_with_heartbeat` live-yielding chunks (main.py); component `TestEntrypointHeartbeatWiring.test_slow_validate_emits_heartbeats_and_terminal_last` drives real `main.invoke` and asserts ≥1 heartbeat + terminal-last + agent-written `succeed`; EC-6 bound test + RT-1 (40 iters) pass. Defense-in-depth: `idleRuntimeSessionTimeout` raised 300→900 in `agentcore.json`. Live >5 min run (SC-1) **not executed — blocked on AgentCore redeploy** (task 1.21). | **Pass (pre-deploy proxy); live verification Blocked** |
| **AC3** — long `llm_fix` reaches agent-written terminal | SC-2 (live >20 min) | SC-3, EC-8 (reaper coherence), RT-1 | Component + live | Pre-deploy proxies **Pass**: `llm_fix` step also wrapped in `run_with_heartbeat` (main.py); same component harness exercises the llm_fix path to an agent-written terminal; EC-8 reaper-coherence covered by the clock invariant (`MAX_LIFETIME 3600 ≤ REAPER_THRESHOLD 3720`). Live >20 min run (SC-2) **not executed — blocked on AgentCore redeploy** (task 1.22). | **Pass (pre-deploy proxy); live verification Blocked** |
| **AC4** — clocks reconciled & documented | SC-6 (doc), CT-4 (no migration) | SC-4 (inconsistency rejected), EC-1, EC-2, EC-8, RT-2 | Unit + doc + property | `assert_clock_invariant()` enforces `TOOL_COMMAND_TIMEOUT(180) ≤ TEST_TIMEOUT(600) ≤ IDLE_SESSION_TIMEOUT(900) ≤ MAX_LIFETIME(3600) ≤ REAPER_THRESHOLD(3720)` and `0 < HEARTBEAT_INTERVAL(120) ≤ idle/2`; called fail-fast at entrypoint start. `test_clock_invariant.py`: shipped-config consistency, per-relation rejection (SC-4), EC-2 (interval ≥ idle rejected), RT-2 property (300 iters) all pass. Documented as single source of truth in tech-guidelines §8; `agentcore.json` idle=900/maxLifetime=3600 match constants. CT-4: no DB migration (config/entrypoint only). | **Pass** |
| **AC5** — heartbeat distinguishable; terminal last | SC-5 (parse), CT-1, CT-2, CT-3 | SC-3, EC-3 (audit_only), EC-4 (early returns), RT-1, RT-3 (parser fuzz) | Unit + component + property | `heartbeat_chunk` (`{"heartbeat":{...}}`) vs `terminal_chunk` (`event.contentBlockDelta.delta.text`) structurally distinct; `is_heartbeat_chunk`/`is_terminal_chunk`/`read_terminal_payload` classify correctly. `test_heartbeat.py`: CT-1/CT-2/CT-3 (terminal shape preserved + always last), RT-1 terminal-last property, RT-3 fuzz (500 iters) all pass. Component test confirms consumer reads terminal payload despite interleaved heartbeats. **Minor code-consistency drift:** the 5 top-level exception handlers in `main.py` emit the terminal shape as a raw literal instead of calling `terminal_chunk()` — behaviorally identical output (still classified terminal, still last, outside the heartbeat block), so no AC impact. | **Pass (with Minor drift, non-blocking)** |
| **AC6** — best-effort SIGKILL flush / reaper backstop | SC-7 (SIGTERM handler) | EC-5 (exception mid-step), EC-7 (secret scrub), CT-4 | Unit + component + doc | `signal_backstop.py`: SIGTERM handler marks active run `failed / SIGNAL_TERMINATION`, never raises, no-op when already terminal or run is None; installed after `RunReporter` created in main.py. `test_signal_backstop.py`: error-code, already-terminal no-op, EC-7 secret-scrub, reporter-error swallow, None-run, main-thread registration, off-main-thread no-op — all pass. EC-5 (exception mid-step) covered by `test_heartbeat.py` (exception captured in `HeartbeatResult`, re-raised so `__exit__` writes `failed`). SIGKILL-is-reaper-only documented in tech-guidelines §8. | **Pass** |

## Coverage Summary

| Metric | Value |
| --- | --- |
| Total ACs | 6 |
| ACs with ≥1 positive test | 6 / 6 |
| ACs with ≥1 negative/edge test | 6 / 6 |
| Uncovered ACs | 0 |
| ACs requiring live execution | AC2, AC3 (component proxies SC-3/RT-1 cover pre-deploy) |

## Audit Result Summary (Audit Mode, PR #103)

| Metric | Value |
| --- | --- |
| ACs Pass (pre-deploy) | 6 / 6 |
| ACs with residual live verification Blocked | AC2, AC3 (AgentCore redeploy) |
| Drift items | 1 (Minor, Intended, non-blocking) — exception handlers bypass `terminal_chunk()` helper |
| Suite | 416 pass (34 net-new for #98); coverage_gate = PASS |
| Overall fidelity | High |

## Test Case Index

| ID | Title | Type | AC(s) |
| --- | --- | --- | --- |
| SC-1 | Long `validate` completes without reclamation | happy-path | AC2 |
| SC-2 | Long `llm_fix` reaches agent-written terminal | happy-path | AC3 |
| SC-3 | Silent-death regression | negative-path | AC2, AC3, AC6 |
| SC-4 | Clock inconsistency rejected | negative-path | AC4 |
| SC-5 | Consumer parses terminal payload despite heartbeats | happy-path | AC5 |
| SC-6 | Root-cause evidence documented | happy-path | AC1 |
| SC-7 | SIGKILL best-effort backstop | negative-path | AC6 |
| CT-1 | Heartbeat chunk shape valid + non-terminal | contract | AC5 |
| CT-2 | Terminal payload schema unchanged | contract | AC5 |
| CT-3 | Terminal payload always last | contract | AC5 |
| CT-4 | No DB migration / `error_code` free-form | contract | AC4, AC6 |
| EC-1 | Duration at idle boundary | edge | AC2, AC4 |
| EC-2 | Heartbeat interval ≥ idle timeout | edge | AC2, AC4 |
| EC-3 | `audit_only` short run, no spurious heartbeats | edge | AC5 |
| EC-4 | Early-return branches during a step | edge | AC5, AC6 |
| EC-5 | Exception during a heartbeated step | edge | AC6 |
| EC-6 | Heartbeat does not flood logs/stream | edge | AC2 |
| EC-7 | Secret scrubbing on best-effort flush | edge | AC6 |
| EC-8 | Heartbeat vs. reaper threshold coherence | edge | AC3, AC4 |
| EC-9 | `0 packages changed` yet proceeds to `validate` | edge | AC1 |
| RT-1 | Property: terminal payload always terminates stream | property | AC2, AC5 |
| RT-2 | Property: heartbeat interval < idle bound | property | AC4 |
| RT-3 | Fuzz: malformed/interleaved chunks | fuzz | AC5 |
