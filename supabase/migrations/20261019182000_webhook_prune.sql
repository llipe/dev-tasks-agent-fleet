-- =====================================================================
-- Agent Fleet -- Webhook Triggers Phase 1: delivery retention prune
-- Story S-167 (#311), decision D-W14 (OQ-2: prune in v1).
--
-- webhook_deliveries gets a row for every inbound attempt (D-W16), so it is
-- bounded by age: rows older than webhook.config.delivery_retention_days
-- (default 30, see S-166) are deleted daily, oldest first, in capped batches
-- so a backlog never holds a long lock. The run history is the durable
-- record; deleting a delivery never touches `runs` (run_id is the FK from
-- deliveries to runs, not the other way round).
--
-- Rollback:
--   select cron.unschedule('webhook-prune-deliveries');
--   drop function webhook.prune_deliveries(integer);
-- =====================================================================

create or replace function webhook.prune_deliveries(p_batch integer default 5000)
returns integer
language plpgsql
security definer
set search_path = public, webhook, pg_temp
as $$
declare
  v_deleted integer;
begin
  if p_batch is null or p_batch < 1 then
    raise exception 'prune batch size must be >= 1' using errcode = '22023';
  end if;

  delete from public.webhook_deliveries
   where id in (
     select id
       from public.webhook_deliveries
      where created_at < now() - make_interval(days => webhook.delivery_retention_days())
      order by created_at
      limit p_batch
   );
  get diagnostics v_deleted = row_count;
  return v_deleted;
end $$;

-- service_role only (the #357 lesson). The cron job runs as the migration
-- owner (postgres), which owns the function and keeps access.
revoke execute on function webhook.prune_deliveries(integer) from public, anon, authenticated;
grant  execute on function webhook.prune_deliveries(integer) to service_role;

-- ---------------------------------------------------------------------
-- Daily at 03:17 UTC (off the hour, so it doesn't line up with other jobs).
-- Capacity is one batch (5000 rows) per day. That's ample for a single org's
-- GitHub traffic. If sustained inflow ever exceeds it (for example an
-- unauthorized flood against a leaked URL, test plan R-3), the table will
-- grow; then raise the batch or run the job more often. Registration uses the
-- same do-block-unschedule plus top-level select style as the scheduler crons
-- (fire_due).
-- ---------------------------------------------------------------------
do $$
begin
  perform cron.unschedule('webhook-prune-deliveries')
   where exists (select 1 from cron.job where jobname = 'webhook-prune-deliveries');
exception when others then
  null;
end $$;

select cron.schedule('webhook-prune-deliveries', '17 3 * * *', $$select webhook.prune_deliveries()$$);
