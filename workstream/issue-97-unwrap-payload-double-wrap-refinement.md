# Refinement — Issue #97: `unwrap_payload` double-wrap breaks agentcore CLI ≥ 0.28.0 invocations

- **Repository:** `llipe/dev-tasks-agent-fleet`
- **Issue:** [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97)
- **Type:** bug · `priority:high` · `size:S`
- **Discovery source:** [#94](https://github.com/llipe/dev-tasks-agent-fleet/issues/94) (pg_cron reaper verification), see `docs/runbooks/issue-94-reaper-verification.md` §4.1

## Changelog

| Version | Date       | Summary                                                                                                   | Author           |
| ------- | ---------- | --------------------------------------------------------------------------------------------------------- | ---------------- |
| 1.0     | 2026-08-31 | Initial refinement. Verified issue claims against code/tests/docs; corrected file paths; sharpened AC3/AC5. | product-engineer |

## 1. Problem (verified)

`agentcore invoke <arg>` in CLI v0.28.0 treats its argument **as** the prompt and wraps it itself as `{"prompt": "<arg>"}`. The runtime's `unwrap_payload()` strips exactly **one** level of the `prompt` wrapper, so passing the previously-documented pre-wrapped form `'{"prompt": "{...}"}'` arrives **double-wrapped**:

- CLI produces `{"prompt": "{\"prompt\": \"{...}\"}"}`.
- One unwrap yields `{"prompt": "{...}"}` — a dict, so it passes the `isinstance(inner, dict)` guard and is returned as-is.
- `validate_payload()` finds no `run_id` / `repository_org` / `repository_name` and returns `None`.
- The run terminates `failed / not_applicable / INVALID_PARAMS` with the log line `"Invalid payload — missing required fields"`.

Confirmed live: runs `cba355cb-199e-4444-8818-d0d4cb9c4335` and `18310475-3285-4b28-81f2-39a5e1f6ceeb` failed this way; switching to the bare inner JSON via `--prompt-file` worked (run `f63ac9f3-14b0-4157-9484-f2f6b062f846`). This is a CLI behaviour change since #77, not a doc that was always wrong.

### Code confirmation

- `unwrap_payload()` — single-level unwrap, no loop; guard is `isinstance(inner, dict)` only.
- `validate_payload()` — requires the three string fields; returns `None` otherwise.
- The `None` path emits `log.error("Invalid payload — missing required fields")` and builds `INVALID_PARAMS`.
- `runs.error_code` is a free-form `text` column in `docs/reference/001_schema.sql` — **no enum/check constraint**, so error-code changes carry **no DB migration**.

## 2. Path corrections (source-of-truth fix)

The issue References section points at paths that are one directory too shallow. Correct paths:

| Issue reference (stale)                                                  | Correct path                                                                          |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| `agents/dependency-update/main.py::unwrap_payload`                       | `agents/dependency-update/app/dependencyUpdate/main.py::unwrap_payload`               |
| `agents/dependency-update/tests/component/test_pipeline.py::TestUnwrapPayload` | `agents/dependency-update/app/dependencyUpdate/tests/component/test_pipeline.py::TestUnwrapPayload` |

The two doc paths in the issue are correct as written:

- `agents/dependency-update/README.md` (§Invocation)
- `docs/runbooks/issue-77-deployment-e2e.md` (§7.7–7.10)

## 3. Refined Scope

- [ ] Harden `unwrap_payload()` (in `agents/dependency-update/app/dependencyUpdate/main.py`) to tolerate both CLI conventions: unwrap **repeatedly** while the result is a dict whose only key is `prompt` and whose value parses as a JSON dict. The loop must terminate on any non-`prompt`-only dict, on non-string `prompt` values, and on JSON that does not parse to a dict (existing fallbacks preserved).
- [ ] Emit a **specific, actionable** log message when validation fails because the post-unwrap payload is wrapper-only (its only key is `prompt`), distinct from the generic missing-fields message. Keep `error_code = INVALID_PARAMS` (see AC3 decision below).
- [ ] Add unit tests for the double-wrapped and wrapper-only shapes in `agents/dependency-update/app/dependencyUpdate/tests/component/test_pipeline.py::TestUnwrapPayload` (co-located with the existing cases).
- [ ] Revise the invocation examples in `agents/dependency-update/README.md` §Invocation so the documented form works verbatim on CLI ≥ 0.28.0; update/remove the "until #97 fixes it" workaround note.
- [ ] Revise `docs/runbooks/issue-77-deployment-e2e.md` §7.7–7.10 / the E2E preamble note so the #97 workaround caveat reflects the fix (see AC5 decision below).
- [ ] Note the required/observed `agentcore` CLI version alongside the examples so a future CLI change is easier to spot.

## 4. Sharpened Acceptance Criteria

1. A double-wrapped payload (`{"prompt": "{\"prompt\": \"{...}\"}"}`) is unwrapped correctly and the run proceeds.
2. A bare payload and a single-wrapped payload both still work (no regression). Existing `TestUnwrapPayload` cases (passthrough, invalid-JSON, non-string prompt, non-dict JSON) continue to pass.
3. **(sharpened)** When a payload really is missing required fields, the failure is distinguishable from a wrapper problem. **Decision:** keep `error_code = INVALID_PARAMS` for both (both are genuinely invalid params, and `error_code` is free-form `text` with no constraint — no migration), but emit a **distinct, actionable log message** for the wrapper-only case (e.g. naming the double-wrap and pointing at the bare-payload form). Introducing a new `error_code` value is explicitly **not** required.
4. Unit tests cover bare / single-wrap / double-wrap / wrapper-only shapes.
5. **(sharpened)** README and #77 runbook examples reflect the fix:
   - **README §Invocation:** the pre-wrapped example works verbatim on CLI ≥ 0.28.0; the "until #97 fixes it / use `--prompt-file`" workaround note is removed or rewritten as normal guidance. The observed CLI version is stated next to the examples.
   - **#77 runbook §7.7–7.10:** this file is a **historical record of what was executed**. Keep the executed commands verbatim, but update the preamble caveat (§E2E validation, item 1) so it no longer says the fix is *pending* — reference #97 as *resolved* and state that current invocations should use the (now-working) documented form. Do **not** rewrite the recorded pass/fail checkboxes.

## 5. Out of scope

- Any change to the AgentCore runtime config or to the `agentcore` CLI itself.
- Everything covered by #94 (reaper scheduling and verification).
- The unrelated "direct invoke does not insert the `runs` row" gotcha ([#100](https://github.com/llipe/dev-tasks-agent-fleet/issues/100)) — the doc notes referencing it stay, but fixing it is not part of this issue.

## 6. Design notes / risks

- **No DB migration.** `runs.error_code` is `text`; no schema change needed for AC3.
- **Termination safety.** The repeated-unwrap loop must guard against a payload whose inner value is itself `{"prompt": ...}` indefinitely; termination is guaranteed because each iteration requires the JSON to parse to a dict whose *only* key is `prompt` — any other shape stops the loop, and a genuinely malformed inner string stops it via the existing `JSONDecodeError` fallback.
- **Test layer.** New tests co-locate with the existing `TestUnwrapPayload` under `tests/component/` (auto-marked `component` by `conftest.py`). These are pure-function tests with no I/O; placing them under `tests/unit/` would also be valid, but co-location keeps the wrapper cases together.
- **`main.py` orchestrator is coverage-excluded.** The wrapper-only log-message branch lives in the streamed entrypoint; assert the behaviour via the `unwrap_payload`/`validate_payload` seam and a targeted test rather than the excluded orchestrator, per `TESTING.md`.

## 7. Definition of Done

- `unwrap_payload()` hardened; wrapper-only validation failure emits a distinct log message.
- Unit tests cover bare / single-wrap / double-wrap / wrapper-only.
- README §Invocation and #77 runbook §7.7–7.10 updated per AC5; CLI version noted.
- `make validate` (lint + format:check + typecheck + test-cov + audit) passes.
- PR opened with `Closes #97`, reviewed, and merged; issue closed only after merge.
