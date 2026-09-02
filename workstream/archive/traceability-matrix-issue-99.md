# Traceability Matrix — Issue #99: reap_stale_runs closes open run_steps

> Mode: **verifier / Design Mode** (pre-implementation)
> Companion: `workstream/test-plan-issue-99.md`
> Format: `AC-ID → Test-Case-ID → Observed-Result → Pass/Fail/Drift`
> `Observed-Result` / `Verdict` are filled during execution (operator run / Audit Mode). All `Pending` at design time.

## AC → Test Coverage

| AC | Statement | Positive test(s) | Negative / edge test(s) | Observed Result | Verdict |
|---|---|---|---|---|---|
| AC-1 | `timed_out` run has no `run_steps` left in `running` | TC-1, TC-2, CT-3 | TC-5 (un-reaped step untouched), EC-1 (terminal step not overwritten) | Live Supabase (`hegxeycmbmjfgzqpdiik`): TC-1 step running→failed, 0 running steps; TC-2 seq2/seq3→failed, seq1 succeeded untouched, 0 open; CT-3 invariant=0; TC-5 healthy run+step stay running; EC-1 pre-failed msg preserved | **PASS** |
| AC-2 | `failed_to_start` handled with or without steps, no error | TC-3 (with step) | TC-4 (no step — primary guard), TC-5 | Live: TC-3 run→failed_to_start, pending step→failed w/ finished_at; TC-4 run→failed_to_start with zero steps, no SQL error (reap returned count=5 including it) | **PASS** |
| AC-3 | Chosen terminal step status documented in `technical-guidelines.md` | DOC-1, DOC-2 | grep old §7 caveat absent/qualified | §8 "Reaper mirrors the agent's step-closure" note present; §7 caveat reworded open→resolved; §18 #99 row Resolved; changelog 1.9 | **PASS** |
| AC-4 | `001_schema.sql` reflects the updated function | ART-1 | CT-1 (no new `step_status` enum value) | `001_schema.sql` has `update run_steps` in both loops; deployed `pg_proc` body confirms 2 occurrences; enum still exactly 5 baseline values | **PASS** |

## Business-Rule → Test Coverage

| BR | Rule | Test(s) | Observed Result | Verdict |
|---|---|---|---|---|
| BR-1 | Reaped step status is `failed` | TC-1, TC-3, CT-2 | All closed steps = `failed`; CT-2 shape parity holds | **PASS** |
| BR-2 | Only `running`/`pending` steps closed; terminal untouched | TC-2 (seq1 succeeded), EC-1 | seq1 `succeeded` untouched; EC-1 pre-`failed` msg `ORIGINAL-agent-message` preserved | **PASS** |
| BR-3 | Closed step gets `finished_at` + attributing `error_message` | TC-1, TC-3 | `finished_at` set; message names `reap_stale_runs` + `RUNTIME_TIMEOUT`/`START_TIMEOUT` | **PASS** |
| BR-4 | Run transitions/thresholds/cron unchanged | TC-5, TC-6, CT-1 | timed_out `error_code=RUNTIME_TIMEOUT` + failed_to_start `error_code=START_TIMEOUT` intact; reap count excluded healthy TC-5; cron re-scheduled active | **PASS** |
| BR-5 | Reaper idempotent on already-reaped runs | EC-3, RT-2 | 2nd reap: step rows byte-identical (EXCEPT diff = 0) | **PASS** |

## Test Case Index

| Test ID | Title | Kind | AC / BR |
|---|---|---|---|
| TC-1 | `timed_out` + single open step | Positive | AC-1, BR-1, BR-3 |
| TC-2 | `timed_out` + multiple mixed steps | Positive (fan-out) | AC-1, BR-2 |
| TC-3 | `failed_to_start` + open step | Positive | AC-2, BR-1 |
| TC-4 | `failed_to_start` + no steps | Edge (primary AC-2 guard) | AC-2 |
| TC-5 | Healthy run below threshold | Negative (must-not-act) | AC-1, BR-4 |
| TC-6 | `v_runs` two-layer read unchanged | Regression | BR-4 |
| CT-1 | No new `step_status` enum value | Contract / schema-compat | AC-4 |
| CT-2 | Reaper step-close shape == agent path | Contract / symmetry | BR-1, BR-3 |
| CT-3 | Zero open steps under terminal runs invariant | Contract / consumer | AC-1 (+ backfill verify) |
| EC-1 | Already-terminal step not overwritten | Negative | BR-2 |
| EC-2 | `pending`-only steps closed | Edge | AC-1 |
| EC-3 | Idempotent double reap | Negative | BR-5 |
| EC-4 | Multiple reaped runs, mixed states | Data boundary | AC-1 |
| RT-1 | Property: no open step survives a reap | Randomized (seeded) | AC-1 |
| RT-2 | Property: idempotence | Randomized (seeded) | BR-5 |
| DOC-1 | §8 documents `failed` closure | Doc | AC-3 |
| DOC-2 | §7/§18 caveat resolved | Doc | AC-3 |
| ART-1 | `update run_steps` in both loops | Artifact | AC-4 |

## Coverage Verdict (design-time)

- Every AC has ≥1 positive **and** ≥1 negative/edge test: **satisfied**.
- Every derived business rule is mapped: **satisfied**.
- Out-of-scope items (run transitions/thresholds/cron, heartbeat, cancellation, retention, application code) have explicit **regression guards** (TC-5, TC-6, CT-1), not new behavior.
- **AC coverage status: covered (4/4).** No uncovered AC.
- **Blocking gaps:** none at design time. Execution constraint recorded: operator-driven SQL (no automated DB-function harness; tracked in `TESTING.md`).

## Execution Record (post-implementation, live Supabase)

- **Target:** Supabase cloud project `dev-tasks-agent-fleet` (ref `hegxeycmbmjfgzqpdiik`), via `supabase db query --linked`.
- **Method:** cron `reap-stale-runs` unscheduled for determinism → synthetic `runs`/`run_steps` tagged `idempotency_key like 'tc99-%'` → direct `select reap_stale_runs()` → labeled assertions → synthetic rows deleted → cron re-scheduled `* * * * *` (verified active).
- **Pre-check:** deployed reaper did **not** touch `run_steps` (bug confirmed live); `runs_eligible_for_reaping_now = 0` (no genuine rows at risk); 1 pre-existing real orphan step under a `timed_out` run (backfill population).
- **Result:** reap returned count **5** (TC-1/2/3/4 + EC-1); healthy TC-5 excluded. **19/19** behavioral assertions PASS; EC-3 idempotency, CT-1 enum-unchanged, CT-2 shape-parity all PASS.
- **Final DB state:** 0 synthetic rows remaining, cron active, deployed reaper closes steps = true, 1 pre-existing orphan left untouched pending the confirmation-gated backfill (Task 4).
- **All 4 ACs: PASS. All 5 BRs: PASS.**

## Backfill Record (Task 4 — historical orphan cleanup)

- **User confirmation:** "clean the orphan" (go-ahead given after sizing).
- **Sized before:** exactly 1 orphan step (real run `f63ac9f3-…`, `validate`) `running`/`finished_at=null` under a `timed_out` run.
- **Applied:** `update run_steps set status='failed', finished_at=coalesce(r.finished_at, now()), error_message='Backfilled by issue #99: step left open by a pre-fix reaper run.'` scoped to steps `running`/`pending` under `timed_out`/`failed_to_start` runs — 1 row updated.
- **Verified after:** `orphan_steps_remaining = 0`; `run_steps` in `running` DB-wide = **0**. The consumer invariant (no open step inside a terminal run) now holds across the whole database.
