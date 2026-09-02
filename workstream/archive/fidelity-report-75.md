# Fidelity Report — Issue #75: LLM Fix Agent Escape Hatch

## 1. Header / Verdict

- **Overall fidelity: HIGH**
- **Highest drift impact present: Minor**
- **Scope:** Issue #75 · Draft PR #85 · branch `issue/75-llm-fix-agent-escape-hatch` · base `main` · repo `llipe/dev-tasks-agent-fleet`
- **Mode:** Audit (grey-box) · **Gate:** additive, non-blocking
- **Quality gates (reported upstream):** lint / format:check / typecheck / audit clean; 288 tests pass; qa `coverage_gate: PASS` (fix_agent.py 91%)
- **Targeted suite re-run during this audit:** 63 passed (`test_safe_path`, `test_mandate_check`, `test_fix_tools`, `test_fix_agent`)

The escape-hatch feature is faithfully delivered. Seven of the eight audited requirements are **Met** with direct code evidence and passing tests. One requirement (req 52) is **Partial** — the values exist and are returned from the entrypoint, but are not persisted to the `runs.metrics` column; this coincides with the acknowledged deferral tied to #76/#77 and is non-blocking.

## 2. Human-Readable Summary (what changed and why)

Issue #75 adds the "escape hatch": when a dependency update leaves the project's checks (lint/format/typecheck/tests) broken, the agent hands control to an AI helper that can edit **source code** — and only source code — to make the checks pass again. Everything else in the pipeline stays deterministic; the AI is deliberately reachable from exactly one place.

The delivered work does what was asked:

- The AI is only called when validation fails after an update, and only in the mode that is allowed to open PRs. It is never used to judge vulnerabilities, pick versions, or write the PR text.
- The AI gets exactly five tools (run a command, read a file, write a file, find files, search files). Every tool that takes a file path refuses to touch anything outside the project checkout — no reading `/etc/passwd`, no writing above the workspace, symlink escapes are blocked too.
- The AI is told, in plain rules, that it may not disable tests, roll back the dependency update, or widen version ranges to dodge an error.
- Because a written instruction is not a guarantee, there is a hard backstop: after the AI runs, the agent checks `package.json` and, if the AI changed any dependency version, the run is stopped as a `MANDATE_VIOLATION` and **no** pull request is opened.
- The AI gets a bounded number of tries (`max_fix_attempts`), re-checking after each try, and if it succeeds the static checks are re-run because the AI may have edited files after they last passed.

Two acceptance criteria are intentionally left for later work: recording the test-output tail as an artifact when the AI runs out of tries (needs the #76 artifact/PR plumbing), and fully writing the "was the AI used / how many tries" numbers into the run's metrics column (the numbers are already produced and returned, just not persisted). Both are legitimately out of scope for #75.

## 3. Per-Requirement Result Table

| Req | Description | Codebase evidence | Test evidence | Result |
| --- | --- | --- | --- | --- |
| 44 | LLM invoked ONLY on "validation failed after update in llm_fix mode"; not happy path, not classification | `main.py:566` guard `if not val_result.passed and params["max_fix_attempts"] > 0`, inside llm_fix-only branch (audit_only returns at `main.py:475`); classification is deterministic (`classify_advisories`, no Agent call) | `test_fix_agent.py::TestMaxAttemptsZero` (0 attempts → Agent never constructed); pipeline audit_only paths never touch fix loop | **Met** |
| 45 | Exactly 5 tools, no more | `fix_agent.py:75,108,132,155,188` — five `@tool` fns: shell/read_file/write_file/find_files/grep_code; `run_fix_loop` passes `tools=[...]` of length 5 (`fix_agent.py:410`) | `test_fix_agent.py::TestToolCalls::test_tools_passed_to_agent` asserts `len==5` and exact name set | **Met** |
| 46 | Every path-taking tool resolves against workspace root and refuses escapes | `_safe_path` (`fix_agent.py:47`) rejects absolute, `..` traversal, and symlink escape via `realpath` prefix check; `read_file`/`write_file` route through it; `find_files`/`grep_code`/`shell` are cwd-confined to `_WORKSPACE` | `test_safe_path.py` (traversal/absolute/symlink/null-byte); `test_fix_tools.py` (read/write reject `../../etc/passwd`, absolute) | **Met** |
| 47 | System prompt forbids weakening tests, rolling back deps, widening ranges / major bumps | `FIX_AGENT_SYSTEM_PROMPT` (`fix_agent.py:225`) rules 1-5 cover test-weakening, version rollback, range widening/major bump, dep add/remove, lockfile edits | `test_fix_agent.py::test_system_prompt_passed` asserts prompt content passed to Agent | **Met** |
| 48 | Fix loop bounded by max_fix_attempts; re-validates after each attempt | `run_fix_loop` (`fix_agent.py:376`) `for attempt in range(1, max_attempts+1)`, `run_validation(...)` after each attempt, breaks on pass | `test_fix_agent.py::TestRetryBudget` (exhausts budget = 3; stops early on success = 2) | **Met** |
| 49 | On fix success, re-run lint/format/typecheck | `rerun_static_checks_after_fix` (`main.py:200`) runs lint+format+typecheck, preserves test result; called at `main.py:576` guarded by `val_result.passed and val_result.llm_used` | Helper is unit-shaped/testable; exercised via pipeline; note main.py excluded from coverage (see Drift D3) | **Met** |
| 50 | package.json specifier change → MANDATE_VIOLATION, no PR (enforcement, not just prompt) | `verify_no_mandate_violation` (`fix_agent.py:296`) detects add/remove/change; `check_mandate` (`main.py:230`) + terminal path `main.py:588-602` returns `failed`/`needs_review`/`MANDATE_VIOLATION` and `return`s before `open_pr` | `test_mandate_check.py` (widened/added/removed/multiple); `test_fix_agent.py::TestMandateIntegration` | **Met** |
| 52 | llm_used and fix_attempts recorded in `runs.metrics` | Values set on `ValidationResult` (`fix_agent.py:398-399`) and placed in the **entrypoint return payload** via `build_return_payload` (`main.py:311`, req 63). **Not** written to the `runs.metrics` jsonb column — no `run.succeed(metrics=...)`/`run.fail(metrics=...)` call in `main.py` passes `metrics=` | Return-payload values covered indirectly; no test asserts `runs.metrics` persistence | **Partial** |

## 4. Drift Catalog

> All drift below is **non-blocking** to PR/issue completion (Audit Mode is additive).

### D1 — req 52: metrics returned but not persisted to `runs.metrics`
- **Description:** `llm_used`/`fix_attempts` are computed and returned in the entrypoint payload (satisfies req 63), but `agent_reporter`'s `succeed(metrics=...)`/`fail(metrics=...)` channel — the path that writes the `runs.metrics` jsonb column named by req 52 — is never invoked with these values in `main.py`.
- **Impact class:** Minor. **Intent class:** Intended (matches the caller's stated "full runs.metrics population" deferral, dependent on #76/#77 wiring).
- **Evidence:** `main.py:367,590,651` (`run.succeed`/`run.fail` called without `metrics=`); `agent_reporter.py:215-225` (metrics params exist and are unused by caller); spec §6.2 lines 252-255 (return-payload path is the one implemented).
- **Recommendation:** `developer` — wire `metrics={"llm_used": ..., "fix_attempts": ..., "packages_changed": ...}` into the terminal `run.succeed`/`run.fail` calls when the run-completion path is finalized under #76/#77. Route through `product-engineer` `activity-drift-reconciliation` for changelog/task write-back.

### D2 — req 51: test-output-tail artifact on budget exhaustion not emitted
- **Description:** On `VALIDATION_FAILING` after budget exhaustion the run correctly terminates `failed`/`needs_review`/`VALIDATION_FAILING` with no PR (`main.py:626-645`), but the required `run_artifacts` row carrying the test-output tail is not created.
- **Impact class:** Minor. **Intent class:** Intended (out of scope for #75 — artifact plumbing lands with #76; `open_pr`/artifact path is an explicit stub at `main.py:638-642`).
- **Evidence:** `main.py:626` (VALIDATION_FAILING return, no `run.artifact(...)`); task plan 6.x owns PR/artifact work.
- **Recommendation:** `no action needed` for #75; track under #76. Confirm the artifact obligation is carried in #76's task list.

### D3 — req 49/50 wiring in `main.py` is coverage-excluded
- **Description:** `main.py` is listed in `[tool.coverage.run] omit` (`pyproject.toml:92`), so the fix-loop wiring, the req-49 re-check call site, and the req-50 terminal path are not measured by the 91% figure (which is `fix_agent.py`). The helpers (`rerun_static_checks_after_fix`, `check_mandate`) are extracted specifically to be testable, but no test asserts the main-orchestrator guard ordering (e.g., that req-49 re-check runs before the req-50 mandate gate, and that mandate failure returns before `open_pr`).
- **Impact class:** Minor. **Intent class:** Undetermined (coverage omit of `main.py` is a pre-existing project choice, not introduced by #75; the ordering is correct by reading, but unguarded by test).
- **Evidence:** `pyproject.toml:88-93`; `main.py:576` (req49) precedes `main.py:588` (req50) precedes `main.py:638` (open_pr) — correct by inspection.
- **Recommendation:** `developer` (optional hardening) — add a component test that drives `invoke`'s fix branch with mocked steps to lock the req49→req50→open_pr ordering; or `no action needed` if orchestrator coverage is deliberately deferred to #77 E2E.

### D4 — req 50 baseline is post-update, not literal "pre-update state"
- **Description:** req 50 text says specifiers must be "unchanged from the **pre-update state**", but the snapshot (`main.py:564`) is taken **after** `update_packages` (`main.py:508`). This is deliberate and arguably more correct: `pnpm/npm update` bumps only within declared ranges (`updater.py:64-79`), so a literal pre-update baseline would false-positive on the legitimate update, whereas the post-update baseline isolates exactly the LLM's changes — which is the true intent of req 50 / req 47 / D25.
- **Impact class:** Minor. **Intent class:** Intended (implementation serves intent better than the literal wording).
- **Evidence:** `main.py:508` (update) → `main.py:564` (snapshot) → fix loop → `main.py:588` (check); `updater.py:73` (`update` stays in-range).
- **Recommendation:** `product-engineer` — clarify req 50 wording to "unchanged from the post-deterministic-update state (i.e., detect only LLM-introduced changes)" so spec and code agree. No code change needed.

## 5. Deferred Acceptance Criteria — Scope Confirmation

Both criteria the caller flagged are **legitimately out of scope for #75**:

1. **Test-output artifact on budget exhaustion (part of req 51):** depends on the artifact/PR-creation plumbing owned by **#76** (`open_pr` is an explicit stub at `main.py:638-642`, task plan 6.x). The terminal `VALIDATION_FAILING` verdict itself is correctly implemented; only the artifact emission is deferred.
2. **Full `runs.metrics` population (req 52 persistence):** the metric values are produced and returned in the entrypoint payload today; persisting them into `runs.metrics` naturally lands with the run-completion/E2E wiring in **#76 / #77**. Non-blocking.

Neither deferral undermines the #75 core deliverable (the bounded, sandboxed, mandate-enforced escape hatch).

## 6. Edge-Case / Randomized Outcomes

No Design-Mode test plan was supplied for this scope, so this section reflects the delivered test suite only. Notable covered edges: path traversal / absolute / symlink / null-byte (`test_safe_path.py`); mandate add/remove/change/multiple/malformed-json/missing-file (`test_mandate_check.py`); `max_attempts=0` → zero LLM calls, budget exhaustion, early success, agent-exception resilience (`test_fix_agent.py`). No randomized/fuzz tactics were in scope.

## 7. Recommendations Summary

| Item | Owner | Action |
| --- | --- | --- |
| D1 — persist metrics to `runs.metrics` | `developer` | Wire `metrics=` into terminal `run.succeed`/`run.fail` under #76/#77 |
| D2 — test-output artifact (req 51) | (deferred) | Track under #76; no action for #75 |
| D3 — orchestrator ordering test | `developer` (optional) | Add component test locking req49→req50→open_pr, or defer to #77 E2E |
| D4 — req 50 wording | `product-engineer` | Clarify "pre-update" → "post-deterministic-update" baseline; no code change |

**Verdict: HIGH fidelity.** The escape hatch is delivered with correct invocation gating, exact tool surface, enforced path sandboxing, prompt constraints, a bounded re-validating loop, post-success static re-checks, and a hard mandate-violation backstop that blocks PR creation. Remaining drift is Minor and Intended, aligned with the #76/#77 deferrals. Non-blocking to completion.
