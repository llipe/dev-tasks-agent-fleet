# Fidelity Report — Issue #99: `reap_stale_runs()` closes orphan `run_steps`

## 1. Verdict

| Field | Value |
|---|---|
| **Overall fidelity** | **High** |
| **Highest drift impact** | **None** |
| **Out-of-scope boundary** | **Held** (no run-level transitions/thresholds/cron changed; no application code touched) |
| **Scope** | Issue #99 · branch `issue/99-reaper-close-orphan-run-steps` · Draft PR #104 · base `main` |
| **Mode** | verifier / Audit Mode (grey-box) |
| **AC coverage** | 4/4 covered and PASS · 5/5 business rules PASS |

Delivered behavior matches requested intent on every acceptance criterion. This is a
DB-only PL/pgSQL change; the four sources cross-checked (codebase diff, `/workstream`
artifacts, test evidence, and PRD/spec intent in `technical-guidelines.md`) agree with
no unintended divergence.

## 2. Human-Readable Summary — what changed and why

Before this change, the system's automatic "reaper" — the background job that gives up
on runs that hung or never started — correctly marked the *run* as timed-out or
failed-to-start, but it left the run's individual *steps* (like "validate") frozen in a
"running" state forever. A finished run would still appear to have a step spinning
inside it, which is misleading and would have forced the upcoming Run Detail screen to
work around a contradiction.

The fix teaches the reaper to also close those leftover steps — marking them "failed",
stamping when they ended, and writing a short note explaining that the reaper closed
them and why. It does this for both kinds of reaped run (hung and never-started), and it
is careful in two ways: it only touches steps that were still open, and it does nothing
harmful when a run has no steps at all. This mirrors exactly what the agent already does
when it fails on its own, so both paths now leave the database in the same shape.

Nothing else changed. The rules for *when* a run is reaped, the timeout thresholds, and
the every-minute schedule are all untouched — those were verified in a previous issue
(#94) and were deliberately left alone. No application code (Python agent, front-end)
was modified. The change was applied to the live Supabase project and exercised with
synthetic test rows, all of which passed; the test rows were cleaned up afterward.

One item is intentionally left for later: a single real, historical frozen step from an
older run still exists. Cleaning it up is a separate, data-touching backfill step that
is deliberately held behind an explicit user go/no-go gate (task 4, still open). This is
a conscious deferral, not an oversight.

## 3. Per-AC Result Table

| AC | Description | Codebase evidence | Workstream evidence | Test evidence | Result |
|---|---|---|---|---|---|
| AC-1 | A `timed_out` run has no `run_steps` left `running` | `001_schema.sql` timed_out loop adds `update run_steps set status='failed', finished_at=now(), error_message=… where run_id=v_run.id and status in ('running','pending')` after the runs update + run_events insert | test-plan TC-1/TC-2/CT-3; matrix AC-1 row | Live: TC-1 step running→failed, 0 running; TC-2 seq2/seq3→failed, seq1 succeeded untouched; CT-3 invariant=0; negatives TC-5/EC-1 PASS | **Pass** |
| AC-2 | A `failed_to_start` run handled with or without steps, no error | `001_schema.sql` failed_to_start loop adds the same guarded `update run_steps`; safe 0-row no-op when no steps | test-plan TC-3/TC-4; matrix AC-2 row | Live: TC-3 pending step→failed; TC-4 zero-step run reaped, no SQL error, included in count=5 | **Pass** |
| AC-3 | Chosen terminal step status documented in `technical-guidelines.md` | §8 "Reaper mirrors the agent's step-closure" note; §7 caveat reworded open→resolved; §18 #99 row Resolved; changelog 1.9 | test-plan DOC-1/DOC-2; matrix AC-3 row | Doc grep confirms §8 assertion present (not merely a changelog line); §7/§18 flipped | **Pass** |
| AC-4 | `001_schema.sql` reflects the updated function | Both loops contain `update run_steps`; `create type step_status` unchanged (5 values: pending/running/succeeded/failed/skipped) | test-plan ART-1/CT-1; matrix AC-4 row | Diff shows exactly 2 added `update run_steps` blocks; deployed `pg_proc` body confirmed 2 occurrences; enum unchanged | **Pass** |

**Business rules:** BR-1 (status=`failed`), BR-2 (only `running`/`pending` closed; terminal
untouched), BR-3 (`finished_at` + attributing `error_message`), BR-4 (run
transitions/thresholds/cron unchanged), BR-5 (idempotent) — **all PASS** per the live
Execution Record and independently corroborated below.

## 4. Drift Catalog

No **unintended** drift was found. The items below are **intended** design decisions,
recorded for transparency. Per operating rules, drift is **non-blocking** to PR/issue
completion.

| # | Item | Impact | Intent | Evidence source(s) | Note |
|---|---|---|---|---|---|
| D-1 | Reaper closes steps with `finished_at = now()`, whereas the deferred backfill query uses `finished_at = coalesce(r.finished_at, now())` | Minor | Intended | `001_schema.sql` (reaper) vs. tasks §4.1 (backfill) | Asymmetry is deliberate and correct: the reaper closes steps in the same transaction it sets the run terminal, so `now()` ≈ run `finished_at`; the backfill retroactively closes steps of *already-terminal* runs and rightly prefers the run's recorded `finished_at`. No AC governs this. Non-blocking. |
| D-2 | One pre-existing historical orphan step (real run `f63ac9f3-…` `validate`) remains open | Minor | Intended (deferred) | tasks §4.3/§4.4 (open); matrix Execution Record | Backfill is confirmation-gated (data-touching, count=1). AC-1/AC-2 concern *reaping behavior going forward*, which is satisfied; the historical row is out of the reaping path. Consciously deferred, not missed. Non-blocking. |
| D-3 | `coverage_gate` recorded `SKIPPED` | Minor | Intended | tasks §6.4/§6.5; TESTING.md (no DB-function harness) | DB-only PL/pgSQL change; repo has no automated DB-function test runner (tracked in TESTING.md). `SKIPPED(<reason>)` with a non-empty reason satisfies the completion contract; only omission would be incomplete. Non-blocking. |

## 5. Out-of-Scope Boundary Check (must-NOT-have-changed)

**Held.** Verified directly from `git diff main...HEAD`:

- **Run-level reaper transitions** (`timed_out` / `failed_to_start`, `error_code`
  `RUNTIME_TIMEOUT` / `START_TIMEOUT`, explanatory `run_events` at `max(seq)+1`) —
  unchanged; the diff adds only the two `update run_steps` blocks *after* the existing
  logic.
- **Thresholds** (`max_runtime_seconds + grace_seconds`, `start_timeout_seconds`,
  `make_interval` clocks) — unchanged.
- **`cron.schedule('reap-stale-runs', '* * * * *', …)`** — unchanged.
- **`v_runs` view** — not in the diff (TC-6 regression guard).
- **`step_status` enum** — unchanged (still exactly 5 values; no migration).
- **Application code** — `git diff --name-only` shows only `docs/reference/001_schema.sql`,
  `docs/technical-guidelines.md`, and three `workstream/` files. No `.py`/`.ts`/`.tsx`/`.js`
  touched.

These match the regression guards in #94 and the issue's stated non-goals.

## 6. Edge-Case & Randomized Test Outcomes

From the live Execution Record (Supabase project `dev-tasks-agent-fleet`, ref
`hegxeycmbmjfgzqpdiik`), run in deterministic mode (cron unscheduled → synthetic rows →
direct `select reap_stale_runs()` → assert → cleanup → cron re-scheduled active):

- **Reap count = 5** (TC-1/TC-2/TC-3/TC-4 + EC-1); healthy TC-5 correctly excluded.
- **19/19 behavioral assertions PASS.**
- **EC-1** already-terminal step not overwritten (pre-set `error_message` preserved) — PASS.
- **EC-3 / RT-2** idempotency: second reap left step rows byte-identical (EXCEPT diff = 0) — PASS.
- **CT-1** enum-unchanged, **CT-2** shape-parity with the agent failure path — PASS.
- Final DB state: 0 synthetic rows remaining, cron active, deployed reaper closes steps = true.

**Note on evidence provenance:** the live results are reported in the workstream
artifacts, not re-executed by this audit (the auditor has no live-DB handle here). They
are corroborated — not merely trusted — by the static diff, which shows the deployed body
can only produce the asserted behavior: both loops contain the guarded `update`, the
predicate is `status in ('running','pending')`, and the enum is untouched. The claim
"deployed `pg_proc` body has 2 `update run_steps`" is consistent with the 2 blocks in the
committed DDL.

## 7. Recommendations

| Item | Suggested next step |
|---|---|
| D-1 (`now()` vs `coalesce`) | No action needed — deliberate and correct. |
| D-2 (historical orphan) | `developer` + user: proceed through the confirmation-gated backfill (task 4.3/4.4), or explicitly record a decision to leave the single historical row. Not required to close #99. |
| D-3 (coverage_gate SKIPPED) | No action needed for this issue. Longer term, the DB-function test-harness gap is already tracked in `TESTING.md`; a lightweight pgTAP/SQL harness would let AC-1/AC-2 be re-run automatically instead of operator-driven. |
| Completion | Proceed with the remaining `implement` gates (verifier audit posted — this report, PR draft→ready, user review/merge to `main`). Drift here is non-blocking. |

## 8. Additive / Non-Blocking Statement

This audit is **additive and non-blocking**. It does not gate PR #104 or issue #99
completion and does not replace the existing quality gates
(`test`/`lint`/`format:check`/`typecheck`/`audit`). All drift recorded above is
intended; any follow-up (the deferred backfill) is routed through the normal
confirmation gate, not through this report.
