---
name: runbook-webhook-deployment
trigger: Enabling webhook triggers against the live Supabase project, adding a GitHub webhook endpoint, or rotating an endpoint's signing secret
owner: operator (repository owner)
last_verified: never — written with S-166; steps run against the local stack only so far
related: ["supabase/migrations/20261019181000_webhook_vault_config.sql", "supabase/migrations/20261019180000_webhook_schema.sql"]
---

# Runbook — Webhook triggers deployment

> Operator procedure for enabling Webhook Triggers Phase 1 on the live Supabase
> project and the deployed Fly panel. Companion to
> [`prd-webhook-triggers`](../requirements/prd-webhook-triggers.md) and
> [`specification-prd-webhook-triggers`](../../workstream/specification-prd-webhook-triggers.md).
>
> **Scope as of S-166:** the database prerequisites and the per-endpoint secret
> (steps 1–4). Later stories add the retention cron (S-167), the release-gate probe
> (S-175), and live verification. Nothing here runs in CI.
>
> **Blast radius:** step 1 changes the live schema (additive). Steps 2–4 write to
> live configuration and Vault. A wrong `bot_login` disables the self-trigger guard
> (step 2). A leaked secret lets anyone holding the URL fire agents (step 3).

## Preconditions

- Webhook migrations merged to `main`. In particular `20261019180000_webhook_schema.sql`
  and `20261019181000_webhook_vault_config.sql`.
- `supabase` CLI linked to the live project (`supabase projects list` shows it linked).
- Explicit approval for each live step. `supabase db push` and any SQL against the live
  project are irreversible-in-practice actions.
- `#357` (anon-executable scheduler RPCs) is a separate fix and is **not** a
  precondition. The webhook functions revoke `EXECUTE` from `anon` and `authenticated` on their own.

## Steps

### 1. Apply the migrations

```bash
supabase db push     # applies only migrations not yet recorded on the live project
```

### 2. Set the bot identity (self-trigger guard, FR19)

The guard excludes events whose `sender.login` equals this value **and** whose
`sender.type` is `Bot`. The value is the GitHub App's slug followed by `[bot]`.

```bash
gh api /app --jq '.slug + "[bot]"'     # with the App's JWT; or read the slug from the App settings page
```

```sql
update webhook.config set value = '<app_slug>[bot]', updated_at = now()
 where key = 'bot_login';
```

### 3. Create an endpoint and store its signing secret

From S-176 onward, use the panel's `/webhooks` screen. It generates the token and
secret and shows the secret once. **Until S-176 ships**, or to recover by hand:

```bash
# 32 random bytes each. Generate them locally and never paste them into a chat or ticket.
TOKEN=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')
SECRET=$(openssl rand -hex 32)
```

```sql
insert into webhook_endpoints (name, url_token, source, event_allowlist)
values ('GitHub org', '<TOKEN>', 'github',
        array['pull_request','issue_comment','pull_request_review_comment','push'])
returning id;

select webhook.set_endpoint_secret('<endpoint id>', '<SECRET>');
```

The secret lives only in Vault (`webhook_endpoint_<id>`). It is never in a table
column, and the panel reads it through the service_role-only
`public.webhook_endpoint_secret` RPC.

### 4. Register the webhook in GitHub

In the organization (or repository) **Settings → Webhooks → Add webhook**:

- **Payload URL:** `https://dt-agent-fleet-panel.fly.dev/api/webhooks/<TOKEN>`
- **Content type:** `application/json`
- **Secret:** `<SECRET>`
- **Events:** the same set as `event_allowlist`. Anything else is recorded as `ignored`.

## Rotating a secret

1. `select webhook.set_endpoint_secret('<endpoint id>', '<NEW SECRET>');` (or rotate in the panel).
2. Update the GitHub webhook's **Secret** field right away. Deliveries signed with the
   old secret return `401` and are recorded as `unauthorized` until GitHub uses the new one.

If the **URL token** leaks, rotating the secret is not enough: the leaked URL can still
add `unauthorized` rows (test plan R-3). Create a new endpoint, move the GitHub
webhook to the new URL, and disable or delete the old endpoint.

## Verification

```sql
-- the secret exists and is readable by the definer path (prints true, not the value)
select webhook.read_endpoint_secret('<endpoint id>') is not null as has_secret;

-- anon and authenticated cannot read secrets (all false)
select has_function_privilege('anon',          'public.webhook_endpoint_secret(uuid)', 'execute') as anon,
       has_function_privilege('authenticated', 'public.webhook_endpoint_secret(uuid)', 'execute') as authed;

select key, value from webhook.config;
```

From S-169 onward: GitHub's **Recent Deliveries** shows `2xx` for a ping, and the
panel's delivery log shows the event.

## Rollback

- Stop deliveries at once: `update webhook_endpoints set is_enabled = false where id = '<id>';`
  The route then answers `404`. Also remove or disable the webhook in GitHub.
- Remove a secret: `select webhook.delete_endpoint_secret('<id>');`
- Schema rollback (destructive; drops all endpoints, rules and deliveries): see the
  headers of the two migrations. Get explicit approval first.

## Escalation

The repository owner. For a suspected secret leak, disable the endpoint first, then rotate.
