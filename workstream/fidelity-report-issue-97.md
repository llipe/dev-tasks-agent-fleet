# Fidelity Report — Issue #97: `unwrap_payload` double-wrap fix

## Header / Verdict

- **Fidelity: High**
- **Highest drift impact present: Minor**
- **Scope:** Issue [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97) · PR [#102](https://github.com/llipe/dev-tasks-agent-fleet/pull/102) · branch `issue/97-unwrap-payload-double-wrap`
- **Mode:** Audit (grey-box) · **Phase:** Reporting & Publication
- **Result:** All 5 acceptance criteria genuinely satisfied by code + tests. One Minor, Intended semantic-boundary note on AC-3. Drift is **non-blocking** to completion.

## Changelog

| Version | Date       | Summary                                          | Author   |
| ------- | ---------- | ------------------------------------------------ | -------- |
| 1.0     | 2026-08-31 | Initial Audit-Mode fidelity report for PR #102.  | verifier |

---

## 1. Human-readable summary — what changed and why

Before this change, the agent could only "unwrap" a payload one time. A recent
upgrade to the invocation tool (`agentcore` CLI 0.28.0+) started adding its own
wrapper around whatever you hand it. So the previously-documented "already
wrapped" payload arrived wrapped **twice**, the agent only peeled off one layer,
and the run died with a vague "missing required fields" error that gave no clue
the real problem was double-wrapping. This cost real debugging time during the
#94 reaper verification.

The fix teaches the agent to keep peeling wrappers until it reaches the real
payload — but only when the thing it is looking at is unmistakably *just* a
wrapper (a box whose only label is `prompt`). If the box also contains real
content, or the wrapper does not open cleanly, it stops immediately, so a
legitimate payload that happens to carry its own `prompt` field is never
damaged. When a payload still looks like an empty wrapper after all the peeling,
the agent now prints a specific, actionable message ("appears double-wrapped —
pass the bare inner JSON") instead of the old generic one. Nothing about the
database or error codes changed.

The documentation was also refreshed: the README now says both the bare and the
pre-wrapped forms work on CLI 0.28.0+ and names the CLI version tested, and the
#77 runbook's warning was updated from "fix pending" to "resolved in #97" while
keeping the original executed commands and pass/fail record intact as history.

No behavior a non-engineer would notice was removed or altered beyond making a
previously-broken invocation form work again and making one error message
clearer.

---

## 2. Per-AC result table

| AC   | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
| ---- | ----------- | ----------------- | ------------------- | ------------- | ------ |
| AC-1 | Double-wrapped payload unwraps correctly and run proceeds | `unwrap_payload()` now loops up to `_MAX_UNWRAP_DEPTH=16`, peeling each lone-`prompt` layer (`main.py` L71–110) | tasks 1.1/1.11; refinement §3, §4.1 | `test_unwraps_double_wrapped`, `test_unwraps_triple_wrapped`, `test_idempotent_across_depths`, `TestUnwrapPayloadProperties::test_any_depth_valid_payload_unwraps` (seed `97_0831`, k∈0..8); each asserts `validate_payload(result) is not None` | **Pass** |
| AC-2 | Bare + single-wrap still work; no regression | Loop returns `current` unchanged for bare/non-wrapper dicts; all original fallbacks preserved | tasks 1.6/1.12 | Original `TestUnwrapPayload` (5 cases) intact + `test_single_wrap_still_unwraps`, `test_bare_still_passthrough`, `test_always_returns_dict` (CT-5); 25 unwrap/classify tests pass | **Pass** |
| AC-3 | Missing-fields distinguishable from wrapper problem; `error_code` stays `INVALID_PARAMS`, no new code, no migration | New pure helper `classify_invalid_payload()` returns `"wrapper_only"` \| `"missing_fields"` (`main.py` L119–132); entrypoint `validated is None` branch emits distinct `log.error` per class while `build_return_payload(..., "INVALID_PARAMS")` unchanged (L488–503) | refinement §4 AC3 decision (keep code, distinct log, no migration); test-plan CT-2/CT-3/CT-4; `error_code` is free-form `text` in `001_schema.sql` | `TestClassifyInvalidPayload` (5 cases incl. `test_distinct_reasons`=CT-4); grep confirms no new error-code symbol/enum | **Pass** (see Drift D-1) |
| AC-4 | Unit tests cover bare / single-wrap / double-wrap / wrapper-only | n/a (test AC) | tasks 1.4–1.6/1.14; test-plan §8 | `TestUnwrapPayloadDoubleWrap` (bare, single, double, triple, wrapper-only-empty, scalar/array/invalid fallbacks, EC-10/EC-11 boundary), `TestClassifyInvalidPayload`, `TestUnwrapPayloadProperties` | **Pass** |
| AC-5 | README + #77 runbook reflect fix; CLI version noted; runbook kept as historical record | README §Invocation rewritten: both forms work, "appears double-wrapped" message documented, "validated against `agentcore` CLI 0.28.x" stated, old "until #97 fixes it" note removed; runbook preamble changed pending→resolved | tasks 1.9/1.10/1.15; refinement §4 AC5 | Diff confirms runbook §7.7–7.10 executed commands + checkboxes **unchanged** (grep: no step-body/checkbox lines added — preamble-only) | **Pass** |

---

## 3. Drift catalog

> All drift below is **non-blocking** to PR/issue completion, per the Audit-Mode
> operating rules. It is recorded for `product-engineer`'s
> `activity-drift-reconciliation` flow to route as it sees fit.

### D-1 — Wrapper-only diagnostic boundary differs from the test-plan E2E-4 narrative

- **Impact class: Minor** · **Intent class: Intended**
- **Description:** The delivered `wrapper_only` classification fires when a
  post-unwrap payload's **only key is `prompt`** — i.e. a lone-`prompt` wrapper
  the loop could **not** peel further (its value is invalid JSON, a JSON array,
  or a scalar). Verified at runtime:
  - `{"prompt": "[1,2,3]"}` → `wrapper_only` ✓
  - `{"prompt": "not json{{{"}` → `wrapper_only` ✓
  - `{"prompt": "5"}` → `wrapper_only` ✓
  - `{"prompt": "{\"prompt\": \"{}\"}"}` (test-plan E2E-4's literal "double-wrapped
    empty inner") → unwraps fully to `{}` → classified **`missing_fields`**.

  The test-plan's E2E-4 prose implies the double-wrapped-empty-inner input yields
  the wrapper-only diagnostic. In the implementation that specific input peels
  cleanly to `{}` (a genuinely field-less payload), so `missing_fields` is the
  defensible and arguably more correct label. The delivered test
  `test_wrapper_only_empty_inner_stops_safely` is honest: it asserts only that
  the input **stops safely and validates to `None`**, and does **not** claim the
  wrapper-only signal for it. The wrapper-only signal is instead asserted on
  `{"prompt": "{}"}` in `TestClassifyInvalidPayload::test_wrapper_only_after_unwrap`,
  which is exactly the un-peelable lone-`prompt` shape.
- **Evidence source(s):** `main.py` `classify_invalid_payload` + `_is_lone_prompt_wrapper`;
  runtime trace; `test_pipeline.py` `TestClassifyInvalidPayload`, `test_wrapper_only_empty_inner_stops_safely`;
  `test-plan-issue-97.md` §3 E2E-4.
- **Why Intended:** The AC-3 *decision* in the refinement (§4) requires only "a
  distinct, actionable log message emitted when the post-unwrap payload's only
  key is `prompt`." The implementation matches that decision text exactly. The
  divergence is between the implementation and one illustrative test-plan *row*,
  not between the implementation and the acceptance criterion. AC-3's intent
  (distinguishable, actionable diagnostic; no new error code; no migration) is
  fully met.
- **Note:** Non-blocking. Suggested disposition: reconcile the test-plan E2E-4
  wording (or add a note) so the "wrapper-only" example uses an un-peelable
  lone-`prompt` payload rather than a cleanly-peelable empty inner.

### D-2 — `unwrap_payload` accepts a broader input type than the annotation states (observation)

- **Impact class: Minor** · **Intent class: Intended**
- **Description:** `unwrap_payload(raw: dict)` is annotated `dict`; the loop
  guards every branch (`_is_lone_prompt_wrapper` first checks `isinstance(payload, dict)`)
  and always returns a `dict`, so CT-5 holds. No functional defect — noting only
  that the contract is enforced by guards rather than the type alone. `mypy` is
  reported clean in `make validate`.
- **Evidence source(s):** `main.py` `unwrap_payload`/`_is_lone_prompt_wrapper`; `test_always_returns_dict` (CT-5).
- **Note:** Non-blocking. No action needed.

---

## 4. Focused checks requested by the caller

- **AC-3 distinction real and asserted?** Yes. `classify_invalid_payload` is a
  pure, importable helper with direct assertions (`TestClassifyInvalidPayload`,
  incl. `test_distinct_reasons` = CT-4). The entrypoint selects between two
  distinct `log.error` strings. `error_code` remains the literal string
  `"INVALID_PARAMS"` on both paths (`build_return_payload(..., "INVALID_PARAMS")`),
  no new error-code symbol/enum introduced, and `runs.error_code` is free-form
  `text` in `001_schema.sql` → **no schema change / no migration**. Confirmed.
- **Do-not-over-unwrap boundary protected and tested?** Yes. `_is_lone_prompt_wrapper`
  gates on `list(payload.keys()) == ["prompt"]`, so a dict with sibling keys or a
  legitimate inner payload carrying its own `prompt` field is never stripped.
  Tested by `test_does_not_unwrap_prompt_with_sibling_keys` (EC-10),
  `test_does_not_strip_legit_inner_prompt_field` (EC-11, asserts the inner
  `prompt` field survives **and** validates), and property test
  `test_sibling_key_stops_unwrap` (PB-3, seed `97_0831`).
- **Loop termination safety?** Guaranteed three ways: (1) hard bound
  `_MAX_UNWRAP_DEPTH=16`; (2) each iteration must strip exactly one lone-`prompt`
  layer or it returns; (3) non-dict/invalid-JSON/scalar `prompt` values return
  immediately. Tested by `test_deep_wrapper_only_chain_terminates` (EC-12, depth 8),
  `test_prompt_scalar_json_falls_back` (EC-4), `test_always_dict_and_terminates` (PB-2).
- **Docs — README works verbatim on CLI ≥ 0.28.0?** Yes. README §Invocation now
  presents both the bare `--prompt-file` form and the pre-wrapped form as working,
  states "validated against `agentcore` CLI 0.28.x", documents the new
  "appears double-wrapped" failure message, and removes the old "until #97 fixes
  it" workaround.
- **#77 runbook kept as historical record, preamble-only?** Yes. The diff touches
  only the E2E-validation preamble caveat (pending → resolved) and the
  payload-wrapping note; grep confirms **no** §7.7–7.10 executed-command or
  pass/fail-checkbox lines were added or modified.

---

## 5. Edge-case & randomized test outcomes (against the prior test plan)

- **E2E-1..E2E-6:** covered (E2E-4 semantics reconciled under Drift D-1). 
- **CT-1..CT-5:** covered — CT-1 (`test_idempotent_across_depths`), CT-2
  (`error_code == "INVALID_PARAMS"` both paths), CT-3 (no new error-code symbol —
  confirmed by inspection), CT-4 (`test_distinct_reasons`), CT-5
  (`test_always_returns_dict`).
- **EC-1..EC-15:** covered by `TestUnwrapPayload` (existing) + `TestUnwrapPayloadDoubleWrap`
  + `TestClassifyInvalidPayload`. EC-16/EC-17 verified by doc read-through.
- **PB-1..PB-3:** implemented in `TestUnwrapPayloadProperties`, seed `97_0831`
  recorded in-module with the `(seed, k, payload)` triple logged on failure for
  deterministic replay (200 iterations each).
- **Local run:** `pytest -k "Unwrap or Classify"` → **25 passed**. Full suite per
  caller context: `make validate` → **382 tests, 94% coverage, ruff + mypy +
  pip-audit clean**; `qa-engineer` `coverage_gate = PASS`.

---

## 6. Recommendations

| Item  | Recommendation | Owner |
| ----- | -------------- | ----- |
| D-1   | Reconcile the test-plan E2E-4 example wording (use an un-peelable lone-`prompt` payload for the "wrapper-only" illustration). Non-blocking; documentation-only. | `product-engineer` (via `activity-drift-reconciliation`) |
| D-2   | No action needed. | — |
| AC-1..AC-5 | No action needed — all satisfied. | — |

---

## Output Contract

- **Mode / phase:** Audit / Reporting & Publication
- **Source artifacts:** `issue-97-...-refinement.md`, `test-plan-issue-97.md`, `traceability-matrix-issue-97.md`, `tasks-issue-97-...md`, GitHub issue #97 Refined Scope; delivered diff (`main.py`, `test_pipeline.py`, `README.md`, `issue-77-deployment-e2e.md`)
- **Output file:** `workstream/fidelity-report-issue-97.md`
- **AC coverage status:** 5/5 covered — AC-1 Pass, AC-2 Pass, AC-3 Pass, AC-4 Pass, AC-5 Pass
- **Overall fidelity verdict:** High · **Highest drift impact:** Minor (D-1, Intended)
- **Blocking gaps:** None
