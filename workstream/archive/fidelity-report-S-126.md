# Fidelity Report — S-126: Severity normalization (`severity.py`)

**Fidelity: High**
**Highest drift impact present: Minor**
**Scope:** Issue #186 / Story S-126, PR #219 (`story/S-126-severity-normalization` → `integration/security-analyst-agent`)

## Human-Readable Summary

This story teaches the agent how to translate five different security scanners' own severity
labels (or lack of any) into one common critical/high/medium/low scale, so downstream logic
(pass/fail decisions, reporting) can treat all five tools uniformly. The mapping table itself —
which scanner value becomes which normalized severity — was checked row by row against the
approved specification and matches exactly, including the two "no signal available" fallback
cases (Trivy's `UNKNOWN`, Checkov's routine no-severity case) and CodeQL's two-step fallback
(numeric score, then text level, then the shared floor). A rule that nothing in this module should
read free-text descriptions or messages — only the specific named fields — was also independently
confirmed by reading every function body.

One deliberate change from the specification's literal example code was called out by the
developer in advance: the Semgrep function was made more defensive than the spec's example so
that an unrecognized severity value falls back to a safe default instead of crashing the whole
run. That fix was verified to work exactly as claimed. However, the same defensive change was
also quietly made to the Checkov function, and that one was not flagged, documented, or tested
the way the Semgrep one was — it is very likely a good and intentional consistency choice (the
same reasoning applies to both), but the story's paper trail treats it as if only one function
changed. This is a paperwork/coverage gap, not a behavioral concern; nothing in the observable,
spec-documented mapping table changed for either function.

Every quality gate the developer reported (tests, coverage, lint, formatting, type-checking, and
a dependency vulnerability scan) was independently re-run in this audit rather than taken on
trust, and all reproduced the same passing result.

## Per-AC / Requirement Result Table

| AC-ID | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
|---|---|---|---|---|---|
| PRD AC12a | All five tools' severity mappings match PRD §7.4b's table exactly, including both unknown-severity-floor paths and CodeQL's dual fallback | `severity.py` read line-by-line and each of the 5 functions' literal in-table values diffed against §7.4b's table text (Semgrep ERROR/WARNING/INFO; Gitleaks unconditional; Trivy 4-level pass-through + UNKNOWN; Checkov pass-through + absent-field case; CodeQL `security-severity` thresholds (≥9.0/≥7.0/≥4.0) + `level` fallback + dual-absent case) — exact match, no row omitted or altered | Task list 2.1–2.6 all marked done; traceability matrix SC-20/RT-4; test plan §RT-4 baseline | `tests/unit/test_severity.py` (44 cases) independently re-run: **44 passed**, `severity.py` at 100% statement+branch coverage (independently measured, not just reported) | **Pass** |
| PRD req 61 | No function inspects free-text rule metadata beyond the fields named in §7.4b's table | Every function signature inspected directly: `severity_from_semgrep(raw_severity: str)`, `severity_from_gitleaks(_finding: dict)` (body returns `Severity.CRITICAL` unconditionally, never touches the dict), `severity_from_trivy(raw_severity: str)`, `severity_from_checkov(raw_severity: str \| None)`, `severity_from_codeql(security_severity: float \| None, level: str \| None)` — no function reads a `message`, `description`, or other free-text field | Task 2.8 marked done | `TestNoFreeTextMetadataInspection` class (6 tests) — signature-shape assertions plus a direct Gitleaks test injecting a `Description` field containing the words "critical"/"low"/"severity" and confirming zero effect on the result — independently re-run: pass | **Pass** |
| Semgrep-totality deviation (PR-disclosed) | `severity_from_semgrep` uses `.get(..., floor)` instead of spec §8.1a's literal raw dict indexing, to close the KeyError gap flagged by the S-125 audit (RT-4) | `severity.py` lines 42-55 confirmed to use `.get(raw_severity, _UNKNOWN_SEVERITY_FLOOR)`; module docstring (lines 11-20) and function docstring both document the deviation and cite RT-4 | Test plan RT-4 explicitly names this as the discrepancy to fix, not replicate; PR body discloses it | Independently reproduced: `severity_from_semgrep("bogus")` returns `Severity.MEDIUM`, no `KeyError` raised; `TestSemgrepIsTotal` (5 out-of-table values) re-run: pass; confirmed no in-table value's output changed (ERROR/WARNING/INFO still high/medium/low) | **Pass** — deviation closes the KeyError gap as claimed, is documented in code, and does not alter any documented in-table mapping |
| Checkov defensive-`.get()` (undisclosed twin of the above) | Spec §8.1a's literal `severity_from_checkov` also uses raw indexing (`{...}[raw_severity]`) for the non-`None` branch, which would raise `KeyError` on an out-of-table non-`None` value; the delivered code uses the same `.get(..., floor)` pattern here too | `severity.py` lines 86-103: `mapping.get(raw_severity, _UNKNOWN_SEVERITY_FLOOR)` — confirmed by direct read and by executing `severity_from_checkov("bogus")` → `Severity.MEDIUM`, no error | **Not mentioned** anywhere: not in the module docstring, not in the PR body's "Spec deviation" callout, not in test plan RT-4 (which names only Semgrep), not in a dedicated regression-test class analogous to `TestSemgrepIsTotal` | No test exercises an out-of-table **non-`None`** Checkov value (e.g. `"bogus"`) — only the `None`-absent case is tested. Verified by ad-hoc execution in this audit, not by the shipped suite | **Drift** (see catalog below) |

## Drift Catalog

| # | Description | Impact | Intent | Evidence | Non-blocking note |
|---|---|---|---|---|---|
| D1 | `severity_from_checkov` silently carries the same defensive `.get(..., floor)` fix as `severity_from_semgrep` for an out-of-table, non-`None` raw value — a second, real deviation from spec §8.1a's literal raw-indexing pseudocode — but it is undocumented (not in the module docstring's deviation note, not in the PR body, not in test-plan RT-4's baseline) and untested (no case covers a Checkov value like `"bogus"` that is neither `None` nor one of the four named levels) | Minor | Undetermined (very likely intentional/good — same reasoning as the disclosed Semgrep fix — but never explicitly confirmed the way Semgrep's was, per this audit's brief) | `severity.py` lines 86-103 vs. spec §8.1a lines 411-415; `tests/unit/test_severity.py` `TestSeverityFromCheckov` (only covers `None` and the 4 named values, no out-of-table non-`None` case); PR #219 body and module docstring (mention only the Semgrep deviation) | Drift is non-blocking to PR/issue completion; does not gate merge; does not replace `test`/`lint`/`format:check`/`typecheck`/`audit` gates, all of which independently passed |

No other drift found. AC12a's table match, requirement 61's field-scoping, and the disclosed Semgrep deviation are all confirmed **Pass** with no discrepancy between codebase, workstream artifacts, tests, and PRD/spec intent.

## Independently Re-Run Quality Gates

| Gate | Command | Result |
|---|---|---|
| Unit tests (full suite) | `python -m pytest -q` | 80 passed (matches PR-reported count, includes pre-existing S-125 suites) |
| Unit tests (severity only) | `python -m pytest tests/unit/test_severity.py -q` | 44 passed (matches PR-reported count) |
| Coverage (severity.py) | `python -m pytest tests/unit/test_severity.py --cov=severity --cov-report=term-missing -q` | 100% statement, 100% branch (33 stmts, 12 branches, 0 missed) |
| Lint | `ruff check .` | All checks passed |
| Format check | `ruff format --check .` | 14 files already formatted |
| Typecheck | `mypy .` | Success: no issues found in 14 source files |
| Dependency audit | `pip-audit . --strict` | No known vulnerabilities found |

## Edge-Case and Randomized Test Outcomes (vs. test-plan baseline)

- **RT-4** (test plan): "Every `severity_from_*` function is total... including out-of-table values, falling to the documented floor," with an explicit flag on the Semgrep KeyError gap. Verified: Semgrep, Trivy, and CodeQL's `level` fallback all have an explicit out-of-table regression test and are confirmed total by direct execution. **Checkov's out-of-table non-`None` case is the one path in RT-4's stated scope ("every `severity_from_*` function," "across its tool's full native-value input space") that has no corresponding test** — this is the same gap as Drift D1, seen from the test-plan angle rather than the code angle.
- **SC-20** (test plan): "Full severity table exercised end-to-end" — confirmed present and passing across all 5 tools' parametrized table-row tests.

## Recommendations

1. **D1 (Checkov undisclosed `.get()` deviation):** Route to `developer` to (a) extend the module docstring's deviation note to cover Checkov alongside Semgrep, (b) add a `TestCheckovIsTotal`-style regression test for an out-of-table non-`None` value (e.g. `"bogus"` or `"UNKNOWN"`), and (c) update PR #219's body to disclose the second deviation explicitly, matching the rigor already applied to Semgrep. Alternatively, if `product-engineer`/planner wants this treated as a spec-level correction (since it mirrors the same requirement-58 "MUST carry a normalized severity" total-function argument used to justify the Semgrep fix), escalate to `product-engineer` for an explicit confirmation note, then have `developer` add the same test/doc coverage.
2. No other action needed — AC12a, requirement 61, the disclosed Semgrep deviation, and all reported quality gates are independently confirmed accurate. **This story is ready to merge into `integration/security-analyst-agent`**; D1 is non-blocking and can be closed out in a fast follow-up commit on the same PR or a subsequent small patch.
