# Runbook — Agent Scheduler deployment

> Operator procedure for enabling the Phase 4 Agent Scheduler against the live
> Supabase project + the deployed Fly panel. Requires live Supabase (dashboard +
> SQL), `flyctl`, and AWS (IAM, SES) access. Companion to
> [`prd-agent-scheduler`](../requirements/prd-agent-scheduler.md) /
> [`specification-prd-agent-scheduler`](../../workstream/specification-prd-agent-scheduler.md).
>
> **Scope of this runbook as of S-151:** the extension + secret + settings
> prerequisites (steps 1–3). Steps for the SES sender/IAM (S-159), the `pg_cron`
> job registration (S-154/S-158/S-159), and the live verification are appended by
> those stories. Nothing here is applied by CI — it is operator-executed,
> consistent with the panel deploy + reaper runbooks.

## 0. Preconditions

- The scheduler migrations are merged and applied to the live project
  (`supabase db push` or the project's migration pipeline). On the **local**
  stack `supabase db reset` applies them and bootstraps a dev secret + settings
  automatically — no manual steps needed locally.
- The panel is deployed and reachable (see `panel-deployment.md`).

## 1. Enable the extensions (privileged — Supabase dashboard)

`pg_net` must be enabled with sufficient privilege; the migration's
`create extension if not exists pg_net` succeeds locally but on hosted Supabase
enable it explicitly if the migration could not:

1. Supabase dashboard → **Database → Extensions**.
2. Enable **`pg_net`** (the Postgres→panel HTTP transport, SD-T4).
3. Confirm **`supabase_vault`** is enabled (it is by default) and **`pg_cron`**
   is enabled (already on, from the reaper — ADR-004).

Verify:

```sql
select extname from pg_extension where extname in ('pg_net','supabase_vault','pg_cron');
-- expect all three
```

## 2. Set the shared trigger secret (Vault + fly secrets)

The `pg_cron` fire job authenticates to the panel's `/api/internal/**` endpoints
with a shared secret, compared constant-time and fail-closed (SD-A1/SD-A2). The
**same value** must live in Vault (Postgres side) and `fly secrets` (panel side).

1. Generate a high-entropy secret:
   ```bash
   openssl rand -hex 32
   ```
2. Store it in Vault (replace the dev default):
   ```sql
   select scheduler.set_secret('scheduler_trigger_secret', '<generated>');
   -- verify (value is returned decrypted — run only in a trusted session):
   select length(scheduler.read_secret('scheduler_trigger_secret')) > 0;
   ```
3. Mirror it to the panel:
   ```bash
   fly secrets set SCHEDULER_TRIGGER_SECRET='<generated>' -a dt-agent-fleet-panel
   ```
   **Never** log or echo the value in CI or a shared terminal. Rotation = repeat
   steps 1–3 (set both sides); no code change.

## 3. Point the scheduler at the panel + set the concurrency cap

The fire job targets `scheduler.config.panel_base_url`; set it to the deployed
host (local defaults to `http://127.0.0.1:54321`):

```sql
update scheduler.config set value = 'https://dt-agent-fleet-panel.fly.dev', updated_at = now()
 where key = 'panel_base_url';

-- optional: tune the global in-flight cap (G4, default 3)
update scheduler.config set value = '3', updated_at = now() where key = 'max_inflight';

-- verify
select key, value from scheduler.config order by key;
select scheduler.get_setting('panel_base_url'), scheduler.max_inflight();
```

## 4. (S-154 / S-158 / S-159) Register the pg_cron jobs

> Appended by the trigger/sweep/digest stories. The jobs are
> `fire-due-schedules` (`* * * * *`), `scheduler-notify-sweep` (`* * * * *`), and
> `scheduler-daily-digest` (`<min> <hour> * * *`). Verify with
> `select jobname, schedule from cron.job order by jobname;`.

## 5. (S-159) SES sender + IAM

> Appended by the digest story. Verify the `NOTIFICATION_SENDER` identity in SES,
> add `ses:SendEmail`/`ses:SendRawEmail` scoped to that identity's ARN to the
> panel's AgentCore role, and set `NOTIFICATION_SENDER`/`NOTIFICATION_RECIPIENT`
> via `fly secrets`.

## 6. (post-trigger) Live verification

> Appended once the trigger path lands: create a near-future schedule, confirm it
> fires once (a `runs` row with `trigger_type='schedule'`), that a guardrail skip
> is visible, a notification is recorded, and (next morning) the digest sends.
> Run the auth release gate (now asserting `/api/internal/**` → 401 for an
> unauthenticated probe, S-160) against the deployed host.
