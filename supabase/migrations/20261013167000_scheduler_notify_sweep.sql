-- =====================================================================
-- Agent Fleet -- Phase 4 Agent Scheduler: notify-sweep tick (S-158, #270)
--
-- A pg_cron tick (`* * * * *`) that records the notable scheduled-run events
-- the fire endpoint did NOT observe synchronously (SD-N1, second source):
--
--   * run_failed    -- a scheduled run that newly reached a terminal FAILURE
--                      (failed / failed_to_start / timed_out), INCLUDING the
--                      reaper-materialized ones the panel never saw (FR17/AC10).
--   * pr_opened     -- a scheduled run whose `pull_request` artifact appeared
--                      after the fire response (SD-N3/N4); also arms the G5
--                      open-PR block on the owning schedule (SD-G5).
--   * run_succeeded -- only for schedules that opted in (notify_on_success).
--
-- Exactly-once (SD-N2): every insert is `on conflict (run_id, kind) do nothing`
-- against uq_notifications_run_kind, so the sweep is idempotent and safe every
-- minute. The G3 counter increment for a reaper-materialized failure is GATED
-- on that run_failed insert actually happening (the insert is the once-per-run
-- latch), so re-running the sweep never double-counts a failure (SD-G3).
--
-- Uses v_runs.effective_status (not raw status) so a run the reaper will convert
-- within a tick is treated as terminal here too -- consistent with the
-- guardrail reads (S-154..S-156).
--
-- A scheduled run is linked to its schedule by `runs.triggered_by =
-- 'schedule:<uuid>'` (S-150, SD7) -- there is no runs.schedule_id column. The
-- helper below extracts that uuid; an inner join to `schedules` drops rows whose
-- schedule was deleted.
-- =====================================================================

-- scheduler.schedule_id_of(triggered_by) -> the schedule uuid, or null when the
-- run was not schedule-triggered / the suffix is not a valid uuid.
create or replace function scheduler.schedule_id_of(p_triggered_by text)
returns uuid
language sql
immutable
as $$
  select case
           when p_triggered_by like 'schedule:%'
                and substring(p_triggered_by from 10)
                    ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
             then substring(p_triggered_by from 10)::uuid
           else null
         end
$$;

create or replace function scheduler.sweep_schedule_notifications()
returns integer
language plpgsql
security definer
set search_path = public, scheduler
as $$
declare
  v_recorded integer := 0;
  v_rec      record;
  v_inserted boolean;
begin
  -- -------------------------------------------------------------------
  -- 1. run_failed -- scheduled runs that newly reached a terminal failure.
  --    One row per (run_id, 'run_failed'); for each NEW one we also feed the
  --    G3 circuit breaker exactly once (gated on the insert below).
  -- -------------------------------------------------------------------
  for v_rec in
    select vr.id            as run_id,
           s.id             as schedule_id,
           vr.agent_id,
           vr.repository_id,
           vr.agent_name,
           vr.repository_full_name,
           vr.effective_status,
           vr.error_code,
           vr.error_message
      from v_runs vr
      join schedules s on s.id = scheduler.schedule_id_of(vr.triggered_by)
     where vr.trigger_type = 'schedule'
       and vr.effective_status in ('failed', 'failed_to_start', 'timed_out')
       and not exists (
         select 1 from notifications n
          where n.run_id = vr.id and n.kind = 'run_failed'
       )
  loop
    insert into notifications (kind, schedule_id, agent_id, repository_id, run_id, title, detail, data)
    values (
      'run_failed',
      v_rec.schedule_id,
      v_rec.agent_id,
      v_rec.repository_id,
      v_rec.run_id,
      format('Scheduled run %s', v_rec.effective_status),
      format('%s%s%s',
             coalesce(v_rec.agent_name, 'agent'),
             case when v_rec.repository_full_name is not null
                  then ' · ' || v_rec.repository_full_name else '' end,
             case when v_rec.error_code is not null
                  then ' · ' || v_rec.error_code else '' end),
      jsonb_build_object('status', v_rec.effective_status, 'error_code', v_rec.error_code)
    )
    on conflict (run_id, kind) do nothing;

    get diagnostics v_inserted = row_count;
    if v_inserted then
      v_recorded := v_recorded + 1;
      -- Feed the G3 circuit breaker (increment + possible auto-pause). Gated on
      -- the insert succeeding, so a re-run never double-counts (SD-G3).
      perform public.scheduler_record_fire_failure(
        v_rec.schedule_id,
        coalesce(v_rec.error_code, v_rec.effective_status::text)
      );
    end if;
  end loop;

  -- -------------------------------------------------------------------
  -- 2. pr_opened -- a scheduled run whose pull_request artifact appeared after
  --    the fire response (SD-N3). Record the notification AND arm the G5 block
  --    on the owning schedule (SD-G5) so it stops stacking PRs.
  -- -------------------------------------------------------------------
  for v_rec in
    select distinct on (r.id)
           r.id            as run_id,
           s.id            as schedule_id,
           r.agent_id,
           r.repository_id,
           ag.name         as agent_name,
           rp.full_name    as repository_full_name,
           art.url         as pr_url,
           art.metadata    as pr_metadata
      from runs r
      join schedules s on s.id = scheduler.schedule_id_of(r.triggered_by)
      join run_artifacts art on art.run_id = r.id and art.type = 'pull_request'
      join agents ag on ag.id = r.agent_id
      left join repositories rp on rp.id = r.repository_id
     where r.trigger_type = 'schedule'
       and not exists (
         select 1 from notifications n
          where n.run_id = r.id and n.kind = 'pr_opened'
       )
     order by r.id, art.created_at asc
  loop
    insert into notifications (kind, schedule_id, agent_id, repository_id, run_id, title, detail, data)
    values (
      'pr_opened',
      v_rec.schedule_id,
      v_rec.agent_id,
      v_rec.repository_id,
      v_rec.run_id,
      'Scheduled run opened a pull request',
      format('%s%s%s',
             coalesce(v_rec.agent_name, 'agent'),
             case when v_rec.repository_full_name is not null
                  then ' · ' || v_rec.repository_full_name else '' end,
             case when v_rec.pr_url is not null
                  then ' · ' || v_rec.pr_url else '' end),
      jsonb_build_object('url', v_rec.pr_url) || coalesce(v_rec.pr_metadata, '{}'::jsonb)
    )
    on conflict (run_id, kind) do nothing;

    get diagnostics v_inserted = row_count;
    if v_inserted then
      v_recorded := v_recorded + 1;
      -- Arm the G5 open-PR block (SD-G5): only if the schedule is not already
      -- blocked for another reason, and this PR has not been manually cleared.
      update schedules s
         set state = 'blocked',
             block_reason = 'open_pr',
             blocked_at = now(),
             pr_block_run_id = v_rec.run_id
       where s.id = v_rec.schedule_id
         and s.state = 'active';
    end if;
  end loop;

  -- -------------------------------------------------------------------
  -- 3. run_succeeded -- opt-in only (notify_on_success). A scheduled run that
  --    reached 'succeeded' on a schedule that asked for success notifications.
  -- -------------------------------------------------------------------
  for v_rec in
    select vr.id         as run_id,
           s.id          as schedule_id,
           vr.agent_id,
           vr.repository_id,
           vr.agent_name,
           vr.repository_full_name
      from v_runs vr
      join schedules s on s.id = scheduler.schedule_id_of(vr.triggered_by)
     where vr.trigger_type = 'schedule'
       and vr.effective_status = 'succeeded'
       and s.notify_on_success
       and not exists (
         select 1 from notifications n
          where n.run_id = vr.id and n.kind = 'run_succeeded'
       )
  loop
    insert into notifications (kind, schedule_id, agent_id, repository_id, run_id, title, detail, data)
    values (
      'run_succeeded',
      v_rec.schedule_id,
      v_rec.agent_id,
      v_rec.repository_id,
      v_rec.run_id,
      'Scheduled run succeeded',
      format('%s%s',
             coalesce(v_rec.agent_name, 'agent'),
             case when v_rec.repository_full_name is not null
                  then ' · ' || v_rec.repository_full_name else '' end),
      '{}'::jsonb
    )
    on conflict (run_id, kind) do nothing;

    get diagnostics v_inserted = row_count;
    if v_inserted then
      v_recorded := v_recorded + 1;
    end if;
  end loop;

  return v_recorded;
end $$;

comment on function scheduler.sweep_schedule_notifications() is
  'Phase 4 notify-sweep (S-158): records run_failed / pr_opened / run_succeeded '
  'notifications for scheduled runs the fire endpoint did not observe (incl. '
  'reaper-materialized failures), idempotent via uq_notifications_run_kind. '
  'Feeds the G3 counter and arms the G5 block.';

-- ---------------------------------------------------------------------
-- Register the notify-sweep cron job (every minute), alongside
-- fire-due-schedules and reap-stale-runs. Idempotent: unschedule-if-present
-- then schedule, mirroring the fire-due migration.
-- ---------------------------------------------------------------------
do $$
begin
  if exists (select 1 from cron.job where jobname = 'scheduler-notify-sweep') then
    perform cron.unschedule('scheduler-notify-sweep');
  end if;
end $$;

select cron.schedule('scheduler-notify-sweep', '* * * * *', $$select scheduler.sweep_schedule_notifications()$$);
