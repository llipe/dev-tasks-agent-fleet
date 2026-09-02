-- =====================================================================
-- S-103 (issue #116) — English-only SQL surface: reap_stale_runs()
--
-- Behavior-preserving `create or replace` of the reaper. Only the
-- operator-facing TEXT changes (the two run_events messages and the two
-- runs.error_message strings) from Spanish to English. Everything else is
-- byte-identical to the baseline body in
-- 20260902200101_initial_schema.sql:
--   - status transitions (timed_out / failed_to_start)
--   - error_code values (RUNTIME_TIMEOUT / START_TIMEOUT)
--   - seq = coalesce(max(seq),0)+1
--   - data.reaped_by / data.reason
--   - the issue #99 open-run_steps closure on BOTH branches
--   - security definer, search_path = public, for update skip locked
--
-- Reversible: re-apply the prior (Spanish) body from the baseline migration.
-- The prior body is reproduced verbatim in the PR description for rollback.
-- =====================================================================

create or replace function reap_stale_runs() returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count integer := 0;
  v_run   record;
begin
  -- 1. running that exceeded max_runtime + grace
  for v_run in
    select id, max_runtime_seconds, grace_seconds
    from runs
    where status = 'running'
      and started_at is not null
      and now() > started_at + make_interval(secs => max_runtime_seconds + grace_seconds)
    for update skip locked
  loop
    update runs
       set status = 'timed_out',
           finished_at = now(),
           error_code = 'RUNTIME_TIMEOUT',
           error_message = format(
             'No completion report after %s s (max_runtime %s + grace %s).',
             v_run.max_runtime_seconds + v_run.grace_seconds,
             v_run.max_runtime_seconds, v_run.grace_seconds)
     where id = v_run.id;

    insert into run_events (run_id, seq, level, message, data)
    select v_run.id,
           coalesce((select max(seq) from run_events where run_id = v_run.id), 0) + 1,
           'error',
           'The system marked this run as timed_out: the agent never reported completion.',
           jsonb_build_object('reaped_by', 'reap_stale_runs', 'reason', 'RUNTIME_TIMEOUT');

    -- Close any steps left open, mirroring the agent's own failure path
    -- (technical-guidelines §8). Does not assume steps exist.
    update run_steps
       set status = 'failed',
           finished_at = now(),
           error_message = 'Closed by reap_stale_runs: the run was marked timed_out (RUNTIME_TIMEOUT).'
     where run_id = v_run.id
       and status in ('running', 'pending');

    v_count := v_count + 1;
  end loop;

  -- 2. queued that never started
  for v_run in
    select id, start_timeout_seconds
    from runs
    where status = 'queued'
      and now() > queued_at + make_interval(secs => start_timeout_seconds)
    for update skip locked
  loop
    update runs
       set status = 'failed_to_start',
           finished_at = now(),
           error_code = 'START_TIMEOUT',
           error_message = format('The agent did not report a start after %s s.', v_run.start_timeout_seconds)
     where id = v_run.id;

    insert into run_events (run_id, seq, level, message, data)
    select v_run.id,
           coalesce((select max(seq) from run_events where run_id = v_run.id), 0) + 1,
           'error',
           'The invocation never reported a start. Check the runtime in AgentCore.',
           jsonb_build_object('reaped_by', 'reap_stale_runs', 'reason', 'START_TIMEOUT');

    -- A failed_to_start run normally has no steps, but we do not assume so:
    -- the update is a safe 0-row no-op when there are no open steps.
    update run_steps
       set status = 'failed',
           finished_at = now(),
           error_message = 'Closed by reap_stale_runs: the invocation was marked failed_to_start (START_TIMEOUT).'
     where run_id = v_run.id
       and status in ('running', 'pending');

    v_count := v_count + 1;
  end loop;

  return v_count;
end $$;
