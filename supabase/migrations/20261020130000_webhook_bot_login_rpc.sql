-- =====================================================================
-- Agent Fleet -- Webhook Triggers Phase 1: bot login read path
-- Story S-171 (#316). The route reads webhook.config's bot_login (the
-- self-trigger guard, FR19 / D-W12) through PostgREST, which only exposes
-- `public`. Same access model as public.webhook_endpoint_secret (S-166):
-- SECURITY DEFINER, executable by service_role only (#357 lesson; enforced by
-- definer-grants.test.ts, which enumerates every public SECURITY DEFINER fn).
--
-- Rollback: drop function public.webhook_bot_login();
-- =====================================================================

create or replace function public.webhook_bot_login()
returns text
language sql
stable
security definer
set search_path = webhook, pg_temp
as $$
  select webhook.bot_login()
$$;

revoke execute on function public.webhook_bot_login() from public, anon, authenticated;
grant  execute on function public.webhook_bot_login() to service_role;
