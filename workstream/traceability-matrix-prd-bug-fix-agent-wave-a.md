# Traceability Matrix — Bug Fix Agent, Wave A (verifier, Design Mode)

> Companion to [`test-plan-prd-bug-fix-agent-wave-a.md`](test-plan-prd-bug-fix-agent-wave-a.md). Scope: S-180–S-189
> (#326–#335). Maps **PRD FR/AC → story AC → test case IDs → task-list sub-task**, with every story AC
> carrying at least one positive and one negative or edge test. The `Observed` and `Result` columns follow
> the `AC-ID → Test-Case-ID → Observed-Result → Pass/Fail/Drift` structure and stay **PENDING** until Audit Mode.
>
> Status codes (from the plan): **R** runnable now · **R-DB** local Supabase · **R-CI** Docker CI runner ·
> **R(F-n)** runnable once finding F-n fixes the expected value · **OP** blocked on S-188 operator
> prerequisites · **CAN** blocked on the S-189 canary.
> Task references are sub-task numbers in [`tasks-prd-bug-fix-agent-plan.md`](tasks-prd-bug-fix-agent-plan.md).

## Changelog

| Version | Date       | Summary                                      | Author   |
| ------- | ---------- | -------------------------------------------- | -------- |
| 1.0     | 2026-10-19 | Initial Wave A matrix from test plan v1.0.   | verifier |

---

## 1. Story AC → tests → tasks (57 rows)

| PRD FR / AC (spec)                  | Story AC  | Positive test(s)                                   | Negative / edge test(s)                                                                 | Task sub-task(s)        | Status            | Observed | Result  |
| ----------------------------------- | --------- | -------------------------------------------------- | --------------------------------------------------------------------------------------- | ----------------------- | ----------------- | -------- | ------- |
| FR-1, FR-11, FR-32 (§4.2, §9.2, §15.1) | S180-AC1 | TC-180-01, TC-180-03                               | TC-180-02, SN-08                                                                        | 1.4, 1.9                | R                 | PENDING  | PENDING |
| AC-18 (startup), FR-31 (§11.3)      | S180-AC2  | TC-180-04, CT-18, RT-07                            | TC-180-05, TC-180-06, TC-187-08                                                         | 1.1, 1.5, 1.10, 1.13    | R                 | PENDING  | PENDING |
| FR-31, FR-12, AC-18 (step primitive) (§11.2) | S180-AC3 | TC-180-07, RT-05                         | TC-180-08, TC-180-09, EC-22, RT-06                                                      | 1.2, 1.5, 1.11, 1.13    | R                 | PENDING  | PENDING |
| FR-25 (reporter contract)           | S180-AC4  | TC-180-10                                          | TC-180-11                                                                               | 1.3, 1.6, 1.12          | R                 | PENDING  | PENDING |
| spec §14 (CI)                       | S180-AC5  | TC-180-12                                          | TC-180-13                                                                               | 1.7, 1.12               | R                 | PENDING  | PENDING |
| spec §14 (`TESTING.md`)             | S180-AC6  | TC-180-14                                          | TC-180-15                                                                               | 1.8, 1.12               | R                 | PENDING  | PENDING |
| FR-11 (§9.1)                        | S181-AC1  | TC-181-03, TC-181-07                               | TC-181-04, SN-17                                                                        | 2.3, 2.6, 2.10          | R / R-CI          | PENDING  | PENDING |
| FR-9, FR-11, AC-5 (deny), AC-19 (config) (§12.3) | S181-AC2 | TC-181-01                             | TC-181-02, SN-16, SN-22                                                                 | 2.1, 2.4, 2.7           | R (SN-22 CAN)     | PENDING  | PENDING |
| FR-11, AC-19 (§12.2)                | S181-AC3  | TC-181-05                                          | TC-181-06, SN-16                                                                        | 2.3, 2.8                | R-CI              | PENDING  | PENDING |
| FR-11 (§14 image smoke)             | S181-AC4  | TC-181-07                                          | TC-181-08, EC-27                                                                        | 2.2, 2.9                | R-CI              | PENDING  | PENDING |
| FR-49a (§9.1)                       | S181-AC5  | TC-181-09                                          | TC-181-10                                                                               | 2.5, 2.9                | R                 | PENDING  | PENDING |
| FR-1, PRD §9 `agents` row (§5.1)    | S182-AC1  | TC-182-01, CT-16                                   | TC-182-02, EC-12                                                                        | 3.3, 3.4, 3.6, 3.7      | R-DB              | PENDING  | PENDING |
| FR-1, FR-12 (§5.1)                  | S182-AC2  | TC-182-03, TC-182-12, CT-17                        | TC-182-04, CT-19                                                                        | 3.4, 3.7, 3.8           | R; CT-19 R(F-1)   | PENDING  | PENDING |
| FR-1 (§6.1, §13)                    | S182-AC3  | TC-182-05, CT-01, CT-03                            | TC-182-06, TC-182-07, CT-02, CT-04, CT-05, EC-01, EC-28, RT-09                          | 3.1, 3.5, 3.7           | R; TC-182-07/CT-05/EC-28 R(F-2) | PENDING | PENDING |
| FR-1, FR-7 (D-35)                   | S182-AC4  | TC-182-08                                          | TC-182-09, EC-02, LV-04                                                                 | 3.2, 3.5, 3.7           | R; EC-02 R(F-18)  | PENDING  | PENDING |
| FR-12, FR-31 (§11.1)                | S182-AC5  | TC-182-10, CT-18                                   | TC-182-11                                                                               | 3.3, 3.7                | R                 | PENDING  | PENDING |
| FR-2, FR-7, FR-22, FR-24 (§6.2)     | S183-AC1  | TC-183-01, CT-08, CT-09, CT-12                     | TC-183-02, TC-183-12 (S-183 business rule: mutations only via `claim.py`), CT-10, EC-10, EC-23 | 4.1, 4.2, 4.5, 4.7, 4.8 | R; CT-12 live half OP | PENDING | PENDING |
| spec §6.2 retries                   | S183-AC2  | TC-183-03                                          | TC-183-04, EC-18, EC-24                                                                 | 4.2, 4.5, 4.7           | R                 | PENDING  | PENDING |
| FR-28, AC-17 (§6.2, §13)            | S183-AC3  | TC-183-05, LV-02                                   | TC-183-06, TC-183-07, SN-14, LV-03                                                      | 4.3, 4.6, 4.7           | R; TC-183-07 R(F-3); LV OP | PENDING | PENDING |
| FR-7, FR-24 (D-36)                  | S183-AC4  | TC-183-08, CT-11                                   | TC-183-09                                                                               | 4.5, 4.7                | R (TC-183-09 code F-10) | PENDING | PENDING |
| FR-9, PRD §9 sensitivity (§12.2)    | S183-AC5  | TC-183-10, RT-10                                   | TC-183-11, SN-01                                                                        | 4.4, 4.7                | R                 | PENDING  | PENDING |
| FR-2, FR-4, AC-1 (§8.1)             | S184-AC1  | TC-184-01, RT-08                                   | TC-184-02, EC-21                                                                        | 5.1, 5.6, 5.8           | R; RT-08/EC-21 R(F-8) | PENDING | PENDING |
| FR-3, AC-2 (§8.1)                   | S184-AC2  | TC-184-03                                          | TC-184-04, SN-20, EC-01, EC-04                                                          | 5.3, 5.6, 5.7, 5.8      | R                 | PENDING  | PENDING |
| FR-2 (D-37)                         | S184-AC3  | TC-184-05, RT-01, RT-02                            | TC-184-06                                                                               | 5.2, 5.6                | R                 | PENDING  | PENDING |
| FR-5, FR-6, AC-4 (§8.2)             | S184-AC4  | TC-184-07                                          | TC-184-08                                                                               | 5.4, 5.5, 5.8           | R                 | PENDING  | PENDING |
| FR-6 (D-17)                         | S184-AC5  | TC-184-09                                          | TC-184-10                                                                               | 5.5, 5.8                | R (reason F-13)   | PENDING  | PENDING |
| FR-7, AC-3 (§8.3)                   | S185-AC1  | TC-185-01, TC-185-13                               | TC-185-02, EC-05, EC-08, EC-13, RT-11                                                   | 6.3, 6.5, 6.7, 6.8      | R; EC-05/EC-08 R(F-15); TC-185-13 OP | PENDING | PENDING |
| FR-7, FR-24, AC-13 (D-36)           | S185-AC2  | TC-185-03, RT-04                                   | TC-185-04, RT-03, EC-03, EC-19, EC-26, SN-11                                            | 6.1, 6.5, 6.7           | R                 | PENDING  | PENDING |
| FR-22, AC-11 (protocol) (§8.4)      | S185-AC3  | TC-185-05                                          | TC-185-06, EC-20, SN-15                                                                 | 6.2, 6.5, 6.7, 6.8      | R                 | PENDING  | PENDING |
| FR-22, FR-23 (§8.4)                 | S185-AC4  | TC-185-07                                          | TC-185-08, EC-07                                                                        | 6.2, 6.7                | R; TC-185-08 R(F-14) | PENDING | PENDING |
| FR-26 (§8.4, §13)                   | S185-AC5  | TC-185-09                                          | TC-185-10                                                                               | 6.4, 6.6, 6.7           | R                 | PENDING  | PENDING |
| FR-8                                | S185-AC6  | TC-185-11                                          | TC-185-12, SN-18                                                                        | 6.3, 6.7                | R; TC-185-12/SN-18 R(F-18) | PENDING | PENDING |
| FR-24, AC-13                        | S186-AC1  | TC-186-01                                          | TC-186-02, EC-23, SN-12                                                                 | 7.2, 7.4, 7.6           | R                 | PENDING  | PENDING |
| FR-24, AC-13 (§5.3)                 | S186-AC2  | TC-186-03, TC-186-11, CT-13, CT-15                 | TC-186-04, TC-186-12, CT-14, EC-06, EC-09, EC-17, EC-25, SN-13                           | 7.1, 7.3, 7.4, 7.6      | R / R-DB; EC-06 R(F-4) | PENDING | PENDING |
| FR-24, FR-22                        | S186-AC3  | TC-186-05                                          | TC-186-06, EC-14                                                                        | 7.2, 7.5                | R (reason F-6)    | PENDING  | PENDING |
| FR-24, AC-13 (D-16, D-36)           | S186-AC4  | TC-186-07                                          | TC-186-08, SN-10, SN-11, SN-12, RT-11                                                   | 7.1, 7.2, 7.5, 7.6      | R                 | PENDING  | PENDING |
| FR-24 (§4.1 step 3)                 | S186-AC5  | TC-186-09                                          | TC-186-10, EC-16                                                                        | 7.2, 7.5                | R (F-5 read client) | PENDING | PENDING |
| FR-25 (steps 1–5), FR-5 (§4.1, §6.1) | S187-AC1 | TC-187-01, CT-06, CT-20, LV-08                     | TC-187-02, CT-02, EC-15                                                                 | 8.2, 8.4, 8.7, 8.8      | R; LV-08 OP       | PENDING  | PENDING |
| spec §15.1 (flag)                   | S187-AC2  | TC-187-03, LV-08                                   | TC-187-04                                                                               | 8.2, 8.5, 8.7           | R; TC-187-04 R(F-9) | PENDING | PENDING |
| FR-26, AC-11/AC-12/AC-14 (outcome half) (§8.8) | S187-AC3 | TC-187-05, CT-07                        | TC-187-06                                                                               | 8.1, 8.7                | R                 | PENDING  | PENDING |
| FR-23, FR-25, AC-18 (D-30)          | S187-AC4  | TC-187-07                                          | TC-187-08, EC-11                                                                        | 8.3, 8.6, 8.7, 8.8      | R (code F-10)     | PENDING  | PENDING |
| FR-9, PRD §9 (§12.2)                | S187-AC5  | TC-187-09, RT-10                                   | TC-187-10, SN-01, SN-02, SN-03                                                          | 8.3, 8.6, 8.7           | R                 | PENDING  | PENDING |
| FR-26, FR-28 (§13)                  | S187-AC6  | TC-187-11                                          | TC-187-12                                                                               | 8.4, 8.7, 8.8           | R                 | PENDING  | PENDING |
| FR-28, AC-17, PRD §12/§16 (D-25)    | S188-AC1  | LV-01, LV-02                                       | LV-03                                                                                   | 9.3, 9.11, 9.12         | OP                | PENDING  | PENDING |
| FR-1, FR-7 (D-35)                   | S188-AC2  | LV-04                                              | TC-182-09                                                                               | 9.5, 9.12               | OP / R            | PENDING  | PENDING |
| FR-32, FR-11 (D-41–D-43)            | S188-AC3  | LV-05                                              | TC-188-07, LV-14                                                                        | 9.4, 9.12               | OP; TC-188-07 R(F-10); LV-14 CAN | PENDING | PENDING |
| FR-32 (§7.2, D-40)                  | S188-AC4  | LV-05                                              | TC-188-04, SN-19                                                                        | 9.6                     | OP / R            | PENDING  | PENDING |
| PRD §12/§16 #280 (§7.2)             | S188-AC5  | TC-188-01, LV-06                                   | TC-188-02, LV-07                                                                        | 9.1, 9.8, 9.12          | R / OP            | PENDING  | PENDING |
| spec §7.2 (D-26)                    | S188-AC6  | TC-188-03, LV-09                                   | TC-188-03 (null or mismatched ARN fails), TC-188-02                                     | 9.8, 9.9                | R (after deploy) / OP | PENDING | PENDING |
| FR-1, FR-4, §15.1 (AC-16 precursor) | S188-AC7  | LV-08                                              | TC-187-03, TC-187-04                                                                    | 9.7, 9.11               | OP / R            | PENDING  | PENDING |
| FR-49a (§15)                        | S188-AC8  | TC-188-05                                          | TC-188-06                                                                               | 9.10                    | R                 | PENDING  | PENDING |
| spec §15.1 (canary gate)            | S189-AC1  | TC-189-01, LV-10                                   | TC-189-02, SN-08, SN-09, CT-19, LV-15                                                   | 10.1, 10.6, 10.8, 10.10 | R; CT-19 R(F-1); LV CAN | PENDING | PENDING |
| PRD §17, §18 Q1; FR-9, FR-32, AC-5 (env) (§12.4) | S189-AC2 | TC-189-03, LV-11                      | TC-189-04, SN-04, SN-05, SN-06, SN-21                                                   | 10.2, 10.3, 10.6        | R; LV/SN-21 CAN   | PENDING  | PENDING |
| PRD §18 Q5 (§11.2)                  | S189-AC3  | TC-189-05, LV-12                                   | TC-189-12                                                                               | 10.2, 10.4, 10.6        | R; LV CAN         | PENDING  | PENDING |
| FR-11, FR-12, FR-30, FR-32, AC-19; PRD §18 Q2–Q4 | S189-AC4 | TC-189-06, LV-13                      | TC-189-07, SN-07, SN-22, LV-14                                                          | 10.2, 10.5, 10.6, 10.10 | R; LV/SN-22 CAN   | PENDING  | PENDING |
| PRD §18, spec §17                   | S189-AC5  | TC-189-08                                          | TC-189-09                                                                               | 10.7                    | CAN               | PENDING  | PENDING |
| PRD §17 (blocking), D-27            | S189-AC6  | TC-189-10                                          | TC-189-11                                                                               | 10.9                    | CAN               | PENDING  | PENDING |

Task-list rows with no story AC of their own: 1.14, 2.11, 3.9, 4.9, 5.9, 6.9, 7.7, 8.9, 9.13, 10.11 (per-story `make validate`, `coverage_gate`, verifier audit, PR), 9.2 (change-record plan), 10.12 (Wave B/C hand-off), 11.1–11.2 (close-out). These are process gates, not behavior, so they have no test case. Per the `audit` caveat, the `make validate` steps record a pre-existing `audit` failure; they do not block these test cases.

---

## 2. PRD FR / AC → Wave A coverage roll-up

| PRD item | Wave A story ACs                                  | Wave A coverage | Notes                                                                                                                  |
| -------- | ------------------------------------------------- | --------------- | ---------------------------------------------------------------------------------------------------------------------- |
| FR-1     | S180-AC1, S182-AC1–AC4, S188-AC2, S188-AC7        | Full            | Lifetime-as-param conflict: F-11                                                                                       |
| FR-2     | S183-AC1, S184-AC1, S184-AC3                      | Full            | Regex limits: F-12; tie-break: F-8                                                                                     |
| FR-3     | S184-AC2                                          | Full            | Non-existent issue reason: F-13                                                                                        |
| FR-4     | S184-AC1, S188-AC7                                | Full            |                                                                                                                        |
| FR-5     | S184-AC4, S187-AC1                                | Full            |                                                                                                                        |
| FR-6     | S184-AC4, S184-AC5                                | Full            | Unsupported package manager: F-13                                                                                      |
| FR-7     | S183-AC1, S183-AC4, S185-AC1, S185-AC2, S182-AC4, S188-AC2 | Full (protocol; L1/L2 only, no live claim in Wave A) | Race: F-15                                                                     |
| FR-8     | S185-AC6                                          | Full            | Bot login as param: F-18                                                                                               |
| FR-9     | S181-AC2, S183-AC5, S187-AC5, S189-AC2            | Partial         | Wrapper-side secret handling and canary child env; the CLI env itself is Wave B (S-191)                                |
| FR-11    | S180-AC1, S181-AC1–AC4, S189-AC4                  | Partial         | Image and managed settings; honoring by the CLI is CAN (SN-22, F-17); CLI flags are Wave B                             |
| FR-12    | S180-AC3, S182-AC2, S182-AC5, S189-AC4            | Partial         | Deadline primitive and param ranges; ceilings are Wave B (S-200)                                                       |
| FR-22    | S183-AC1, S185-AC3, S186-AC3                      | Partial         | Disposition protocol only; disposition triggers are Wave B                                                             |
| FR-23    | S185-AC4, S187-AC4                                | Partial         | Backstop wiring; `finally` disposition is Wave B                                                                       |
| FR-24    | S183-AC1, S185-AC2, S186-AC1–AC5                  | Full            | Gaps: F-4, F-5, F-7                                                                                                    |
| FR-25    | S180-AC4, S187-AC1, S187-AC4                      | Partial         | Steps 1–5 only                                                                                                         |
| FR-26    | S185-AC5, S187-AC3, S187-AC6                      | Full (mapping)  | Missing codes: F-10                                                                                                    |
| FR-28    | S183-AC3, S187-AC6, S188-AC1                      | Partial         | Write permission not observable: F-3                                                                                   |
| FR-30    | S189-AC4                                          | Canary only     | `plan` under `-p` (CAN)                                                                                                |
| FR-31    | S180-AC2, S180-AC3, S182-AC5                      | Partial         | Primitive and invariant; step wiring is Wave B (S-200)                                                                 |
| FR-32    | S180-AC1, S188-AC3, S188-AC4, S189-AC2, S189-AC4  | Partial         | Key provisioning, role, canary reachability; CLI-only passing is Wave B (S-191)                                        |
| AC-1     | S184-AC1                                          | Full            |                                                                                                                        |
| AC-2     | S184-AC2                                          | Full            |                                                                                                                        |
| AC-3     | S185-AC1                                          | Full at L2      | Live claim is Wave B/C (flag off in Wave A)                                                                            |
| AC-4     | S184-AC4                                          | Full            |                                                                                                                        |
| AC-5     | S181-AC2, S189-AC2                                | Partial         | Deny rules and child env without AWS variables; full CLI env assertion is Wave B (S-191)                               |
| AC-11    | S185-AC3, S187-AC3                                | Partial         | Protocol and outcome mapping; end-to-end no-PR paths are Wave B (S-200)                                                |
| AC-12    | S187-AC3                                          | Partial         | `needs_review` → `succeeded` mapping; G3 behavior is Wave C (S-202)                                                    |
| AC-13    | S185-AC2, S186-AC1–AC4                            | Full            |                                                                                                                        |
| AC-14    | S187-AC3                                          | Partial         | Ceiling → `needs_review` mapping only                                                                                  |
| AC-17    | S183-AC3, S188-AC1                                | Partial         | F-3: "lacking Issues write" not detectable by the specified preflight                                                  |
| AC-18    | S180-AC2, S180-AC3, S187-AC4                      | Partial         | Startup refusal full; step-level `RUN_BUDGET_EXHAUSTED` is Wave B (S-200)                                              |
| AC-19    | S181-AC2, S181-AC3, S189-AC4                      | Partial         | Configuration only; effect is CAN (SN-22), and the canary does not include it today (F-17)                             |
| Out of Wave A | —                                            | None            | FR-10, FR-13–FR-21, FR-27, FR-29; AC-6–AC-10, AC-15, AC-16, AC-20 (Waves B/C)                                         |

---

## 3. Coverage assertion

- **57 / 57 story ACs** have at least one positive and at least one negative or edge test. **No uncovered AC.**
- **211 test cases**: 115 story (TC), 20 contract (CT; CT-21 N/A), 28 edge (EC), 22 security-negative (SN), 11 randomized (RT), 15 live (LV).
- **By layer:** L1 103 · L2 69 · L2.5 8 · image smoke 7 · live/manual/doc 24.
- **Security-negative:** 22 (SN-01–SN-22), covering token, Supabase key, and AWS variable leaks; foreign, unmarked, and body-planted claims never touched by the sweep; canary output never carrying secrets or the Anthropic key; `ALLOW_CANARY` gating; no Bedrock permission.
- **Blocked on the S-189 canary (12):** TC-189-08, TC-189-09, TC-189-10, TC-189-11, LV-10–LV-15, SN-21, SN-22.
- **Blocked on S-188 operator prerequisites (11):** LV-01–LV-09, SN-19, TC-185-13 (plus the live half of CT-12).
- **Waiting on a finding for the expected value (16):** TC-182-07, TC-183-07, TC-185-08, TC-185-12, TC-187-04, TC-188-07, CT-05, CT-19, EC-02, EC-05, EC-06, EC-08, EC-21, EC-28, SN-18, RT-08.
- **Runnable now:** the remaining 172.
- **No case depends on `audit` being green.**
- **Partial PRD coverage is by design:** Wave A builds the contract and claim protocol. Rows marked "Partial" in §2 complete in Waves B/C and must be re-traced in their plan.
