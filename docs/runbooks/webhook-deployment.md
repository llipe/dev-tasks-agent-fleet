---
name: runbook-webhook-deployment
trigger: Enabling webhook triggers against the live Supabase project, adding a GitHub webhook endpoint, or rotating an endpoint's signing secret
owner: operator (repository owner)
last_verified: never — written with S-166; steps run against the local stack only so far
related: ["scripts/verify-panel-auth.sh", "supabase/migrations/20261019181000_webhook_vault_config.sql", "supabase/migrations/20261019180000_webhook_schema.sql", "supabase/migrations/20261019182000_webhook_prune.sql"]
---

# Runbook — Webhook triggers deployment

> Operator procedure for enabling Webhook Triggers Phase 1 on the live Supabase
> project and the deployed Fly panel. Companion to
> [`prd-webhook-triggers`](../requirements/prd-webhook-triggers.md) and
> [`specification-prd-webhook-triggers`](../../workstream/specification-prd-webhook-triggers.md).
>
> **Scope as of S-167:** the database prerequisites, the per-endpoint secret
> (steps 1–4), and the delivery retention cron (step 1 registers it; see
> Verification). Later stories add the release-gate probe (S-175) and live
> verification. Nothing here runs in CI.
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

### 5. Create the release-gate probe endpoint (S-175)

The panel release gate (`scripts/verify-panel-auth.sh`, check 6) sends an
**unsigned** POST to `/api/webhooks/<token>` and requires `401`. The route answers
`404` for an unknown or disabled token before it checks the signature, so the gate
needs the token of a real, **enabled** endpoint. Use a dedicated one: no rules, so
it can never start a run, and a throwaway secret that nobody keeps.

Do this **after step 1 and before the first panel deploy that carries S-175**.
Otherwise that deploy's gate fails at check 6.

```bash
PROBE_TOKEN=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')
```

```sql
insert into webhook_endpoints (name, url_token, source, is_enabled, event_allowlist)
values ('release-gate probe (no rules)', '<PROBE_TOKEN>', 'github', true, array['ping'])
returning id;

-- a secret nobody keeps: the probe only needs signature checks to run and fail
select webhook.set_endpoint_secret('<probe endpoint id>', encode(gen_random_bytes(32), 'hex'));
```

Store `PROBE_TOKEN` with the other deploy credentials (a password manager, not
the repo). Export it before every gate run:

```bash
export WEBHOOK_PROBE_TOKEN='<PROBE_TOKEN>'
./scripts/verify-panel-auth.sh https://dt-agent-fleet-panel.fly.dev -a dt-agent-fleet-panel
# check 6 passes on 401. It fails (exit 1) on 2xx (signature not enforced),
# 404 (wrong token or endpoint disabled), any other code, or an unset token.
```

Each gate run records one `unauthorized` delivery on the probe endpoint. The
daily prune removes those with the rest. Never add rules to this endpoint and
never disable it. If the token leaks, create a new probe endpoint and delete the
old one.

## Rotating a secret

1. `select webhook.set_endpoint_secret('<endpoint id>', '<NEW SECRET>');` (or rotate in the panel).
2. Update the GitHub webhook's **Secret** field right away. Deliveries signed with the
   old secret return `401` and are recorded as `unauthorized` until GitHub uses the new one.

If the **URL token** leaks, rotating the secret is not enough: the leaked URL can still
add `unauthorized` rows (test plan R-3). Create a new endpoint, move the GitHub
webhook to the new URL, and disable or delete the old endpoint.

## Verification

```bash
# the release gate's webhook check (step 5) passes against the deployed app
WEBHOOK_PROBE_TOKEN='<PROBE_TOKEN>' ./scripts/verify-panel-auth.sh https://dt-agent-fleet-panel.fly.dev -a dt-agent-fleet-panel
```

```sql
-- the secret exists and is readable by the definer path (prints true, not the value)
select webhook.read_endpoint_secret('<endpoint id>') is not null as has_secret;

-- anon and authenticated cannot read secrets (all false)
select has_function_privilege('anon',          'public.webhook_endpoint_secret(uuid)', 'execute') as anon,
       has_function_privilege('authenticated', 'public.webhook_endpoint_secret(uuid)', 'execute') as authed;

select key, value from webhook.config;

-- the retention prune is scheduled daily (S-167) and has run successfully
select jobname, schedule, active from cron.job where jobname = 'webhook-prune-deliveries';
select status, return_message, start_time
  from cron.job_run_details
 where jobid = (select jobid from cron.job where jobname = 'webhook-prune-deliveries')
 order by start_time desc limit 3;
```

### Retention tuning

`delivery_retention_days` (default 30) is the prune horizon. Invalid or non-positive
values fall back to 30, so a bad setting can't wipe the log. The job deletes at most
5000 rows a day, oldest first. If `select count(*) from webhook_deliveries where
created_at < now() - interval '30 days'` keeps growing, raise the batch
(`select webhook.prune_deliveries(20000);` once, by hand) and look for an
`unauthorized` flood (rotate the URL token, per "Rotating a secret").

```sql
update webhook.config set value = '14', updated_at = now() where key = 'delivery_retention_days';
```

From S-169 onward: GitHub's **Recent Deliveries** shows `202` for the initial `ping` (not on
the allowlist, so it's recorded as `ignored`, which is expected). A `401` there means the
secret in GitHub doesn't match Vault, and a `404` means the token is wrong or the endpoint is
disabled. Check the outcome per attempt:

```sql
select received_at, delivery_id, event_type, outcome, reason
  from webhook_deliveries where endpoint_id = '<endpoint id>'
 order by received_at desc limit 20;
```

## Rollback

- Stop deliveries at once: `update webhook_endpoints set is_enabled = false where id = '<id>';`
  The route then answers `404`. Also remove or disable the webhook in GitHub.
- Remove a secret: `select webhook.delete_endpoint_secret('<id>');`
- Stop the retention prune: `select cron.unschedule('webhook-prune-deliveries');`
- Schema rollback (destructive; drops all endpoints, rules and deliveries): see the
  headers of the two migrations. Get explicit approval first.

## Escalation

The repository owner. For a suspected secret leak, disable the endpoint first, then rotate.
