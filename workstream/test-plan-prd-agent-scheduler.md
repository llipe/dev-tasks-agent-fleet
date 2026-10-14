# Compliance Test Plan — Agent Scheduler (verifier, Design Mode)

> Pre-implementation, black-box-first compliance test plan derived from
> [`prd-agent-scheduler`](../docs/requirements/prd-agent-scheduler.md) (FR1–FR26, AC1–AC15),
> [`specification-prd-agent-scheduler`](specification-prd-agent-scheduler.md) (SD-*), and the
> stories ([`user-stories-prd-agent-scheduler`](user-stories-prd-agent-scheduler.md), S-149…S-164,
> GitHub #261–#276). Companion: [`traceability-matrix-prd-agent-scheduler`](traceability-matrix-prd-agent-scheduler.md).
>
> **Verdict context:** this is a Design-Mode artifact (test plan), not an audit. It is
> additive and non-blocking; it does not replace `make validate`/lint/typecheck/audit.
> Every AC maps to ≥1 positive **and** ≥1 negative/edge test. The scheduler's correctness
> is concentrated in plpgsql + the Layer 2.5 integration surface (the reaper precedent), so
> the plan is weighted there; UI stories are covered black-box at component/E2E.

## Changelog

| Version | Date       | Summary                                   | Author   |
| ------- | ---------- | ----------------------------------------- | -------- |
| 1.0     | 2026-10-13 | Initial compliance test plan from spec v1.1 / stories v1.0. | verifier |

## 1. Source input summary

- **Mode:** Design (pre-implementation).
- **Scope:** the whole Phase 4 scheduler feature (16 stories).
- **Primary artifacts:** PRD v1.0, spec v1.1, stories v1.0, DESIGN.md §5.7/§5.8 + `docs/prototype/Agent Scheduler.dc.html`.
- **Test runners (per `TESTING.md`):** Vitest (L1 unit / L2 component / L2.5 integration against live local Supabase, `REQUIRE_LOCAL_DB=1`), Playwright (E2E). plpgsql behavior is exercised through L2.5 against the real stack (the `reaper.test.ts` precedent), **not** mocked.

## 2. Acceptance-criteria extraction (numbered)

| AC | Statement (observable behavior) | Primary story |
| --- | --- | --- |
| AC1 | A "daily/weekly at local HH:MM" schedule fires at the correct wall-clock time across a DST transition (the UTC instant shifts). | S-152 |
| AC2 | A scheduled firing produces a `runs` row with `trigger_type='schedule'`, `triggered_by='schedule:<id>'`, via insert-then-invoke (never-start → `failed_to_start`). | S-150+S-153 |
| AC3 | Unauthenticated / wrong-secret `POST /api/internal/schedules/{id}/fire` → `401`; only correct-secret fires; secret never logged; release gate asserts it. | S-153+S-160 |
| AC4 | While a prior run for the same (agent,repo) is non-terminal (by `effective_status`), the next firing is skipped with a reason and resumes once terminal. | S-155 |
| AC5 | A due time passing while the fire path is down produces no catch-up run; the miss is recorded; next due time proceeds. | S-154 |
| AC6 | After N (=3) consecutive failed firings the schedule auto-pauses with a reason + one notification; resume clears it; one success resets the counter. | S-157 |
| AC7 | With cap K=3 and 5 due, exactly 3 fire and 2 are skipped (`concurrency_cap`), re-evaluated next tick. | S-154 |
| AC8 | After a scheduled run opens a PR, subsequent firings of that (agent,repo) schedule are blocked until manually cleared or superseded by a manual run. | S-156 |
| AC9 | A terminal failure, a G3 auto-pause, and a PR-opened each produce exactly one `notifications` row; a success produces one only with per-schedule opt-in. | S-158 |
| AC10 | A reaper-materialized `timed_out` scheduled run (no panel involvement) still produces exactly one `run_failed` notification. | S-158 |
| AC11 | The panel feed renders newest-first with unread indicator + mark-(all)-read, server-read, RLS deny-all. | S-163 |
| AC12 | On a day with notable events exactly one SES digest is sent and those rows marked delivered; an empty day sends nothing. | S-159 |
| AC13 | Creating a schedule for each agent renders its `params_schema` form, validates with Ajv at save, needs no agent-specific scheduler code. | S-162 |
| AC14 | Every schedule CRUD op redirects `/login` (UI) / returns 401 (API) when unauthenticated; only `/api/internal/**` uses the shared secret. | S-161 |
| AC15 | The deployed scheduler fires + emails with no static AWS keys (OIDC→STS for both `InvokeAgentRuntime` and `ses:SendEmail`). | S-159 |

**Business rules / invariants** (constrain the tests): explicitness-over-inference (every
skip/block/pause recorded with a visible reason); snapshot-over-live (per-run timeout
snapshot via `buildRunInsert`); exactly-once notifications (`uq_notifications_run_kind`);
guardrails evaluate `effective_status` not raw `status`; fail-closed internal auth;
no-catch-up; channel-agnostic notifications; untrusted detail rendered as text only.

## 3. E2E scenarios (black-box)

| ID | Scenario | AC | Expected observable | Layer |
| --- | --- | --- | --- | --- |
| E2E-1 | Operator creates a daily schedule via the dialog for `dependency-update`, saves. | AC13 | Row appears in `/schedules` with the correct cadence summary + a computed Next run; a `schedules` row persists with the validated params + `next_run_at`. | Playwright + L2.5 assert |
| E2E-2 | Operator creates a schedule for **each** enabled agent. | AC13 | Each renders the correct `params_schema` form; save validates; no agent-specific code path. | Playwright |
| E2E-3 | Unauthenticated visit to `/schedules`, `/notifications`, and a CRUD POST. | AC14 | UI → 302 `/login`; API/action → 401. | Playwright |
| E2E-4 | Unauthenticated + wrong-secret `POST /api/internal/schedules/<id>/fire`. | AC3 | Both → `401` (not 404/409); correct secret (test-only) → fires. | Playwright + L1 |
| E2E-5 | Operator pauses, then resumes, then deletes a schedule. | AC14 | State transitions reflected; delete removes the schedule but its produced runs remain. | Playwright + L2.5 |
| E2E-6 | Operator opens the bell, sees unread badge, marks all read; opens `/notifications` feed. | AC11 | Badge count correct; feed newest-first; mark-read clears unread; detail is inert text. | Playwright |
| E2E-7 | An `open_pr`-blocked schedule shows the reason chip + "PR handled · resume anyway"; operator clicks it. | AC8 | Block reason visible; clicking clears the block; schedule resumes. | Playwright + L2.5 |

**Note:** actual wall-clock `pg_cron` firing is **not** E2E'd (minute waits are not
E2E-friendly); firing/guardrail/DST correctness is proven deterministically at L2.5 with a
fixed clock. E2E covers the human surfaces + the auth boundary.

## 4. Contract / schema-compatibility scenarios

| ID | Contract | AC/SD | Positive | Negative |
| --- | --- | --- | --- | --- |
| CT-1 | `runs` insert from a schedule (`buildRunInsert` schedule descriptor). | AC2 / SD-X1 | Row has `trigger_type='schedule'`, `triggered_by='schedule:<id>'`, all 3 timeout snapshots from the agent. | Malformed `schedule:` identity rejected at the type level; missing timeout → `RunSnapshotError` (never a silent default). |
| CT-2 | Fire endpoint request/response. | AC2/AC3 / SD-T9 | Correct secret → `202 {run_id}`; blocked → `200 {skipped,reason}`. | No/short/wrong secret → `401`; stale/disabled schedule → `409`; the handler never 200s past a bad secret. |
| CT-3 | `compute_next_run_at` RPC vs. internal call. | AC1 / SD-T6 | RPC and direct call return identical instants for every kind. | Unparseable advanced cron → null + surfaced error (both paths agree). |
| CT-4 | `notifications` uniqueness. | AC9 / SD-N2 | One row per `(run_id, kind)`. | A duplicate insert `on conflict do nothing` adds no row (idempotent sweep). |
| CT-5 | `params` vs `agents.params_schema` at save (schedule) and at fire. | AC13 / FR24 | Valid params persist/fire. | Invalid params rejected at save (dialog) **and** at fire (`INVALID_PARAMS`, counts toward G3). |
| CT-6 | SES send contract (`@aws-sdk/client-ses` over OIDC→STS). | AC15 / SD-N7 | A send uses `credentialSource(): fly-oidc`, no static keys; recipient/sender from secrets. | A send failure classified `SES_SEND_FAILED`, never leaks content/credentials; `emailed_at` left null. |
| CT-7 | RLS deny-all on `schedules` + `notifications`. | AC11 / D11 | service_role reads; the panel reads server-side. | anon reads **0** rows from both tables (non-vacuous seeded guard). |
| CT-8 | `pg_net` → fire endpoint call shape. | AC2 / SD-T4 | POST to `/api/internal/schedules/<id>/fire` with the `X-Scheduler-Secret` header from Vault, 5s timeout. | Secret absent in the job body (read from Vault); the call is fire-and-forget (tick does not block). |

## 5. Edge-case catalog (by category)

**Timezone / DST / time boundaries (S-152, AC1) — the highest-risk area.**
- EC-1 Daily 02:30 local on a **spring-forward** day where 02:30 does not exist → defined resolution (skip-forward to the next valid instant; documented, deterministic).
- EC-2 Daily 01:30 local on a **fall-back** day where 01:30 occurs twice → fires once (first occurrence), not twice.
- EC-3 Weekly Mon 00:00 computed from a Sunday 23:59 `from_ts` → next Monday, not today.
- EC-4 `every_n_hours` where N does not divide 24 (e.g. 5) → chains from `last_fired_at`, no drift to a "same clock time daily" assumption.
- EC-5 A schedule created with `next_run_at` in the past (clock skew) → fires on the next tick, then advances forward (no infinite backfill).
- EC-6 Leap-year Feb 29 in an advanced cron `0 0 29 2 *` → fires only on a leap year; no error on non-leap years.
- EC-7 DST transition **between** `last_fired_at` and the computed next for `every_n_hours` → interval is wall-clock N hours or absolute N hours — assert the chosen, documented semantics.

**Cron grammar (S-152).**
- EC-8 Each token form: `*`, `5`, `1,15,30`, `1-5`, `*/15`, combinations; and rejects `60` (minute), `*/0`, `5-1` (inverted), `abc`, 4-field and 6-field expressions.
- EC-9 `day-of-month` + `day-of-week` both restricted → OR semantics (cron standard), with `*`-handling per the parser (`domStar`/`dowStar`).

**Guardrails (S-154–S-157).**
- EC-10 (G1) The blocking run is itself a **stale `running`** past its reaper threshold → `effective_status` resolves it so the schedule is **not** blocked forever (AC4 negative).
- EC-11 (G1) Two schedules on the **same agent, different repos** → do **not** block each other (block scope is (agent,repo)).
- EC-12 (G4) Exactly K due (boundary) → all fire; K+1 due → one skipped; 0 in-flight vs cap already met → all skipped.
- EC-13 (G4) A stale `running` scheduled run counts against the cap for ≤1 tick (safe over-count, then the reaper converges).
- EC-14 (G2) The fire path down for several ticks → at most the single next occurrence fires on recovery (no burst).
- EC-15 (G3) Counter increments from **both** the fire endpoint (invoke-time) and the sweep (reaper `timed_out`) → a mix of the two still trips at exactly N.
- EC-16 (G3) A success between failures resets the counter (2 fail, 1 ok, 2 fail → no pause).
- EC-17 (G5) Multiple PR-producing runs → the **most-recent** unresolved PR governs the block.
- EC-18 (G5) `pr_block_cleared_at` set, then a **new** scheduled run opens a **new** PR → re-blocks (clear is per-PR, via `pr_block_run_id`).
- EC-19 (G5+G1) A schedule simultaneously overlap-blocked **and** open-PR-blocked → one unified blocked state, a deterministic single reason shown (precedence documented).

**Notifications (S-158, S-159).**
- EC-20 Reaper marks `timed_out` **and** the panel also observed a failure path → still exactly one `run_failed` row (`on conflict`), no double.
- EC-21 Sweep runs every minute over the same terminal run repeatedly → idempotent (no new rows after the first).
- EC-22 `notify_on_success` off → no `run_succeeded` row even on success; on → exactly one.
- EC-23 Digest when `emailed_at`-null set spans multiple days of backlog (prior send failed) → one digest includes all un-delivered, marks all.
- EC-24 Empty window → `204`, zero SES calls, nothing marked.
- EC-25 SES accepts then the DB `emailed_at` update fails → next run must not double-send the same rows (define: mark-before-send-with-rollback OR accept a rare duplicate; the spec says mark-after-confirmed-send, so a crash between send and mark can re-send — **document this residual**, it is the one at-most-once-vs-at-least-once seam).

**Auth / boundary (S-153, S-160).**
- EC-26 Secret present but empty string → fail-closed 401.
- EC-27 Secret of the wrong **length** → constant-time compare still returns 401 without throwing (length-guarded before `timingSafeEqual`).
- EC-28 `/api/internal/schedules/<id>/fire/extra` or `/api/internal/other` → classified `internal`, still secret-gated (no widened read surface).
- EC-29 A valid session cookie but **no** secret on an `/api/internal/**` route → still 401 (session does not satisfy the internal class).

**Data / UI (S-161–S-164).**
- EC-30 A schedule whose agent was later disabled → surfaced sensibly (shown with a state, not a crash); firing is skipped.
- EC-31 A schedule whose repository was archived → firing blocked/skipped with a reason (the invoke path already rejects archived repos).
- EC-32 Notification `detail` containing HTML/script-like text → rendered as inert text, never markup, never a metadata-built link (security-negative, mirrors §5.3).
- EC-33 Agent-page indicator with 0 schedules → zero-state per the prototype, link still valid.
- EC-34 Cadence dialog: invalid cron disables submit; the Next-3 preview shows the error, not stale times.

## 6. Randomized / property tactics (reproducible)

Seeded, replayable (capture seed + vector per the failure-triage workflow).

- RT-1 (cron parser property) For a generated valid cron, `parseCron` accepts and `compute_next_run_at` returns a time whose fields **satisfy** the expression; for a generated invalid token, it rejects. Seed-logged.
- RT-2 (DST property) For random daily/weekly local times across random dates spanning a DST boundary, the computed UTC instant re-localized back to the schedule tz equals the requested wall-clock HH:MM. (Round-trip invariant — the strongest DST check.)
- RT-3 (next-run monotonicity) For a random schedule, chaining `compute_next_run_at(prev)` yields a strictly increasing sequence with no gaps/dupes for its kind.
- RT-4 (notify idempotency) Apply the sweep a random number of times over a fixed terminal-run set → the `notifications` row count is invariant after the first (exactly-once).
- RT-5 (guardrail safety) For a random mix of in-flight scheduled runs vs. cap, the number dispatched never exceeds `cap − in_flight` and is never negative.

## 7. Execution checklist (test-first order)

Author in this order, before each story's implementation task:

1. **S-152 first** (highest risk): the DST matrix (EC-1…EC-7, RT-2) + cron grammar (EC-8/EC-9, RT-1) + RPC parity (CT-3) — L2.5 + L1.
2. **S-153/S-160 auth** (CT-2, EC-26…EC-29, E2E-4) — L1 + E2E + release-gate parser.
3. **S-149 schema** (CT-7, CT-4) — L2.5.
4. **S-154 tick** (AC5/AC7, EC-12…EC-14, RT-5) — L2.5.
5. **S-155/S-156/S-157 guardrails** (AC4/AC6/AC8, EC-10/EC-11/EC-15…EC-19) — L2.5 + L1.
6. **S-158 sweep** (AC9/AC10, EC-20…EC-22, RT-4) — L2.5.
7. **S-159 digest** (AC12/AC15, CT-6, EC-23…EC-25) — L1 + L2.5 (SES mocked at the SDK boundary).
8. **S-161…S-164 UI** (AC11/AC13/AC14, E2E-1…E2E-7, EC-30…EC-34, CT-5) — L2 + L2.5 + E2E, each pixel-matched to DESIGN.md §5.7/§5.8.

## 8. Known residual risks to assert or document (not defects)

- **EC-25 at-most-once vs at-least-once digest seam:** mark-after-confirmed-send means a
  crash between SES accept and the `emailed_at` update can re-send. The plan asserts the
  common path (no double-send on a clean run) and **documents** the rare duplicate as an
  accepted single-tenant trade-off unless the team opts for a pre-mark + rollback. **Route
  to `product-engineer` for a decision if duplicates are unacceptable.**
- **EC-1 spring-forward nonexistent local time:** the resolution (skip-forward) must be
  pinned by a test so it is deterministic, not left to Postgres default behavior.
- **G5 v1 is manual-clear only** (no GitHub poll): the tests assert the manual/supersede
  paths and explicitly assert v1 makes **no** GitHub call (negative), so the FR-FF1
  fast-follow has a clean seam.

## 9. Output contract

- **Mode/phase:** Design / Test Design complete.
- **Artifacts:** this plan + `traceability-matrix-prd-agent-scheduler.md`.
- **AC coverage:** all 15 ACs have ≥1 positive + ≥1 negative/edge (see matrix).
- **Blocking gaps:** none for planning. Two items routed to `product-engineer` (EC-25
  digest-duplicate policy; OQ-S2 advanced-cron timezone, already flagged on #264).
- **Handoff:** `developer` implements test-first per §7; after implementation, `verifier`
  Audit Mode cross-checks delivered behavior against this plan.
