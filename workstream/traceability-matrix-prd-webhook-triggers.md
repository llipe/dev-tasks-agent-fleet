# Traceability Matrix — Webhook Triggers Phase 1 (verifier, Design Mode)

> Companion to [`test-plan-prd-webhook-triggers.md`](test-plan-prd-webhook-triggers.md).
> Maps every AC to at least one positive and one negative or edge test, using the shape
> `AC-ID → Test-Case-ID → Observed-Result → Pass/Fail/Drift`. The Observed and Result columns stay
> **PENDING** until implementation and the Audit Mode run.

## Changelog

| Version | Date       | Summary                            | Author   |
| ------- | ---------- | ---------------------------------- | -------- |
| 1.0     | 2026-10-19 | Initial matrix from test plan v1.0. | verifier |

## AC → tests

| AC | Positive | Negative / edge | Stories / layer | Observed | Result |
| --- | --- | --- | --- | --- | --- |
| AC1 signed delivery → webhook run | E2E-1, CT-6 (valid), EC-4, EC-36 | EC-15 (slow invoke), EC-22 (invoke throws), CT-6 (missing snapshot / bad identity), EC-8 (bad token) | S-169, S-171, S-172 / L1, L2.5, E2E | PENDING | PENDING |
| AC2 bad signature 401 / replay is a no-op | RT-1 (exact header verifies), E2E-3 (first POST fires) | E2E-2, E2E-7 (old secret), CT-1 (sha1 / bare hex / uppercase), EC-1–EC-3, EC-14, EC-18, EC-20, RT-5 | S-168, S-169 / L1, L2.5, E2E | PENDING | PENDING |
| AC3 oversized 413 / not allowlisted → ignored | CT-3 (valid within cap), EC-29 (exactly the cap) | EC-29 (cap + 1, chunked with no length), E2E-5, CT-1 (missing event), CT-3 (invalid JSON) | S-169 / L1, L2.5, E2E | PENDING | PENDING |
| AC4 first match wins, payload repo, no_match | E2E-1, E2E-8, RT-3, EC-9 | EC-5, EC-6, EC-30, EC-31, EC-33, EC-34, RT-2, CT-4 (missing, mismatched, extra keys) | S-170, S-171 / L1, L2.5, E2E | PENDING | PENDING |
| AC5 repo / params rejected | CT-5 (declared keys validate), EC-7 (exact match resolves) | EC-7 (variants rejected), EC-13, CT-5 (missing, mismatched, undeclared), RT-4, repo row count unchanged (task 7.2) | S-171 / L1, L2.5 | PENDING | PENDING |
| AC6 guardrails skip + run_failed notification | EC-19 (one notification), RT-6 (disable after N failures) | EC-10 (reset by success), EC-16 (cap race), EC-24 (#302 deleted rule), G1/G5 skips (task 9.1) | S-173, S-174 / L2.5 | PENDING | PENDING |
| AC7 bot author excluded | E2E-4, task 6.2 (bot + type Bot excluded) | EC-28 (human with bot-like login, other app's bot), guard toggle off + explicit condition | S-170 / L1, E2E | PENDING | PENDING |
| AC8 UI, boundary, release gate | E2E-1, E2E-7, E2E-8, CT-11 (401 passes) | E2E-6, E2E-9 (XSS inert), EC-11, EC-12, EC-25, EC-26, EC-32, CT-11 (2xx/404/5xx, unset token) | S-175–S-178 / L1, L2, L2.5, E2E | PENDING | PENDING |
| AC9 no secret leaked | CT-10 (Vault round-trip) | EC-21 (null secret fails closed), EC-27 (no secret in RSC/HTML), CT-2 (no echo), CT-9 (anon reads 0), log grep (task 5.2) | S-166, S-168, S-169, S-176 / L1, L2.5 | PENDING | PENDING |

## Invariants → tests

| Invariant | Tests |
| --- | --- |
| I-1 verify before parse or route | task 5.2 ordering, EC-3, CT-3 (invalid JSON after a valid signature only) |
| I-2 one recorded row per non-401/404/413 delivery | RT-5, EC-23 |
| I-3 at most one run per delivery id | EC-14, EC-18, RT-5 |
| I-4 never auto-create a repo | task 7.2 count before and after, EC-7 |
| I-5 only declared param keys | CT-5, RT-4 |
| I-6 one invoke path, fire route unchanged | CT-6, CT-7 (baseline count) |
| I-7 untrusted text rendered inert | E2E-9, task 14.3 |
| I-8 prune never deletes runs | EC-17, EC-35, task 3.1 |

## Coverage assertion

- **9 of 9 ACs** have at least one positive and one negative or edge test. No AC is uncovered.
- **8 of 8 invariants** are covered by at least one test.
- Every RT tactic has a default seed and replay instructions (test plan §6).
- Open boundary items B-1 to B-3 are listed in test plan §8. B-4 was decided on 2026-10-19 (D-W16).
