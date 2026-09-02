# Runbook — Issue #116 / S-103: English-only SQL surface

Operator procedures, rollback text, and impact analysis for the two S-103
migrations. Referenced by the user-confirmation gate (task 2.13) before any
live apply.

## Migrations in this story

| Order | File | Effect |
|---|---|---|
| 1 | `supabase/migrations/20260903090000_english_reaper_messages.sql` | `create or replace function reap_stale_runs()` — English `error_message` (both branches) + English explanatory `run_events` messages. Behavior-preserving. |
| 2 | `supabase/migrations/20260903090100_seed_params_schema_english.sql` | `update agents set params_schema = <english>` where `slug = 'dependency-update'` — English `title`/`description`; structure unchanged. |

Both are DDL/DML on a **function body** and a **single seeded row** respectively.
No table, column, enum, index, view, RLS, or `cron` schedule is touched.

## Apply (local — already verified)

```bash
supabase db reset   # applies baseline + both S-103 migrations + seed
pnpm --filter panel run test:integration   # 14 passing (reaper 7 + seed-schema 4 + baseline 3)
```

## Apply (live — requires explicit user confirmation, task 2.13/2.14)

```bash
supabase db push    # applies only the two new migrations (baseline already registered in S-102)
```

## Rollback

Both migrations are reversible by re-applying the prior body/JSON. No data is
lost — the reaper change only affects the *text* written by future reaps; the
seed change only affects operator-facing labels.

### 1. Revert `reap_stale_runs()` to the prior (Spanish) body

Re-apply the baseline body verbatim (from `20260902200101_initial_schema.sql`):

```sql
create or replace function reap_stale_runs() returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count integer := 0;
  v_run   record;
begin
  for v_run in
    select id, max_runtime_seconds, grace_seconds
    from runs
    where status = 'running'
      and started_at is not null
      and now() > started_at + make_interval(secs => max_runtime_seconds + grace_seconds)
    for update skip locked
  loop
    update runs
       set status = 'timed_out',
           finished_at = now(),
           error_code = 'RUNTIME_TIMEOUT',
           error_message = format(
             'Sin reporte de término tras %s s (max_runtime %s + grace %s).',
             v_run.max_runtime_seconds + v_run.grace_seconds,
             v_run.max_runtime_seconds, v_run.grace_seconds)
     where id = v_run.id;

    insert into run_events (run_id, seq, level, message, data)
    select v_run.id,
           coalesce((select max(seq) from run_events where run_id = v_run.id), 0) + 1,
           'error',
           'El sistema marcó esta ejecución como timed_out: el agente nunca reportó término.',
           jsonb_build_object('reaped_by', 'reap_stale_runs', 'reason', 'RUNTIME_TIMEOUT');

    update run_steps
       set status = 'failed',
           finished_at = now(),
           error_message = 'Cerrado por reap_stale_runs: la ejecución fue marcada timed_out (RUNTIME_TIMEOUT).'
     where run_id = v_run.id
       and status in ('running', 'pending');

    v_count := v_count + 1;
  end loop;

  for v_run in
    select id, start_timeout_seconds
    from runs
    where status = 'queued'
      and now() > queued_at + make_interval(secs => start_timeout_seconds)
    for update skip locked
  loop
    update runs
       set status = 'failed_to_start',
           finished_at = now(),
           error_code = 'START_TIMEOUT',
           error_message = format('El agente no reportó inicio tras %s s.', v_run.start_timeout_seconds)
     where id = v_run.id;

    insert into run_events (run_id, seq, level, message, data)
    select v_run.id,
           coalesce((select max(seq) from run_events where run_id = v_run.id), 0) + 1,
           'error',
           'La invocación nunca reportó inicio. Revisar el runtime en AgentCore.',
           jsonb_build_object('reaped_by', 'reap_stale_runs', 'reason', 'START_TIMEOUT');

    update run_steps
       set status = 'failed',
           finished_at = now(),
           error_message = 'Cerrado por reap_stale_runs: la invocación fue marcada failed_to_start (START_TIMEOUT).'
     where run_id = v_run.id
       and status in ('running', 'pending');

    v_count := v_count + 1;
  end loop;

  return v_count;
end $$;
```

### 2. Revert `params_schema` to the prior (Spanish) JSON

```sql
update agents
   set params_schema = $json${
     "type": "object",
     "additionalProperties": false,
     "required": ["fix_mode"],
     "properties": {
       "fix_mode": {
         "type": "string",
         "title": "Modo de corrección",
         "description": "audit_only reporta hallazgos. llm_fix intenta corregir y abrir un PR.",
         "enum": ["audit_only", "llm_fix"],
         "default": "audit_only"
       },
       "fail_on_findings": {
         "type": "boolean",
         "title": "Fallar si hay hallazgos",
         "description": "Solo aplica en modo audit_only.",
         "default": true
       },
       "max_fix_attempts": {
         "type": "integer",
         "title": "Intentos máximos del agente LLM",
         "description": "Solo aplica en modo llm_fix. 0 desactiva el agente LLM. Rango 0..5.",
         "minimum": 0,
         "maximum": 5,
         "default": 3
       },
       "base_branch": {
         "type": "string",
         "title": "Rama base del PR",
         "description": "Rama contra la que se abre el PR. Por defecto la rama por defecto del repo (main).",
         "default": "main"
       }
     }
   }$json$::jsonb
 where slug = 'dependency-update';
```

## Impact

- **Reaper migration.** A bad function body is the only real risk: the reaper is
  the sole layer that materializes terminal state *and* records **why** an
  unreported run ended (the explanatory `run_events` row — product-context
  success metric 3). If the replacement body were malformed, the reaper would
  stop materializing terminal states and the `v_runs` read-time layer would keep
  the UI looking correct while `runs.status` stayed wrong. Mitigation: the Layer
  2.5 reaper tests exercise both branches, the step closure, seq assignment, and
  the no-op/idempotency edges on every `db reset`, and the body is a verbatim
  copy of the baseline with only string literals changed.
- **Seed migration.** Operator-facing labels only. No machine contract
  (`enum`/`default`/`minimum`/`maximum`/`required`/`additionalProperties`)
  changes, so no invoke-form validation behavior changes.
- **No schedule impact.** `cron.schedule('reap-stale-runs', ...)` is not touched;
  `create or replace function` keeps the same function OID the job calls.

## `start_timeout_seconds` resolution (task 2.8)

Direction A — **corrected the comment, kept the value at 300**. `start_timeout_seconds`
is the queue clock (`queued_at`-based, D9); `idleRuntimeSessionTimeout` (raised to
900 in issue #98) is an output-idle clock. They measure different failures and were
never meant to be equal. Recorded in `supabase/seed.sql` block 3 and
`docs/technical-guidelines.md` §8.
