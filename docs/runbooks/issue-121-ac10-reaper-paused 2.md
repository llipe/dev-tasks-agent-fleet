# Operator Runbook — Issue #121 (AC10): Run History Shows `timed_out` While the Reaper Is Paused

> **Audience:** the developer/operator with a local Supabase stack (`supabase start` +
> `supabase db reset`) and the panel running locally (`pnpm --filter panel dev`).
>
> **Why this exists:** AC-108.4 (PRD **AC10**) asserts that the run-history screen shows a run's
> **derived** status, so that a run past its timeout threshold reads `timed_out` **even when the
> `pg_cron` reaper has not yet materialized it**. This is the two-layer design from
> `technical-guidelines.md` §3 observed from the UI: `v_runs.effective_status` (layer 2) tells the
> immediate truth while the reaper (layer 1) is behind. Proving it requires pausing the reaper and
> observing a stale row — a manipulation that cannot be automated end-to-end from a unit/component
> test, so it is a manual procedure backed by a Layer 2.5 test (see the closing note).

| Field             | Value                                                                                    |
| ----------------- | ---------------------------------------------------------------------------------------- |
| Issue             | [#121](https://github.com/llipe/dev-tasks-agent-fleet/issues/121)                        |
| PR                | [#140](https://github.com/llipe/dev-tasks-agent-fleet/pull/140)                          |
| Branch            | `story/S-108-run-history`                                                                 |
| Acceptance        | AC-108.4 / PRD **AC10**                                                                   |
| Schema reference  | `supabase/migrations/20260902200101_initial_schema.sql` (`v_runs`, `reap_stale_runs()`) |
| Environment       | **Local Supabase stack only** — never the hosted project                                 |

---

## Why the local stack, not the hosted project

Pausing the reaper on the **hosted** project would leave every genuinely stale production run
unreaped for the duration of the test, and the hosted project holds real Phase 1 run data. The
verification uses a **synthetic** run with a small threshold against the **local** stack, so the
mechanism is proven in seconds with zero blast radius. Do **not** run any step below against the
hosted database.

---

## The two-layer design under test

| Layer               | Mechanism                                                                                              | Timing         |
| ------------------- | ------------------------------------------------------------------------------------------------------ | -------------- |
| **1 — materialize** | `pg_cron` runs `reap_stale_runs()` every minute; writes the terminal `status` + explanatory event      | up to 60s late |
| **2 — read time**   | `v_runs.effective_status` computes `timed_out`/`failed_to_start` on read from the per-run snapshot      | instant        |

AC10 is specifically about **layer 2 with layer 1 disabled**: the screen must read `timed_out` from
`effective_status` before (or without) the reaper ever running. The panel's `lib/domain/status.ts`
mirrors the `v_runs` `case` expression, and S-108's row shaper routes every displayed status through
it (`effectiveStatus`), so the row and the view agree by construction.

---

## Prerequisites

- [ ] Local stack up: `supabase start` then `supabase db reset` (applies the migration + seed).
- [ ] Panel running: `pnpm --filter panel dev`, reachable at `http://localhost:3000`.
- [ ] The seeded `dependency-update` agent exists and is enabled.
- [ ] You have the local Postgres connection (see `panel/tests/integration/db.ts`:
      `127.0.0.1:54322`, user/password `postgres`).

---

## Procedure

Run each SQL block in the **local** database (e.g. `psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres"`
or the Supabase Studio SQL editor pointed at the local stack).

### 1. Pause the reaper

```sql
-- Disable the per-minute reaper so layer 1 cannot materialize the run.
select cron.unschedule('reap-stale-runs');
```

Confirm it is gone:

```sql
select jobname from cron.job where jobname = 'reap-stale-runs';  -- expect zero rows
```

### 2. Insert a synthetic `running` run already past its threshold

The run's window is `max_runtime_seconds + grace_seconds`. Using small values makes it stale
immediately. `started_at` is set well before `now() - window`.

```sql
-- Capture the agent + a repository for a realistic row.
with a as (select id from agents where slug = 'dependency-update'),
     r as (select id from repositories order by full_name limit 1)
insert into runs (
  id, agent_id, repository_id, agent_version, status,
  queued_at, started_at, finished_at,
  max_runtime_seconds, grace_seconds, start_timeout_seconds,
  params
)
select
  gen_random_uuid(), a.id, r.id, '0.1.0', 'running',
  now() - interval '30 min',   -- queued_at
  now() - interval '25 min',   -- started_at (25 min ago)
  null,                        -- never finished
  60, 30, 300,                 -- 60s + 30s = 90s window → long past 25 min
  jsonb_build_object('branch', 'main')
from a, r
returning id, status, started_at;
```

Note the returned `id` — call it `$RUN_ID`.

### 3. Confirm the raw row is still `running` but the view derives `timed_out`

```sql
-- Layer-1 (raw) truth: still running, because the reaper is paused.
select status from runs where id = '$RUN_ID';                  -- expect: running

-- Layer-2 (read-time) truth: the view derives timed_out.
select status, effective_status from v_runs where id = '$RUN_ID';
-- expect: status = running, effective_status = timed_out
```

This divergence is the whole point: the reaper has **not** run (raw `status` is still `running`),
yet the view already reports `timed_out`.

### 4. Load the run-history page and confirm the row reads `timed_out`

1. Open `http://localhost:3000/agents/dependency-update`.
2. Find the synthetic run's row (top of the list — newest-first).
3. **Confirm the status pill reads `timed_out`, not `running`.**

The page reads through `v_runs` and the row shaper derives status through `effectiveStatus`, so the
UI must match step 3's `effective_status`.

### 5. Restore the reaper

```sql
-- Re-enable the per-minute reaper.
select cron.schedule('reap-stale-runs', '* * * * *', $$select reap_stale_runs()$$);
```

Confirm it is back:

```sql
select jobname, schedule from cron.job where jobname = 'reap-stale-runs';
-- expect one row: reap-stale-runs | * * * * *
```

### 6. Clean up the synthetic row

```sql
delete from run_events where run_id = '$RUN_ID';
delete from run_steps  where run_id = '$RUN_ID';
delete from runs       where id     = '$RUN_ID';
```

---

## Evidence to record in the PR

Paste into PR #140:

- The `select ... from v_runs` output from step 3 showing `status = running` and
  `effective_status = timed_out`.
- The observed UI state from step 4 (the pill reading `timed_out`).
- Confirmation from step 5 that `reap-stale-runs` is scheduled again (`* * * * *`).

---

## Closing note — why a Layer 2.5 test backs this (test-plan G5)

A manual runbook verifies AC10 once and then rots: nothing re-runs it, so a future regression that
made the row read the raw `status` would pass CI. To keep the guarantee live, S-108 adds a Layer 2.5
integration test (`panel/tests/integration/runs-by-agent.test.ts`) that inserts the same synthetic
stale `running` row against the local stack and asserts the run-history read path presents
`timed_out`. That test is the standing guard; this runbook is the one-time human confirmation that
the guard corresponds to what an operator actually sees in the browser.


---

## Recorded evidence (2026-09-04, local stack)

The SQL half of the procedure was executed against the local Supabase stack
(`127.0.0.1:54322`) via the `pg` client. Observed:

- **Step 0** — reaper scheduled before the test: `reap-stale-runs | * * * * *`.
- **Step 1** — after `cron.unschedule('reap-stale-runs')`: zero rows (paused).
- **Step 2** — synthetic run inserted, `status = running`, `started_at` 25 min in the past,
  window `60 + 30 = 90s`.
- **Step 3 (the AC10 assertion)** — with the reaper paused:

  | source              | value       |
  | ------------------- | ----------- |
  | `runs.status`       | `running`   |
  | `v_runs.status`     | `running`   |
  | `v_runs.effective_status` | `timed_out` |

  The raw row is still `running` (the reaper never ran), yet the view already derives `timed_out`
  from the per-run snapshot — layer 2 telling the immediate truth while layer 1 is disabled.

- **Step 5** — reaper restored: `reap-stale-runs | * * * * *`.
- **Step 6** — synthetic `run_events` / `run_steps` / `runs` rows deleted.

The **UI half** (loading `/agents/dependency-update` and confirming the pill reads `timed_out`) is
covered by the manual UI verification (task 3.17). The panel reads through `v_runs` and derives the
displayed status with `effectiveStatus` (the pinned mirror of `v_runs.effective_status`), so the
pill matches the `effective_status` observed in step 3 by construction. The standing Layer 2.5 test
`panel/tests/integration/runs-by-agent.test.ts` re-asserts step 3's property on every run.
