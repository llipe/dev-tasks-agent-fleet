# Traceability Matrix — Issue #355

Source: [#355](https://github.com/llipe/dev-tasks-agent-fleet/issues/355) v1.1 · Plan: [`test-plan-issue-355.md`](test-plan-issue-355.md) · Audit: [`fidelity-report-issue-355.md`](fidelity-report-issue-355.md)
Observed against PR [#381](https://github.com/llipe/dev-tasks-agent-fleet/pull/381), CI run 39446648244.

| AC-ID | Requirement | Positive tests | Negative / edge tests | Observed Result | Pass/Fail/Drift |
| --- | --- | --- | --- | --- | --- |
| AC-1 | Audit passes; ignores only CVE-2026-59951 | E2E-1a, CT-3 | E2E-1b, E2E-1c, EC-9, EC-12 | Local + CI: `No known vulnerabilities found, 1 ignored`. The stub test asserts argv is exactly `. --strict --ignore-vuln CVE-2026-59951`. E2E-1c: `requests==2.19.0` still fails (exit 1) with the ignore active | Pass |
| AC-2 | Expiry enforced, message refs #360 | E2E-2a, E2E-2g | E2E-2b, E2E-2c, EC-5, EC-6 | `AUDIT_TODAY=20261026` passes, `20261027` fails. `make audit AUDIT_EXCEPTION_EXPIRES=20200101` gives exit 2, message cites #360, and the stub shows pip-audit didn't run. `date -u` works on macOS (local) and Ubuntu (CI) | Pass |
| AC-2a | Malformed/empty expiry or date fails closed | RT-1 (valid partition) | E2E-2d/e/f + `202610260`, `-1`, `2026102a`; malformed `AUDIT_TODAY`; RT-1 | All malformed cases exit non-zero. RT-1 passes 100/100 cases with seed 355 | Pass (Minor intended drift: RT-1 runs 100 cases, not 200) |
| AC-2b | Offline component test written first | `test_audit_exception.py`: 17 tests pass | Red commit `beea85c` (16 failed: no rule to make target) comes before green commit `225dabe` | Pass |
| AC-3 | CI runs `make audit`; 5/5 jobs green | E2E-3a, E2E-3c | E2E-3b, CT-1, CT-2, EC-2 | CI log: `Run make audit` in all 4 python jobs; 5/5 success. Root `make audit-py` exit 0. CT-2 stub test: pip-audit exit 1 propagates | Pass |
| AC-4 | dependency-update audit unchanged | E2E-3c | E2E-4a, E2E-4b | `git diff origin/main -- agents/dependency-update/` is empty; `--ignore-vuln` count 0; CI shows `No known vulnerabilities found` | Pass |
| AC-5 | Comment: CVE, reason, expiry, #355/#360 | E2E-5a | E2E-5b | The comment has the CVE, the GHSA, the semgrep/mcp reason, `20261026`, #355, #360, and the test-file pointer. The comment date matches the variable | Pass |
| AC-6 | FR-49a runbook or rationale | E2E-6a | E2E-6a | The PR description explains why no runbook is needed (the one-line `ci.yml` call change has no new operator procedure) | Pass |

Coverage: 8/8 ACs verified.
