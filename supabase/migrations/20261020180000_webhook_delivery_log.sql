-- =====================================================================
-- Agent Fleet -- Webhook Triggers Phase 1: delivery log support
-- Story S-178 (#323), FR23.
--
-- The delivery log states how long deliveries are kept. The value lives in
-- webhook.config (S-167, tunable), which PostgREST can't reach, so this
-- exposes it read-only. It is service_role-only like every other webhook
-- definer function, although it reveals nothing sensitive.
--
-- Rollback: drop function public.webhook_delivery_retention_days().
-- =====================================================================

create or replace function public.webhook_delivery_retention_days()
returns integer
language sql
stable
security definer
set search_path = webhook, pg_temp
as $$
  select webhook.delivery_retention_days()
$$;

revoke execute on function public.webhook_delivery_retention_days() from public, anon, authenticated;
grant  execute on function public.webhook_delivery_retention_days() to service_role;
