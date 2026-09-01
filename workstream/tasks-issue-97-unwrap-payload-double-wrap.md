# Implementation Plan - Issue #97: `unwrap_payload` double-wrap breaks agentcore CLI ≥ 0.28.0 invocations

> Source: `workstream/issue-97-unwrap-payload-double-wrap-refinement.md` · Issue: https://github.com/llipe/dev-tasks-agent-fleet/issues/97
> Repository is a **Python agent** (existing codebase). No JS/TS, no schema/data-model change → no Task 0 and no migration lifecycle. Quality gate: `make validate` (lint + format:check + typecheck + test-cov + audit).

## Relevant Files

- `agents/dependency-update/app/dependencyUpdate/main.py` - `unwrap_payload()` (harden to repeated unwrap) and the streamed entrypoint's wrapper-only log message.
- `agents/dependency-update/app/dependencyUpdate/tests/component/test_pipeline.py` - `TestUnwrapPayload` (add double-wrap + wrapper-only cases); assert the distinct wrapper-only signal.
- `agents/dependency-update/README.md` - §Invocation examples + workaround note (AC5).
- `docs/runbooks/issue-77-deployment-e2e.md` - §E2E validation preamble caveat, §7.7–7.10 (AC5, historical record — preamble only).

## Tasks

- [ ] 1.0 Implement Issue #97 - https://github.com/llipe/dev-tasks-agent-fleet/issues/97: `unwrap_payload` double-wrap fix

  > Note: One unwrap of a CLI-double-wrapped payload leaves `{"prompt": "{...}"}` (dict, only key `prompt`) → passes the current `isinstance(inner, dict)` guard → fails `validate_payload` → `INVALID_PARAMS`. Fix = unwrap repeatedly while the result is a dict whose only key is `prompt` and whose value parses to a JSON dict, plus a distinct log message for the wrapper-only failure.

  ### Implementation
  - [ ] 1.1 Harden `unwrap_payload()` in `main.py`: replace the single-level unwrap with a loop that keeps unwrapping while the value is a dict whose **only** key is `prompt` and whose `prompt` string parses to a JSON dict. Preserve existing fallbacks (non-string `prompt`, non-dict JSON, `JSONDecodeError` → return current value). Ensure guaranteed termination.
  - [ ] 1.2 In the streamed entrypoint (the `validated is None` branch), detect the **wrapper-only** case (post-unwrap payload's only key is `prompt`) and emit a **distinct, actionable** `log.error(...)` naming the double-wrap and pointing at the bare-payload / `--prompt-file` form. Keep `error_code = INVALID_PARAMS` (no new error code, no schema change).
  - [ ] 1.3 Add a code comment / docstring noting the observed `agentcore` CLI version (≥ 0.28.0) that motivated the repeated unwrap, so a future CLI change is easier to spot.

  ### Tests
  - [ ] 1.4 Add unit tests to `TestUnwrapPayload`: **double-wrap** (`{"prompt": "{\"prompt\": \"{...valid inner...}\"}"}`) → returns the inner payload with `run_id`/`repository_org`/`repository_name`.
  - [ ] 1.5 Add unit test: **wrapper-only / no inner fields** (`{"prompt": "{\"prompt\": \"{}\"}"}` or a lone `prompt` with an empty dict) → `unwrap_payload` stops safely and `validate_payload` returns `None`.
  - [ ] 1.6 Add/keep regression tests: **bare** payload and **single-wrap** payload still resolve correctly; existing passthrough / invalid-JSON / non-string-prompt / non-dict-JSON cases still pass unchanged.
  - [ ] 1.7 Add a test asserting the **distinct wrapper-only signal** (the specific log message) is emitted for a wrapper-only payload but **not** for a genuinely-missing-fields payload — assert via the `unwrap_payload`/`validate_payload` seam and captured logs (the `main.py` orchestrator is coverage-excluded).
  - [ ] 1.8 Run tests: `cd agents/dependency-update && pytest -m "unit or component" tests/component/test_pipeline.py -q` (or the package's canonical test target).

  ### Docs (AC5)
  - [ ] 1.9 Update `agents/dependency-update/README.md` §Invocation: make the pre-wrapped example work verbatim on CLI ≥ 0.28.0; remove/rewrite the "until #97 fixes it / use `--prompt-file`" workaround note as normal guidance; state the observed CLI version next to the examples. (Keep the unrelated #100 "runs row not inserted" note.)
  - [ ] 1.10 Update `docs/runbooks/issue-77-deployment-e2e.md`: revise only the §E2E-validation **preamble caveat** (item 1) to reference #97 as *resolved* rather than pending; leave §7.7–7.10 executed commands and recorded pass/fail checkboxes verbatim (historical record).

  ### Acceptance-criteria verification
  - [ ] 1.11 Verify AC1: a double-wrapped payload is unwrapped correctly and the run proceeds (covered by 1.4; confirm inner payload validates).
  - [ ] 1.12 Verify AC2: bare and single-wrapped payloads still work, no regression (covered by 1.6).
  - [ ] 1.13 Verify AC3: genuinely-missing-fields failure is distinguishable from a wrapper problem via the distinct log message, `error_code` stays `INVALID_PARAMS` (covered by 1.7).
  - [ ] 1.14 Verify AC4: unit tests cover bare / single-wrap / double-wrap / wrapper-only (covered by 1.4–1.6).
  - [ ] 1.15 Verify AC5: README and #77 runbook examples reflect the fix; CLI version noted (covered by 1.9–1.10; manual read-through of both files).
  - [ ] 1.16 AC→test mapping recorded: AC1→1.4/1.11, AC2→1.6/1.12, AC3→1.7/1.13, AC4→1.4-1.6/1.14, AC5→1.9-1.10/1.15.

  ### Quality gate
  - [ ] 1.17 Run the aggregate gate: `cd agents/dependency-update && make validate` (lint + format:check + typecheck + test-cov + audit) — all passing.
