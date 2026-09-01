# Traceability Matrix — Issue #98: run dies during `validate` step without reporting terminal status

- **Repository:** `llipe/dev-tasks-agent-fleet`
- **Issue:** [#98](https://github.com/llipe/dev-tasks-agent-fleet/issues/98)
- **Test plan:** `workstream/test-plan-issue-98.md`
- **Source artifact:** `workstream/issue-98-validate-step-no-terminal-report-refinement.md`

## Changelog

| Version | Date       | Summary                                        | Author   |
| ------- | ---------- | ---------------------------------------------- | -------- |
| 1.0     | 2026-08-31 | Initial AC-to-test mapping for all 6 ACs.      | verifier |

## AC → Test Case Mapping

Every AC has ≥1 positive and ≥1 negative/edge test. `Observed-Result` and `Pass/Fail/Drift` are populated during Audit Mode after implementation.

| AC | Positive test(s) | Negative / edge test(s) | Test level | Observed-Result | Pass/Fail/Drift |
| --- | --- | --- | --- | --- | --- |
| **AC1** — root cause recorded w/ evidence | SC-6 (doc review) | EC-9 (`0 packages changed` anomaly) | Doc review + manual | _pending_ | _pending_ |
| **AC2** — long `validate` survives | SC-1 (live >5 min) | SC-3 (silent-death regression), EC-1 (boundary), EC-2 (interval ≥ idle), EC-6 (no flood), RT-1 | Component + live + property | _pending_ | _pending_ |
| **AC3** — long `llm_fix` reaches agent-written terminal | SC-2 (live >20 min) | SC-3, EC-8 (reaper coherence), RT-1 | Component + live | _pending_ | _pending_ |
| **AC4** — clocks reconciled & documented | SC-6 (doc), CT-4 (no migration) | SC-4 (inconsistency rejected), EC-1, EC-2, EC-8, RT-2 | Unit + doc + property | _pending_ | _pending_ |
| **AC5** — heartbeat distinguishable; terminal last | SC-5 (parse), CT-1, CT-2, CT-3 | SC-3, EC-3 (audit_only), EC-4 (early returns), RT-1, RT-3 (parser fuzz) | Unit + component + property | _pending_ | _pending_ |
| **AC6** — best-effort SIGKILL flush / reaper backstop | SC-7 (SIGTERM handler) | EC-5 (exception mid-step), EC-7 (secret scrub), CT-4 | Unit + component + doc | _pending_ | _pending_ |

## Coverage Summary

| Metric | Value |
| --- | --- |
| Total ACs | 6 |
| ACs with ≥1 positive test | 6 / 6 |
| ACs with ≥1 negative/edge test | 6 / 6 |
| Uncovered ACs | 0 |
| ACs requiring live execution | AC2, AC3 (component proxies SC-3/RT-1 cover pre-deploy) |

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
