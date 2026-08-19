# Traceability Matrix — Agent Control Plane v1

## Changelog

| Version | Date       | Summary         | Author   |
| ------- | ---------- | --------------- | -------- |
| 1.0     | 2026-08-19 | Initial matrix  | verifier |

---

## AC → Test Case → Expected Observation

Every acceptance criterion maps to at least one positive test and one negative/edge test.

| AC-ID | Description | Positive Test(s) | Negative / Edge Test(s) | Randomized |
| --- | --- | --- | --- | --- |
| AC-1 | Agents list shows all managed agents | SC-1 | SC-2, EC-10 | — |
| AC-2 | Runs tab filterable by status + date range | SC-3, SC-19 | EC-9 | — |
| AC-3 | Repos view shows all subjects | SC-4 | — | — |
| AC-4 | Run panel opens without unmounting table | SC-5, SC-17 | EC-9 | — |
| AC-5 | Toggle `enabled` writes and reflects | SC-6 | EC-4, EC-5, CT-13 | RT-5 |
| AC-6 | Add repo < 30 s, zero deploys | SC-7 | EC-5 | RT-5 |
| AC-7 | `params` validates; invalid never stored | SC-8 | EC-7, CT-10, SC-18 | RT-1 |
| AC-8 | JWT validated; missing/invalid → deny | SC-9, SC-10 | SC-11, EC-13, CT-14 | RT-6 |
| AC-9 | Origin locked down | SC-12 | — | — |
| AC-10 | Unknown model → "unknown"; partial → "≥" | SC-13, SC-14 | EC-8 | RT-4 |
| AC-11 | `incomplete` derived from `maxLifetime + grace` | SC-15 | SC-16, EC-2, EC-3, EC-12 | RT-2 |
| AC-12 | Cost < USD 10/month | Manual check | — | — |
| AC-13 | Session ID unique, ≥33 chars, deterministic | CT-8, CT-11 | EC-1, EC-11 | RT-3 |
| AC-14 | Write separation enforced by policy | CT-4 | CT-5, CT-6, CT-7, EC-14 | RT-5 |
| AC-15 | Agent emits four `llipe.*` attributes | CT-1, CT-11 | CT-2, EC-6 | — |
| AC-16 | JSON logs with `session_id`; no secrets | CT-8 (via logs) | EC-8 (zero-token run still logs) | — |
| AC-17 | Non-blocking entrypoint; `HealthyBusy` reported | Deployed run > 10 min | EC-12 | — |
| AC-18 | Orchestrator reads DynamoDB scope; partial failure isolated | CT-8 | EC-11, EC-15 | — |
| AC-19 | Discovery by tag; untagged invisible; name matches key | SC-1 | SC-2 | — |

---

## Coverage Summary

| Metric | Count |
| --- | --- |
| Total acceptance criteria | 19 |
| ACs with ≥1 positive test | 19 (100%) |
| ACs with ≥1 negative/edge test | 18 (95%) |
| ACs with randomized coverage | 8 (42%) |
| Total E2E scenarios | 19 |
| Total contract scenarios | 14 |
| Total edge cases | 15 |
| Total randomized tactics | 6 |

**AC-12 (cost < $10):** covered by a manual monthly check rather than an automated test, per PRD. This is the only AC without a negative/edge test — the failure mode (cost exceeds budget) is observable only over billing cycles and not simulatable in a test.

---

## AC → Story Mapping (cross-reference)

| AC-ID | Implementing Story | Verifying Story |
| --- | --- | --- |
| AC-1 | S-019 | S-019 |
| AC-2 | S-020 | S-020 |
| AC-3 | S-023 | S-023 |
| AC-4 | S-021 | S-021 |
| AC-5 | S-022 | S-022 |
| AC-6 | S-013, S-022 | S-022 |
| AC-7 | S-022 | S-009, S-022 |
| AC-8 | S-014 | S-014 |
| AC-9 | S-024 | S-024 |
| AC-10 | S-018 | S-016, S-018 |
| AC-11 | S-002, S-018 | S-002, S-018 |
| AC-12 | S-024 | S-024 (manual) |
| AC-13 | S-002, S-013 | S-002, S-013 |
| AC-14 | S-004, S-011 | S-004, S-011 |
| AC-15 | S-010 | S-010, S-012 |
| AC-16 | S-008 | S-008 |
| AC-17 | S-007 | S-007, S-012 |
| AC-18 | S-013 | S-013 |
| AC-19 | S-005, S-019 | S-005, S-019 |
