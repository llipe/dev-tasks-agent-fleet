# Traceability Matrix — Control Tower, Wave A (verifier, Design Mode)

## Changelog

| Version | Date       | Summary                                                                                     | Author   |
| ------- | ---------- | ------------------------------------------------------------------------------------------- | -------- |
| 1.0     | 2026-11-26 | Initial matrix for Wave A (S-219–S-228, issues #487–#496), built from test plan v1.0.        | verifier |

> Companion to [`test-plan-control-tower-wave-a`](test-plan-control-tower-wave-a.md), which defines every case id used here.
> Sources: `workstream/user-stories-control-tower.md` v1.2, `workstream/specification-control-tower.md` v1.1,
> `docs/requirements/prd-control-tower.md` v1.4, `workstream/tasks-control-tower-plan.md` v1.1.
>
> **Status:** Design Mode. Nothing has been implemented or run, so the observed result of every row is
> "pending" and the verdict column is filled by Audit Mode. The chain is
> `story AC → PRD FR/AC → case ids → observed result → pass / fail / drift`.

## 1. Coverage summary

- Acceptance criteria numbered: **76** across ten stories.
- Test cases: **284** — L1 93, L2 11, L2.5 156, E2E 8, Manual 16.
- Criteria with no test case: **0**. Criteria with no positive case: **0**. Criteria with no negative, edge or security case: **0**.
- Layers: L1 unit, L2 component, L2.5 integration against real Postgres, E2E Playwright, Manual (recorded evidence).
- A case listed under several criteria is counted once in the totals.

| Story | Issue | Criteria | Cases | L1 | L2 | L2.5 | E2E | Manual |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S-219 — Tower schema | #487 | 7 | 18 | 1 | 0 | 17 | 0 | 0 |
| S-220 — Token and repository lifecycle | #488 | 8 | 30 | 9 | 0 | 21 | 0 | 0 |
| S-221 — Ingestion contract version 1 | #489 | 7 | 37 | 26 | 0 | 10 | 0 | 1 |
| S-222 — `tower_apply_push` | #490 | 11 | 53 | 0 | 0 | 53 | 0 | 0 |
| S-223 — `POST /api/tower/ingest` | #491 | 8 | 50 | 12 | 1 | 37 | 0 | 0 |
| S-224 — Retention | #492 | 6 | 22 | 0 | 0 | 22 | 0 | 0 |
| S-225 — Read contract version 1 | #493 | 10 | 51 | 33 | 1 | 17 | 0 | 0 |
| S-226 — Minimal `/tower` | #494 | 8 | 22 | 4 | 9 | 1 | 8 | 0 |
| S-227 — Release-gate probes and runbook | #495 | 5 | 11 | 9 | 0 | 0 | 0 | 2 |
| S-228 — Wave A live (manual checklist) | #496 | 6 | 13 | 0 | 0 | 0 | 0 | 13 |

Cases shared between stories appear in each story's row, so the row totals add up to more than the overall count.

## 2. Story acceptance criteria to test cases

"Positive" lists cases of type `pos`. "Negative, edge, security, property" lists every other type. File keys are resolved in §4.

### S-219 — Tower schema (#487)

| Story AC | Criterion (short) | PRD FR / AC | Positive | Negative, edge, security, property | Layers | Planned test files | Observed result | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S-219-AC-1 | The eight `tower_*` tables exist with the columns, keys and indexes of spec §5.1 | FR-1, FR-2, FR-11, FR-12 | TC-219-01 | TC-219-02, TC-219-03, TC-219-04, TC-219-05 | L2.5 | SCH | pending | — |
| S-219-AC-2 | `full_name` is unique and rejects anything that is not lowercase `owner/name` | FR-1 | TC-219-06 | TC-219-07 | L2.5 | SCH | pending | — |
| S-219-AC-3 | A second active token is rejected; a revoked one plus an active one is allowed | FR-2, FR-3 | TC-219-09 | TC-219-08 | L2.5 | SCH | pending | — |
| S-219-AC-4 | `steps` and `stages` reject an unknown key and an unknown result; a missing key is allowed | FR-17, FR-19, FR-27 | TC-219-10 | TC-219-11, TC-219-12 | L2.5 | SCH | pending | — |
| S-219-AC-5 | `tower.config` exists with the four default values | FR-13, FR-28, FR-31 | TC-219-13 | TC-219-14 | L2.5 | SCH | pending | — |
| S-219-AC-6 | Every new public table is RLS deny-all and is covered by `rls-deny-all` without editing it | FR-14; PRD §17 | TC-219-15 | TC-219-16 | L2.5 | SCH, RLS | pending | — |
| S-219-AC-7 | No existing table is altered | — (D-30) | TC-219-18 | TC-219-17 | L1, L2.5 | REVIEW | pending | — |

### S-220 — Token and repository lifecycle (#488)

| Story AC | Criterion (short) | PRD FR / AC | Positive | Negative, edge, security, property | Layers | Planned test files | Observed result | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S-220-AC-1 | `generateTowerToken()` format and hash; the plain token is returned once and not stored | FR-2 | TC-220-01 | TC-220-02, TC-220-03 | L1, L2.5 | TOK, REP | pending | — |
| S-220-AC-2 | `verifyTowerToken` returns the repository id, or one identical negative for five failure kinds | FR-5; AC-3 | TC-220-04 | TC-220-05, TC-220-06, EC-29, RT-06 | L1, L2.5 | REP, TOK | pending | — |
| S-220-AC-3 | `timingSafeEqual` is used; an unknown id still performs one comparison against a dummy hash | FR-5; PRD §17 | TC-220-07 | TC-220-08 | L1 | TOK | pending | — |
| S-220-AC-4 | `registerTowerRepository` creates repository, token, marker; `already_registered`; `invalid_name` | FR-1, FR-2; AC-1 | TC-220-09 | TC-220-10, TC-220-11, TC-220-12, SN-09 | L1, L2.5 | REP, REVIEW | pending | — |
| S-220-AC-5 | `rotateTowerToken` revokes and issues atomically; the old token no longer verifies | FR-3; AC-5 | TC-220-13 | TC-220-14, TC-220-15, SN-07, SN-09 | L1, L2.5 | REP, ING-I, REVIEW | pending | — |
| S-220-AC-6 | `revokeTowerToken` leaves no active token; `removeTowerRepository` deletes everything under it | FR-3 | TC-220-16, TC-220-17 | TC-220-18, SN-08, SN-09, EC-23 | L1, L2.5 | REP, ING-I, REVIEW, PRU | pending | — |
| S-220-AC-7 | `setTowerStaleThreshold` accepts 1–720 or null and rejects anything else | FR-31 | TC-220-19 | TC-220-20, SN-09, EC-07 | L1, L2.5 | REP, REVIEW, RD-I | pending | — |
| S-220-AC-8 | No function logs the token or the header | PRD §17 | TC-220-23 | TC-220-03, TC-220-21, TC-220-22 | L1, L2.5 | REP, TOK | pending | — |

### S-221 — Ingestion contract version 1 (#489)

| Story AC | Criterion (short) | PRD FR / AC | Positive | Negative, edge, security, property | Layers | Planned test files | Observed result | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S-221-AC-1 | `names.ts` exports the eight step names and the eight stage names in order | FR-17, FR-19 | TC-221-01 | TC-221-02 | L1 | CON | pending | — |
| S-221-AC-2 | `validatePush` accepts every valid fixture (normalized) and rejects every invalid one with path and a value-free message | FR-6 | TC-221-03, CT-I-01 | TC-221-04, TC-221-05, TC-221-24, CT-I-02, SN-11, RT-07 | L1, L2.5 | CON, ING-I, RD-I | pending | — |
| S-221-AC-3 | The listed rejections: version, `push_id`, kinds, names, result, skipped reason, future time, caps | FR-7, FR-8; AC-7 | TC-221-13 | TC-221-06, TC-221-07, TC-221-08, TC-221-09, TC-221-10, TC-221-11, TC-221-12, TC-221-25, CT-I-08, CT-I-12, SN-01, SN-02 | L1, L2.5 | CON, ING-I | pending | — |
| S-221-AC-4 | Unknown extra fields are accepted and ignored | FR-7 | TC-221-14, CT-I-09 | TC-221-15, RT-07 | L1, L2.5 | CON, ING-I | pending | — |
| S-221-AC-5 | The seven event kinds, `session_ended` with `usage`, and `lanes` in both states are accepted | FR-6 (FR-33 to FR-39 reserved) | TC-221-16, TC-221-17, CT-I-03 | TC-221-18 | L1, L2.5 | CON, ING-I | pending | — |
| S-221-AC-6 | The contract document covers envelope, kinds, event kinds, response codes; its examples are the fixtures | FR-7 (D-16) | TC-221-19, TC-221-21, CT-I-14 | TC-221-20 | L1, Manual | CON, REVIEW | pending | — |
| S-221-AC-7 | At most 20 errors are returned | — (spec §6.1) | TC-221-23 | TC-221-22, CT-I-13, RT-07 | L1, L2.5 | CON, ING-I | pending | — |

### S-222 — `tower_apply_push` (#490)

| Story AC | Criterion (short) | PRD FR / AC | Positive | Negative, edge, security, property | Layers | Planned test files | Observed result | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S-222-AC-1 | A repeated `push_id` returns `duplicate` and changes no row | FR-9; AC-6 | TC-222-01 | TC-222-02, TC-222-03, EC-20, RT-02 | L2.5 | APP, PRU, APR | pending | — |
| S-222-AC-2 | A newer `observed_at` replaces a cell; an equal or older one does not | FR-8, FR-9 | TC-222-04 | TC-222-05, TC-222-06, TC-222-07, EC-25, EC-26, RT-01, RT-03 | L2.5 | APP, APR | pending | — |
| S-222-AC-3 | Two branches that disagree leave the newer observation, whichever arrived last | FR-8 | TC-222-08 | TC-222-09, TC-222-10, RT-01 | L2.5 | APP, APR | pending | — |
| S-222-AC-4 | `removed_at`: never from a non-default snapshot; only on items seen on default; cleared on reappearance | FR-8 | TC-222-12, TC-222-14 | TC-222-11, TC-222-13, TC-222-15, EC-26, EC-30, RT-04 | L2.5 | APP, APR | pending | — |
| S-222-AC-5 | An event for an unknown issue is stored unplaced and applied when a snapshot supplies the issue | FR-10; AC-8 | TC-222-16 | TC-222-17, TC-222-18, TC-222-19, RT-04 | L2.5 | APP, APR | pending | — |
| S-222-AC-6 | Rework increments once per distinct key and not on a re-sent failure | FR-25; AC-13 (data half) | TC-222-20, TC-222-21 | TC-222-22, TC-222-23, TC-222-24, RT-03 | L2.5 | APP, APR | pending | — |
| S-222-AC-7 | `block_raised` then `block_cleared` adds to `waiting_seconds`; `waiting_reported` stays false with no block | FR-26; AC-14 (data half) | TC-222-25 | TC-222-26, TC-222-27, TC-222-28 | L2.5 | APP | pending | — |
| S-222-AC-8 | `first_observed_at`, `shipped_at`, `event_count`, `workflow_agents`, `tokens_total`, `models` follow §8.3 | FR-12, FR-24 | TC-222-29, TC-222-30 | TC-222-31, TC-222-32, EC-25, RT-03 | L2.5 | APP, APR | pending | — |
| S-222-AC-9 | Each applied push sets `last_push_received_at`, `last_push_outcome` and increments the marker by one | FR-11; AC-2 | TC-222-33 | TC-222-34, EC-30, RT-02 | L2.5 | APP, APR | pending | — |
| S-222-AC-10 | Executable by `service_role` only; the repository id is an argument, never read from the payload | FR-4 | TC-222-37 | TC-222-35, TC-222-36, SN-03, SN-06 | L2.5 | DEF, APP, ING-I | pending | — |
| S-222-AC-11 | Two concurrent pushes for one repository both succeed with the result of a sequential application | FR-9 | TC-222-38 | TC-222-39, TC-222-40, TC-222-41, EC-22, RT-05 | L2.5 | APP, PRU, APR | pending | — |

### S-223 — `POST /api/tower/ingest` (#491)

| Story AC | Criterion (short) | PRD FR / AC | Positive | Negative, edge, security, property | Layers | Planned test files | Observed result | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S-223-AC-1 | A valid push returns 202; the same `push_id` again returns 200 | FR-5; AC-2, AC-6 | TC-223-01, CT-I-01, CT-I-03, CT-I-04, CT-I-09 | TC-223-02, TC-223-03, CT-I-11, SN-03, EC-27 | L1, L2.5 | ING-I, ING-U | pending | — |
| S-223-AC-2 | Missing, malformed, unknown and revoked each return 401 with the identical body; nothing is stored | FR-5; AC-3 | TC-223-05 | TC-223-04, CT-I-05, SN-04, SN-05, SN-07, SN-08, EC-27, RT-06 | L1, L2.5 | ING-I, TOK | pending | — |
| S-223-AC-3 | A valid token with another repository's name returns 403 and stores no tower data | FR-4, FR-5; AC-4 | TC-223-23 | TC-223-06, TC-223-07, CT-I-06, SN-06 | L2.5 | ING-I | pending | — |
| S-223-AC-4 | Over 1 MiB returns 413 without whole-body buffering; invalid JSON or contract failure returns 422 | FR-7; AC-7 | TC-223-11 | TC-223-08, TC-223-09, TC-223-10, CT-I-02, CT-I-07, CT-I-08, CT-I-12, CT-I-13, SN-01, SN-02, SN-10, SN-12, EC-28 | L1, L2.5 | ING-I, ING-U | pending | — |
| S-223-AC-5 | The body is not read before the token is verified | PRD §17 | TC-223-13 | TC-223-12, TC-223-14 | L1 | ING-U | pending | — |
| S-223-AC-6 | 403, 413 and 422 are recorded in `tower_pushes` and set `last_push_outcome` to `rejected` | FR-11 | TC-223-15 | TC-223-16, EC-06 | L2.5 | ING-I, RD-I | pending | — |
| S-223-AC-7 | `/api/tower/ingest` is class `internal`; every other `/api/tower/**` path stays `api` | FR-5; AC-23 | TC-223-17, TC-223-19 | TC-223-18 | L1, L2 | POL, GATE-C | pending | — |
| S-223-AC-8 | An unhandled error returns 500 and logs only the error name; token, header, body never logged | PRD §17 | TC-223-22 | TC-223-20, TC-223-21, CT-I-10, SN-12 | L1, L2.5 | ING-U, ING-I | pending | — |

### S-224 — Retention (#492)

| Story AC | Criterion (short) | PRD FR / AC | Positive | Negative, edge, security, property | Layers | Planned test files | Observed result | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S-224-AC-1 | Events of an issue shipped longer ago than the retention are deleted; `summary_final_at` set; summary unchanged | FR-12, FR-13; AC-19 | TC-224-01 | TC-224-02, EC-18, EC-19, EC-23 | L2.5 | PRU | pending | — |
| S-224-AC-2 | Events of an open issue, and of one shipped inside the window, are kept whatever their age | FR-13 | TC-224-03 | TC-224-04, EC-18 | L2.5 | PRU | pending | — |
| S-224-AC-3 | Wave-level events are pruned by their wave's `shipped_at` | FR-13 | TC-224-05 | TC-224-06, EC-24 | L2.5 | PRU | pending | — |
| S-224-AC-4 | `tower_pushes` rows older than `push_retention_days` are deleted | — (D-28) | TC-224-07 | TC-224-08, EC-20, EC-21 | L2.5 | PRU | pending | — |
| S-224-AC-5 | `tower-prune` is scheduled daily; a second run changes nothing | FR-13 | TC-224-09 | TC-224-10, TC-224-11, EC-22 | L2.5 | PRU, DEF | pending | — |
| S-224-AC-6 | Changing a `tower.config` value changes the behavior without a migration | FR-13, FR-31 | TC-224-12 | TC-224-13, EC-05, EC-13 | L2.5 | PRU, RD-I | pending | — |

### S-225 — Read contract version 1 (#493)

| Story AC | Criterion (short) | PRD FR / AC | Positive | Negative, edge, security, property | Layers | Planned test files | Observed result | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S-225-AC-1 | `buildRepositoryTree` and `buildRepositorySummaries` are pure and return the §6.2 shapes | FR-14 | TC-225-01, CT-R-01 | TC-225-02, TC-225-03, CT-R-06, SN-11, RT-08 | L1, L2.5 | RD-U, RD-I | pending | — |
| S-225-AC-2 | Step gaps: difference between consecutive `passed` or `skipped` cells; `null` when missing or negative | FR-23 | TC-225-04 | TC-225-05 | L1 | RD-U | pending | — |
| S-225-AC-3 | `in_wave` false with no wave; issues with no PRD under `no_prd_issues` | FR-21, FR-22; AC-12 (data half) | TC-225-06 | TC-225-07 | L1 | RD-U | pending | — |
| S-225-AC-4 | An unreported value is `null` | FR-26, FR-27; AC-14 (data half) | TC-225-08 | TC-225-09, CT-R-03, RT-08 | L1 | RD-U | pending | — |
| S-225-AC-5 | `stale` only with open work and a last push older than the threshold; override, default, `threshold_source` | FR-31; AC-16, AC-17 (data half) | TC-225-10 | TC-225-11, EC-01, EC-02, EC-03, EC-04, EC-05, EC-06, EC-07, RT-08 | L1, L2.5 | RD-U, RD-I | pending | — |
| S-225-AC-6 | `scope=recent` and `scope=all` | FR-28; AC-18 (data half) | TC-225-12, TC-225-13, CT-R-04 | TC-225-14, EC-08, EC-09, EC-10, EC-11, EC-12, EC-13, RT-08 | L1, L2.5 | RD-U, RD-I | pending | — |
| S-225-AC-7 | Rollups match non-removed children; the wave with no audit evidence and a Done ship stage | FR-16, FR-17, FR-18; AC-10 (data half), AC-9 (counts) | TC-225-15, TC-225-16 | TC-225-17, EC-12, RT-08 | L1 | RD-U | pending | — |
| S-225-AC-8 | The two GET endpoints return the module's output; 404 unregistered; 401 unauthenticated | FR-14; AC-23 | TC-225-18, CT-R-02 | TC-225-19, TC-225-20, CT-R-05 | L2, L2.5 | RD-I, GATE-C | pending | — |
| S-225-AC-9 | Reads page in 1,000-row pages; 2,500 issues are all returned | FR-14 | TC-225-21 | TC-225-22, TC-225-23, EC-14, EC-15, EC-16, EC-17 | L1, L2.5 | RD-I, RD-U | pending | — |
| S-225-AC-10 | The read-contract document; one test asserts module output, endpoint body and fixture are equal | FR-14 | TC-225-24, CT-R-01, CT-R-02 | TC-225-25, CT-R-07 | L1, L2.5 | RD-I, RD-U | pending | — |

### S-226 — Minimal `/tower` (#494)

| Story AC | Criterion (short) | PRD FR / AC | Positive | Negative, edge, security, property | Layers | Planned test files | Observed result | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S-226-AC-1 | The sidebar has a "Control Tower" entry leading to `/tower` | FR-15 (D-30) | TC-226-01 | TC-226-02 | L2 | SB-C | pending | — |
| S-226-AC-2 | The list shows last-reported time, last push outcome, accepted and rejected counts for the last day | FR-11, FR-15 | TC-226-03 | TC-226-04, SC-08, EC-15 | L2, L2.5, E2E | UI-C, E2E, RD-I | pending | — |
| S-226-AC-3 | Registering reveals the token once with the CLI line; never again after close and reload | FR-2; AC-1 | SC-01, SC-03 | SC-02 | E2E | E2E | pending | — |
| S-226-AC-4 | A duplicate or invalid name shows the named error and creates nothing | FR-1 | TC-226-06 | TC-226-05, SC-04 | L1, L2, E2E | UI-U, E2E, UI-C | pending | — |
| S-226-AC-5 | Rotate, revoke and remove each ask for confirmation; remove states what is deleted | FR-3 | TC-226-07, SC-05 | TC-226-08, SC-08 | L2, E2E | UI-C, E2E | pending | — |
| S-226-AC-6 | The threshold field shows the value in effect and its source; clearing returns to the default | FR-31 | TC-226-09 | TC-226-10, SC-06 | L1, E2E | UI-U, E2E | pending | — |
| S-226-AC-7 | Empty states with the next CLI step; the page says the hierarchy arrives with the next wave | FR-32 | TC-226-11 | TC-226-12 | L2 | UI-C | pending | — |
| S-226-AC-8 | A logged-out visit to `/tower` redirects to `/login` | FR-14; AC-23 | TC-226-13 | SC-07 | L1, E2E | E2E, POL | pending | — |

### S-227 — Release-gate probes and runbook (#495)

| Story AC | Criterion (short) | PRD FR / AC | Positive | Negative, edge, security, property | Layers | Planned test files | Observed result | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S-227-AC-1 | `verify-panel-auth.sh` probes ingest (no token) and read (no session) and requires 401 for both | AC-3, AC-23 | TC-227-01 | TC-227-02, TC-227-03 | L1, Manual | REVIEW, PAC-CLI | pending | — |
| S-227-AC-2 | `evaluateAuthGate` fails when either probe returns anything else, including 404 and 302 | AC-3, AC-23 | TC-227-04 | TC-227-05 | L1 | PAC | pending | — |
| S-227-AC-3 | The parser's unit tests cover pass/pass, each failing, both failing; CI runs them | AC-3, AC-23 | TC-227-06 | TC-227-07 | L1 | PAC, REVIEW | pending | — |
| S-227-AC-4 | The runbook covers its five procedures | — (spec §15) | TC-227-08 | TC-227-09 | L1, Manual | REVIEW | pending | — |
| S-227-AC-5 | The runbooks index links the new runbook | — (spec §15) | TC-227-10 | TC-227-11 | L1 | REVIEW | pending | — |

### S-228 — Wave A live (manual checklist) (#496)

| Story AC | Criterion (short) | PRD FR / AC | Positive | Negative, edge, security, property | Layers | Planned test files | Observed result | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S-228-AC-1 | Pre-checks on the hosted project: `pg_cron`, Realtime, `service_role` execute | — (spec §15) | MV-228-01 | MV-228-02, MV-228-03 | Manual | LIVE | pending | — |
| S-228-AC-2 | Migrations applied live after owner confirmation; `tower-prune` listed in `cron.job` | FR-13 | MV-228-04 | MV-228-05 | Manual | LIVE | pending | — |
| S-228-AC-3 | Panel deployed; the release gate passes with the two new probes | AC-3, AC-23 | MV-228-06 | MV-228-07 | Manual | LIVE | pending | — |
| S-228-AC-4 | One live repository; snapshot 202, event 202, repeat 200, wrong token 401 | FR-1; AC-2, AC-3, AC-6 | MV-228-08 | MV-228-09 | Manual | LIVE | pending | — |
| S-228-AC-5 | `/tower` shows the repository with its last-reported time and push counts | FR-11, FR-15 | MV-228-10 | MV-228-11 | Manual | LIVE | pending | — |
| S-228-AC-6 | Technical guidelines, roadmap row and `infra/changes/` record updated | — (spec §15) | MV-228-12 | MV-228-13 | Manual | LIVE | pending | — |

## 3. PRD acceptance criteria in Wave A scope

PRD AC-20 to AC-22 are Wave C. The rendering half of AC-9 to AC-12 and AC-15 to AC-18 belongs to Wave B stories; only the data half is traced here.

| PRD AC | Scope in Wave A | Story ACs | Cases |
| --- | --- | --- | --- |
| AC-1 | Full | S-220-AC-4, S-226-AC-3 | TC-220-09, TC-220-10, TC-220-11, TC-220-12, SN-09, SC-01, SC-02, SC-03 |
| AC-2 | Full | S-222-AC-9, S-223-AC-1, S-228-AC-4 | TC-222-33, TC-222-34, EC-30, RT-02, TC-223-01, TC-223-02, TC-223-03, CT-I-01, CT-I-03, CT-I-04, CT-I-09, CT-I-11, SN-03, EC-27, MV-228-08, MV-228-09 |
| AC-3 | Full, plus release gate | S-220-AC-2, S-223-AC-2, S-227-AC-1, S-227-AC-2, S-227-AC-3, S-228-AC-3, S-228-AC-4 | TC-220-04, TC-220-05, TC-220-06, EC-29, RT-06, TC-223-04, TC-223-05, CT-I-05, SN-04, SN-05, SN-07, SN-08, EC-27, TC-227-01, TC-227-02, TC-227-03, TC-227-04, TC-227-05, TC-227-06, TC-227-07, MV-228-06, MV-228-07, MV-228-08, MV-228-09 |
| AC-4 | Full | S-223-AC-3 | TC-223-06, TC-223-07, TC-223-23, CT-I-06, SN-06 |
| AC-5 | Full | S-220-AC-5 | TC-220-13, TC-220-14, TC-220-15, SN-07, SN-09 |
| AC-6 | Full | S-222-AC-1, S-223-AC-1, S-228-AC-4 | TC-222-01, TC-222-02, TC-222-03, EC-20, RT-02, TC-223-01, TC-223-02, TC-223-03, CT-I-01, CT-I-03, CT-I-04, CT-I-09, CT-I-11, SN-03, EC-27, MV-228-08, MV-228-09 |
| AC-7 | Full | S-221-AC-3, S-223-AC-4 | TC-221-06, TC-221-07, TC-221-08, TC-221-09, TC-221-10, TC-221-11, TC-221-12, TC-221-13, TC-221-25, CT-I-08, CT-I-12, SN-01, SN-02, TC-223-08, TC-223-09, TC-223-10, TC-223-11, CT-I-02, CT-I-07, CT-I-13, SN-10, SN-12, EC-28 |
| AC-8 | Full (data) | S-222-AC-5 | TC-222-16, TC-222-17, TC-222-18, TC-222-19, RT-04 |
| AC-9 | Rollup counts only; rendering is S-230 | S-225-AC-7 | TC-225-15, TC-225-16, TC-225-17, EC-12, RT-08 |
| AC-10 | Data half; rendering is S-229/S-230 | S-225-AC-7 | TC-225-15, TC-225-16, TC-225-17, EC-12, RT-08 |
| AC-12 | Data half (`in_wave`); rendering is S-230 | S-225-AC-3 | TC-225-06, TC-225-07 |
| AC-13 | Data half (rework count) | S-222-AC-6 | TC-222-20, TC-222-21, TC-222-22, TC-222-23, TC-222-24, RT-03 |
| AC-14 | Data half (`null`, never 0) | S-222-AC-7, S-225-AC-4 | TC-222-25, TC-222-26, TC-222-27, TC-222-28, TC-225-08, TC-225-09, CT-R-03, RT-08 |
| AC-16 | Data half (`stale`) | S-225-AC-5 | TC-225-10, TC-225-11, EC-01, EC-02, EC-03, EC-04, EC-05, EC-06, EC-07, RT-08 |
| AC-17 | Data half (`stale`) | S-225-AC-5 | TC-225-10, TC-225-11, EC-01, EC-02, EC-03, EC-04, EC-05, EC-06, EC-07, RT-08 |
| AC-18 | Data half (`scope`) | S-225-AC-6 | TC-225-12, TC-225-13, TC-225-14, CT-R-04, EC-08, EC-09, EC-10, EC-11, EC-12, EC-13, RT-08 |
| AC-19 | Full | S-224-AC-1 | TC-224-01, TC-224-02, EC-18, EC-19, EC-23 |
| AC-23 | Full, plus release gate | S-223-AC-7, S-225-AC-8, S-226-AC-8, S-227-AC-1, S-227-AC-2, S-227-AC-3, S-228-AC-3 | TC-223-17, TC-223-18, TC-223-19, TC-225-18, TC-225-19, TC-225-20, CT-R-02, CT-R-05, SC-07, TC-226-13, TC-227-01, TC-227-02, TC-227-03, TC-227-04, TC-227-05, TC-227-06, TC-227-07, MV-228-06, MV-228-07 |
| AC-11 | Out of scope (rendering, S-229/S-230). The validator rule behind it is S-221-AC-3 | — | TC-221-10 |
| AC-15 | Out of scope (Wave B, S-232) | — | — |
| AC-20 to AC-22 | Out of scope (Wave C) | — | — |

## 4. Planned test files

| Key | File | Cases |
| --- | --- | --- |
| E2E | `panel/tests/e2e/tower-repositories.spec.ts` | 8 |
| SCH | `panel/tests/integration/tower-schema.test.ts` | 15 |
| RLS | `panel/tests/integration/rls-deny-all.test.ts` | 1 |
| DEF | `panel/tests/integration/definer-grants.test.ts` | 2 |
| TOK | `panel/tests/unit/tower-token.test.ts` | 8 |
| REP | `panel/tests/integration/tower-repository.test.ts` | 17 |
| CON | `panel/tests/unit/tower-contract.test.ts` | 26 |
| APP | `panel/tests/integration/tower-apply-push.test.ts` | 43 |
| APR | `panel/tests/integration/tower-apply-push-random.test.ts` | 5 |
| ING-U | `panel/tests/unit/tower-ingest.test.ts` | 9 |
| POL | `panel/tests/unit/auth-route-policy.test.ts` | 3 |
| GATE-C | `panel/tests/component/proxy-gate.test.ts` | 2 |
| ING-I | `panel/tests/integration/tower-ingest.test.ts` | 36 |
| PRU | `panel/tests/integration/tower-prune.test.ts` | 19 |
| RD-U | `panel/tests/unit/tower-read.test.ts` | 33 |
| RD-I | `panel/tests/integration/tower-read.test.ts` | 17 |
| UI-U | `panel/tests/unit/tower-repository-input.test.ts` | 3 |
| UI-C | `panel/tests/component/tower-repositories.test.tsx` | 7 |
| SB-C | `panel/tests/component/Sidebar.test.tsx` | 2 |
| PAC | `panel/tests/unit/panel-auth-check.test.ts` | 3 |
| PAC-CLI | `panel/tests/unit/panel-auth-check-cli.test.ts` | 1 |
| REVIEW | No test file. A recorded review or script run in the story PR | 11 |
| LIVE | `infra/changes/<date>-control-tower-wave-a/` (recorded live evidence) | 13 |

## 5. Open findings that hold a case's expected result

These cases are specified but cannot assert a final value until `product-engineer` decides the finding (test plan §8). They are not coverage gaps.

| Finding | Cases waiting on it |
| --- | --- |
| A-01 | TC-222-15, RT-01 |
| A-02 | TC-223-15, MV-228-10 |
| A-03 | TC-222-28, RT-01 |
| A-04 | MV-228-10, EC-06 |
| A-05 | EC-20 |
| A-06 | EC-19 |
| A-07 | CT-I-12 |
| A-08 | EC-26 |
| A-10 | CT-R-04, EC-12 |
| A-11 | TC-224-04, EC-08, EC-21 |
| A-12 | TC-225-07 |
| A-13 | MV-228-07 |
| A-14 | TC-222-32 |
| A-16 | TC-221-05 |
| A-17 | EC-25 |
| A-18 | TC-220-11 |
| A-19 | TC-220-18, SC-08, EC-27, EC-28 |
| A-20 | TC-223-09 |
| A-21 | MV-228-03 |
| A-25 | TC-220-01, TC-220-03, MV-228-12 |
