-- =====================================================================
-- Agent Fleet -- Webhook Triggers Phase 1: rule editor RPCs
-- Story S-177 (#322), FR22, D-W7.
--
--   webhook_create_rule(endpoint, rule jsonb) -> uuid
--       Appends the rule at max(position)+1 while holding the endpoint row
--       lock, so two concurrent creates can't pick the same position.
--   webhook_reorder_rules(endpoint, ordered rule ids)
--       Renumbers every rule of the endpoint to 0..n-1 in ONE UPDATE. The
--       `(endpoint_id, position)` unique is DEFERRABLE, so it is checked at the
--       end of the statement, not row by row, and any permutation works. The id
--       list must be exactly the endpoint's rules (no missing, duplicate or
--       foreign ids); otherwise nothing changes.
--
-- The rule body is validated in the panel before it gets here
-- (lib/domain/webhook-rule-save.ts); the table CHECKs and the one-default
-- partial unique stay the final authority. Both functions are SECURITY
-- DEFINER and service_role-only.
--
-- Rollback: drop both functions. No data change.
-- =====================================================================

create or replace function public.webhook_create_rule(p_endpoint_id uuid, p_rule jsonb)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_id  uuid;
  v_pos integer;
begin
  perform 1 from webhook_endpoints where id = p_endpoint_id for update;
  if not found then
    raise exception 'unknown webhook endpoint' using errcode = '23503';
  end if;
  select coalesce(max(position) + 1, 0) into v_pos from webhook_rules where endpoint_id = p_endpoint_id;

  insert into webhook_rules (
    endpoint_id, position, name, event_types, conditions, is_default, agent_id,
    repo_mode, repository_id, repo_payload_field, params,
    auto_disable_threshold, notify_on_success, is_enabled
  ) values (
    p_endpoint_id,
    v_pos,
    coalesce(p_rule->>'name', ''),
    coalesce(array(select jsonb_array_elements_text(p_rule->'event_types')), '{}'),
    coalesce(p_rule->'conditions', '[]'::jsonb),
    coalesce((p_rule->>'is_default')::boolean, false),
    (p_rule->>'agent_id')::uuid,
    p_rule->>'repo_mode',
    nullif(p_rule->>'repository_id', '')::uuid,
    p_rule->>'repo_payload_field',
    coalesce(p_rule->'params', '{}'::jsonb),
    coalesce((p_rule->>'auto_disable_threshold')::integer, 3),
    coalesce((p_rule->>'notify_on_success')::boolean, false),
    coalesce((p_rule->>'is_enabled')::boolean, true)
  )
  returning id into v_id;
  return v_id;
end $$;

create or replace function public.webhook_reorder_rules(p_endpoint_id uuid, p_rule_ids uuid[])
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_current uuid[];
begin
  perform 1 from webhook_endpoints where id = p_endpoint_id for update;
  if not found then
    raise exception 'unknown webhook endpoint' using errcode = '23503';
  end if;

  select coalesce(array_agg(id order by id), '{}') into v_current
    from webhook_rules where endpoint_id = p_endpoint_id;

  if coalesce(array_length(p_rule_ids, 1), 0) <> coalesce(array_length(v_current, 1), 0)
     or (select count(distinct x) from unnest(p_rule_ids) x) <> coalesce(array_length(p_rule_ids, 1), 0)
     or (select array_agg(x order by x) from unnest(p_rule_ids) x) is distinct from
        (case when array_length(v_current, 1) is null then null else v_current end) then
    raise exception 'rule ids must be exactly this endpoint''s rules' using errcode = '22023';
  end if;

  update webhook_rules r
     set position = o.ord - 1
    from unnest(p_rule_ids) with ordinality as o(id, ord)
   where r.id = o.id
     and r.endpoint_id = p_endpoint_id;
end $$;

revoke execute on function public.webhook_create_rule(uuid, jsonb) from public, anon, authenticated;
revoke execute on function public.webhook_reorder_rules(uuid, uuid[]) from public, anon, authenticated;
grant  execute on function public.webhook_create_rule(uuid, jsonb) to service_role;
grant  execute on function public.webhook_reorder_rules(uuid, uuid[]) to service_role;
