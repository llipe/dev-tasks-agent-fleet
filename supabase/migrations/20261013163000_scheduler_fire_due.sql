-- =====================================================================
-- Agent Fleet -- Phase 4 Agent Scheduler: fire_due_schedules() due-tick
-- Story S-154 (#266). A single pg_cron job (mirroring the reaper) that finds
-- due schedules, enforces the concurrency cap (G4), dispatches each via pg_net
-- to the panel fire endpoint (SD-T4), and advances the due cursor with no
-- catch-up (G2). Guardrail overlap/open-PR checks are added in S-155/S-156.
-- =====================================================================

-- ---------------------------------------------------------------------
-- scheduler.in_flight_scheduled_runs()  -- the G4 count. Counts non-terminal
--   runs that were triggered by a schedule. A stale 'running' counts for at
--   most one reaper cycle (safe over-count, SD-G4) -- we do not re-derive
--   effective_status here because the reaper converges it within a tick and an
--   over-count only makes the cap more conservative, never less.
-- ---------------------------------------------------------------------
create or replace function scheduler.in_flight_scheduled_runs()
returns integer
language sql
stable
as $$
  select count(*)::integer
    from runs
   where trigger_type = 'schedule'
     and status in ('queued', 'running')
$$;

-- ---------------------------------------------------------------------
-- scheduler.fire_due_schedules()  -- the minute tick.
--   Returns the number of schedules DISPATCHED this tick (for diagnostics /
--   cron.job_run_details). Over-cap due schedules are marked skipped with a
--   recorded reason and left for the next tick (no backlog). Each dispatched
--   schedule's next_run_at is advanced to the next future occurrence from now()
--   (G2 no-catch-up: a missed slot is never replayed).
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
  v_run        record;
  v_next       timestamptz;
begin
  v_budget := greatest(v_cap - v_inflight, 0);

  -- Configuration guard: without a base URL or secret the tick cannot safely
  -- dispatch. Record the condition on due rows and return rather than firing
  -- blind (fail-closed).
  if v_base_url is null or v_base_url = '' or v_secret is null or v_secret = '' then
    update schedules
       set last_skipped_reason = 'config_missing', last_skipped_at = now()
     where is_enabled and state = 'active' and next_run_at is not null and next_run_at <= now();
    return 0;
  end if;

  for v_run in
    select id
      from schedules
     where is_enabled
       and state = 'active'
       and next_run_at is not null
       and next_run_at <= now()
     order by next_run_at asc
     for update skip locked
  loop
    if v_dispatched >= v_budget then
      -- Over the cap this tick: skip with a recorded reason, re-evaluate next
      -- tick. next_run_at is NOT advanced, so it stays due.
      update schedules
         set last_skipped_reason = 'concurrency_cap', last_skipped_at = now()
       where id = v_run.id;
      continue;
    end if;

    -- Dispatch: fire-and-forget POST to the panel fire endpoint (SD-T4). The
    -- panel performs the full invoke; we only record the dispatch + advance the
    -- cursor. pg_net enqueues asynchronously (does not block the tick).
    perform net.http_post(
      url     := v_base_url || '/api/internal/schedules/' || v_run.id::text || '/fire',
      headers := jsonb_build_object('Content-Type', 'application/json',
                                    'X-Scheduler-Secret', v_secret),
      body    := '{}'::jsonb,
      timeout_milliseconds := 5000
    );

    -- Advance the cursor to the next future occurrence from NOW (G2: no
    -- catch-up of a missed slot).
    v_next := scheduler.compute_next_run_at(v_run.id, now());
    update schedules
       set last_fired_at = now(),
           next_run_at   = v_next,
           last_skipped_reason = null,
           last_skipped_at     = null
     where id = v_run.id;

    v_dispatched := v_dispatched + 1;
  end loop;

  return v_dispatched;
end $$;

-- ---------------------------------------------------------------------
-- Schedule the tick every minute, mirroring the reaper (ADR-004). Requires
-- pg_cron (enabled in S-151 / already on from the reaper). Idempotent via
-- unschedule-if-exists.
-- ---------------------------------------------------------------------
do $$
begin
  perform cron.unschedule('fire-due-schedules')
   where exists (select 1 from cron.job where jobname = 'fire-due-schedules');
exception when others then
  -- cron may be unavailable in a bare test DB; the schedule below is the point.
  null;
end $$;

select cron.schedule('fire-due-schedules', '* * * * *', $$select scheduler.fire_due_schedules()$$);
