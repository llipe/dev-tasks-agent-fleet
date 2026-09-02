# Runbook — S-102 / issue #115: Supabase CLI baseline adoption

Adopting `supabase/migrations/20260902200101_initial_schema.sql` as the baseline
for the **live** project `hegxeycmbmjfgzqpdiik` (`dev-tasks-agent-fleet`, org
`llipe`). Per SD3 the baseline **records already-existing state** — it must be
registered without re-running DDL.

## Local stack verification (Docker) — PASS

`supabase start` + `supabase db reset` applied the baseline migration and
`supabase/seed.sql` cleanly, on a Postgres image that ships `pg_cron`.

| Check | Result |
| --- | --- |
| `v_runs` view exists | 1 |
| `v_runs.effective_status` column present | 1 |
| `reap_stale_runs()` callable | returns `0` |
| `cron.job` lists `reap-stale-runs` | `* * * * *` |
| Seed rows | installations=1, repositories=2, agents=1 |
| Public tables present | 7/7 |
| Seed applied twice | no duplicates (still 1/2/1) — `on conflict` paths |
| `db reset` from seeded state | recreates cleanly; history = `20260902200101 initial_schema` |
| `pnpm run test:integration` | 3 passed (executes, not skipped) |

## Live-vs-baseline diff (`supabase db diff --linked --use-migra`)

`supabase migration list --linked` beforehand: **Local `20260902200101` /
Remote (empty)** — the live DB has the schema objects (from the original manual
`001_schema.sql` run) but **no migration history**.

The diff is **not byte-empty**, but it is a **schema-level no-op**: every
statement is Supabase **platform-managed** state that our baseline neither
contains nor should contain. Category breakdown (205 lines total):

| Category | Count | What it is |
| --- | --- | --- |
| `grant … to anon/authenticated/service_role` on public tables | 84 | Supabase's automatic default table privileges |
| `create or replace function public.rls_auto_enable()` (+ event trigger) | 1 | Supabase platform trigger that auto-enables RLS on new public tables |
| `drop extension if exists "pg_net"` | 1 | `pg_net` is a Supabase default platform extension |

**Zero** statements touch our own objects: no `create/drop/alter` of any table,
enum, index, constraint, the `v_runs` view, `reap_stale_runs()`, the RLS
`enable` statements, the `pg_cron` schedule, or the Realtime publication. The
live schema therefore already matches the baseline; the non-empty diff is the
well-known noise the CLI emits when adopting a hosted project against a bare
shadow DB.

**Decision (per task 1.11 impact rule):** do **not** author a corrective
migration for any of the diffed statements, and do **not** run the diff SQL
against live — dropping `pg_net` or rewriting platform grants would be
destructive platform tampering, not schema adoption. Register the baseline as
**applied** without executing DDL.

## Registration command (baseline/repair — no DDL executed)

```bash
supabase migration repair --status applied 20260902200101
```

This inserts the version into `supabase_migrations.schema_migrations` on the
live project and runs **no** DDL. Nothing is dropped, no grant changes, no
destructive action. Rollback position: none needed — no state is mutated beyond
the history row (reversible with `--status reverted`).

## Post-apply verification (run after registration)

```bash
supabase migration list --linked   # 20260902200101 shows under BOTH Local and Remote
```

Plus, against live: `cron.job` still lists `reap-stale-runs`; `runs` and
`run_events` row counts unchanged (registration touches only the migration
history table).

## Applied — evidence (registered after explicit user approval)

```
$ supabase migration repair --status applied 20260902200101
Repaired migration history: [20260902200101] => applied

$ supabase migration list --linked
   Local            | Remote           | Time (UTC)
  ------------------|------------------|-----------------------
   20260902200101   | 20260902200101   | 2026-09-02 20:01:01
```

- **No DDL executed.** `migration repair` writes only to
  `supabase_migrations.schema_migrations`. A **post-apply** `supabase db diff --linked --use-migra`
  returned the *same* 205 lines as before (platform-managed grants /
  `rls_auto_enable()` / `pg_net` only) — **zero** changes to our tables, enums,
  indexes, `v_runs`, `reap_stale_runs()`, the `pg_cron` schedule, or the
  Realtime publication. This corroborates that the reaper and its schedule are
  untouched and that no `runs`/`run_events` data was mutated.
- **Empirical live `cron.job` / row-count spot-check (optional).** Not run from
  the implementation environment because the live DB password is not present
  here. `migration repair` cannot change these by construction, and the
  identical post-apply diff confirms `public` is unchanged. To confirm directly,
  an operator with the DB password can run:

  ```sql
  select jobname, schedule from cron.job where jobname = 'reap-stale-runs';
  select (select count(*) from runs) as runs, (select count(*) from run_events) as events;
  ```
