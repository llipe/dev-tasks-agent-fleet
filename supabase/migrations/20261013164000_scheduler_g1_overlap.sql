-- =====================================================================
-- Agent Fleet -- Phase 4 Agent Scheduler: G1 overlap suppression
-- Story S-155 (#267). A schedule must not fire while a PRIOR run for the same
-- (agent, repository) is still non-terminal -- so a long-running agent (e.g.
-- security-analyst's 90-min scan) is never double-fired. Evaluated by
-- effective_status (not raw status) so a stale 'running' the reaper will convert
-- does not block forever (SD-G0/SD-G1). The block is sticky in state='blocked'
-- with block_reason='overlap' and AUTO-CLEARS on the next tick once the run is
-- terminal.
-- =====================================================================

-- ---------------------------------------------------------------------
-- scheduler.has_active_run(agent_id, repository_id)
--   True iff a run for this (agent, repository) is non-terminal by
--   effective_status. Reads v_runs so a stale 'running' past its reaper
--   threshold reads as timed_out and does NOT count as active (SD-G0).
--   repository_id may be null (no-repository agents) -- matched with
--   null-safe equality.
-- ---------------------------------------------------------------------
create or replace function scheduler.has_active_run(p_agent_id uuid, p_repository_id uuid)
returns boolean
language sql
stable
as $$
  select exists (
    select 1
      from v_runs
     where agent_id = p_agent_id
       and repository_id is not distinct from p_repository_id
       and effective_status in ('queued', 'running')
  )
$$;

-- ---------------------------------------------------------------------
-- Re-define fire_due_schedules() with the G1 overlap check inserted before
-- dispatch. A due schedule whose (agent, repository) has an active run is set
-- state='blocked'/block_reason='overlap' and skipped (next_run_at NOT advanced,
-- so it re-evaluates). A previously-overlap-blocked schedule whose run has since
-- gone terminal is cleared back to active and allowed to fire this tick.
-- ---------------------------------------------------------------------
create or replace function scheduler.fire_due_schedules()
returns integer
language plpgsql
security definer
set search_path = public, scheduler
as $$
declare
  v_cap        integer := scheduler.max_inflight();
  v_inflight   integer := scheduler.in_flight_scheduled_runs();
  v_budget     integer;
  v_base_url   text    := scheduler.get_setting('panel_base_url');
  v_secret     text    := scheduler.read_secret('scheduler_trigger_secret');
  v_dispatched integer := 0;
  v_sched      record;
  v_next       timestamptz;
begin
  v_budget := greatest(v_cap - v_inflight, 0);

  if v_base_url is null or v_base_url = '' or v_secret is null or v_secret = '' then
    update schedules
       set last_skipped_reason = 'config_missing', last_skipped_at = now()
     where is_enabled and state = 'active' and next_run_at is not null and next_run_at <= now();
    return 0;
  end if;

  -- G1 auto-clear: an overlap-blocked schedule whose (agent, repository) no
  -- longer has an active run returns to 'active' so it can be considered below.
  update schedules s
     set state = 'active', block_reason = null, blocked_at = null
   where s.state = 'blocked'
     and s.block_reason = 'overlap'
     and not scheduler.has_active_run(s.agent_id, s.repository_id);

  for v_sched in
    select id, agent_id, repository_id
      from schedules
     where is_enabled
       and state = 'active'
       and next_run_at is not null
       and next_run_at <= now()
     order by next_run_at asc
     for update skip locked
  loop
    -- G1 overlap: block (do not fire) while a prior run is non-terminal.
    if scheduler.has_active_run(v_sched.agent_id, v_sched.repository_id) then
      update schedules
         set state = 'blocked', block_reason = 'overlap', blocked_at = now()
       where id = v_sched.id;
      continue;
    end if;

    if v_dispatched >= v_budget then
      update schedules
         set last_skipped_reason = 'concurrency_cap', last_skipped_at = now()
       where id = v_sched.id;
      continue;
    end if;

    perform net.http_post(
      url     := v_base_url || '/api/internal/schedules/' || v_sched.id::text || '/fire',
      headers := jsonb_build_object('Content-Type', 'application/json',
                                    'X-Scheduler-Secret', v_secret),
      body    := '{}'::jsonb,
      timeout_milliseconds := 5000
    );

    v_next := scheduler.compute_next_run_at(v_sched.id, now());
    update schedules
       set last_fired_at = now(),
           next_run_at   = v_next,
           last_skipped_reason = null,
           last_skipped_at     = null
     where id = v_sched.id;

    v_dispatched := v_dispatched + 1;
  end loop;

  return v_dispatched;
end $$;
