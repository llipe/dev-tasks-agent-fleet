-- =====================================================================
-- Agent Fleet -- Phase 4 Agent Scheduler: pg_net + Vault + settings
-- Story S-151 (#263). Enables the extensions the trigger path needs and
-- provisions the shared-secret + runtime settings. No functions that fire
-- anything yet (that is S-152/S-154). Idempotent.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Extensions
--   pg_net  -- the Postgres -> panel HTTP call (SD-T4). Must be enabled
--             with sufficient privilege; on hosted Supabase enable it in
--             Database > Extensions (see the deployment runbook). The local
--             stack lets `create extension` succeed directly.
--   supabase_vault -- stores SCHEDULER_TRIGGER_SECRET so the pg_cron job
--             reads it without the value living in the job body (SD-A2).
--             Already present on Supabase; created here for completeness.
-- ---------------------------------------------------------------------
create extension if not exists pg_net;
create extension if not exists supabase_vault;

-- ---------------------------------------------------------------------
-- scheduler schema -- a home for the scheduler's helper functions so they
-- do not crowd `public`. The due-tick / sweep / digest functions (S-154 /
-- S-158 / S-159) live here too.
-- ---------------------------------------------------------------------
create schema if not exists scheduler;

-- ---------------------------------------------------------------------
-- scheduler.read_secret(name)  -- the single read path the pg_net calls use
--   (SD-A2 / SD-T4). Supabase Vault exposes no `read_secret` helper, only the
--   `vault.decrypted_secrets` view; wrapping it keeps the call sites simple and
--   gives one place to change if the Vault API moves. SECURITY DEFINER so the
--   function owner's Vault access is used, not the (cron) caller's.
--   Returns null when the secret is absent -- callers must treat a null secret
--   as a hard configuration error (the fire path refuses to call without it).
-- ---------------------------------------------------------------------
create or replace function scheduler.read_secret(p_name text)
returns text
language sql
security definer
set search_path = vault, public
as $$
  select decrypted_secret
    from vault.decrypted_secrets
   where name = p_name
   limit 1
$$;

-- ---------------------------------------------------------------------
-- scheduler.set_secret(name, value)  -- idempotent upsert of a Vault secret.
--   The OPERATOR sets the real SCHEDULER_TRIGGER_SECRET out-of-band (runbook):
--     select scheduler.set_secret('scheduler_trigger_secret', '<generated>');
--   mirrored into `fly secrets SCHEDULER_TRIGGER_SECRET` so the panel compares
--   against the same value. This migration does NOT bake in a production secret.
-- ---------------------------------------------------------------------
create or replace function scheduler.set_secret(p_name text, p_value text)
returns void
language plpgsql
security definer
set search_path = vault, public
as $$
declare
  v_id uuid;
begin
  select id into v_id from vault.secrets where name = p_name limit 1;
  if v_id is null then
    perform vault.create_secret(p_value, p_name, 'Agent Scheduler shared secret / setting');
  else
    perform vault.update_secret(v_id, p_value, p_name);
  end if;
end $$;

-- ---------------------------------------------------------------------
-- Runtime settings (SD-T8 / SD-G4). A small key/value table rather than
-- database-level custom GUCs: on Supabase the migration role cannot
-- `ALTER DATABASE ... SET app.*` (permission denied), and a table is more
-- inspectable and overridable per environment anyway.
--   scheduler.panel_base_url      -- base the pg_net call targets (local vs Fly host)
--   scheduler.max_inflight        -- G4 concurrency cap (default 3)
-- The operator overrides panel_base_url in production via the runbook:
--   update scheduler.config set value = 'https://dt-agent-fleet-panel.fly.dev'
--    where key = 'panel_base_url';
-- ---------------------------------------------------------------------
create table scheduler.config (
  key        text primary key,
  value      text not null,
  updated_at timestamptz not null default now()
);

insert into scheduler.config (key, value) values
  ('panel_base_url', 'http://127.0.0.1:54321'),
  ('max_inflight',   '3')
on conflict (key) do nothing;

-- Typed readers the scheduler functions use (SD-T8 / SD-G4). A missing key is a
-- configuration error for base_url (null -> the fire path refuses to call); the
-- cap falls back to a safe default of 3.
create or replace function scheduler.get_setting(p_key text)
returns text
language sql
stable
as $$
  select value from scheduler.config where key = p_key limit 1
$$;

create or replace function scheduler.max_inflight()
returns integer
language sql
stable
as $$
  select coalesce(nullif(scheduler.get_setting('max_inflight'), ''), '3')::integer
$$;

-- ---------------------------------------------------------------------
-- Local/dev bootstrap of the trigger secret so `supabase db reset` yields a
-- working local scheduler without a manual step. This is a DEV-ONLY default
-- value; production is set by the operator via scheduler.set_secret(...) +
-- `fly secrets` (runbook). Safe + idempotent.
-- ---------------------------------------------------------------------
select scheduler.set_secret('scheduler_trigger_secret', 'local-dev-scheduler-secret');
