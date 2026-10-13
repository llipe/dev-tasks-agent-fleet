-- =====================================================================
-- Agent Fleet -- Phase 4 Agent Scheduler: G3 circuit breaker (auto-pause)
-- Story S-157 (#269). After N consecutive FAILED firings a schedule pauses
-- itself and records exactly one schedule_auto_paused notification (AC6). The
-- increment + threshold trip + notification must be ATOMIC, so this is a single
-- plpgsql function rather than multiple round-trips (which could race and
-- double-notify). Lives in `public` (prefixed) so PostgREST exposes exactly it
-- to the fire endpoint's service-role .rpc() call, without exposing the whole
-- `scheduler` schema.
--
-- A successful firing resets the counter (handled by recordScheduleFired in the
-- fire endpoint). Reaper-materialized failures feed this same function from the
-- notify-sweep (S-158).
-- =====================================================================

create or replace function public.scheduler_record_fire_failure(
  p_schedule_id uuid,
  p_error       text
) returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count      integer;
  v_threshold  integer;
  v_agent_id   uuid;
  v_repo_id    uuid;
  v_name       text;
  v_agent_name text;
  v_repo_name  text;
begin
  -- Increment atomically and capture the new count + the context we need for a
  -- possible notification, all under the row lock.
  update schedules
     set consecutive_failures = consecutive_failures + 1,
         last_fire_error      = p_error
   where id = p_schedule_id
   returning consecutive_failures, auto_pause_threshold, agent_id, repository_id, name
        into v_count, v_threshold, v_agent_id, v_repo_id, v_name;

  if not found then
    return; -- schedule vanished; nothing to do
  end if;

  -- Trip the breaker exactly once: only when we CROSS the threshold (==), not
  -- on every subsequent failure, so a schedule that is already paused does not
  -- re-notify. (A paused schedule is not fired, so in practice we only reach
  -- here again if it was resumed.)
  if v_count = v_threshold then
    update schedules
       set state = 'paused',
           block_reason = 'auto_paused:consecutive_failures',
           blocked_at = now()
     where id = p_schedule_id;

    select a.name, r.full_name
      into v_agent_name, v_repo_name
      from agents a
      left join repositories r on r.id = v_repo_id
     where a.id = v_agent_id;

    insert into notifications (kind, schedule_id, agent_id, repository_id, title, detail, data)
    values (
      'schedule_auto_paused',
      p_schedule_id,
      v_agent_id,
      v_repo_id,
      format('Schedule auto-paused after %s consecutive failures', v_threshold),
      format('%s%s · last error %s',
             coalesce(v_agent_name, 'agent'),
             case when v_repo_name is not null then ' · ' || v_repo_name else '' end,
             p_error),
      jsonb_build_object('consecutive_failures', v_count, 'threshold', v_threshold)
    );
  end if;
end $$;
