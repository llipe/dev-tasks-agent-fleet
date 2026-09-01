# Compliance Test Plan — Issue #99: reap_stale_runs leaves open run_steps in running state

> Mode: **verifier / Design Mode** (test-first, pre-implementation)
> Source: [#99](https://github.com/llipe/dev-tasks-agent-fleet/issues/99) body + `docs/reference/001_schema.sql` (`reap_stale_runs()`, `v_runs`, `run_steps`/`step_status` DDL)
> Grounding: `docs/runbooks/issue-94-reaper-verification.md` (synthetic-row technique), `docs/technical-guidelines.md` §7/§8/§18
> Companion artifact: `workstream/traceability-matrix-issue-99.md`

## 1. Source Input Summary

`reap_stale_runs()` materializes stale-run terminal state in two loops — `running → timed_out` (clock `started_at`, threshold `max_runtime_seconds + grace_seconds`) and `queued → failed_to_start` (clock `queued_at`, threshold `start_timeout_seconds`). Each loop updates `runs` and inserts one explanatory `run_events` row, but **neither touches `run_steps`**. A reaped run therefore leaves every open step pinned `status='running'`, `finished_at=null` — inconsistent with the agent's own failure path (technical-guidelines §8: "open steps are closed as `failed`") and a contradictory state for the Phase 2 Run Detail panel (a perpetually pulsing step inside a terminal run).

The fix adds a step-closing `update` to **both** loops. This plan derives compliance tests from the **observable post-reaper database state**, not from the function's internals.

**Testability constraint (must be honored by the plan).** This is a PL/pgSQL change with **no host application that invokes the reaper** in Phase 1 — the Next.js panel is Phase 2 and the Python agent never calls `reap_stale_runs()`. The repo has **no automated DB-function test harness** (`TESTING.md`, Database / reaper layer, records this as a known gap). Consequently every scenario below is a **SQL-level black-box scenario** executed by the operator against a live/dev Supabase project using the synthetic-row-with-backdated-timestamps technique proven in the #94 runbook. Where a value is time-sensitive, the plan states the ordering constraint explicitly.

## 2. Acceptance Criteria Extraction

| AC | Statement | Type |
|---|---|---|
| AC-1 | A run reaped to `timed_out` has no `run_steps` left in `running`. | Behavioral (DB state) |
| AC-2 | A run reaped to `failed_to_start` is handled without error whether or not steps exist. | Behavioral (DB state + no-error) |
| AC-3 | The chosen terminal step status is documented in `docs/technical-guidelines.md`. | Documentation |
| AC-4 | `docs/reference/001_schema.sql` reflects the updated function. | Artifact/static |

### Business rules (derived — drive negative & edge tests)

| BR | Rule | Source |
|---|---|---|
| BR-1 | Terminal step status for a reaped step is `failed`. | Scope decision; technical-guidelines §8 symmetry |
| BR-2 | Only open steps (`running`, `pending`) are closed; `succeeded`/`failed`/`skipped` steps are untouched. | Fix predicate `status in ('running','pending')` |
| BR-3 | A closed step gets `finished_at = now()` and an attributing `error_message` (names reaper + reason). | Scope sub-tasks 1.2–1.4 |
| BR-4 | Run-level transitions, thresholds, and `cron.schedule` are unchanged. | Issue "Out of scope"; #94 |
| BR-5 | Reaper is idempotent — a second run over an already-reaped run causes no duplicate/harmful step side effects. | Existing loop guards `status='running'/'queued'` on `runs` |

### Non-goals (must NOT be exercised as pass conditions)

- Changing `runs` reaper transitions/thresholds (verified correct in #94).
- Heartbeat-based detection, run cancellation, `run_events` retention.
- Any application-code test (no application code is in scope).

## 3. Test Environment & Fixtures

- **Target:** a dev Supabase project with `001_schema.sql` + `002_seed.sql` applied and the **updated** `reap_stale_runs()` deployed (Task 3 of the plan). Prefer a dedicated dev project over production (R7).
- **Seed dependencies:** `agent_id` (`dependency-update`) and `repository_id` resolved from `002_seed.sql`.
- **Synthetic-row technique:** insert `runs` rows with **backdated** clock columns so they are already past threshold; only wait for the next `* * * * *` cron tick (≤ ~60 s). This is the exact method used in the #94 runbook §2/§3.
- **Deterministic materialization option:** to observe pre/post state reliably, `select cron.unschedule('reap-stale-runs')` → set up rows → `select reap_stale_runs()` directly (synchronous, returns the reaped count) → assert → `select cron.schedule('reap-stale-runs','* * * * *', $$select reap_stale_runs()$$)`. Calling the function directly is the **recommended** execution path for these scenarios because it removes tick-timing flakiness.
- **Isolation:** each scenario uses fresh `gen_random_uuid()` run ids; tests assert only on their own run ids. Clean up synthetic rows after the run (`delete from runs where id = '<uuid>'` cascades to `run_steps`/`run_events`).

### Reusable fixture — helper insert shapes (pseudo-SQL)

```sql
-- A: running run already past threshold, WITH an open step
insert into runs (id, agent_id, agent_version, repository_id, installation_id,
                  status, started_at, queued_at,
                  max_runtime_seconds, grace_seconds, start_timeout_seconds)
select :rid, a.id, a.version, r.id, r.installation_id,
       'running', now() - interval '75 seconds', now() - interval '80 seconds',
       60, 10, 300
from agents a join repositories r on r.full_name = 'llipe/memo-cli'
where a.slug = 'dependency-update';

insert into run_steps (id, run_id, seq, key, status, started_at)
values (gen_random_uuid(), :rid, 1, 'validate', 'running', now() - interval '70 seconds');
```

## 4. E2E / Behavioral Scenarios (black-box, SQL-level)

> Each scenario: preconditions → action (`select reap_stale_runs()` or one cron tick) → observable assertions. "Observed result" is filled during execution (Audit Mode / operator run).

### TC-1 — `timed_out` run with a single open `running` step  → AC-1, BR-1, BR-3 (positive)
- **Pre:** fixture A (one `validate` step `running`).
- **Action:** `select reap_stale_runs();`
- **Assert:**
  - `runs.status = 'timed_out'` (regression guard, BR-4 unchanged).
  - `run_steps.status = 'failed'` for the step (BR-1).
  - `run_steps.finished_at is not null` (BR-3).
  - `run_steps.error_message` is non-null and names the reaper + `RUNTIME_TIMEOUT` (BR-3).
  - **AC-1 core:** `select count(*) from run_steps where run_id=:rid and status='running'` = `0`.

### TC-2 — `timed_out` run with multiple open steps → AC-1, BR-2 (positive, fan-out)
- **Pre:** running run past threshold with 3 steps: seq1 `succeeded`, seq2 `running`, seq3 `pending`.
- **Action:** reap.
- **Assert:** seq2 → `failed`, seq3 → `failed`, **seq1 stays `succeeded`** (BR-2 — already-terminal untouched), and `finished_at` unchanged on seq1. No `running`/`pending` steps remain.

### TC-3 — `failed_to_start` run WITH an open step → AC-2, BR-1 (positive)
- **Pre:** `queued` run with backdated `queued_at` past `start_timeout_seconds`, plus one `pending` step (unusual but must not error).
- **Action:** reap.
- **Assert:** `runs.status='failed_to_start'`; the step → `failed`, `finished_at` set; no open steps remain; **no SQL error raised**.

### TC-4 — `failed_to_start` run with NO steps → AC-2 (positive, the normal case)
- **Pre:** `queued` run past threshold, zero `run_steps`.
- **Action:** reap.
- **Assert:** `runs.status='failed_to_start'`; the `update run_steps` matches 0 rows and **raises no error**; reaped count increments normally. This is the primary AC-2 guard (the code "should not assume steps exist").

### TC-5 — Healthy `running` run below threshold → BR-4 (negative / must-not-act)
- **Pre:** `running` run with `started_at = now()` (well within threshold), one `running` step.
- **Action:** reap.
- **Assert:** `runs.status` stays `running`; **the step stays `running`** (the fix must not close steps of un-reaped runs); reaped count does not include this run.

### TC-6 — Two-layer read consistency untouched → BR-4 (regression)
- **Pre:** fixture A, **before** reaping.
- **Action:** `select status, effective_status from v_runs where id=:rid;`
- **Assert:** `status='running'`, `effective_status='timed_out'` — confirms the fix did not alter `v_runs` (out of scope). Step-level state is not part of `v_runs`; this guards against accidental view edits.

## 5. Contract Validation Scenarios

The "contract" here is the **post-reaper row shape** other components consume (Phase 2 Run Detail panel per `DESIGN.md` §5.3, and the agent-vs-reaper symmetry in §8).

- **CT-1 (schema-compat):** closed steps use only the existing `step_status` enum value `failed` — **no new enum value** is introduced. Assert by inspecting `001_schema.sql` `create type step_status` is unchanged (still 5 values) AND the function writes `'failed'`. (Prevents a silent enum migration.)
- **CT-2 (symmetry contract):** the reaper's step-close shape (`status='failed'`, `finished_at` set, `error_message` populated) matches the agent failure-path shape described in technical-guidelines §8. Assert field-by-field parity in documentation review + TC-1 assertions.
- **CT-3 (consumer contract):** after any reap, `select count(*) from run_steps s join runs r on r.id=s.run_id where r.status in ('timed_out','failed_to_start') and s.status in ('running','pending')` = `0`. This is the exact invariant the Run Detail panel relies on (no pulsing step in a terminal run) and doubles as the **backfill verification** (plan Task 4.4).

## 6. Edge-Case Catalog (by category)

| Category | Edge case | Test | Expected |
|---|---|---|---|
| State transition | Step already `succeeded` before reap | TC-2 seq1 | Untouched (BR-2) |
| State transition | Step already `failed`/`skipped` before reap | EC-1 | Untouched; `error_message`/`finished_at` not overwritten |
| Input domain | Run with zero steps (`failed_to_start`) | TC-4 | No error, 0 rows updated |
| Input domain | Run with only `pending` steps (never started) | EC-2 | `pending` → `failed` (open = `running`+`pending`) |
| Idempotency | Reaper runs twice over same reaped run | EC-3 | 2nd pass: run no longer `running`/`queued`, so loop skips it; steps unchanged; no duplicate `run_events` |
| Timing | `v_runs` read between reaps | TC-6 | `effective_status` leads; unchanged by fix |
| Data boundary | Multiple reaped runs in one `reap_stale_runs()` call, mixed step states | EC-4 | Each run's open steps closed independently; no cross-run leakage |
| Failure mode | `error_message` length | EC-5 | Within column bounds; message truncation policy (8 KB `run_events` rule) not applicable to `run_steps.error_message` but message stays short |
| Concurrency | `for update skip locked` on `runs` still holds | EC-6 | Fix adds only a `run_steps` update keyed by `run_id`; no new lock contention on `runs` |
| Regression | `runs` transition/threshold/cron unchanged | TC-5, TC-6, CT-1 | No behavioral change to run-level reaping |

**EC-1 (must-not-overwrite, negative):** pre-set a step to `failed` with a distinct `error_message='original'`; reap; assert `error_message` still `'original'` and `finished_at` unchanged (predicate `status in ('running','pending')` excludes it).

**EC-3 (idempotency, negative):** reap fixture A; capture `run_events` count and step row; reap again; assert step row byte-identical and no new reaper `run_events` row (run is already `timed_out`, so the `running` loop skips it).

## 7. Randomized / Property-Based Tactics

Randomization is low-value for a small deterministic PL/pgSQL predicate, but two properties are worth a seeded generator if the operator wants extra assurance:

- **RT-1 (property — no open step survives a reap):** generate N runs (seed-controlled) with random eligible clocks and a random mix of step states (`pending`/`running`/`succeeded`/`failed`/`skipped`), run one `reap_stale_runs()`, assert the CT-3 invariant holds for **every** reaped run and **no** un-reaped run had a step mutated. Property: `∀ reaped run r: 0 open steps AND ∀ step previously terminal: unchanged`.
- **RT-2 (property — idempotence):** apply `reap_stale_runs()` twice; assert `run_steps` snapshot after pass 1 == after pass 2 (set equality on `(id, status, finished_at, error_message)`).

**Seed policy:** record the seed used to generate the run/step fixtures (e.g. `setseed(0.4299)` before `random()` calls, or a fixed VALUES list generated from a documented seed). On failure, capture the seed + the offending `run_id`/`step` row, re-run with the same seed to confirm deterministic reproduction, minimize to the smallest run/step set that reproduces, then classify per the Failure Triage Workflow (spec gap → product-engineer; implementation defect → developer; non-reproducing → `inconclusive` after ≤3 attempts).

## 8. Documentation & Artifact Assertions

- **DOC-1 → AC-3:** `docs/technical-guidelines.md` §8 states the reaper closes open `run_steps` as `failed` on termination (symmetry with agent path). Grep for the assertion; confirm it is not merely in a changelog line.
- **DOC-2 → AC-3:** §7 "Current state (issue #94)" orphan-step caveat reworded from open-defect to resolved; §18 table row #99 flipped Open → Resolved.
- **ART-1 → AC-4:** `docs/reference/001_schema.sql` `reap_stale_runs()` body contains an `update run_steps ... set status='failed'` in **both** loops (grep both branches). `create type step_status` unchanged (CT-1).

## 9. Execution Checklist (operator, test-first order)

Run this plan **before** wiring implementation into the live DB is finalized — it doubles as the acceptance harness for plan Tasks 3–5.

1. [ ] Apply updated `reap_stale_runs()` to the **dev** project (or run the candidate body ad-hoc via `create or replace function`).
2. [ ] `select cron.unschedule('reap-stale-runs');` (deterministic mode).
3. [ ] TC-1 → TC-6 in order; record observed row states.
4. [ ] EC-1, EC-2, EC-3, EC-4; record.
5. [ ] CT-1, CT-2, CT-3; record.
6. [ ] (Optional) RT-1, RT-2 with recorded seed.
7. [ ] DOC-1, DOC-2, ART-1 static checks (can run at any point).
8. [ ] `select cron.schedule('reap-stale-runs','* * * * *', $$select reap_stale_runs()$$);` (restore).
9. [ ] Clean up synthetic rows.
10. [ ] Transfer per-AC verdicts into `workstream/traceability-matrix-issue-99.md`.

## 10. Coverage Statement

Every AC maps to ≥1 positive test **and** ≥1 negative/edge test (see traceability matrix):

- AC-1 → positive TC-1/TC-2; negative TC-5 (must-not-close un-reaped), EC-1 (must-not-overwrite).
- AC-2 → positive TC-3 (with step); edge TC-4 (no step, primary guard); negative TC-5.
- AC-3 → DOC-1/DOC-2 positive; negative = grep must NOT find the old "does not close open run_steps" caveat left unqualified in §7.
- AC-4 → ART-1 positive; negative = CT-1 (must NOT introduce a new `step_status` enum value).

**Status:** `ready` — all four ACs covered by positive + negative/edge scenarios. No blocking gaps. Known constraint recorded: execution is operator-driven SQL because no automated DB-function test harness exists in the repo (tracked in `TESTING.md`).
