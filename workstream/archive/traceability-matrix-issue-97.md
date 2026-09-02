# Traceability Matrix — Issue #97: `unwrap_payload` double-wrap fix

- **Mode:** Design (verifier)
- **Repository:** `llipe/dev-tasks-agent-fleet`
- **Issue:** [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97)
- **Companion:** `workstream/test-plan-issue-97.md`

## Changelog

| Version | Date       | Summary                                             | Author   |
| ------- | ---------- | --------------------------------------------------- | -------- |
| 1.0     | 2026-08-31 | Initial AC → test-case mapping for refined #97.     | verifier |

## AC → Test-Case mapping

Format: `AC-ID -> Test-Case-ID -> Observed-Result (to be filled at execution) -> Pass/Fail/Drift`. In Design Mode, Observed-Result is `pending`.

| AC    | Positive test(s)             | Negative / edge test(s)                          | Test IDs                                | Observed | Status  |
| ----- | ---------------------------- | ------------------------------------------------ | --------------------------------------- | -------- | ------- |
| AC-1  | E2E-1, E2E-6, CT-1, PB-1     | EC-11 (do-not-over-unwrap boundary)              | E2E-1, E2E-6, CT-1, PB-1, EC-7, EC-8, EC-11 | pending  | pending |
| AC-2  | E2E-2, E2E-3, CT-5           | EC-1, EC-2, EC-3, EC-10, EC-5, EC-6, PB-3        | E2E-2, E2E-3, CT-5, EC-1, EC-2, EC-3, EC-5, EC-6, EC-10, PB-3 | pending  | pending |
| AC-3  | E2E-4 (wrapper-only signal)  | E2E-5, EC-9, EC-13, EC-14, EC-15, CT-2, CT-4     | E2E-4, E2E-5, CT-2, CT-3, CT-4, EC-9, EC-13, EC-14, EC-15 | pending  | pending |
| AC-4  | E2E-2/E2E-3 (bare/single), E2E-1 (double) | E2E-4 (wrapper-only)                | E2E-1, E2E-2, E2E-3, E2E-4 (bare/single/double/wrapper-only shapes) | pending  | pending |
| AC-5  | EC-16 (README verbatim)      | EC-17 (#77 runbook preamble-only edit)           | EC-16, EC-17                            | pending  | pending |

## Business-rule coverage

| Rule | Description                                              | Covered by                     |
| ---- | ------------------------------------------------------- | ------------------------------ |
| BR-1 | Repeated unwrap terminates on all fallback shapes       | CT-5, PB-2, PB-3, EC-4, EC-8, EC-10, EC-11, EC-12 |
| BR-2 | No new error code / no schema migration                 | CT-2, CT-3                     |
| BR-3 | AC-3/AC-4 assertable without the coverage-excluded orchestrator | §7 design recommendation + CT-4 assertion at helper seam |

## Coverage summary

- ACs total: **5** — covered: **5** — uncovered: **0**.
- Every AC has ≥1 positive and ≥1 negative/edge test. **Coverage: complete.**
- Randomized tactics (PB-1..PB-3) seed-pinned (`97_0831`) with deterministic replay.
