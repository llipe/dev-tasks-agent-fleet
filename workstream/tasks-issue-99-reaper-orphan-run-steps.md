# Implementation Plan - Issue #99: reap_stale_runs leaves open run_steps in running state

> Source issue: [#99](https://github.com/llipe/dev-tasks-agent-fleet/issues/99) — `fix(db): reap_stale_runs leaves open run_steps in running state`
> Labels: `bug`, `priority:medium`, `phase:infrastructure`, `size:S`
> Discovery source: [#94](https://github.com/llipe/dev-tasks-agent-fleet/issues/94) (reaper verification, Known limitations §2)

## Execution Roles

Each sub-task is tagged with who executes it:

- **[DEV]** — developer agent, repo-side (SQL/docs edits, commits, PR sync). Autonomous.
- **[MANUAL]** — operator (you), live infrastructure. Requires Supabase SQL Editor / dashboard access the agent does not have.

## Scope & Decisions

- **DB-only change.** The fix is confined to the `reap_stale_runs()` PL/pgSQL function and its documentation. **No application code** (Python agent, TS front-end) is in scope.
- **Chosen terminal step status: `failed`.** For symmetry with the agent's own failure path (technical-guidelines §8: "open steps are closed as `failed`"). The `step_status` enum already contains `failed` (`001_schema.sql` line 21), so no enum migration is required. This resolves the issue's open decision item; rationale is documented in sub-task 1.6.
- **Both reaper branches.** The step-closing logic applies to both loops (`timed_out` and `failed_to_start`). `failed_to_start` runs normally have no steps, but the `update` must be a no-op-safe blanket statement that does not assume rows exist.
- **Migration convention.** This repo has no separate migrations directory; `docs/reference/001_schema.sql` is the canonical DDL and the function is redefined in place with `create or replace function`. The live change is **operator-applied** via the Supabase SQL Editor (same pattern as #94). This carries a live-DB confirmation gate (Task 3).
- **No `main` push / no inline `--body`** (repo git-guard invariants).

## Relevant Files

**Modified:**

- `docs/reference/001_schema.sql` — redefine `reap_stale_runs()` to close open `run_steps` (`status='failed'`, `finished_at=now()`, explanatory `error_message`) in both reaper branches. **[DEV]**
- `docs/technical-guidelines.md` — document the chosen terminal step status and its symmetry with §8; refresh the §7 "Current state (issue #94, ADR-004)" caveat that currently records the orphan-step defect as open (#99); add a changelog row. **[DEV] + technical-writer**

**Created (as needed):**

- `docs/adr/ADR-00X-reaper-closes-orphan-run-steps.md` — records the decision to close reaped steps as `failed` for symmetry (only if the team wants a standalone ADR; otherwise folded into the technical-guidelines §7/§8 update). **[DEV] — confirm during 1.6**
- `workstream/test-plan-issue-99.md` — verifier Design Mode compliance test plan. **[verifier]**
- `workstream/traceability-matrix-issue-99.md` — AC → test → verdict mapping. **[DEV/verifier]**

**Not modified (deliberately):** no application code, no run-level reaper transitions or thresholds (verified correct in #94 — explicitly out of scope).

## Tasks

- [x] 1.0 Implement Issue #99 - https://github.com/llipe/dev-tasks-agent-fleet/issues/99: Close open run_steps when the reaper terminates a run

  > Note: `reap_stale_runs()` currently updates `runs` and inserts a `run_events` row in each of its two loops but never touches `run_steps`. Add an `update run_steps` in both loops to close any step still `running` (or `pending`) for the reaped run.

  - [x] 1.1 Read the current `reap_stale_runs()` definition and the `run_steps` / `step_status` DDL in `docs/reference/001_schema.sql` to confirm column names (`status`, `finished_at`, `error_message`) and the `failed` enum value.
  - [x] 1.2 In the `timed_out` loop (`status='running'` branch), after the `runs` update and `run_events` insert, add an `update run_steps set status='failed', finished_at=now(), error_message='<closed by reaper — run timed_out>' where run_id = v_run.id and status in ('running','pending')`.
  - [x] 1.3 In the `failed_to_start` loop (`status='queued'` branch), add the equivalent `update run_steps` guarded the same way. Ensure it is a safe no-op when the run has no steps (blanket `where` with no row match returns 0 rows, no error).
  - [x] 1.4 Confirm the `error_message` text on the closed steps clearly attributes closure to the reaper and names the reason (`RUNTIME_TIMEOUT` / `START_TIMEOUT`), consistent with the `run_events` `data.reason` already written.
  - [x] 1.5 Keep the change inside the single `create or replace function reap_stale_runs()` block; do not alter the run-level transitions, thresholds, or the `cron.schedule` call (out of scope).
  - [x] 1.6 Decide and record the terminal step status (`failed`, per Scope & Decisions) — DECIDED: inline note in technical-guidelines §7/§8, no standalone ADR (consistent with #94's doc-gate pass under the existing ADR-004; symmetry rationale captured inline).

- [x] 2.0 Document the fix

  - [x] 2.1 Update `docs/technical-guidelines.md` §8 to state that the reaper closes open `run_steps` as `failed` on termination, matching the agent failure path.
  - [x] 2.2 Update the §7 "Current state (issue #94, ADR-004)" paragraph: the orphan-step caveat (`the function does not close open run_steps ... (#99)`) is now resolved — reword from open-defect to fixed, referencing this issue.
  - [x] 2.3 Update the §18 "Open defects discovered during reaper verification" table row for #99 from **Open** to **Resolved**, with a one-line description of the fix.
  - [x] 2.4 Add a changelog row to `docs/technical-guidelines.md` (increment version, date, summary, author) describing the reaper orphan-step fix. Delegate the doc-drift/stale-doc pass to `technical-writer`.

- [x] 3.0 Apply the DDL change to the live database (migration lifecycle — confirmation-gated)

  > Note: `docs/reference/001_schema.sql` is the canonical DDL; the function must be redefined in the live Supabase project via `create or replace function`. This is a live-DB change and requires explicit user confirmation before applying.
  > APPLIED to Supabase cloud project `dev-tasks-agent-fleet` (ref `hegxeycmbmjfgzqpdiik`) per user direction to test against Supabase cloud. Deployed `pg_proc` body confirmed to contain 2 `update run_steps` statements.

  - [x] 3.1 **[DEV]** Provide the exact `create or replace function reap_stale_runs() ...` statement (full updated body) as a ready-to-paste migration snippet, plus rollback notes (re-apply the previous function body to revert; the change is additive and idempotent, no data destruction).
  - [x] 3.2 **[DEV]** Document rollback/impact: the only effect is that open steps of *future* reaped runs are closed; existing terminal runs are unaffected until backfill (Task 4). No `runs`/`run_events` behavior changes.
  - [x] 3.3 **[MANUAL/DEV]** ⚠️ Live-DB change. Applied via `supabase db query --linked` against the `dev-tasks-agent-fleet` cloud project (user directed testing against Supabase cloud). Ran under deterministic mode (cron unscheduled during tests, re-scheduled after).
  - [x] 3.4 **[DEV]** Verify applied state: `select position('update run_steps' in prosrc) from pg_proc where proname='reap_stale_runs'` → 2 occurrences confirmed; cron re-scheduled and active.

- [ ] 4.0 Handle existing orphan steps (AC — backfill or document)

  > Note: Live pre-check found **exactly 1** pre-existing orphan step under a `timed_out` run (the real `f63ac9f3-…` `validate` step). ⏳ AWAITING USER CONFIRMATION before applying the backfill (see 4.3).

  - [x] 4.1 **[DEV]** Provide a backfill query that closes orphan steps belonging to already-terminal runs: `update run_steps s set status='failed', finished_at=coalesce(r.finished_at, now()), error_message='<backfilled: closed by reaper fix #99>' from runs r where s.run_id = r.id and r.status in ('timed_out','failed_to_start') and s.status in ('running','pending');`
  - [x] 4.2 **[DEV]** Document rollback/impact of the backfill (it only touches steps of already-terminal runs; sized via `select count(*)` = **1**).
  - [ ] 4.3 **[MANUAL]** ⚠️ Live-DB data change — **confirmation gate**. Sizing done (count=1); AWAITING user go/no-go to apply the backfill (or explicitly decide to leave the single historical orphan and record that decision instead).
  - [ ] 4.4 **[MANUAL]** Verify: orphan-step count returns `0` (if backfill applied).

- [x] 5.0 Verify Acceptance Criteria

  > Verified live against Supabase cloud `dev-tasks-agent-fleet`. Full results in `workstream/traceability-matrix-issue-99.md` (Execution Record). 19/19 behavioral assertions + contract/idempotency checks PASS.

  - [x] 5.1 Verify Acceptance Criterion 1: a run reaped to `timed_out` has no `run_steps` left in `running`. (TC-1/TC-2/CT-3 PASS; TC-5/EC-1 negatives PASS.)
  - [x] 5.2 Verify Acceptance Criterion 2: a run reaped to `failed_to_start` is handled without error whether or not steps exist. (TC-3 with step + TC-4 no-step PASS; reap count=5 included the no-step run, no error.)
  - [x] 5.3 Verify Acceptance Criterion 3: the chosen terminal step status is documented in `docs/technical-guidelines.md` (§7/§8/§18 + changelog 1.9).
  - [x] 5.4 Verify Acceptance Criterion 4: `docs/reference/001_schema.sql` reflects the updated function (both `update run_steps` statements present; deployed body confirms 2; enum unchanged per CT-1).

- [ ] 6.0 Tests, quality gates & acceptance-criteria-to-tests mapping

  > Note: This is a PL/pgSQL DB-function change with no host application to unit-test it in Phase 1 (the Next.js panel is Phase 2; the Python agent does not call the reaper). Verification is therefore the live SQL scenarios in Task 5 plus a recorded traceability mapping. `TESTING.md` (Database / reaper layer) tracks the absence of an automated DB test harness as a known gap.

  - [x] 6.1 **[verifier]** Design Mode test plan produced: `workstream/test-plan-issue-99.md` (AC1–AC4 + edge cases + idempotency).
  - [x] 6.2 Build the acceptance-criteria-to-tests mapping in `workstream/traceability-matrix-issue-99.md` (each AC → scenario → observed verdict). Done with live results.
  - [x] 6.3 Record edge-case coverage: (a) multi open steps all closed — TC-2 PASS; (b) already-terminal step untouched — TC-2 seq1 + EC-1 PASS; (c) `failed_to_start` zero steps — TC-4 PASS; (d) reaper re-run idempotency — EC-3 PASS.
  - [x] 6.4 Quality gates: DB-only change, no application code modified → recorded `SKIPPED (DB-only PL/pgSQL change; no application test package exercises the reaper; no DB-function test runner in repo)`.
  - [x] 6.5 `coverage_gate` recorded via `qa-engineer`: **SKIPPED** (DB-only PL/pgSQL; no automated DB-function harness / SQL coverage provider; verified by 19/19 live SQL scenarios; residual gap tracked in `TESTING.md`). Non-blocking.

- [ ] 7.0 Completion & wrap-up

  - [x] 7.1 Confirm out-of-scope items were not touched: no run-level transitions/thresholds changed, no `cron.schedule` change, no application code, no heartbeat/cancellation/retention work. **Verified by the verifier audit** (out-of-scope boundary HELD).
  - [x] 7.2 Run `verifier` in Audit Mode against the delivered change; post the human-readable summary to PR and issue #99 (via `github-ops`, `--body-file`). **Done** — Fidelity High, drift None; posted to PR #104 + issue #99. `workstream/fidelity-report-issue-99.md`.
  - [ ] 7.3 Sync the GitHub issue #99 Scope + this task checklist to final state and post a completion summary comment (via `github-ops`, `--body-file`).
  - [ ] 7.4 Convert the PR from draft to ready for review; notify the user for review + merge (PR targets `main` → user approves and merges).
