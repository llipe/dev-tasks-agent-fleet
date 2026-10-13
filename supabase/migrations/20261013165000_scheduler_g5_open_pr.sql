-- =====================================================================
-- Agent Fleet -- Phase 4 Agent Scheduler: G5 open-PR backoff (phased a+c)
-- Story S-156 (#268). A schedule must not keep firing while a PRIOR run of the
-- same (agent, repository) left a pull_request artifact that is still
-- unresolved -- so an unattended fix-mode schedule does not stack redundant PRs.
--
-- v1 "resolved" (no GitHub call -- FR-FF1 is the future auto-poll):
--   G5-c manual: pr_block_cleared_at >= the blocking PR's created_at
--   G5-a supersede: a later MANUAL run of the same (agent, repository) created
--                   after the blocking run exists
-- Precedence: G1 overlap (an active run) is evaluated first in the tick; this
-- adds the open-PR block for the terminal-but-unreviewed-PR case.
-- =====================================================================

-- ---------------------------------------------------------------------
-- scheduler.open_pr_block_run(agent, repo, cleared_at)
--   Returns the run_id of the most-recent run for this (agent, repository) that
--   produced a pull_request artifact that is STILL unresolved, or null if none.
--   Unresolved = the PR artifact's created_at is after `cleared_at` (manual
--   clear, G5-c) AND no later MANUAL run of the same (agent, repository) exists
--   (supersede, G5-a).
-- ---------------------------------------------------------------------
create or replace function scheduler.open_pr_block_run(
  p_agent_id uuid, p_repository_id uuid, p_cleared_at timestamptz
) returns uuid
language sql
stable
as $$
  with pr_runs as (
    select r.id as run_id, a.created_at as pr_at
      from runs r
      join run_artifacts a on a.run_id = r.id and a.type = 'pull_request'
     where r.agent_id = p_agent_id
       and r.repository_id is not distinct from p_repository_id
  ),
  latest as (
    select run_id, pr_at
      from pr_runs
     order by pr_at desc
     limit 1
  )
  select l.run_id
    from latest l
   where (p_cleared_at is null or l.pr_at > p_cleared_at)   -- G5-c: not manually cleared
     and not exists (                                        -- G5-a: not superseded by a later manual run
       select 1 from runs m
        where m.agent_id = p_agent_id
          and m.repository_id is not distinct from p_repository_id
          and m.trigger_type = 'manual'
          and m.created_at > l.pr_at
     )
$$;

-- ---------------------------------------------------------------------
-- Re-define fire_due_schedules() adding the G5 open-PR check AFTER the G1
-- overlap check and its auto-clear. The two share the unified blocked state
-- (SD-G6): G1 uses block_reason='overlap', G5 uses 'open_pr' + pr_block_run_id.
-- An open-PR block auto-clears here only when open_pr_block_run returns null
-- (manual clear via pr_block_cleared_at, or a superseding manual run).
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
  v_pr_run     uuid;
begin
  v_budget := greatest(v_cap - v_inflight, 0);

  if v_base_url is null or v_base_url = '' or v_secret is null or v_secret = '' then
    update schedules
       set last_skipped_reason = 'config_missing', last_skipped_at = now()
     where is_enabled and state = 'active' and next_run_at is not null and next_run_at <= now();
    return 0;
  end if;

  -- G1 auto-clear (overlap resolved).
  update schedules s
     set state = 'active', block_reason = null, blocked_at = null
   where s.state = 'blocked' and s.block_reason = 'overlap'
     and not scheduler.has_active_run(s.agent_id, s.repository_id);

  -- G5 auto-clear (open PR resolved: manually cleared or superseded).
  update schedules s
     set state = 'active', block_reason = null, blocked_at = null, pr_block_run_id = null
   where s.state = 'blocked' and s.block_reason = 'open_pr'
     and scheduler.open_pr_block_run(s.agent_id, s.repository_id, s.pr_block_cleared_at) is null;

  for v_sched in
    select id, agent_id, repository_id, pr_block_cleared_at
      from schedules
     where is_enabled and state = 'active'
       and next_run_at is not null and next_run_at <= now()
     order by next_run_at asc
     for update skip locked
  loop
    -- G1 overlap (active run) first.
    if scheduler.has_active_run(v_sched.agent_id, v_sched.repository_id) then
      update schedules
         set state = 'blocked', block_reason = 'overlap', blocked_at = now()
       where id = v_sched.id;
      continue;
    end if;

    -- G5 open-PR backoff.
    v_pr_run := scheduler.open_pr_block_run(
                  v_sched.agent_id, v_sched.repository_id, v_sched.pr_block_cleared_at);
    if v_pr_run is not null then
      update schedules
         set state = 'blocked', block_reason = 'open_pr', blocked_at = now(),
             pr_block_run_id = v_pr_run
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
       set last_fired_at = now(), next_run_at = v_next,
           last_skipped_reason = null, last_skipped_at = null
     where id = v_sched.id;

    v_dispatched := v_dispatched + 1;
  end loop;

  return v_dispatched;
end $$;
