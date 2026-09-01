# Compliance Test Plan — Issue #97: `unwrap_payload` double-wrap fix

- **Mode:** Design (verifier) — test-first, pre-implementation
- **Repository:** `llipe/dev-tasks-agent-fleet`
- **Issue:** [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97)
- **Source artifacts:** `workstream/issue-97-unwrap-payload-double-wrap-refinement.md`, GitHub issue #97 (Refined Scope)
- **Input type:** issue (refined)
- **Companion:** `workstream/traceability-matrix-issue-97.md`

## Changelog

| Version | Date       | Summary                                                              | Author   |
| ------- | ---------- | -------------------------------------------------------------------- | -------- |
| 1.0     | 2026-08-31 | Initial Design-Mode compliance test plan derived from refined #97.   | verifier |

---

## 1. Source input summary

The `dependency-update` agent's `unwrap_payload()` strips exactly one `prompt` wrapper. Since `agentcore` CLI ≥ 0.28.0 wraps the prompt argument itself, the previously-documented pre-wrapped payload arrives double-wrapped; one unwrap leaves `{"prompt": "{...}"}` (a dict whose only key is `prompt`), which passes the current `isinstance(inner, dict)` guard, then fails `validate_payload()` and dies `failed / not_applicable / INVALID_PARAMS` with a generic log line. The fix hardens `unwrap_payload()` to unwrap repeatedly, emits a distinct wrapper-only diagnostic, adds tests, and refreshes the README and #77 runbook.

**Behavior under test (observable contract):**

- Input: a `raw` payload dict handed to the runtime (as AgentCore delivers it).
- Output: the fully-unwrapped inner payload, or an unchanged/safe fallback value.
- Downstream observable: `validate_payload` returns the payload (run proceeds) or `None` (terminates `INVALID_PARAMS`); on the wrapper-only failure a **distinct, actionable diagnostic** is emitted.

## 2. Acceptance criteria extraction

| AC    | Criterion (from refined issue #97)                                                                                                                   |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| AC-1  | A double-wrapped payload (`{"prompt": "{\"prompt\": \"{...}\"}"}`) is unwrapped correctly and the run proceeds.                                       |
| AC-2  | A bare payload and a single-wrapped payload both still work (no regression); existing passthrough / invalid-JSON / non-string / non-dict cases pass. |
| AC-3  | A genuinely-missing-fields failure is distinguishable from a wrapper problem: distinct actionable diagnostic, `error_code` stays `INVALID_PARAMS`, no new error code, no migration. |
| AC-4  | Unit tests cover bare / single-wrap / double-wrap / wrapper-only shapes.                                                                             |
| AC-5  | README §Invocation and #77 runbook §7.7–7.10 reflect the fix; observed CLI version noted. Runbook kept as historical record (preamble caveat only).  |

**Business rules / constraints:**

- BR-1 — Repeated unwrap **MUST terminate** on any non-`prompt`-only dict, non-string `prompt`, or JSON that does not parse to a dict (existing fallbacks preserved).
- BR-2 — No new `error_code` value; `runs.error_code` stays free-form `text` (no schema migration).
- BR-3 — The wrapper-only diagnostic branch currently lives in `@app.entrypoint invoke`, which is coverage-excluded (`pyproject.toml` `omit=["main.py"]`). AC-3/AC-4 must be assertable **without** relying on the excluded orchestrator — see §7 Design Recommendation.

**Non-goals:** AgentCore runtime config / CLI changes; #94 reaper scope; the #100 "runs row not inserted" gotcha.

## 3. E2E / black-box scenarios

These treat `unwrap_payload` + `validate_payload` as the black box (input dict → resolved payload / terminal decision). "Run proceeds" = `validate_payload` returns non-`None`.

| ID     | Scenario                          | Input (raw)                                                                 | Expected observable                                          | AC     |
| ------ | --------------------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------- | ------ |
| E2E-1  | Double-wrapped valid payload      | `{"prompt": "{\"prompt\": \"{\\\"run_id\\\":\\\"u\\\",\\\"repository_org\\\":\\\"o\\\",\\\"repository_name\\\":\\\"r\\\"}\"}"}` | Inner `{run_id,repository_org,repository_name}` resolved; `validate_payload` non-`None`; run proceeds | AC-1   |
| E2E-2  | Bare (unwrapped) valid payload    | `{"run_id":"u","repository_org":"o","repository_name":"r"}`                 | Passthrough unchanged; run proceeds                         | AC-2   |
| E2E-3  | Single-wrapped valid payload      | `{"prompt": "{\"run_id\":\"u\",\"repository_org\":\"o\",\"repository_name\":\"r\"}"}` | Inner payload resolved; run proceeds                        | AC-2   |
| E2E-4  | Wrapper-only (double-wrapped, empty inner) | `{"prompt": "{\"prompt\": \"{}\"}"}`                               | Unwrap stops safely; `validate_payload` → `None`; terminal `INVALID_PARAMS`; **wrapper-only** diagnostic | AC-3   |
| E2E-5  | Genuinely missing fields          | `{"run_id":"u"}` (no org/name), single-wrap variant too                     | `validate_payload` → `None`; terminal `INVALID_PARAMS`; **missing-fields** diagnostic (NOT wrapper-only) | AC-3   |
| E2E-6  | Triple-wrapped valid payload      | inner JSON wrapped three times in `prompt`                                  | Fully unwrapped; run proceeds (loop, not fixed-depth)       | AC-1   |

## 4. Contract validation scenarios

The unwrap function is the boundary contract between the AgentCore CLI/SDK convention and the pipeline.

| ID    | Contract property                                                                 | Assertion                                                                                          | AC   |
| ----- | --------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | ---- |
| CT-1  | Idempotent depth handling                                                         | `unwrap_payload` returns the same inner dict for 1..N `prompt` layers wrapping the same inner JSON | AC-1 |
| CT-2  | `error_code` contract unchanged                                                   | Both wrapper-only and missing-fields terminate with `error_code == "INVALID_PARAMS"` (string, unchanged) | AC-3, BR-2 |
| CT-3  | No new error-code / no schema surface                                             | No new symbol/enum introduced for error codes; `001_schema.sql` `error_code` column untouched      | BR-2 |
| CT-4  | Diagnostic distinguishability                                                     | Wrapper-only failure emits a diagnostic distinct from the missing-fields diagnostic (different, greppable text) | AC-3 |
| CT-5  | Return-type contract                                                              | `unwrap_payload` always returns a `dict` (never `None`/`str`) for every branch                     | AC-2, BR-1 |

## 5. Edge-case catalog (by category)

**Input domain**
- EC-1 `prompt` present but value is non-string (e.g. `42`) → fallback to raw (existing). [AC-2]
- EC-2 `prompt` string is invalid JSON (`"not json{{{"`) → fallback to raw (existing). [AC-2]
- EC-3 `prompt` string parses to a non-dict (JSON array `"[1,2,3]"`) → fallback to raw (existing). [AC-2]
- EC-4 `prompt` string parses to a JSON scalar (`"5"`, `"\"x\""`, `"null"`) → fallback, no crash. [BR-1]

**State transition (unwrap depth)**
- EC-5 Zero wraps (bare) → returned unchanged. [AC-2]
- EC-6 One wrap → inner resolved. [AC-2]
- EC-7 Two wraps (the bug) → inner resolved. [AC-1]
- EC-8 N wraps → inner resolved (loop terminates). [AC-1, BR-1]

**Wrapper-only / ambiguity**
- EC-9 Dict whose only key is `prompt` but inner is `{}` → stops, `None` from validate, wrapper-only diagnostic. [AC-3]
- EC-10 Dict with `prompt` **plus** other keys (`{"prompt":"...","run_id":"u"}`) → NOT wrapper-only; do not over-unwrap; current single-key guard governs. [AC-2, BR-1]
- EC-11 Legitimate inner payload that itself contains a `prompt` field alongside required fields → must NOT be stripped further (only-key guard protects this). [AC-1, BR-1]

**Termination / safety**
- EC-12 Deeply nested wrapper-only chain ending in `{}` → terminates without infinite loop or stack growth. [BR-1]
- EC-13 Empty dict `{}` input → returned unchanged, `None` from validate (missing-fields, not wrapper-only). [AC-3]

**Failure-mode diagnostics**
- EC-14 Missing-fields path does NOT emit the wrapper-only diagnostic. [AC-3]
- EC-15 Wrapper-only path does NOT emit the plain missing-fields diagnostic as its only signal. [AC-3]

**Docs (manual/structural)**
- EC-16 README §Invocation example, copied verbatim, is not the double-wrap form and states CLI ≥ 0.28.0. [AC-5]
- EC-17 #77 runbook §7.7–7.10 executed commands + checkboxes unchanged; only the preamble caveat updated to "resolved". [AC-5]

## 6. Randomized / property-based tactics

Property tests over generated wrap depth and payload shape. **Seed policy:** fixed seed `97_0831` recorded in the test module; on failure, capture seed + generated vector per the Failure Triage Workflow.

| ID     | Property                                                                                          | Generator                                                                 | AC        |
| ------ | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | --------- |
| PB-1   | For any valid inner payload wrapped `k` times (`k` in 0..8), `unwrap_payload` returns the inner dict | random valid inner + random `k`                                          | AC-1, BR-1 |
| PB-2   | `unwrap_payload` always returns a `dict` and always terminates within `k+2` iterations            | random `k`-deep wrapper-only chains, including malformed tails            | BR-1, CT-5 |
| PB-3   | Adding a non-`prompt` sibling key at any layer stops unwrapping at that layer                     | random payloads with an injected sibling key                              | AC-2, BR-1 |

Deterministic replay: each PB test seeds a local RNG from `97_0831`; a failing case logs the exact `(seed, k, payload)` triple and is copied into a static regression test.

## 7. Design recommendation for testability (AC-3 / AC-4 — advisory, non-binding)

Because `main.py` is coverage-excluded and the wrapper-only diagnostic currently sits inside `@app.entrypoint invoke`, asserting AC-3's "distinct signal" through the orchestrator would be untestable within the covered surface. **Recommended (for `developer`):** extract the wrapper-only decision into a pure, importable helper in a covered module — e.g. `is_wrapper_only(payload: dict) -> bool` (or a small `classify_invalid_payload(payload) -> reason` returning `"wrapper_only" | "missing_fields"`) — and have the entrypoint call it purely to select the log message. Tests then assert the helper directly (Layer 1) and, optionally, assert the emitted message via `caplog`. This keeps AC-3/AC-4 verifiable without exercising the excluded orchestrator. If `developer` instead asserts via `caplog` against `invoke`, that is acceptable but will not count toward coverage.

## 8. Test placement & framework

- **Framework:** `pytest 8.3.5` (+ `pytest-cov`, branch coverage), per `TESTING.md` / `pyproject.toml`.
- **Location:** extend `agents/dependency-update/app/dependencyUpdate/tests/component/test_pipeline.py::TestUnwrapPayload` (co-located with existing cases; auto-marked `component` by `tests/conftest.py`). Pure-function cases MAY instead live under `tests/unit/` (auto-marked `unit`) — either satisfies AC-4; co-location is preferred for cohesion.
- **New test classes (suggested):** `TestUnwrapPayloadDoubleWrap`, `TestInvalidPayloadDiagnostic` (asserts wrapper-only vs missing-fields signal), plus property tests in a `TestUnwrapPayloadProperties` class.
- **No fixtures/externals** required — these are pure-function tests (no Secrets Manager / PostgREST / git mocking needed).

## 9. Execution checklist

- [ ] E2E-1..E2E-6 implemented and passing.
- [ ] CT-1..CT-5 implemented and passing.
- [ ] EC-1..EC-15 covered (EC-16/EC-17 verified by doc read-through).
- [ ] PB-1..PB-3 implemented with seed `97_0831` recorded; replay instructions in module docstring.
- [ ] Existing `TestUnwrapPayload` cases still green (no regression).
- [ ] `error_code` asserted `== "INVALID_PARAMS"` on both invalid paths (CT-2); no new error code (CT-3).
- [ ] README §Invocation + #77 runbook checked against EC-16/EC-17.
- [ ] `cd agents/dependency-update && make validate` (lint + format:check + typecheck + test-cov + audit) passing.

## 10. Coverage status

Every AC maps to ≥1 positive and ≥1 negative/edge test — see `traceability-matrix-issue-97.md`. **Coverage: complete** (AC-1..AC-5 all covered). No uncovered ACs.
