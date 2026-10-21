-- =====================================================================
-- Agent Fleet -- Webhook Triggers Phase 1: guardrails for webhook runs
-- Story S-173 (#318), D-W10 / FR17.
--
-- The schedule guardrails live in the SQL due-tick (fire_due_schedules), with
-- block/clear state on the `schedules` row. Webhooks have no such row, so they
-- get a stateless decision that reuses the scheduler's own predicates:
--   G1 overlap  -- scheduler.has_active_run (effective_status, SD-G0)
--   G5 open PR  -- scheduler.open_pr_block_run, with no manual clear; a later
--                  manual run supersedes the block (G5-a)
--   G4 cap      -- scheduler.max_inflight() over in-flight schedule AND
--                  webhook runs: ONE cap shared by both automated triggers
-- G2 (no catch-up) has no meaning for edge-triggered webhooks.
-- G3 is per rule: webhook_record_rule_result() counts consecutive fire-time
-- failures and, at auto_disable_threshold, disables the rule and writes one
-- `webhook_rule_auto_disabled` notification.
--
-- Behavior change for the scheduler: in_flight_scheduled_runs() now also
-- counts webhook runs, so in-flight webhook runs consume the shared cap and
-- can cause a scheduled run to be skipped with `concurrency_cap`.
--
-- Rollback:
--   restore in_flight_scheduled_runs() to `trigger_type = 'schedule'` only;
--   drop function public.webhook_guardrail(uuid, uuid);
--   drop function public.webhook_record_rule_result(uuid, boolean, text);
--   alter table notifications drop column webhook_rule_id;
--   The enum value 'webhook_rule_auto_disabled' cannot be dropped; leave it.
-- =====================================================================

alter type notification_kind add value if not exists 'webhook_rule_auto_disabled';

alter table notifications
  add column if not exists webhook_rule_id uuid references webhook_rules(id) on delete set null;
create index if not exists idx_notifications_webhook_rule on notifications (webhook_rule_id)
  where webhook_rule_id is not null;

-- G4: one cap across both automated triggers (FR17). Manual runs never count.
create or replace function scheduler.in_flight_scheduled_runs()
returns integer
language sql
stable
as $$
  select count(*)::integer
    from runs
   where trigger_type in ('schedule', 'webhook')
     and status in ('queued', 'running')
$$;

-- The webhook guardrail decision. Returns null to allow, else the skip reason.
create or replace function public.webhook_guardrail(p_agent_id uuid, p_repository_id uuid)
returns text
language plpgsql
stable
security definer
set search_path = public, scheduler, pg_temp
as $$
begin
  if scheduler.has_active_run(p_agent_id, p_repository_id) then
    return 'overlap';
  end if;
  if scheduler.open_pr_block_run(p_agent_id, p_repository_id, null) is not null then
    return 'open_pr';
  end if;
  if scheduler.in_flight_scheduled_runs() >= scheduler.max_inflight() then
    return 'concurrency_cap';
  end if;
  return null;
end $$;

-- G3 per rule. Atomic under the row lock so concurrent results can't
-- double-notify, mirroring scheduler_record_fire_failure (S-157).
create or replace function public.webhook_record_rule_result(
  p_rule_id uuid, p_ok boolean, p_error text
) returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_count     integer;
  v_threshold integer;
  v_enabled   boolean;
  v_agent_id  uuid;
  v_rule_name text;
  v_ep_name   text;
begin
  if p_ok then
    update webhook_rules set consecutive_failures = 0 where id = p_rule_id;
    return;
  end if;

  update webhook_rules
     set consecutive_failures = consecutive_failures + 1
   where id = p_rule_id
   returning consecutive_failures, auto_disable_threshold, is_enabled, agent_id, name
        into v_count, v_threshold, v_enabled, v_agent_id, v_rule_name;

  if v_count is null then
    return; -- rule deleted meanwhile
  end if;

  if v_enabled and v_count >= v_threshold then
    update webhook_rules set is_enabled = false where id = p_rule_id;
    select e.name into v_ep_name
      from webhook_rules r join webhook_endpoints e on e.id = r.endpoint_id
     where r.id = p_rule_id;
    insert into notifications (kind, webhook_rule_id, agent_id, title, detail)
    values (
      'webhook_rule_auto_disabled',
      p_rule_id,
      v_agent_id,
      format('Webhook rule disabled after %s consecutive failures (%s%s)',
             v_count,
             coalesce(nullif(v_ep_name, ''), 'endpoint'),
             case when coalesce(v_rule_name, '') <> '' then ' / ' || v_rule_name else '' end),
      left(coalesce(p_error, ''), 500)
    );
  end if;
end $$;

revoke execute on function public.webhook_guardrail(uuid, uuid) from public, anon, authenticated;
revoke execute on function public.webhook_record_rule_result(uuid, boolean, text) from public, anon, authenticated;
grant  execute on function public.webhook_guardrail(uuid, uuid) to service_role;
grant  execute on function public.webhook_record_rule_result(uuid, boolean, text) to service_role;
