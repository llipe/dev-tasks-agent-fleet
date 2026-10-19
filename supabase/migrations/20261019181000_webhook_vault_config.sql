-- =====================================================================
-- Agent Fleet -- Webhook Triggers Phase 1: Vault signing secret + config
-- Story S-166 (#310). Per-endpoint signing secrets live in Vault, never in
-- a table column (D-W4, AC9). Settings live in webhook.config.
--
-- ACCESS MODEL (read this before adding a function here):
--   Postgres grants EXECUTE to PUBLIC on every new function by default, and a
--   SECURITY DEFINER function runs as its owner, bypassing RLS. #357 is the
--   pre-existing bug where scheduler RPCs in `public` were callable by `anon`
--   through PostgREST. Every function below therefore REVOKEs EXECUTE from
--   public/anon/authenticated and GRANTs it to service_role only. The
--   webhook-vault.test.ts suite asserts this for each function, at the SQL
--   level and through PostgREST with the anon key.
--
--   `public.webhook_endpoint_secret` is the panel's only read path (PostgREST
--   exposes `public` only). It returns a secret, so the service_role-only
--   grant is the whole boundary -- do not widen it.
--
-- Rollback:
--   drop function public.webhook_endpoint_secret(uuid);
--   drop schema webhook cascade;
--   delete from vault.secrets where name like 'webhook_endpoint_%';
-- =====================================================================

create schema if not exists webhook;
revoke all on schema webhook from public;
grant usage on schema webhook to service_role;

-- ---------------------------------------------------------------------
-- Settings (mirrors scheduler.config, SD-T8). A table rather than custom
-- GUCs: the Supabase migration role cannot ALTER DATABASE SET app.*.
--   delivery_retention_days -- prune horizon for webhook_deliveries (S-167, D-W14)
--   bot_login               -- the GitHub App's bot identity, `<app_slug>[bot]`,
--                              excluded by the self-trigger guard (FR19, D-W12).
--                              The local default is a placeholder; production
--                              sets the real value via the runbook.
-- ---------------------------------------------------------------------
create table webhook.config (
  key        text primary key,
  value      text not null,
  updated_at timestamptz not null default now()
);
revoke all on webhook.config from public, anon, authenticated;
grant select, insert, update on webhook.config to service_role;

insert into webhook.config (key, value) values
  ('delivery_retention_days', '30'),
  ('bot_login',               'dev-tasks-agent-fleet[bot]')
on conflict (key) do nothing;

create or replace function webhook.get_setting(p_key text)
returns text
language sql
stable
set search_path = webhook, pg_temp
as $$
  select value from webhook.config where key = p_key limit 1
$$;

-- Falls back to 30 when the key is missing, empty, non-numeric, or < 1, so a
-- bad setting can never make the prune delete everything.
create or replace function webhook.delivery_retention_days()
returns integer
language plpgsql
stable
set search_path = webhook, pg_temp
as $$
declare
  v text := webhook.get_setting('delivery_retention_days');
begin
  if v is null or v !~ '^[0-9]{1,5}$' or v::integer < 1 then
    return 30;
  end if;
  return v::integer;
end $$;

create or replace function webhook.bot_login()
returns text
language sql
stable
set search_path = webhook, pg_temp
as $$
  select nullif(webhook.get_setting('bot_login'), '')
$$;

-- ---------------------------------------------------------------------
-- Vault wrappers, keyed `webhook_endpoint_<endpoint_id>`. SECURITY DEFINER
-- so the owner's Vault access is used; the grants below decide who may call.
-- ---------------------------------------------------------------------
create or replace function webhook.set_endpoint_secret(p_endpoint_id uuid, p_value text)
returns void
language plpgsql
security definer
set search_path = vault, webhook, public, pg_temp
as $$
declare
  v_name text := 'webhook_endpoint_' || p_endpoint_id::text;
  v_id   uuid;
begin
  if p_value is null or char_length(p_value) = 0 then
    raise exception 'webhook secret must be non-empty' using errcode = '22023';
  end if;
  if not exists (select 1 from public.webhook_endpoints where id = p_endpoint_id) then
    raise exception 'unknown webhook endpoint' using errcode = '23503';
  end if;
  select id into v_id from vault.secrets where name = v_name limit 1;
  if v_id is null then
    perform vault.create_secret(p_value, v_name, 'Webhook endpoint signing secret');
  else
    perform vault.update_secret(v_id, p_value, v_name);
  end if;
end $$;

create or replace function webhook.read_endpoint_secret(p_endpoint_id uuid)
returns text
language sql
stable
security definer
set search_path = vault, pg_temp
as $$
  select decrypted_secret
    from vault.decrypted_secrets
   where name = 'webhook_endpoint_' || p_endpoint_id::text
   limit 1
$$;

create or replace function webhook.delete_endpoint_secret(p_endpoint_id uuid)
returns void
language sql
security definer
set search_path = vault, pg_temp
as $$
  delete from vault.secrets where name = 'webhook_endpoint_' || p_endpoint_id::text
$$;

-- The panel's read path (server-only, service-role client). Returns null when
-- no secret is set; the inbound route treats null as a 401 (fail closed).
create or replace function public.webhook_endpoint_secret(p_endpoint_id uuid)
returns text
language sql
stable
security definer
set search_path = webhook, pg_temp
as $$
  select webhook.read_endpoint_secret(p_endpoint_id)
$$;

-- ---------------------------------------------------------------------
-- Grants: service_role only (see ACCESS MODEL above, and #357).
-- ---------------------------------------------------------------------
revoke execute on function webhook.get_setting(text)                from public, anon, authenticated;
revoke execute on function webhook.delivery_retention_days()        from public, anon, authenticated;
revoke execute on function webhook.bot_login()                      from public, anon, authenticated;
revoke execute on function webhook.set_endpoint_secret(uuid, text)  from public, anon, authenticated;
revoke execute on function webhook.read_endpoint_secret(uuid)       from public, anon, authenticated;
revoke execute on function webhook.delete_endpoint_secret(uuid)     from public, anon, authenticated;
revoke execute on function public.webhook_endpoint_secret(uuid)     from public, anon, authenticated;

grant execute on function webhook.get_setting(text)                to service_role;
grant execute on function webhook.delivery_retention_days()        to service_role;
grant execute on function webhook.bot_login()                      to service_role;
grant execute on function webhook.set_endpoint_secret(uuid, text)  to service_role;
grant execute on function webhook.read_endpoint_secret(uuid)       to service_role;
grant execute on function webhook.delete_endpoint_secret(uuid)     to service_role;
grant execute on function public.webhook_endpoint_secret(uuid)     to service_role;
