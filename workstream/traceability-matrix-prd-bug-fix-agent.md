# Traceability Matrix — Bug Fix Agent (verifier, Design Mode)

> Companion to [`test-plan-prd-bug-fix-agent.md`](test-plan-prd-bug-fix-agent.md) **v2.0**. It maps:
> - **PRD FR → PRD AC → story AC → test case IDs → layer** (§A);
> - each PRD AC to at least one positive and one negative or edge test (§B);
> - every active story AC (17 stories, 109 ACs; S-194-AC9 added in v2.4) to its tests (§C).
>
> Sources: PRD v2.0, spec v2.0, stories v2.0, task list v2.0, decisions D-01…D-106, and the merged
> webhook trigger (`origin/main`: `panel/lib/domain/webhook-routing.ts`, `webhook-resolve.ts`,
> `panel/lib/webhooks/fire.ts`, migrations `20261020140000_webhook_guardrails.sql` and
> `20261020150000_webhook_notify_generalize.sql`), read-only.
>
> The `AC-ID → Test-Case-ID → Observed → Pass/Fail/Drift` columns are filled in Audit Mode.
> Every **Observed** and **Result** cell is `PENDING` until the work is implemented and audited.
>
> Path prefixes: `A/` = `agents/bug-fix/app/bugFix/`, `P/` = `panel/`. Layers: L1 unit, L2
> component, L2.5 integration (local Supabase), IC (in-container, deployed runtime), Live (fixture
> repo, real AWS or GitHub), MR (manual or review evidence). E2E has no active test in v2.0 (D-95).
> Test IDs are defined in the test plan: TC §4, SC §5, CT §6, RT §9. Rows changed in v2.0 are
> marked **(v2.0)**. Requirements, ACs and tests removed by PRD v2.0 are kept and marked
> **removed** or **retired (v2.0)**.

## Changelog

| Version | Date       | Summary                                                                                   | Author   |
| ------- | ---------- | ----------------------------------------------------------------------------------------- | -------- |
| 2.4 | 2026-10-24 | Drift reconciliation of S-190 audit findings DF-190-01/04/05/06/10 and the stream rule, confirmed by @llipe 2026-10-24, against test plan v2.5, spec v2.7 and stories v2.6. DF-190-01 (Major): PRD AC-20 and FR-5 gain S-194-AC9 and TC-194-21/-22 (the post-check and pre-push `linked_pr` re-checks) and EC-56; new row S-194-AC9; S-194-AC7 carries the flag gate (AC9 green, fix runner wired, DF-190-04); RT-07's `TestOwnedWhileAPrIsOpen` is pinned as a strict xfail until S-194 (§D.3). DF-190-05/06 and the stream rule: FR-26 names the entrypoint codes and `result.reason` (TC-190-03). DF-190-10: S-180-AC7 now maps to the entrypoint shell, with the step behaviour in TC-190-01/-02. DF-190-02 stays open (§D.3). Story ACs 108 → 109. | product-engineer |
| 2.3 | 2026-10-24 | Drift reconciliation of S-189 audit findings DF-189-01/04/05/07/08 and the S-189 fix-round hardening, confirmed by @llipe 2026-10-24, against test plan v2.4, spec v2.6 and stories v2.5. DF-189-01: S-189-AC3 and S-193-AC6 name the raw-blob tar, not `git archive`. Fix-round hardening: S-189-AC1 and AC3 gain TC-189-23 (`fsckObjects`, `.git` components, tar caps) and AC3 gains TC-189-22 (the link-free work-tree walk); FR-9 and AC-5 list both. DF-189-04/05/08: FR-6, S-189-AC4 and AC5 name the new repo-gate items, the fixed reply phrases and GNU make's makefile order. DF-189-07: S-180-AC5, S-189-AC1 and S-193-AC6 drop the `wrapper` user (D-110). §D.4 records the S-189 routing. | product-engineer |
| 2.2 | 2026-10-24 | D-112 / OQ-1 and drift reconciliation of DF-38 (race-loss part) and S-188 audit findings DF-188-01/02/05, confirmed by @llipe 2026-10-24, against test plan v2.3, spec v2.5 and stories v2.4. D-112 / OQ-1: S-189-AC6 states the rule (a Python repo needs `make install`, else refusal `repo_gate` "missing install target") and maps to TC-189-10, TC-189-07 and TC-189-14. DF-38 race-loss part resolved: S-188-AC2 states the withdrawal-fault rule and gains TC-185-14; §D.3's DF-38 row records the decision and keeps the S-194/S-186 parts open. DF-188-01: S-188-AC2 and §D.3's DF-33 row name both halves, `markers.open_claims()` and `refusal.active_claim_runs()`. DF-188-02 lands in TC-185-14 (test plan). DF-188-05: RT-07 leaves S-188-AC2 and S-188-AC5 and joins S-190-AC3. §D.4 records DF-188-01…07. No test added or retired; counts unchanged. | product-engineer |
| 2.1 | 2026-10-24 | Drift reconciliation of DF-33 and S-185 audit findings DF-185-01/02/03/05/06/07, confirmed by @llipe 2026-10-24, against test plan v2.2, spec v2.4 and stories v2.3. DF-33 resolved: S-185-AC2 and S-188-AC2 rows state the single open-claim definition (`markers.open_claims()`), and §D.3 no longer pins TC-185-20, TC-186-06 and TC-188-16 to the old S-185 rule. S-185-AC2 and S-185-AC5 gain CT-33 and CT-34 at L2 (the fix-round tests); CT-34's real-database L2.5 read is a residual (DF-185-08). §D.4 records DF-185-01…09. No test added or retired; counts unchanged. | product-engineer |
| 2.0 | 2026-10-22 | **Issue-mode refresh** against PRD v2.0 (FR-1, FR-3, FR-5–FR-23, FR-25–FR-34; AC-1–AC-12, AC-14, AC-16, AC-19–AC-24), spec v2.0, stories v2.0 (17 active, 108 story ACs), task list v2.0 and D-88…D-106. FR-1a, FR-1b, FR-2, FR-4 and FR-24, and AC-13, AC-15, AC-17 and AC-18, are marked removed, with their tests retired, not deleted. New rows: FR-28…FR-34; AC-19…AC-24; S-199. Counted tests 306 → 306 (76 retired, 76 new, 86 changed). Every v2.0 FR and AC, and every active story AC, maps to at least one active test. Known red: CT-28, SC-LIVE-10, SC-LIVE-15 (DF-29); TC-197-05 (failed half), CT-29, SC-LIVE-06 step 3 (DF-30). New findings DF-29…DF-38; highest impact Critical (DF-29). | verifier |
| 1.2 | 2026-10-20 | Supersedes the parallel design line merged in PR #350 (D-87, @llipe, 2026-10-20). Decision IDs from this line are renumbered D-25–D-67 → D-44–D-86 after main's D-43. The superseded line's changelog rows remain in git history (`875299a`, PR #350). Mechanical ID renumber only. | product-engineer |
| 1.1     | 2026-10-20 | Refresh after drift reconciliation D-62…D-78, against PRD v1.3, spec v1.3, stories v1.3 and task list v1.3. Story ACs renumbered to stories v1.3 (105 → 115). New tests from test plan v1.1 (269 → 306 counted) added to every affected row. DF-01…DF-19 marked resolved, and the new findings DF-20…DF-28 referenced where they pin a row. Gap G-6 closed by D-77; G-1…G-5 re-stated as still open. Two tests are known red against spec v1.3: TC-196-15 (DF-20) and TC-196-18 (DF-21). | verifier |
| 1.0     | 2026-10-20 | Initial matrix from test plan v1.0 (269 counted tests; 105 story ACs; 18 PRD ACs; FR-1…FR-27). | verifier |

## A. PRD FR → PRD AC → story AC → tests **(v2.0)**

| FR     | Requirement (short)                                  | PRD AC              | Story ACs                                                                                   | Test case IDs                                                                                                     | Layers                  | Gap / drift |
| ------ | ---------------------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ----------------------- | ----------- |
| FR-1   | Run repository (not a param); `issue_number` required, `trigger_comment_id`, Projects params, caps and budgets; registered schema validated by the invoke and webhook paths **(v2.0)** | AC-1, AC-19 | S-184-AC1–AC5 | TC-184-01…08, TC-184-10…15, TC-184-17, CT-01…04, CT-06, CT-19, CT-21…24, RT-06 | L1, L2.5, MR | DF-34 |
| FR-1a  | *Removed in v2.0 (label parameters, D-90, D-93)*     | (AC-17, AC-18 removed) | —                                                                                        | Retired: TC-184-09, TC-183-*, CT-05, RT-10, SC-E2E-01…05                                                          | —                       | — |
| FR-1b  | *Removed in v2.0 (label check, D-93)*                | (AC-18 removed)     | —                                                                                            | Retired: TC-185-03…08, TC-185-15, CT-11, RT-03, SC-LIVE-05                                                        | —                       | — |
| FR-2   | *Removed in v2.0 (oldest-ready-bug selection, D-90)* | (AC-1 v1.x)         | —                                                                                            | Retired: TC-187-*, CT-09, RT-11, SC-LIVE-04. Linked-PR detection lives on in FR-5(c)                               | —                       | — |
| FR-3   | Works on `issue_number` only; labels have no effect **(v2.0)** | — (business rule) | S-185 BR; S-190-AC1, AC2                                                                | TC-185-25, TC-190-12, TC-190-13, TC-184-12, RT-13                                                                 | L1, L2                  | — |
| FR-4   | *Removed in v2.0 (`no_findings`, D-90)*              | —                   | —                                                                                            | Retired: TC-187-08, TC-187-16. TC-190-12 asserts the agent never emits `no_findings`                               | —                       | — |
| FR-5   | Refusal cases (a)–(e): no claim, one reply, `not_applicable` **(v2.0)** | AC-2, AC-4, AC-20, AC-24 | S-185-AC1–AC5; S-189-AC5; S-194-AC9 (**v2.4**)                                        | TC-185-09…11, TC-185-13, TC-185-16…23, TC-189-07, TC-189-08, TC-189-21, CT-12, CT-33, CT-34, RT-02, RT-15, SC-LIVE-09, TC-194-21, TC-194-22 | L1, L2, L2.5, Live | DF-33 (resolved v2.1), DF-34, DF-35, DF-190-01 (decided v2.4, delivered in S-194) |
| FR-6   | Repo gate: `developer.md` + four gates (plus manifest, lockfile, supported manager, Python `install`) **(v2.3)** | AC-4                | S-189-AC4, S-189-AC5                                                                         | TC-189-04…09                                                                                                      | L1, L2                  | — |
| FR-7   | Claim: 👀 on the trigger comment + marked claim comment; no labels or assignees **(v2.0)** | AC-3, AC-19 | S-188-AC1, AC4; S-186-AC1–AC3                                                  | TC-188-02, TC-188-03, TC-188-08, TC-188-15, TC-186-01…07, TC-186-15, TC-186-17, CT-32, RT-02, SC-LIVE-01            | L1, L2, Live            | DF-32 |
| FR-8   | No assignee **(v2.0)**                               | AC-3                | S-188 BR; S-188-AC4                                                                          | TC-188-09, TC-188-08                                                                                              | L2                      | — |
| FR-9   | Wrapper owns GitHub and the board; confined CLI and repo scripts; wrapper git confined **(v2.0)** | AC-5, AC-6 | S-180-AC5, AC6; S-182-AC1–AC5; S-189-AC1–AC3; S-191-AC1, AC8; S-192-AC1; S-193-AC3, AC6; S-194-AC2; S-195-AC1–AC4 | TC-180-07…11, TC-182-01…05, TC-189-02, TC-189-16…20, TC-189-22, TC-189-23, TC-191-01, TC-191-02, TC-191-13, TC-191-18, TC-192-17, TC-193-14, TC-194-13, TC-194-18, SC-IC-01…05, SC-IC-07, SC-IC-08 | L1, L2, IC | — |
| FR-10  | Issue text as quoted, untrusted data                 | AC-6                | S-191-AC1, S-191-AC2                                                                         | TC-191-04, TC-191-14, RT-04, SC-IC-07, SC-IC-10                                                                   | L1, L2, IC              | — |
| FR-11  | Repo `.claude/` + `developer`, `MODEL_ID`, Anthropic API | — (no PRD AC)   | S-180-AC3 (`MODEL_ID` only)                                                                  | TC-180-03, TC-180-04, TC-191-01, TC-191-15, SC-IC-09                                                              | L1, L2, IC              | **G-1** (open) |
| FR-12  | Turn, CLI-time and run budgets → disposition         | AC-14               | S-191-AC4, S-191-AC7; S-184-AC4                                                              | TC-191-06…08, TC-191-11, TC-184-07, TC-184-13, TC-184-14                                                          | L1, L2                  | — |
| FR-13  | 10 code files / 400 code lines; docs and tests exempt | AC-7               | S-192-AC1, AC2, AC8                                                                          | TC-192-01…03, TC-192-05, TC-192-07, TC-192-15, TC-192-18, TC-184-13, RT-01, RT-08                                 | L1, L2                  | — |
| FR-14  | Forbidden paths: lockfiles, `.github/`, `.claude/` (case-insensitive) | AC-7 | S-192-AC2, AC3, AC4                                                                         | TC-192-01, TC-192-02, TC-192-04, TC-192-15, TC-192-16, TC-192-19, TC-192-20, RT-01                                | L1, L2                  | — |
| FR-15  | At least one test changed                            | AC-8                | S-192-AC2                                                                                    | TC-192-06                                                                                                         | L2                      | — |
| FR-16  | Per-file rationale; model text neutralized           | — (AC-10 body)      | S-192-AC5; S-194-AC3, AC4; S-186-AC4                                                         | TC-192-08, TC-194-04, TC-194-05, TC-194-17, RT-12                                                                 | L1, L2                  | — |
| FR-17  | Wrapper runs the four gates itself                   | AC-9                | S-189-AC7; S-192-AC7                                                                         | TC-189-11, TC-192-11, TC-192-12                                                                                   | L2                      | — |
| FR-18  | `audit` recorded, never blocks                       | AC-9                | S-189-AC7, AC8; S-192-AC7                                                                    | TC-189-13, TC-192-11, TC-192-13                                                                                   | L2                      | — |
| FR-19  | Red-to-green                                         | AC-8                | S-193-AC1–AC7                                                                                | TC-193-01…17, RT-05                                                                                               | L1, L2                  | — |
| FR-20  | Draft PR, branch, Conventional Commit, `--body-file`, body sections; 🚀 + a comment linking the PR **(v2.0)** | AC-10, AC-19 | S-194-AC1–AC4, AC6                                                      | TC-194-01…06, TC-194-09, TC-194-17…20, RT-09, RT-12, SC-LIVE-02                                                   | L1, L2, Live            | DF-37 (no `pr` marker in FR-20), DF-38 |
| FR-21  | `pull_request` artifact                              | AC-10               | S-194-AC5                                                                                    | TC-194-07                                                                                                         | L2                      | — |
| FR-22  | Disposition on every no-PR path: 😕 + diagnosis, issue open, labels and assignees untouched, no auto-retry **(v2.0)** | AC-11 | S-186-AC5; S-191-AC4–AC6; S-192-AC2, AC3, AC5–AC7; S-193-AC2, AC5, AC6 | TC-186-08…12, TC-186-16, TC-191-09, TC-191-16, TC-194-16, SC-LIVE-03                    | L2, Live                | **G-4** (open); DF-38 |
| FR-23  | `finally` path + signal backstop, only after confirmed ownership **(v2.0)** | AC-11 | S-186-AC6; S-188-AC3; S-190-AC3                                                     | TC-186-13, TC-186-14, TC-188-12, TC-188-14, TC-190-06…08, TC-199-18                                               | L2                      | — |
| FR-24  | *Removed in v2.0 (stale-claim sweep, D-94).* Residual: a killed run's claim stays; once the reaper marks it `timed_out`, a new `/bug-fix` proceeds | AC-24 | S-188 (testing note) | Retired: TC-196-*, CT-10, CT-20, SC-LIVE-07. Residual covered by TC-188-10, TC-185-20, CT-34, SC-LIVE-12 | L2, L2.5, Live | — |
| FR-25  | Steps and `run_events` per step (incl. refusal checks and board update); heartbeat; backstop **(v2.0)** | — (no PRD AC) | S-190-AC1 (Wave A steps only)                                                  | TC-190-01, TC-194-14                                                                                              | L2                      | **G-2** (open) |
| FR-26  | Outcome mapping; only `failed` counts toward the webhook rule's breaker **(v2.0)** | AC-2, AC-11, AC-12 | S-190-AC2; S-185-AC1, AC4, AC5; S-191-AC4–AC6; S-194-AC8; S-197-AC4      | TC-190-03…05, TC-190-11, TC-190-12, TC-185-10, TC-185-14, TC-191-10, TC-191-16, TC-191-17, TC-194-11, TC-197-05, TC-197-07, CT-29 | L1, L2, L2.5 | **DF-30** (Major); DF-190-05/06 decided v2.4: the entrypoint codes are `failed`, counted, with no outcome; `result.reason` on `needs_review` (TC-190-03) |
| FR-27  | `runs.metrics`, including board results **(v2.0)**   | — (no PRD AC)       | S-190-AC4; S-191-AC3; S-199-AC5; S-198-AC6                                                   | TC-190-09, CT-14, TC-194-15, TC-199-15, TC-198-05                                                                 | L1, L2, Live            | **G-3** (open, narrowed) |
| FR-28  | Webhook rule on `issue_comment`, configured in the panel, no new trigger code; runbook documents the rule **(v2.0, new)** | AC-1, AC-16 | S-184-AC5; S-197-AC2, AC3                          | CT-23…28, TC-197-03, TC-197-11, RT-14, SC-LIVE-08, SC-LIVE-15                                                      | L1, L2.5, Live, MR      | **DF-29** (Critical), DF-31 |
| FR-29  | Who may trigger = the rule's configuration; the agent checks nothing **(v2.0, new)** | AC-1 | S-185 BR; S-197-AC2                                                                | CT-25, RT-14, TC-185-24, SC-LIVE-08                                                                               | L1, L2, Live            | — |
| FR-30  | No schedule seeded or recommended **(v2.0, new)**    | —                   | S-197 (context)                                                                              | TC-197-03, TC-197-09                                                                                              | MR, Live                | — |
| FR-31  | Detect linked boards; one or override → claim `In progress`, PR `In review`, disposition `Ready`; add the card if absent **(v2.0, new)** | AC-21 | S-199-AC1, AC2; S-182-AC7                     | TC-199-01…07, TC-199-18, CT-30, CT-31, RT-16, SC-IC-11, SC-LIVE-02, SC-LIVE-03, SC-LIVE-14                         | L1, L2, IC, Live        | — |
| FR-32  | No board → only detection; several → skip + `run_event`; refusals never touch the board **(v2.0, new)** | AC-22, AC-2 | S-199-AC3, AC5; S-185-AC4; S-188-AC2                                     | TC-199-08…10, TC-199-14, TC-185-23, TC-188-14, TC-189-21, SC-LIVE-14                                               | L2, Live                | DF-35 |
| FR-33  | Params `project`, `status_in_progress`, `status_in_review`, `status_ready`; an unknown status is logged and skipped **(v2.0, new)** | AC-22, AC-23 | S-199-AC1, AC4; S-184-AC3, AC4                                  | TC-199-02, TC-199-03, TC-199-05, TC-199-07, TC-199-10, TC-184-07, TC-184-13, CT-21                                | L1, L2, L2.5            | — |
| FR-34  | Classic PAT, `project` scope, wrapper-only, scrubbed; best effort, never changes the outcome or the breaker **(v2.0, new)** | AC-5, AC-23 | S-181-AC3, AC4; S-182-AC7; S-199-AC4, AC6; S-180-AC3 | TC-181-12, TC-181-13, TC-199-11…13, TC-199-16, TC-199-17, TC-199-19, TC-199-20, TC-180-15, TC-182-01, TC-191-02, SC-IC-13, SC-IC-14, SC-LIVE-13 | L1, L2, IC, Live | DF-36 |

## B. PRD AC rollup (positive + negative/edge) **(v2.0)**

| PRD AC | Story ACs                                                         | Positive                                                     | Negative / edge                                                                            | Layers                     | Observed | Result  |
| ------ | ----------------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------ | -------------------------- | -------- | ------- |
| AC-1 (trigger) **(v2.0)** | S-184-AC5; S-197-AC2, AC3                      | CT-23, CT-25 (match cases), SC-LIVE-08 (step 1)              | CT-24, CT-25 (non-match cases), CT-26, CT-28 (known red, DF-29), RT-14, SC-LIVE-08 (steps 2–5), SC-LIVE-15 (known red) | L1, L2.5, Live | PENDING  | PENDING |
| AC-2 (refusals) **(v2.0)** | S-185-AC2–AC4; S-189-AC5; S-198-AC3         | TC-185-16, TC-185-17, TC-185-18, TC-185-19, TC-185-20, SC-LIVE-09 | TC-185-09, TC-185-13, TC-185-21, TC-185-23, TC-189-08, TC-189-21, CT-33, RT-15             | L1, L2, Live               | PENDING  | PENDING |
| AC-3 (claim) **(v2.0)** | S-188-AC1, AC4; S-186-AC1                        | TC-188-02, TC-188-03, TC-188-08, SC-LIVE-01                  | TC-188-04, TC-188-06, TC-188-09, TC-188-15, RT-07                                          | L1, L2, Live               | PENDING  | PENDING |
| AC-4 (repo gate) **(v2.0)** | S-189-AC5                                    | TC-189-06                                                    | TC-189-07, TC-189-08, TC-189-09, TC-189-21                                                 | L1, L2                     | PENDING  | PENDING |
| AC-5 (confinement) **(v2.0)** | S-180-AC5, AC6; S-182-AC1–AC5, AC7; S-189-AC1–AC3; S-191-AC1, AC8; S-194-AC2; S-195-AC2, AC3; S-199-AC6 | TC-182-01, TC-191-02, TC-180-10, TC-189-18, TC-199-16 | SC-IC-01, SC-IC-03, SC-IC-04, SC-IC-05, SC-IC-08, SC-IC-13, TC-180-09, TC-182-05, TC-189-02, TC-189-16, TC-189-17, TC-189-19, TC-189-22, TC-189-23, TC-191-18, TC-194-18, TC-199-17 | L1, L2, IC | PENDING  | PENDING |
| AC-6 (injection) | S-191-AC1, AC2; S-194-AC3; S-195-AC1–AC4                 | TC-191-04, SC-IC-07                                          | RT-04, TC-191-13, TC-194-05, TC-194-13, TC-194-17, RT-12, TC-186-16, SC-IC-05 (residual, D-66), SC-IC-08, SC-IC-10 | L1, L2, IC | PENDING  | PENDING |
| AC-7 (caps)   | S-192-AC1–AC4, AC8                                          | TC-192-05 (10 files / 400 lines pass; docs and tests exempt), TC-192-01 | TC-192-05 (11 / 401), TC-192-04, TC-192-15, TC-192-16, TC-192-18, TC-192-19, TC-192-20, RT-01, RT-08 | L1, L2 | PENDING  | PENDING |
| AC-8 (regression test) | S-192-AC2; S-193-AC5, AC7                          | TC-193-08, TC-193-13, TC-193-17                              | TC-192-06, TC-193-06, TC-193-11, TC-193-12                                                 | L1, L2                     | PENDING  | PENDING |
| AC-9 (gates)  | S-189-AC7; S-192-AC7                                        | TC-192-11                                                    | TC-192-12 (×4 gates), TC-192-13                                                            | L2                         | PENDING  | PENDING |
| AC-10 (PR) **(v2.0)** | S-194-AC1–AC6; S-198-AC1                           | TC-194-03, TC-194-04, TC-194-07, TC-194-19, SC-LIVE-02       | TC-194-05, TC-194-06, TC-194-09, TC-194-11, TC-194-12, TC-194-17, TC-194-20                | L1, L2, Live               | PENDING  | PENDING |
| AC-11 (disposition) **(v2.0)** | S-186-AC5, AC6; S-191-AC6; S-198-AC2      | TC-186-08, TC-194-16, SC-LIVE-03                             | TC-186-10, TC-186-11, TC-186-12, TC-186-14, TC-186-16, TC-191-16, TC-194-11                | L2, Live                   | PENDING  | PENDING |
| AC-12 (breaker) **(v2.0)** | S-190-AC2; S-197-AC4                          | TC-197-05 (needs_review/not_applicable half), TC-197-07, TC-190-05 | TC-197-05 (failed half, **known red**, DF-30), CT-29 (known red), SC-LIVE-06 (step 3 known red) | L1, L2.5, Live | PENDING  | PENDING |
| AC-13  | *Removed in v2.0 (D-94).* Retired: TC-196-*, SC-LIVE-07, RT-07 (sweep half) | —                                     | —                                                                                          | —                          | n/a      | n/a     |
| AC-14 (budget) | S-191-AC4, AC7                                             | TC-191-06, TC-191-07, TC-191-08                              | TC-191-11, TC-184-07, TC-184-13, TC-184-14                                                 | L1, L2                     | PENDING  | PENDING |
| AC-15  | *Removed in v2.0 (D-96).* Retired: TC-197-06; SC-LIVE-06 re-targeted | —                                            | —                                                                                          | —                          | n/a      | n/a     |
| AC-16 (live) **(v2.0)** | S-198-AC1, AC2                                   | SC-LIVE-02                                                   | SC-LIVE-03, SC-LIVE-15 (known red, DF-29)                                                  | Live                       | PENDING  | PENDING |
| AC-17  | *Removed in v2.0 (D-93).* Retired: TC-187-12, TC-185-05, TC-185-15, RT-03, RT-11, SC-E2E-01/02/05, SC-LIVE-04 | — | —                                                                                          | —                          | n/a      | n/a     |
| AC-18  | *Removed in v2.0 (D-93).* Retired: TC-185-03…09 (label parts), TC-184-09, SC-E2E-03, SC-LIVE-05. TC-185-09 and TC-185-13 re-targeted | — | —                                                                    | —                          | n/a      | n/a     |
| AC-19 (manual invoke) **(v2.0, new)** | S-188-AC1; S-190-AC5; S-198-AC4    | TC-188-15, SC-LIVE-11, SC-LIVE-01                            | TC-186-15 (no `trigger_comment_id` → no reaction call), TC-194-19 (comment without 🚀)      | L2, Live                   | PENDING  | PENDING |
| AC-20 (concurrency) **(v2.0, new)** | S-185-AC2; S-188-AC2, AC5; S-194-AC9 (**v2.4**); S-198-AC3 | TC-188-13, TC-185-20, TC-194-21, SC-LIVE-10                          | TC-188-04, TC-188-07, TC-188-16, RT-07, TC-194-22, EC-56, CT-28 (known red, DF-29); DF-32 pins TC-188-13; DF-190-01: "never two Draft PRs" holds only once S-194-AC9 lands (RT-07 `TestOwnedWhileAPrIsOpen` strict xfail until then)      | L1, L2, L2.5, Live         | PENDING  | PENDING |
| AC-21 (board linked) **(v2.0, new)** | S-199-AC1, AC2; S-198-AC1, AC2; S-182-AC7 | TC-199-06, TC-199-07, SC-IC-11, SC-LIVE-02, SC-LIVE-03, SC-LIVE-14 | TC-199-01, TC-199-02, TC-199-18, RT-16, CT-30, CT-31                       | L1, L2, IC, Live           | PENDING  | PENDING |
| AC-22 (board none or ambiguous) **(v2.0, new)** | S-199-AC3              | TC-199-08 (no board: run completes, detection only), TC-199-10 (override) | TC-199-09 (ambiguous), TC-199-05, SC-LIVE-14 (no-board repo)               | L2, Live                   | PENDING  | PENDING |
| AC-23 (board best effort) **(v2.0, new)** | S-199-AC4; S-198-AC5; S-182-AC7 | TC-199-11 (outcome equals control), SC-LIVE-13          | TC-199-02, TC-199-12, TC-199-13, TC-199-19, SC-IC-14                                       | L1, L2, IC, Live           | PENDING  | PENDING |
| AC-24 (crash then retry) **(v2.0, new)** | S-185-AC2; S-188 (testing); S-198-AC4 | TC-188-10, TC-185-20 (terminal claim proceeds), SC-LIVE-12 | TC-185-20 (non-terminal claim refused), CT-34, RT-07 (6)                              | L1, L2, L2.5, Live         | PENDING  | PENDING |

**20 of 20 v2.0 PRD ACs** have at least one positive and one negative or edge test. The four removed ACs are kept as `n/a` rows.

## C. Story AC → tests (109 active story ACs, numbered as in stories v2.0; S-194-AC9 added in v2.4) **(v2.0)**

Rows marked *(deployed or manual evidence only)* are still covered. By the nature of the AC (infra, the spike, live runs, documents), their evidence comes from IC, Live or MR checks. §D.2 lists them so the reviewer can see which ACs rely on deployed or manual evidence; they are not gaps.

| Story AC | Issue | Criterion (short) | Test case IDs | Layers | Observed | Result |
| -------- | ----- | ----------------- | ------------- | ------ | -------- | ------ |
| S-180-AC1 | #362 | sibling layout | TC-180-01 | L1 | PENDING | PENDING |
| S-180-AC2 | #362 | copied modules carry a source and commit header | TC-180-02 | L1 | PENDING | PENDING |
| S-180-AC3 | #362 | `agentcore.json`: runtime, network, `maxLifetime`, env vars incl. `PROJECTS_TOKEN_SECRET_ID` and `BOARD_UPDATES_ENABLED`, no Bedrock **(v2.0)** | TC-180-03, TC-180-04, TC-180-05, TC-180-13, TC-180-14 | L1 | PENDING | PENDING |
| S-180-AC4 | #362 | ARM64 image with the toolchain and a pinned CLI | TC-180-06 | L2 | PENDING | PENDING |
| S-180-AC5 | #362 | user `fixer`; root wrapper, no `wrapper` user (D-110); directory ownership **(v2.3)** | TC-180-07, TC-180-08 | L2 | PENDING | PENDING |
| S-180-AC6 | #362 | managed settings: root-owned 0644, sandbox, registry-only network, deny rules | TC-180-09, TC-180-10, TC-180-11 | L1, L2 | PENDING | PENDING |
| S-180-AC7 | #362 | the entrypoint shell reports and exits cleanly; the step behaviour moved to TC-190-01/-02 (DF-190-10, **v2.4**) | TC-180-12 | L1 | PENDING | PENDING |
| S-181-AC1 | #363 | dedicated, spend-capped Anthropic key; the record holds the cap, never the key | TC-181-01, TC-181-02 | L1, Live | PENDING | PENDING |
| S-181-AC2 | #363 | deployed, ARN recorded *(deployed or manual evidence only)* | TC-181-03 | Live | PENDING | PENDING |
| S-181-AC3 | #363 | classic PAT, `project` scope only, stored; scope and expiry recorded, never the token **(v2.0, new)** *(deployed or manual evidence only)* | TC-181-12, TC-181-13 | Live | PENDING | PENDING |
| S-181-AC4 | #363 | role reads exactly four secrets, no `bedrock:*` **(v2.0)** *(deployed or manual evidence only)* | TC-181-04, TC-181-05 | Live | PENDING | PENDING |
| S-181-AC5 | #363 | panel invoke policy has the ARN and `runtime-endpoint/DEFAULT`; the stub invoke works *(deployed or manual evidence only)* | TC-181-06, TC-181-07 | Live | PENDING | PENDING |
| S-181-AC6 | #363 | App has Issues read and write on every installation *(deployed or manual evidence only)* | TC-181-08, TC-181-09 | Live, MR | PENDING | PENDING |
| S-181-AC7 | #363 | backup and revert steps per item (five items) **(v2.0)** *(deployed or manual evidence only)* | TC-181-10 | MR | PENDING | PENDING |
| S-182-AC1 | #364 | `sandbox.py`: `fixer`, minimal env (no PAT), sandbox network; SIGTERM, then SIGKILL after 15 s **(v2.0)** | TC-182-01, TC-182-02, TC-182-03, TC-182-04, TC-182-05 | L1, L2 | PENDING | PENDING |
| S-182-AC2 | #364 | probe mode needs the top-level `__probe` plus `ALLOW_PROBE=1` | TC-182-06, TC-182-07, TC-182-13, TC-182-14, CT-04, CT-22 | L1, L2.5 | PENDING | PENDING |
| S-182-AC3 | #364 | link-local and non-registry hosts unreachable; registries reachable *(deployed or manual evidence only)* | SC-IC-01, SC-IC-02 | IC | PENDING | PENDING |
| S-182-AC4 | #364 | `/proc/<wrapper>/{environ,mem}` unreadable, no `AWS_*` var *(deployed or manual evidence only)* | SC-IC-03, SC-IC-05 | IC | PENDING | PENDING |
| S-182-AC5 | #364 | a managed deny beats a repo allow; `WebFetch` denied *(deployed or manual evidence only)* | SC-IC-04 | IC | PENDING | PENDING |
| S-182-AC6 | #364 | spike report with the CLI version and key names; `managed-settings.json` updated *(deployed or manual evidence only)* | TC-182-11 | MR | PENDING | PENDING |
| S-182-AC7 | #364 | board probe on #5: detection, idempotent add, statuses read back, PAT absent from `fixer`, disabled without the PAT; cleanup **(v2.0, new)** | TC-182-15, TC-182-16, SC-IC-11, SC-IC-12, SC-IC-13, SC-IC-14 | L1, IC, MR | PENDING | PENDING |
| S-182-AC8 | #364 | exit rule (sandbox): any FAIL keeps Wave B blocked *(was AC7)* *(deployed or manual evidence only)* | TC-182-12 | MR | PENDING | PENDING |
| S-184-AC1 | #366 | upsert migration with the `on conflict` shape, mirrored in `seed.sql` | TC-184-01, TC-184-02 | L2.5 | PENDING | PENDING |
| S-184-AC2 | #366 | `requires_repository`, 3600/120/300, `runtime_arn` | TC-184-03, TC-184-04 | L1, L2.5 | PENDING | PENDING |
| S-184-AC3 | #366 | `params_schema` = spec §5.2 v2.0 (`required: ["issue_number"]`); `default_params` = budgets, caps, status names **(v2.0)** | TC-184-07, TC-184-15, TC-184-17, CT-03, CT-04, CT-06, CT-19 | L1, L2.5, MR | PENDING | PENDING |
| S-184-AC4 | #366 | `params.py`: typed, seed-equal defaults, schema bounds; a typed error naming the key → `invalid_params` **(v2.0)** | TC-184-08, TC-184-10, TC-184-11, TC-184-12, TC-184-13, TC-184-14, CT-01, CT-02, CT-21, RT-06 | L1 | PENDING | PENDING |
| S-184-AC5 | #366 | the runbook `from_payload` mapping resolves through `resolveRoute` into valid params **(v2.0, new)** | CT-23, CT-24, RT-14 (TC-184-16 points to CT-23, CT-24) | L1, L2.5 | PENDING | PENDING |
| S-185-AC1 | #367 | preflight: no `issues: write` → `GITHUB_PERMISSION_MISSING`; a params error → `invalid_params` **(v2.0)** | TC-185-01, TC-185-02, TC-185-12, TC-185-13, CT-02, CT-07 | L1, L2 | PENDING | PENDING |
| S-185-AC2 | #367 | refusal checks in order: `pull_request`, `closed`, `linked_pr`, `active_run`; `active_run` = an open claim for another run, by the single definition (DF-33: no trusted `pr`/`disposition`/`refusal` for R, R not terminal; no `v_runs` row = finished with a warning; unknown status = `SUPABASE_UNAVAILABLE`) **(v2.1)** | TC-185-16, TC-185-18, TC-185-19, TC-185-20, CT-12, CT-33, CT-34, RT-02 | L1, L2, L2.5 | PENDING | PENDING |
| S-185-AC3 | #367 | exactly one marked reply, fixed text, run link, no model text, no reaction **(v2.0, new)** | TC-185-09, TC-185-17, RT-15 | L1, L2 | PENDING | PENDING |
| S-185-AC4 | #367 | `succeeded`/`not_applicable` with `result.reason`; no claim, no board call **(v2.0, new)** | TC-185-09, TC-185-10, TC-185-23 | L1, L2 | PENDING | PENDING |
| S-185-AC5 | #367 | reply failure logged, outcome unchanged; `GITHUB_UNAVAILABLE`; `SUPABASE_UNAVAILABLE`; client semantics: read/write retry split, 3 attempts in total, 120 s budget, no redirects, page cap is a fault, GraphQL error classes (DF-185-01/02/05/06) **(v2.1)** | TC-185-11, TC-185-14, TC-185-21, TC-185-22, CT-13, CT-33, CT-34 | L1, L2 | PENDING | PENDING |
| S-186-AC1 | #368 | build and parse the four marker kinds; leading marker block **(v2.0)** | TC-186-01, TC-186-02, TC-186-03, TC-186-06, TC-186-07, TC-186-17, CT-08, CT-32, RT-02 | L1 | PENDING | PENDING |
| S-186-AC2 | #368 | trusted only if the App id matches and `user.type == "Bot"` | TC-186-04, TC-186-05, TC-186-07, RT-02 | L1 | PENDING | PENDING |
| S-186-AC3 | #368 | reactions `eyes`/`rocket`/`confused`; none without `trigger_comment_id` **(v2.0, new)** | TC-186-15 | L2 | PENDING | PENDING |
| S-186-AC4 | #368 | `neutralize.py` (D-65) **(v2.0, new)** | TC-186-16, RT-12, TC-194-05 | L1, L2 | PENDING | PENDING |
| S-186-AC5 | #368 | diagnosis comment + 😕, neutralized, no labels or assignee, idempotent **(v2.0)** | TC-186-08, TC-186-09, TC-186-10, TC-186-11, TC-186-12, TC-186-16 | L2 | PENDING | PENDING |
| S-186-AC6 | #368 | backstop disposes within 10 s before `fail()`, only after confirmed ownership **(v2.0)** | TC-186-13, TC-186-14 | L2 | PENDING | PENDING |
| S-188-AC1 | #370 | claim comment, then 👀; no label or assignee change **(v2.0)** | TC-188-02, TC-188-03, TC-188-15 | L2 | PENDING | PENDING |
| S-188-AC2 | #370 | post-check: lose to a lower-id open claim of another run, read through the single definition's two shared halves, `markers.open_claims()` (markers) and `refusal.active_claim_runs()` (`v_runs` status) (DF-33, DF-188-01: no trusted `pr`/`disposition`/`refusal` for R, R not terminal); delete own comment (a 404 is already gone; any other `DELETE` fault → `failed` with its D-67 code, DF-38 race-loss part); `active_run`; no board call **(v2.2)** | TC-188-04, TC-188-05, TC-188-06, TC-188-07, TC-188-10, TC-188-16, TC-186-06, TC-185-14, RT-02 | L1, L2 | PENDING | PENDING |
| S-188-AC3 | #370 | ownership gate; a post-check failure keeps the comment, applies nothing, `failed` **(v2.0)** | TC-188-12, TC-188-14 | L2 | PENDING | PENDING |
| S-188-AC4 | #370 | PRD AC-3 end state **(v2.0)** | TC-188-08, TC-188-09 | L2 | PENDING | PENDING |
| S-188-AC5 | #370 | PRD AC-20: one owner, one withdrawal **(v2.0, new)**; RT-07 moved to S-190 (DF-188-05, **v2.2**); the late-claim-after-PR shape is S-194-AC9 (DF-190-01, **v2.4**) | TC-188-07, TC-188-13 | L1, L2 | PENDING | PENDING |
| S-189-AC1 | #371 | wrapper clone `/work/wrapper/repo` (root-owned, 0700, D-110), `fsckObjects`, base SHA, D-83 `info/exclude` **(v2.3)** | TC-189-01, TC-189-02, TC-189-03, TC-189-19, TC-189-23 | L2 | PENDING | PENDING |
| S-189-AC2 | #371 | `safe_git.py` hardening; no wrapper git on a `fixer`-writable `.git` | TC-189-16, TC-189-17, TC-189-20 | L1, L2 | PENDING | PENDING |
| S-189-AC3 | #371 | base tree materialized by a raw-blob tar (not `git archive`, DF-189-01) piped to `tar -x` as `fixer`; `.git` components refused, tar caps; link-free work-tree walk (hardlinks, FIFOs, sockets, devices) **(v2.3)** | TC-189-02, TC-189-17, TC-189-18, TC-189-22, TC-189-23 | L2 | PENDING | PENDING |
| S-189-AC4 | #371 | stack detection: pnpm, npm or a Makefile (GNU make's order); yarn/bun unsupported; `include` not followed **(v2.3)** | TC-189-04, TC-189-05 | L1 | PENDING | PENDING |
| S-189-AC5 | #371 | repo gate; a missing item → refusal `repo_gate` (marked reply, fixed phrase per item: `lockfile`, `supported package manager (pnpm or npm)`, `package.json or Makefile`, `install`, …) before the claim **(v2.3)** | TC-189-06, TC-189-07, TC-189-08, TC-189-09, TC-189-21 | L1, L2 | PENDING | PENDING |
| S-189-AC6 | #371 | OQ-1 resolved as D-112: a Python repo needs `make install`, else refusal `repo_gate` "missing install target" **(v2.2)** | TC-189-10, TC-189-07, TC-189-14 | MR, L2 | PENDING | PENDING |
| S-189-AC7 | #371 | `gates.py`: four gates + `audit` through the sandbox, scrubbed tail | TC-189-11, TC-189-12 | L2 | PENDING | PENDING |
| S-189-AC8 | #371 | base results recorded, never blocking | TC-189-13 | L2 | PENDING | PENDING |
| S-189-AC9 | #371 | frozen install per manager; base restore | TC-189-14, TC-189-15 | L2 | PENDING | PENDING |
| S-190-AC1 | #372 | steps `preflight` → `refuse` → `checkout` → `claim` (→ `fix`) with `run_events` **(v2.0)** | TC-190-01, TC-190-02, TC-190-13 | L2 | PENDING | PENDING |
| S-190-AC2 | #372 | outcome mapping §8.9 v2.0 (every refusal code, lost race, D-67 codes); summary carries the reason **(v2.0)** | TC-190-03, TC-190-04, TC-190-05, TC-190-11, TC-190-12 | L1, L2 | PENDING | PENDING |
| S-190-AC3 | #372 | heartbeat and backstop; dispose only after confirmed ownership **(v2.0)**; RT-07 moved here from S-188 (DF-188-05, **v2.2**) | TC-190-06, TC-190-07, TC-190-08, RT-07 | L2 | PENDING | PENDING |
| S-190-AC4 | #372 | metrics: `issue_number` and step timings | TC-190-09 | L2 | PENDING | PENDING |
| S-190-AC5 | #372 | deployed manual invoke claims (no reaction) and disposes **(v2.0)** *(deployed or manual evidence only)* | SC-LIVE-01 | Live | PENDING | PENDING |
| S-191-AC1 | #373 | argv through `sandbox.py` as `fixer`, minimal env, wall clock; prompt on stdin | TC-191-01, TC-191-02, TC-191-14 | L2 | PENDING | PENDING |
| S-191-AC2 | #373 | the prompt: `developer.md`, quoted issue, caps, forbidden paths, test rule, `report.json` | TC-191-03, TC-191-04, RT-04 | L1 | PENDING | PENDING |
| S-191-AC3 | #373 | CLI JSON → metrics | CT-14, CT-16, SC-IC-06 | L1, IC | PENDING | PENDING |
| S-191-AC4 | #373 | turn, time or budget ceiling → disposition and `needs_review` | TC-191-06, TC-191-07, TC-191-08 | L2 | PENDING | PENDING |
| S-191-AC5 | #373 | `gave_up` → disposition; crash or garbage → `CLI_CRASHED` after the disposition | TC-191-09, TC-191-10, TC-191-17 | L2 | PENDING | PENDING |
| S-191-AC6 | #373 | invalid `report.json` → `needs_review` "invalid report"; other subtypes → `CLI_CRASHED` | TC-191-16, TC-191-17, CT-15, CT-17, CT-18 | L1, L2 | PENDING | PENDING |
| S-191-AC7 | #373 | run-budget deadline tracking | TC-191-11 | L1 | PENDING | PENDING |
| S-191-AC8 | #373 | every `fixer` killed before the wrapper reads; `report.json` `O_NOFOLLOW`, ≤ 1 MB | TC-191-13, TC-191-18 | L2 | PENDING | PENDING |
| S-192-AC1 | #374 | capture with `--git-dir/--work-tree add -A`; D-52 over `--numstat -z` | TC-192-03, TC-192-14, TC-192-15, TC-192-17, TC-192-18, TC-189-20, RT-08 | L2 | PENDING | PENDING |
| S-192-AC2 | #374 | forbidden path, caps or no test → disposition | TC-192-04, TC-192-06, TC-192-07, RT-01 | L1, L2 | PENDING | PENDING |
| S-192-AC3 | #374 | symlink or gitlink → disposition; case-insensitive forbidden matching (D-83, D-84) **(v2.0, new AC)** | TC-192-16, TC-192-18, TC-192-20, RT-01, RT-08 | L1, L2 | PENDING | PENDING |
| S-192-AC4 | #374 | the D-69 list additions *(was AC3)* | TC-192-01, TC-192-02, TC-192-19, RT-01 | L1 | PENDING | PENDING |
| S-192-AC5 | #374 | rationale coverage *(was AC4)* | TC-192-08 | L2 | PENDING | PENDING |
| S-192-AC6 | #374 | secret scan (incl. the PAT) *(was AC5)* | TC-192-09, TC-192-10 | L2 | PENDING | PENDING |
| S-192-AC7 | #374 | four final gates block; `audit` recorded only *(was AC6)* | TC-192-11, TC-192-12, TC-192-13 | L2 | PENDING | PENDING |
| S-192-AC8 | #374 | AC-7 boundaries *(was AC7)* | TC-192-05 | L2 | PENDING | PENDING |
| S-193-AC1 | #375 | test files = the D-52 test class | TC-193-01 | L1 | PENDING | PENDING |
| S-193-AC2 | #375 | parent-chain `lstat`; a symlink component → disposition (D-83) **(v2.0, new AC)** | TC-193-16 | L2 | PENDING | PENDING |
| S-193-AC3 | #375 | final tree in the wrapper clone; red tree applied as `fixer`; no `git checkout` *(was AC2)* | TC-193-02 | L2 | PENDING | PENDING |
| S-193-AC4 | #375 | runner per stack; missing pytest → disposition *(was AC3)* | TC-193-03, TC-193-04 | L2 | PENDING | PENDING |
| S-193-AC5 | #375 | red rule incl. the D-64 collection error *(was AC4)* | TC-193-05, TC-193-06, TC-193-07, TC-193-13, TC-193-17, RT-05 | L1, L2 | PENDING | PENDING |
| S-193-AC6 | #375 | final tree restored (raw-blob tar), all pass, planted hooks never run in the root wrapper's git (D-110) *(was AC5)* **(v2.3)** | TC-193-08, TC-193-09, TC-193-10, TC-193-14, TC-193-15 | L2 | PENDING | PENDING |
| S-193-AC7 | #375 | outputs kept; AC-8 (passing on base → disposition) *(was AC6)* | TC-193-11 | L2 | PENDING | PENDING |
| S-194-AC1 | #376 | branch `issue/<N>-<slug>`, Conventional Commit | TC-194-01, TC-194-02, TC-194-17, RT-09 | L1 | PENDING | PENDING |
| S-194-AC2 | #376 | push from the wrapper clone, host-scoped helper, `gh pr create --draft --body-file` | TC-194-03, TC-194-13, TC-194-18 | L2 | PENDING | PENDING |
| S-194-AC3 | #376 | model text neutralized; only the wrapper writes `Fixes #N` | TC-194-05, TC-194-17, RT-12 | L1 | PENDING | PENDING |
| S-194-AC4 | #376 | body sections | TC-194-04, TC-194-06 | L1 | PENDING | PENDING |
| S-194-AC5 | #376 | artifact recorded, `fixed` | TC-194-07 | L2 | PENDING | PENDING |
| S-194-AC6 | #376 | 🚀 + `pr`-marker comment; labels and assignees unchanged; stays Draft **(v2.0)** | TC-194-08, TC-194-09, TC-194-19, TC-194-20 | L2 | PENDING | PENDING |
| S-194-AC7 | #376 | `FIX_LOOP_ENABLED=1`, deployed, only after AC9 passes and the fix runner is wired (DF-190-01, DF-190-04, **v2.4**) | TC-194-10 | L1 | PENDING | PENDING |
| S-194-AC8 | #376 | push or PR failure → disposition, then `PR_CREATE_FAILED` | TC-194-11 | L2 | PENDING | PENDING |
| S-194-AC9 | #376 | never two Draft PRs: post-check `linked_pr` re-check (withdraw, `not_applicable`/`linked_pr`; fault fails closed; ownership only when both reads pass) and pre-push re-check (`needs_review`, no second PR) (DF-190-01) **(v2.4, new)** | TC-194-21, TC-194-22, RT-07 | L2 | PENDING | PENDING |
| S-195-AC1 | #377 | a deployed run processes the injection fixture issue *(deployed or manual evidence only)* | SC-IC-07 | IC | PENDING | PENDING |
| S-195-AC2 | #377 | repo canaries fail every credential, `/proc` and HTTP attempt *(deployed or manual evidence only)* | SC-IC-07 | IC | PENDING | PENDING |
| S-195-AC3 | #377 | no foreign push; no secret (incl. the PAT) in the PR, comments or events **(v2.0)** *(deployed or manual evidence only)* | SC-IC-07, SC-IC-08 | IC | PENDING | PENDING |
| S-195-AC4 | #377 | ends `needs_review` or `fixed`, evidence attached *(deployed or manual evidence only)* | SC-IC-07, SC-IC-10 | IC | PENDING | PENDING |
| S-199-AC1 | new | look-up once after the refusal checks: override or `projectsV2`; `Status` options case-insensitive; PAT **(v2.0, new)** | TC-199-01, TC-199-02, TC-199-03, TC-199-04, TC-199-05, CT-30, RT-16 | L1, L2 | PENDING | PENDING |
| S-199-AC2 | new | one board: add (idempotent) + `In progress`; `In review`; `Ready` **(v2.0, new)** | TC-199-06, TC-199-07, TC-199-18, CT-31, SC-LIVE-14 | L1, L2, Live | PENDING | PENDING |
| S-199-AC3 | new | no board → no call after the look-up; several → no update + `run_event` **(v2.0, new)** | TC-199-08, TC-199-09, TC-199-10 | L2 | PENDING | PENDING |
| S-199-AC4 | new | missing PAT, unknown status, flag off or API error → logged, skipped, outcome unchanged **(v2.0, new)** | TC-199-02, TC-199-11, TC-199-12, TC-199-13, TC-199-19, TC-199-20, RT-16 | L1, L2 | PENDING | PENDING |
| S-199-AC5 | new | refusals and lost races never touch the board; `metrics.board` **(v2.0, new)** | TC-199-14, TC-199-15, TC-185-23, TC-188-14 | L2 | PENDING | PENDING |
| S-199-AC6 | new | PAT wrapper-only, scrubbed, never in a `fixer` env **(v2.0, new)** | TC-199-16, TC-199-17, TC-180-15, SC-IC-13 | L1, L2, IC | PENDING | PENDING |
| S-197-AC1 | #379 | `deploy.sh` prints the ARN; runbook in the same PR | TC-197-01, TC-197-02 | L1, MR | PENDING | PENDING |
| S-197-AC2 | #379 | runbook topics incl. the exact recommended rule, board linking, PAT rotation, no schedule **(v2.0)** | TC-197-03, TC-197-11, CT-27 | L1, MR | PENDING | PENDING |
| S-197-AC3 | #379 | one rule on the fixture repo; `/bug-fix` starts a run, an unrelated comment doesn't **(v2.0)** | SC-LIVE-08 (via TC-197-10), CT-25, CT-26, CT-28 (known red, DF-29), RT-14 | L1, L2.5, Live | PENDING | PENDING |
| S-197-AC4 | #379 | the rule's breaker: `not_applicable`/`needs_review` don't trip it, `failed` does (AC-12) **(v2.0)** | TC-197-05 (failed half known red, DF-30), TC-197-07, CT-29, SC-LIVE-06 (via TC-197-08) | L2.5, Live | PENDING | PENDING |
| S-198-AC1 | #380 | fixable → Draft PR, 🚀 + PR comment, card `In review`, `fixed` **(v2.0)** *(deployed or manual evidence only)* | SC-LIVE-02, SC-LIVE-14, SC-LIVE-15 | Live | PENDING | PENDING |
| S-198-AC2 | #380 | unfixable → 😕 + diagnosis, card `Ready`, issue open, `needs_review` **(v2.0)** *(deployed or manual evidence only)* | SC-LIVE-03, SC-LIVE-14 | Live | PENDING | PENDING |
| S-198-AC3 | #380 | refusals and concurrency (AC-20) **(v2.0, new)** *(deployed or manual evidence only)* | SC-LIVE-09, SC-LIVE-10 | Live | PENDING | PENDING |
| S-198-AC4 | #380 | manual (AC-19) and crash-then-retry (AC-24) **(v2.0, new)** *(deployed or manual evidence only)* | SC-LIVE-11, SC-LIVE-12 | Live | PENDING | PENDING |
| S-198-AC5 | #380 | board degraded (AC-23) **(v2.0, new)** *(deployed or manual evidence only)* | SC-LIVE-13 | Live | PENDING | PENDING |
| S-198-AC6 | #380 | metrics incl. the board (FR-27) **(v2.0)** *(deployed or manual evidence only)* | TC-198-05 | Live | PENDING | PENDING |

### C.2 Removed story ACs (history, not counted)

| Story ACs (stories v1.3) | Removed by | Retired tests |
| ------------------------ | ---------- | ------------- |
| S-183-AC1…AC6 (#365) | D-95 | TC-183-01…17, SC-E2E-01…05, RT-10 |
| S-185-AC2 (label lookup), AC3 (cross-field label rules), AC4 (assignee) | D-93 | TC-185-03…08, TC-185-15, CT-11, RT-03 |
| S-184-AC4/AC5 label parts (required label lists, cross-field rules) | D-93 | TC-184-09 (TC-184-10, TC-184-12, TC-184-13, TC-184-15 re-targeted) |
| S-187-AC1…AC6 (#369) | D-90 | TC-187-01…16, CT-09, RT-11, SC-LIVE-04 (linked-PR checks moved to TC-185-19) |
| S-188-AC1 (pre-check on labels) | D-93 | TC-188-01, TC-188-11 |
| S-196-AC1…AC5 (#378) | D-94 | TC-196-01…18, CT-10, CT-20, SC-LIVE-07 |
| S-197-AC3 (fixture schedule), AC4 G5 part | D-96 | TC-197-04, TC-197-06 |
| S-198-AC3 (custom labels), AC4 (misconfiguration) | D-93 | TC-198-03, TC-198-04, SC-LIVE-05 |

## D. Gaps **(v2.0)**

### D.1 Coverage gaps (ACs or FRs without a test)

- **Story ACs without a test:** none. All 109 of 109 active story ACs (stories v2.6) map to at least one active test.
- **PRD ACs without a positive or negative test:** none. All 20 of 20 v2.0 PRD ACs have both.
- **FRs without a test:** none. FR-1, FR-3, FR-5…FR-23 and FR-25…FR-34 all map to active tests.
- **FRs, ACs and harness items without an owning story AC, or deliverable only with a finding resolved.** Each is closed in the test plan by a test marked **(new)**, but no story AC asserts it. `product-engineer` should add an AC or accept the test as the owner.

| Gap | FR / AC                                          | What is missing                                                                                                   | Closed by (test)                         | Suggested owner story | Status (v2.0) |
| --- | ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------- | --------------------- | ------------- |
| G-1 | FR-11                                            | No story AC asserts that the CLI loads the target repo's own `.claude/` and `developer` definition.              | TC-191-15, SC-IC-09                      | S-191                 | Open |
| G-2 | FR-25                                            | No Wave B story AC asserts the `run_steps` for `fix`, `validate`, `red_to_green`, `open_pr`, or the board-update step v2.0 adds. | TC-194-14                                | S-194 / S-199         | Open |
| G-3 | FR-27                                            | `code_files`, `code_lines`, `gates_base`, `gates_final` and `red_green` are asserted only live (S-198-AC6). `board` is now owned by S-199-AC5. | TC-194-15                                | S-192 / S-193 / S-194 | Open (narrowed) |
| G-4 | PRD AC-11                                        | No story AC asserts the **cross-path** disposition end state (😕, diagnosis, issue open, labels and assignees untouched, `Ready`, outcome, summary) for every FR-22 path. | TC-194-16                                | S-194                 | Open |
| G-5 | RT-01, RT-02, RT-04…RT-09, RT-12, RT-13, RT-15, RT-16 | No property-testing library is in the agent's dev dependencies, and task list v2.0 doesn't add one.          | Add `hypothesis` in S-180 task 1.3       | S-180                 | Open |
| G-6 | S-196 L2.5                                       | —                                                                                                                 | —                                        | —                     | Closed (v1.1, D-77); story removed in v2.0 |
| G-7 | PRD AC-12 (failed half), FR-26 | No story can deliver "repeated `failed` runs trip the rule's breaker" against the merged trigger, which counts only start failures. | TC-197-05, CT-29, SC-LIVE-06 (known red) | S-197 (needs DF-30 decided) | **New**, open |
| G-8 | PRD AC-1 (negative half), FR-29 | S-197-AC3 covers "an unrelated comment starts no run" but not a **disallowed author**, an edited comment, or a PR comment. | CT-25, CT-26, RT-14, SC-LIVE-08 steps 3–6 | S-197 | **New**, open |
| G-9 | FR-28 (routing half) | S-184-AC5 owns `resolveRoute`; no story AC owns the routing conditions (`webhook-routing.ts`) or the guardrails the trigger applies. | CT-25…CT-28, TC-197-11 | S-197 | **New**, open |
| G-10 | PRD AC-16, AC-20 (live sequencing) | On one fixture repo, AC-16's second scenario and AC-20's second comment are skipped by the trigger's G5 and G1 (DF-29). | SC-LIVE-03 ordering, SC-LIVE-10, SC-LIVE-15 | S-198 (needs DF-29 decided) | **New**, open |
| G-11 | S-199 | The story has no GitHub issue number yet, so this matrix shows "new" in its Issue column. | — | publication (`github-ops`) | **New**, open |

### D.2 Story ACs relying on deployed or manual evidence only (24)

| Kind                     | Story ACs                                                                                                    |
| ------------------------ | ------------------------------------------------------------------------------------------------------------ |
| Infra (Live / MR)        | S-181-AC2, S-181-AC3, S-181-AC4, S-181-AC5, S-181-AC6, S-181-AC7 (S-181-AC1 also has the automated grep TC-181-02) |
| Spike (IC / MR)          | S-182-AC3, S-182-AC4, S-182-AC5, S-182-AC6, S-182-AC8 (S-182-AC7 also has the L1 cleanup test TC-182-16)      |
| Confinement (IC)         | S-195-AC1, S-195-AC2, S-195-AC3, S-195-AC4                                                                    |
| Live runs                | S-190-AC5, S-198-AC1…AC6                                                                                      |
| Documents (MR)           | S-189-AC6                                                                                                     |

S-197-AC2 and S-197-AC3 are no longer evidence-only: TC-197-11, CT-25…CT-27 and RT-14 automate them.

### D.3 Rows pinned by an open finding, or known red

| Test(s)                                  | Finding | State against the current design or the merged trigger                    |
| ---------------------------------------- | ------- | ------------------------------------------------------------------------- |
| CT-28, SC-LIVE-10, SC-LIVE-15            | DF-29 (**Critical**) | **Expected to fail**: G1 and G5 skip `/bug-fix` deliveries per repo, silently |
| TC-197-05 (failed half), CT-29, SC-LIVE-06 (step 3) | DF-30 (Major) | **Expected to fail**: the rule's breaker never sees run outcomes |
| CT-26, RT-14, TC-197-03                  | DF-31   | Pinned to the merged trigger: the 1,024-character limit and `prefix` collisions |
| TC-188-13, RT-07 (7)                     | DF-32   | Pinned: the race loser's 👀 stays and it posts no reply; RT-07 (7) expected counterexample |
| RT-07 `TestOwnedWhileAPrIsOpen` (2), TC-194-21, TC-194-22 | DF-190-01 (Major, **decided v2.4**, @llipe 2026-10-24) | Strict xfail until S-194-AC9 adds the `linked_pr` re-checks, then a pass. Gates `FIX_LOOP_ENABLED=1` |
| RT-07 (7) | DF-190-02 (**open**) | Pinned by design: a post-check fault leaves 👀 unanswered (a third exemption to (7)); reconciled with DF-32 |
| TC-185-20, TC-186-06, TC-188-16, RT-02 (3), (6) | DF-33 (**resolved v2.1**, @llipe 2026-10-24) | Assert the single open-claim definition: `pr`, `disposition` or `refusal` for R closes R's claim; a refusal never opens one; R must be non-terminal; no `v_runs` row = finished; unknown status = `SUPABASE_UNAVAILABLE`. The new TC-186-06 cases and TC-188-16 land with S-188 (#370), which moves the rule into `markers.open_claims()`. **v2.2 (DF-188-01):** the rule has two shared halves, `markers.open_claims()` (markers) and `refusal.active_claim_runs()` (`v_runs` status); TC-186-06's status cases are tested in `test_race.py` |
| TC-185-13, TC-185-18, CT-02              | DF-34   | Pinned: `invalid_params` and 404 with no target issue → no write          |
| TC-189-21, TC-199-14, TC-188-14          | DF-35   | Pinned: board look-up placement (recommended: after the repo gate)        |
| TC-180-14, TC-199-11, SC-IC-14           | DF-36   | Pinned: a missing or unreadable PAT disables the board, never fails the run |
| TC-185-14, TC-186-15, TC-194-19          | DF-38   | Pinned: which GitHub writes are best effort. **Race-loss part resolved v2.2** (@llipe 2026-10-24): a 404 on the loser's `DELETE` is already gone; any other fault → `failed` with its D-67 code, no disposition, no board call (TC-185-14). Still open: 🚀/`pr` comment (S-194, TC-194-19) and the diagnosis comment (S-186) |

### D.4 Drift

- **v1.0 findings:** DF-01…DF-19, resolved by D-62…D-78 (test plan §10.1). Several now concern removed features; their rows are kept as history.
- **v1.1 findings:** DF-20…DF-28, resolved by D-79…D-86 (test plan §10.3). DF-20 and DF-21 are superseded by D-94; the others are in force.
- **S-185 audit (v2.1):** DF-185-01…09 (all Minor), routed in test plan §10.5. DF-33 is resolved by the same write-back. CT-34's real-database L2.5 read is a residual (DF-185-08).
- **S-188 audit (v2.2):** DF-188-01…07 (all Minor), routed in test plan §10.6. DF-188-01, -02 and -05 land in spec v2.5 and test plan v2.3; DF-188-03 decides DF-38's race-loss part; DF-188-04 is accepted as is; DF-188-06 and -07 are planner work. D-112 resolves OQ-1 (S-189-AC6).
- **S-189 audit (v2.3):** DF-189-01…09 (all Minor), routed in test plan §10.7. DF-189-01 and -07 land in spec v2.6, stories v2.5 and test plan v2.4 (D-62 amendment); DF-189-02, -03 and -06 are accepted; DF-189-04, -05, -08 and -09 were fixed in #458 and recorded in the same documents (D-112 amendment). The fix-round hardening adds TC-189-22 and TC-189-23.
- **S-190 audit (v2.4):** DF-190-01…12 (one Major, the rest Minor), routed in test plan §10.8. DF-190-01 (Major) is decided: the `linked_pr` re-checks in S-194-AC9 (spec v2.7 §8.6, D-54 amendment), gating `FIX_LOOP_ENABLED=1`. DF-190-04, -05, -06, -10 and the stream rule land in spec v2.7 §8.9 and §13, stories v2.6 and test plan v2.5. DF-190-02 is **open**. DF-190-03 is roadmap work for the planner; DF-190-07 and -11 are accepted; DF-190-08 goes to technical-writer and DF-190-09 to the runbook after 11.7; DF-190-12 was fixed in the S-190 fix round.
- **New in v2.0:** ten advisory findings, **DF-29…DF-38**, in test plan §10.4. Highest impact: **Critical** (DF-29, the trigger's G1/G5 guardrails). Next is **Major** (DF-30, the breaker never sees run outcomes). DF-37 is wording only. All are non-blocking and route to `product-engineer`'s `activity-drift-reconciliation`.

## E. Audit-Mode fill-in protocol

When `verifier` runs Audit Mode after implementation, each row's **Observed** cell gets its evidence: the test file and case, the run result, and for IC, Live and MR rows the evidence document or link. **Result** becomes `Pass`, `Fail` or `Drift`. A drift result carries an impact class (Critical, Major or Minor) and an intent class (Intended, Unintended or Undetermined), and routes to `product-engineer`'s `activity-drift-reconciliation`. A row whose `(new)` test was not written is reported as `Fail` with "test not implemented", not as `Pass`. Rows pinned by a DF item are re-checked against the decision recorded for that DF. A known-red row (§D.3) that still fails because its finding hasn't been reconciled is reported as `Drift` with that DF's classification, not as `Fail`. A **retired (v2.0)** test is never reported; if it was implemented anyway, report it as `Drift` (Minor, Unintended: scope from a removed story).
