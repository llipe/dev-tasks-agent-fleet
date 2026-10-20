# Traceability Matrix — Issue #355

Source: [#355](https://github.com/llipe/dev-tasks-agent-fleet/issues/355) · Plan: [`test-plan-issue-355.md`](test-plan-issue-355.md)
Observed Result / Pass-Fail-Drift are filled in by verifier Audit Mode after implementation.

| AC-ID | Requirement | Positive tests | Negative / edge tests | Observed Result | Pass/Fail/Drift |
| --- | --- | --- | --- | --- | --- |
| AC-1 | Audit passes; ignores only CVE-2026-59951 | E2E-1a, CT-3 | E2E-1b, E2E-1c, EC-9, EC-12 | pending | pending |
| AC-2 | Expiry enforced, message refs #360 | E2E-2a, E2E-2g | E2E-2b, E2E-2c, EC-5, EC-6 | pending | pending |
| AC-2a *(SG-1, accepted v1.1)* | Malformed/empty expiry or date fails closed | RT-1 (valid partition) | E2E-2d, E2E-2e, E2E-2f, RT-1 (malformed partition) | pending | pending |
| AC-2b *(SG-1, accepted v1.1)* | Offline component test written first | `tests/component/test_audit_exception.py` exists and passes | It fails on the pre-change Makefile (red commit precedes green) | pending | pending |
| AC-3 | CI runs `make audit`; 5/5 jobs green | E2E-3a, E2E-3c | E2E-3b, CT-1, CT-2, EC-2 | pending | pending |
| AC-4 | dependency-update audit unchanged | E2E-3c | E2E-4a, E2E-4b | pending | pending |
| AC-5 | Comment: CVE, reason, expiry, #355/#360 | E2E-5a | E2E-5b | pending | pending |
| AC-6 | FR-49a runbook or rationale | E2E-6a | E2E-6a (absent → Fail) | pending | pending |

Coverage: 8/8 ACs (#355 v1.1) each have at least one positive and one negative/edge test.
