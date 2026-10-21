-- =====================================================================
-- Agent Fleet -- Webhook Triggers Phase 1: endpoint admin RPCs for /webhooks
-- Story S-176 (#321), FR20/FR21, D-W4.
--
-- PostgREST only reaches `public`, and the Vault helpers live in `webhook`, so
-- the panel's Server Actions need public wrappers. Each is SECURITY DEFINER and
-- service_role-only, because each one writes a signing secret.
--
--   webhook_create_endpoint(...)        insert + store the secret in ONE
--                                       transaction: an endpoint never exists
--                                       without a secret, and a failed insert
--                                       leaves no orphaned Vault entry.
--   webhook_rotate_endpoint_secret(id, secret)
--   webhook_delete_endpoint(id)         Vault secret first, then the row
--                                       (rules + deliveries cascade).
--
-- The panel generates the token and secret (Node crypto, 32 bytes each) and
-- shows the secret once. None of these functions returns a secret.
-- Updating settings needs no RPC: it is a plain row update with no secret.
--
-- Rollback: drop the three functions. No data change.
-- =====================================================================

create or replace function public.webhook_create_endpoint(
  p_name               text,
  p_source             webhook_source,
  p_event_allowlist    text[],
  p_ignore_bot_author  boolean,
  p_signature_header   text,
  p_delivery_id_header text,
  p_url_token          text,
  p_secret             text
) returns uuid
language plpgsql
security definer
set search_path = public, webhook, pg_temp
as $$
declare
  v_id uuid;
begin
  insert into webhook_endpoints
    (name, source, event_allowlist, ignore_bot_author, signature_header, delivery_id_header, url_token)
  values
    (p_name, p_source, p_event_allowlist, p_ignore_bot_author, p_signature_header, p_delivery_id_header, p_url_token)
  returning id into v_id;
  perform webhook.set_endpoint_secret(v_id, p_secret);
  return v_id;
end $$;

create or replace function public.webhook_rotate_endpoint_secret(p_endpoint_id uuid, p_secret text)
returns void
language plpgsql
security definer
set search_path = public, webhook, pg_temp
as $$
begin
  perform webhook.set_endpoint_secret(p_endpoint_id, p_secret);
end $$;

create or replace function public.webhook_delete_endpoint(p_endpoint_id uuid)
returns void
language plpgsql
security definer
set search_path = public, webhook, pg_temp
as $$
begin
  perform webhook.delete_endpoint_secret(p_endpoint_id);
  delete from webhook_endpoints where id = p_endpoint_id;
end $$;

revoke execute on function public.webhook_create_endpoint(text, webhook_source, text[], boolean, text, text, text, text) from public, anon, authenticated;
revoke execute on function public.webhook_rotate_endpoint_secret(uuid, text) from public, anon, authenticated;
revoke execute on function public.webhook_delete_endpoint(uuid) from public, anon, authenticated;
grant  execute on function public.webhook_create_endpoint(text, webhook_source, text[], boolean, text, text, text, text) to service_role;
grant  execute on function public.webhook_rotate_endpoint_secret(uuid, text) to service_role;
grant  execute on function public.webhook_delete_endpoint(uuid) to service_role;
