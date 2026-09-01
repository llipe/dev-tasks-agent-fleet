# ADR-005: Document the repeated `prompt`-wrapper unwrap + distinct double-wrap diagnostic

## Status

Accepted

## Context

`docs/technical-guidelines.md` §8 (Integration Methods) describes the
`dependency-update` agent's invocation payload contract, and §18 registered
issue #97 as an **open** defect discovered during the issue #94 reaper
verification: `unwrap_payload()` stripped exactly one `prompt` wrapper, but the
`agentcore` CLI ≥ 0.28.0 treats its invoke argument *as* the prompt and wraps it
itself. An already-wrapped argument (the form documented in the README and the
issue #77 runbook) therefore arrived **double-wrapped** and died with a generic
`INVALID_PARAMS` that gave no hint of the real cause.

Issue #97 ("`unwrap_payload` mishandles agentcore CLI ≥ 0.28.0 double-wrapped
invocations"), implemented on branch `issue/97-unwrap-payload-double-wrap`
(PR #102), fixes this in
`agents/dependency-update/app/dependencyUpdate/main.py`:

1. **Repeated unwrap.** `unwrap_payload()` now unwraps **repeatedly** instead of
   once: it keeps stripping while the current value is a dict whose *only* key is
   a string `prompt` that parses to a JSON dict (`_is_lone_prompt_wrapper`),
   bounded by `_MAX_UNWRAP_DEPTH = 16` as a defensive guard against a pathological
   lone-`prompt` chain. Both the bare inner JSON and the pre-wrapped
   (single- or double-wrapped) form now resolve to the same inner payload. The
   loop terminates without over-unwrapping a legitimate inner payload that carries
   its own `prompt` field or sibling keys (only-key check), and stops on a
   non-string `prompt` value or a `prompt` string that does not parse to a JSON
   dict — returning the current value unchanged in every case.

2. **Distinct diagnostic.** A new pure, importable helper
   `classify_invalid_payload()` returns `"wrapper_only"` when a post-unwrap
   payload's only key is still `prompt` (the tell-tale of a double-wrap that could
   not be resolved) versus `"missing_fields"` otherwise. The entrypoint uses this
   to emit a specific "appears double-wrapped" log line pointing the operator at
   the bare-inner-JSON / `--prompt-file` form, instead of the generic
   missing-fields message.

Leaving §8 silent on the repeated-unwrap behavior and §18 marking #97 as still
open would misrepresent the current implemented invocation contract. This ADR
exists to satisfy the repository rule that **every modification to
`docs/technical-guidelines.md` is accompanied by an ADR** — even when the
modification is a factual current-state correction rather than a new
architectural decision (same reasoning as ADR-002 and ADR-003).

## Decision

Record the implemented behavior as current state in `technical-guidelines.md`:

1. §8 — add an "Invocation payload contract" subsection documenting the repeated
   lone-`prompt` unwrap (`_MAX_UNWRAP_DEPTH = 16`, `_is_lone_prompt_wrapper`
   guard), that both the bare and pre-wrapped forms are accepted, the loop's
   termination/no-over-unwrap guarantees, and the `classify_invalid_payload`
   "appears double-wrapped" diagnostic. State explicitly that this is a tolerance
   widening: required fields and the `INVALID_PARAMS` failure mode are unchanged —
   **no new error code, no schema change, no migration.**
2. §18 — flip the #97 row from **Open** to **Resolved (PR #102)** with a one-line
   summary and a pointer to §8 and this ADR.

No enforceable guideline rule (§3 architecture patterns, §5 auth, §6 security) is
changed. The change preserves the fleet's "explicitness over inference" posture
(§10): the wrapper detection is an explicit only-key structural check, and the
double-wrap case is surfaced explicitly to the operator rather than left as an
opaque failure.

## Alternatives Considered

- **Update the guideline without an ADR** because this is a bug-fix status
  correction, not a new architectural decision. Rejected: the repository rule is
  literal — any change to `technical-guidelines.md` requires an ADR. This ADR is
  deliberately scoped as a current-state correction record.
- **Introduce a dedicated error code (e.g. `DOUBLE_WRAPPED_PAYLOAD`).** Rejected
  by the implementation and endorsed here: a new terminal error code is a
  contract change that Phase 2 control-plane and any consumers would have to
  handle. The failure is still fundamentally "the payload lacked required
  fields"; a clearer *log line* addresses the operator-diagnosis problem without
  widening the error-code contract. `error_code` stays `INVALID_PARAMS`.
- **Cap the unwrap at exactly two layers** (single + double wrap). Rejected as
  brittle: a small bounded loop with an only-key guard tolerates both known forms
  and any future extra wrap without special-casing, and `_MAX_UNWRAP_DEPTH = 16`
  still bounds a pathological chain. Real payloads are wrapped at most twice.

## Consequences

- **Positive:** the foundation doc now states the true invocation contract — both
  the bare and pre-wrapped CLI forms work, and an unresolved double-wrap produces
  an actionable diagnostic. §18 no longer carries #97 as an open defect.
- **Negative / cost:** a low-substance ADR for what is essentially a bug-fix
  status update. Accepted as the cost of the "ADR-per-guideline-change" invariant.
- **Follow-up:** none required for #97. The sibling defects surfaced in the same
  §18 exercise (#98 idle/OOM during `validate`, #99 orphan `run_steps` on reap,
  #100 hand-invoke leaves no `runs` row) remain open and independently tracked.

## Related

- Requirements:
  - `docs/requirements/prd-dependency-update-agent.md` (payload validation,
    `INVALID_PARAMS`)
- Workstream:
  - Issue [#97](https://github.com/llipe/dev-tasks-agent-fleet/issues/97) / PR
    [#102](https://github.com/llipe/dev-tasks-agent-fleet/pull/102)
  - Origin: `docs/runbooks/issue-94-reaper-verification.md` §4.1 (where the
    double-wrap was first observed)
- Docs updated:
  - `docs/technical-guidelines.md` (§8 new subsection, §18 #97 row, changelog 1.7)
  - `agents/dependency-update/README.md` (§Invocation — updated in PR #102)
  - `docs/runbooks/issue-77-deployment-e2e.md` (preamble — updated in PR #102)
- Implementation:
  - `agents/dependency-update/app/dependencyUpdate/main.py`
    (`unwrap_payload` repeated-unwrap loop, `_is_lone_prompt_wrapper`,
    `_MAX_UNWRAP_DEPTH`, `classify_invalid_payload`, entrypoint diagnostic)
