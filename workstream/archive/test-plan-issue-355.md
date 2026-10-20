# Test Plan — Issue #355: time-boxed pip-audit exception for CVE-2026-59951

**Status:** Ready for implementation. SG-1 **accepted** by product-engineer on 2026-10-20: #355 v1.1 adds AC-2a (fail-closed) and AC-2b (offline component test), and adopts the `AUDIT_TODAY` / `audit-exception-check` seam.
**Mode:** verifier Design Mode · **Input type:** story (issue body)
**Source:** [#355](https://github.com/llipe/dev-tasks-agent-fleet/issues/355) refined body (2026-10-19) · follow-up [#360](https://github.com/llipe/dev-tasks-agent-fleet/issues/360)
**Traceability:** [`traceability-matrix-issue-355.md`](traceability-matrix-issue-355.md)

## 1. Source summary

`security-analyst` CI fails because `pip-audit . --strict` flags `mcp` 1.29.0 (CVE-2026-59951). `semgrep` pins `mcp==1.29.0` exactly, so nothing can be upgraded today. #355 adds an exception to the agent's `make audit` that ignores only that CVE and stops working after 2026-10-26 UTC. It also switches the CI audit step to `make audit`.

Non-goals: isolating semgrep, bumping semgrep (#360), and any change to `dependency-update`'s audit flags.

## 2. Acceptance criteria

| AC | Requirement (from #355) |
| --- | --- |
| AC-1 | `security-analyst` `make audit` passes today and ignores **only** CVE-2026-59951. Any other vulnerability still fails `--strict`. |
| AC-2 | Expiry is enforced. A past `AUDIT_EXCEPTION_EXPIRES` makes the target exit non-zero and print a message referencing #360. |
| AC-3 | The CI audit step runs `make audit` for both matrix agents. All four `python-quality` jobs and `panel-quality` are green. |
| AC-4 | `dependency-update` `make audit` is unchanged (no `--ignore-vuln`). |
| AC-5 | The Makefile comment states the CVE, the reason, the expiry date, and links #355 and #360. |
| AC-6 | FR-49a: the PR updates a runbook or explains in its description why none is needed. |

Business rules:
- BR-1: the exception fails closed. Once it expires, or if the expiry value is invalid, the gate must go red.
- BR-2: the boundary is calendar-day, in UTC. 2026-10-26 is the last passing day.

## 3. Spec gap found during design (route to `product-engineer`)

**SG-1: the expiry check in the refined snippet fails open.** It uses `[ "$(date -u +%Y%m%d)" -gt "$(AUDIT_EXCEPTION_EXPIRES)" ]`. If `AUDIT_EXCEPTION_EXPIRES` is empty, non-numeric, or written with dashes (e.g. `2026-10-26`), `[` fails with "integer expression expected". The `if` then takes the false branch and pip-audit runs **with the ignore**, so the exception never expires. I reproduced this locally for `""`, `2026-10-26` and `abc`. A typo during renewal (path C in #360) would make the exception permanent without anyone noticing. That breaks BR-1.

Proposed requirement (AC-2a): the target **MUST** exit non-zero unless `AUDIT_EXCEPTION_EXPIRES` matches `^[0-9]{8}$`. E2E-2d through E2E-2f test it.

**Testability seam (recommended, not required by the issue).** To test the date boundary without changing the system clock or running pip-audit, the developer SHOULD:
- add an overridable `AUDIT_TODAY ?= $(shell date -u +%Y%m%d)`;
- move the check into its own target, e.g. `audit-exception-check`, that `audit` depends on.

The tests below assume this seam. Without it, E2E-2a and E2E-2c can only be checked by temporarily editing the date.

## 4. E2E scenarios (black-box: observed through `make` exit code and output)

Run from `agents/security-analyst/app/securityAnalyst/` unless noted. Scenarios marked *(offline)* don't run pip-audit and can be automated in pytest.

| ID | AC | Type | Given / When | Then |
| --- | --- | --- | --- | --- |
| E2E-1a | AC-1 | + | Current lockless install; `make audit` | exit 0; output lists no vulnerabilities apart from the ignored one |
| E2E-1b | AC-1 | − | `make -n audit` *(offline)* | the recipe has exactly one `--ignore-vuln`, its value is `CVE-2026-59951`, and `--strict` is still present |
| E2E-1c | AC-1 | − | Throwaway venv with `pip-audit==2.10.1`; `pip-audit -r <(printf 'requests==2.19.0\nmcp==1.29.0\n') --strict --ignore-vuln CVE-2026-59951` | exit ≠ 0; `requests` advisories are reported; `mcp` CVE-2026-59951 is not |
| E2E-2a | AC-2 | + | `make audit-exception-check AUDIT_TODAY=20261026 AUDIT_EXCEPTION_EXPIRES=20261026` *(offline)* | exit 0 (the last valid day passes) |
| E2E-2b | AC-2 | − | `make audit AUDIT_EXCEPTION_EXPIRES=20200101` | exit ≠ 0; stderr/stdout contains `CVE-2026-59951`, `20200101` and `#360`; pip-audit **does not run** |
| E2E-2c | AC-2 | − | `make audit-exception-check AUDIT_TODAY=20261027 AUDIT_EXCEPTION_EXPIRES=20261026` *(offline)* | exit ≠ 0 (first day after expiry) |
| E2E-2d | AC-2a | − | `AUDIT_EXCEPTION_EXPIRES=` (empty) *(offline)* | exit ≠ 0 (fail closed) |
| E2E-2e | AC-2a | − | `AUDIT_EXCEPTION_EXPIRES=2026-10-26` *(offline)* | exit ≠ 0 |
| E2E-2f | AC-2a | − | `AUDIT_EXCEPTION_EXPIRES=abc` *(offline)* | exit ≠ 0 |
| E2E-2g | AC-2 | + | Default value, real clock, before 2026-10-27 UTC | `make audit-exception-check` exit 0 |
| E2E-3a | AC-3 | + | PR CI run | the `Dependency audit` step shows `run: make audit` in all 4 `python-quality` jobs; all 5 jobs green |
| E2E-3b | AC-3 | − | `make -C agents/dependency-update/app/dependencyUpdate -n audit` | target exists and resolves to `pip-audit . --strict` (CI won't hit "No rule to make target") |
| E2E-3c | AC-3 | + | Repo root `make audit-py` | exit 0 for both agents. The root aggregate already delegates to the agent Makefiles, so CI and local now run the same command |
| E2E-4a | AC-4 | − | `git diff origin/main -- agents/dependency-update/` | empty |
| E2E-4b | AC-4 | − | `grep -c -- '--ignore-vuln' agents/dependency-update/app/dependencyUpdate/Makefile` | `0` |
| E2E-5a | AC-5 | + | `grep` the security-analyst Makefile | contains `CVE-2026-59951`, `GHSA-84m7-p3x7-pcfv`, `20261026`, `#355`, `#360`, and the reason (`semgrep` pins `mcp==1.29.0`) |
| E2E-5b | AC-5 | − | Compare the date in the comment with the `AUDIT_EXCEPTION_EXPIRES` value | they match. A stale comment date counts as drift |
| E2E-6a | AC-6 | + | PR description / diff | either a runbook under `docs/runbooks/` is updated, or the description has an explicit FR-49a "no runbook needed" rationale |

## 5. Contract scenarios

The contract here is between CI and the agent Makefiles: every `matrix.agent` must expose an `audit` target that exits non-zero on any unignored vulnerability.

| ID | AC | Check |
| --- | --- | --- |
| CT-1 | AC-3 | Every entry in `ci.yml` `matrix.include[].package-dir` has a Makefile with an `audit:` target (`make -C <dir> -n audit` exit 0) |
| CT-2 | AC-3, AC-4 | Exit-code contract: `make audit` returns pip-audit's exit code unchanged. The recipe has no `|| true` and no `-` prefix |
| CT-3 | AC-1 | The flag contract is pinned to `pip-audit==2.10.1`: `--ignore-vuln` accepts a CVE ID. pip-audit matches `--ignore-vuln` against advisory aliases, so the ignore still holds if the service reports the vuln as `GHSA-84m7-p3x7-pcfv` or a `PYSEC-*` ID. Verify by running E2E-1a and confirming the vuln is listed as ignored or skipped, not reported |

## 6. Edge-case catalog

| # | Category | Edge case | AC | Covered by |
| --- | --- | --- | --- | --- |
| 1 | Input domain | Empty, dashed or non-numeric expiry value fails open | AC-2a | E2E-2d–2f |
| 2 | Input domain | Expiry overridden on the command line in CI (`make audit AUDIT_EXCEPTION_EXPIRES=...`) | AC-2 | Review: `ci.yml` must call bare `make audit` with no overrides |
| 3 | State transition | Exception active → expired on 2026-10-27; gate flips red without a code change (intended) | AC-2 | E2E-2c |
| 4 | State transition | Renewal (#360 path C) changes only the date | AC-2 | E2E-5b (comment and value stay in sync) |
| 5 | Timing | UTC vs local day: in UTC-3, 2026-10-26 21:00 local is already 10-27 UTC | AC-2 | `date -u` asserted in the recipe; E2E-2c |
| 6 | Timing | macOS BSD `date` vs GNU `date` | AC-2 | `date -u +%Y%m%d` works on both. Run E2E-2g on macOS and in CI |
| 7 | Idempotency | `make audit` run twice gives the same result | AC-1 | E2E-1a run twice |
| 8 | Failure modes | pip-audit can't reach the vulnerability service (network) | AC-1 | Must exit non-zero, i.e. stay fail-closed. Expected pip-audit behavior, not changed by this issue. Observe only |
| 9 | Failure modes | A **new** vuln in any package appears during the window | AC-1 | E2E-1c (the ignore is specific to one ID) |
| 10 | Failure modes | `mcp` is upgraded early (semgrep relaxes its pin) and the ignore becomes unused | AC-1 | pip-audit doesn't fail on an unused ignore. Removing it is tracked by #360, so not a defect here |
| 11 | Auth/permissions | N/A: no auth surface | — | — |
| 12 | Data boundaries | Makefile recipe uses spaces instead of tabs (the issue snippet is indented inside Markdown) | AC-1, AC-2 | `make -n audit` succeeds (E2E-1b) |
| 13 | Resource exhaustion | N/A: the CVE's resource-exhaustion path isn't reachable, because semgrep's MCP server is never started | — | Recorded as residual risk |
| 14 | Versioning | Repo-root `make audit-py` and CI must run the same command | AC-3 | E2E-3c |

## 7. Randomized tactics

**RT-1 (property, offline): fail-closed expiry predicate.** For any `AUDIT_TODAY` and `AUDIT_EXCEPTION_EXPIRES`, `make audit-exception-check` exits 0 **iff** both values match `^[0-9]{8}$` and `AUDIT_TODAY <= AUDIT_EXCEPTION_EXPIRES`.
- Generator: 200 cases.
  - 60% valid 8-digit date pairs near the boundary (±3 days of each other).
  - 40% malformed values: empty, dashed, 7 or 9 digits, alphabetic, trailing whitespace, `-1`.
  - Leading whitespace is **excluded** from the malformed partition: `make` strips it from command-line variable values, so ` 20261026` arrives as a valid `20261026` (observed while checking SG-1). In the reference oracle, apply `lstrip()` before validating.
- Seed: `random.Random(355)`. Record the seed in the test ID, and print the failing `(today, expires)` pair on failure.
- Replay: `pytest tests/component/test_audit_exception.py -k property --seed 355`. If no `--seed` plugin exists, the seed is a module constant: `SEED = 355`.
- Oracle: the reference predicate in Python, compared with `make`'s exit code.
- Fuzz and contract fuzzing are N/A, since there's no user-input surface beyond these two variables.

## 8. Test-first implementation order

1. **Red:** add `tests/component/test_audit_exception.py` (security-analyst).
   - It calls `make -s audit-exception-check` through `subprocess.run` with an explicit env and `cwd`.
   - Cases: E2E-2a, 2c–2f, plus RT-1.
   - It doesn't run pip-audit, so it stays offline, in line with TESTING.md's no-network rule.
   - Add E2E-1b by parsing `make -n audit`.
   - These must fail before the Makefile change. #360 removes this file when the exception is deleted.
2. **Green:** change the Makefile with the seam and the fail-closed regex check. Then change `ci.yml` line 61 to `make audit`.
3. **Manual / CI:** E2E-1a, 1c, 2b, 2g, 3a–3c, 4a–4b, 5a–5b, 6a, CT-1–CT-3.

## 9. Execution checklist

- [x] SG-1 accepted by `product-engineer` (#355 v1.1, 2026-10-20)
- [ ] Red tests committed before the implementation commit
- [ ] Offline tests pass under `make test-cov` (coverage floor 90% unaffected, since the tests don't touch Python sources)
- [ ] E2E-1a, 1c, 2b run locally; outputs pasted in the PR
- [ ] CI: 5/5 jobs green (E2E-3a)
- [ ] AC-4 diff check empty
- [ ] FR-49a rationale or runbook present
- [ ] Audit Mode run after implementation → `workstream/fidelity-report-issue-355.md`

Residual risk (accepted by #355, non-blocking): `mcp` 1.29.0 ships in the image until #360 is resolved.
