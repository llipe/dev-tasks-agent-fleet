# Code review rubric

rubric-version: 1

You review one pull request for whether the code does, correctly, what it is
meant to do. Every finding names exactly one category below, a location, and
its consequence.

## Categories

- `correctness` — logic errors and wrong results; error handling; null, empty and missing values; concurrency; idempotency.
- `edge_case` — boundary inputs; state transitions; failure paths; permissions.
- `maintainability` — fit with the repository's conventions; duplication; premature abstraction; the cost of the next change.
- `intent` — the code does not do what the pull request description, the linked issues or the spec say it is meant to do, or the description contradicts the diff.

## Consequence rule

Every finding states its consequence: what goes wrong, for whom, and when, if
the change ships as written. A finding with no consequence is not reported.
A finding is `blocking` only when it has a location in the diff, a concrete
failure scenario, and a consequence. Anything else is a `suggestion`.

## Out of scope

Do not report these; other tools own them:

- fidelity and acceptance-criteria coverage (the `verifier` agent);
- lint, formatting, typecheck, unit test results, dependency audit, and coverage (CI);
- SAST and secret scanning (CI and the `security-analyst` agent).

## Verifier boundary

The reviewer does not audit fidelity. It does not check acceptance-criteria
coverage, per-AC evidence, traceability, or `/workstream` consistency: that is
`verifier` Audit Mode. It reads the linked issues and the spec to understand
what the code is meant to do, so it can judge whether the code does that
correctly. "AC-3 is not implemented" is verifier scope; "the retry in AC-3's
path double-charges on timeout" is reviewer scope.

The reviewer does not restate the verifier report's drift items as findings.
It only checks the drift candidates it is given, one by one.
