-- =====================================================================
-- Agent Fleet -- Webhook Triggers Phase 1: notify-sweep covers webhook runs
-- Story S-174 (#319), D-W11 / FR18, and issue #302.
--
-- scheduler.sweep_schedule_notifications() now handles every AUTOMATED run:
--   trigger_type 'schedule' -> triggered_by 'schedule:<schedule_id>'
--   trigger_type 'webhook'  -> triggered_by 'webhook:<endpoint_id>:<rule_id>'
-- and records the same kinds for both (run_failed, pr_opened, opt-in
-- run_succeeded), exactly once per (run_id, kind) as before.
--
-- #302 (decided 2026-10-20: left join): a run whose schedule or rule was
-- deleted still gets run_failed / pr_opened, with a null schedule_id /
-- webhook_rule_id (both FKs are `on delete set null`). Its success stays
-- silent: with the trigger gone there is no notify_on_success to read.
--
-- Per-trigger side effects stay where they were:
--   schedule: run_failed feeds G3 (scheduler_record_fire_failure) and
--             pr_opened arms the G5 block on the schedule row. Both are
--             skipped for an orphaned run (no schedule to update).
--   webhook:  none. Webhook G3 counts start failures at fire time (S-173) and
--             webhook G5 is a stateless check, so the sweep doesn't touch
--             webhook_rules.
--
-- Live note: when this ships, the first sweep tick also notifies orphaned
-- scheduled runs that never got one. Checked read-only on 2026-10-20:
-- 1 failed run, 0 PRs.
--
-- Rollback: re-apply the function body from
-- 20261013167000_scheduler_notify_sweep.sql; drop functions
-- scheduler.webhook_rule_id_of(text) and
-- scheduler.automated_run_title(trigger_type, text, text, text); alter table
-- webhook_rules drop column notify_on_success.
-- =====================================================================

alter table webhook_rules
  add column if not exists notify_on_success boolean not null default false;

-- 'webhook:<endpoint_uuid>:<rule_uuid>' -> rule uuid; anything else -> null.
create or replace function scheduler.webhook_rule_id_of(p_triggered_by text)
returns uuid
language sql
immutable
as $$
  select case
           when p_triggered_by ~* '^webhook:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
             then substring(p_triggered_by from 46)::uuid
           else null
         end
$$;

-- Notification title per trigger. Scheduled-run titles are unchanged from
-- S-158; webhook titles name the endpoint and rule when they still exist.
-- p_event: a run status (failed / failed_to_start / timed_out / succeeded)
-- or 'pr_opened'.
create or replace function scheduler.automated_run_title(
  p_trigger_type trigger_type, p_event text, p_endpoint_name text, p_rule_name text
) returns text
language sql
immutable
as $$
  select case
    when p_trigger_type = 'webhook' then
      case p_event when 'pr_opened' then 'Webhook run opened a pull request'
                   else 'Webhook run ' || p_event end
      || case
           when coalesce(p_endpoint_name, '') = '' then ''
           else ' · ' || p_endpoint_name
                || case when coalesce(p_rule_name, '') = '' then '' else ' / ' || p_rule_name end
         end
    else
      case p_event when 'pr_opened' then 'Scheduled run opened a pull request'
                   else 'Scheduled run ' || p_event end
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
  -- 1. run_failed -- automated runs that newly reached a terminal failure.
  -- -------------------------------------------------------------------
  for v_rec in
    select vr.id                   as run_id,
           vr.trigger_type,
           s.id                    as schedule_id,
           w.id                    as webhook_rule_id,
           e.name                  as endpoint_name,
           w.name                  as rule_name,
           vr.agent_id,
           vr.repository_id,
           vr.agent_name,
           vr.repository_full_name,
           vr.effective_status,
           vr.error_code
      from v_runs vr
      left join schedules s         on vr.trigger_type = 'schedule'
                                   and s.id = scheduler.schedule_id_of(vr.triggered_by)
      left join webhook_rules w     on vr.trigger_type = 'webhook'
                                   and w.id = scheduler.webhook_rule_id_of(vr.triggered_by)
      left join webhook_endpoints e on e.id = w.endpoint_id
     where vr.trigger_type in ('schedule', 'webhook')
       and vr.effective_status in ('failed', 'failed_to_start', 'timed_out')
       and not exists (
         select 1 from notifications n
          where n.run_id = vr.id and n.kind = 'run_failed'
       )
  loop
    insert into notifications (kind, schedule_id, webhook_rule_id, agent_id, repository_id, run_id, title, detail, data)
    values (
      'run_failed',
      v_rec.schedule_id,
      v_rec.webhook_rule_id,
      v_rec.agent_id,
      v_rec.repository_id,
      v_rec.run_id,
      scheduler.automated_run_title(v_rec.trigger_type, v_rec.effective_status::text,
                                    v_rec.endpoint_name, v_rec.rule_name),
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
      -- Schedule G3, gated on the insert so a re-run never double-counts
      -- (SD-G3). Skipped for webhook runs and for orphaned scheduled runs.
      if v_rec.schedule_id is not null then
        perform public.scheduler_record_fire_failure(
          v_rec.schedule_id,
          coalesce(v_rec.error_code, v_rec.effective_status::text)
        );
      end if;
    end if;
  end loop;

  -- -------------------------------------------------------------------
  -- 2. pr_opened -- an automated run whose pull_request artifact appeared
  --    after the fire response (SD-N3). Arms G5 on a live schedule only.
  -- -------------------------------------------------------------------
  for v_rec in
    select distinct on (r.id)
           r.id            as run_id,
           r.trigger_type,
           s.id            as schedule_id,
           w.id            as webhook_rule_id,
           e.name          as endpoint_name,
           w.name          as rule_name,
           r.agent_id,
           r.repository_id,
           ag.name         as agent_name,
           rp.full_name    as repository_full_name,
           art.url         as pr_url,
           art.metadata    as pr_metadata
      from runs r
      join run_artifacts art on art.run_id = r.id and art.type = 'pull_request'
      join agents ag on ag.id = r.agent_id
      left join repositories rp     on rp.id = r.repository_id
      left join schedules s         on r.trigger_type = 'schedule'
                                   and s.id = scheduler.schedule_id_of(r.triggered_by)
      left join webhook_rules w     on r.trigger_type = 'webhook'
                                   and w.id = scheduler.webhook_rule_id_of(r.triggered_by)
      left join webhook_endpoints e on e.id = w.endpoint_id
     where r.trigger_type in ('schedule', 'webhook')
       and not exists (
         select 1 from notifications n
          where n.run_id = r.id and n.kind = 'pr_opened'
       )
     order by r.id, art.created_at asc
  loop
    insert into notifications (kind, schedule_id, webhook_rule_id, agent_id, repository_id, run_id, title, detail, data)
    values (
      'pr_opened',
      v_rec.schedule_id,
      v_rec.webhook_rule_id,
      v_rec.agent_id,
      v_rec.repository_id,
      v_rec.run_id,
      scheduler.automated_run_title(v_rec.trigger_type, 'pr_opened',
                                    v_rec.endpoint_name, v_rec.rule_name),
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
      if v_rec.schedule_id is not null then
        update schedules s
           set state = 'blocked',
               block_reason = 'open_pr',
               blocked_at = now(),
               pr_block_run_id = v_rec.run_id
         where s.id = v_rec.schedule_id
           and s.state = 'active';
      end if;
    end if;
  end loop;

  -- -------------------------------------------------------------------
  -- 3. run_succeeded -- opt-in only, read from the live schedule or rule.
  --    An orphaned run has nothing to opt in, so it stays silent.
  -- -------------------------------------------------------------------
  for v_rec in
    select vr.id                   as run_id,
           vr.trigger_type,
           s.id                    as schedule_id,
           w.id                    as webhook_rule_id,
           e.name                  as endpoint_name,
           w.name                  as rule_name,
           vr.agent_id,
           vr.repository_id,
           vr.agent_name,
           vr.repository_full_name
      from v_runs vr
      left join schedules s         on vr.trigger_type = 'schedule'
                                   and s.id = scheduler.schedule_id_of(vr.triggered_by)
      left join webhook_rules w     on vr.trigger_type = 'webhook'
                                   and w.id = scheduler.webhook_rule_id_of(vr.triggered_by)
      left join webhook_endpoints e on e.id = w.endpoint_id
     where vr.trigger_type in ('schedule', 'webhook')
       and vr.effective_status = 'succeeded'
       and coalesce(s.notify_on_success, w.notify_on_success, false)
       and not exists (
         select 1 from notifications n
          where n.run_id = vr.id and n.kind = 'run_succeeded'
       )
  loop
    insert into notifications (kind, schedule_id, webhook_rule_id, agent_id, repository_id, run_id, title, detail, data)
    values (
      'run_succeeded',
      v_rec.schedule_id,
      v_rec.webhook_rule_id,
      v_rec.agent_id,
      v_rec.repository_id,
      v_rec.run_id,
      scheduler.automated_run_title(v_rec.trigger_type, 'succeeded',
                                    v_rec.endpoint_name, v_rec.rule_name),
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
