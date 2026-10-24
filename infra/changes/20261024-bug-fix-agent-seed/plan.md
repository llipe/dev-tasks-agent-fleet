# Plan: 20261024-bug-fix-agent-seed

- **ChangeId:** `infra/changes/20261024-bug-fix-agent-seed/`
- **Story:** S-184 (#366), PR #449, tasks 5.6–5.7 and 5.10; also the deferred S-181 AC4 (live panel invoke)
- **Environment:** production Supabase project `dev-tasks-agent-fleet` (`hegxeycmbmjfgzqpdiik`), `production: true`
- **Identity:** Supabase CLI 2.122.0, logged in by @llipe to the account that owns `hegxeycmbmjfgzqpdiik` and linked (`supabase/.temp/project-ref`). Checked with `supabase projects list` on 2026-10-24T18:11Z. The earlier login was to the Riel org and was replaced.
- **Approval:** the plan and step 1 need @llipe's approval. Each step is approved on its own.

## Cost

$0: one row in an existing table, on the existing plan.

## Discovery (read-only, 2026-10-24T18:11:40Z)

- `supabase db push --dry-run` lists **only** `20261024130000_seed_bug_fix_agent.sql`.
- Live `agents` rows: `dependency-update` and `security-analyst`; no `bug-fix` (`backup/agents.before.json`).
- Latest live migration: `20261020180000` (`backup/schema_migrations.before.json`).

## Steps

### Step 1: apply the seed migration
- **Kind:** database migration · **Tool:** supabase · **Touches state:** yes (production)
- **Backup:** `backup/agents.before.json` and `backup/schema_migrations.before.json` (no `bug-fix` row exists, so restoring means deleting the row).
- **Forward:** `supabase db push --linked` (applies only `20261024130000_seed_bug_fix_agent.sql`; re-check that the output names only that file).
- **Verify:** `select slug, requires_repository, params_schema->'required' from agents where slug = 'bug-fix';` returns `bug-fix | t | ["issue_number"]`, and the runtime ARN and timeouts match; `schema_migrations` records `20261024130000`.
- **Revert:**
  - `delete from agents where slug = 'bug-fix';` (no `runs`, `webhook_rules` or `schedules` rows exist for it yet) and `delete from supabase_migrations.schema_migrations where version = '20261024130000';`
  - Order: the migration record goes after the row, so the next push doesn't think the row exists.

### Step 2: panel check and live invoke (5.10, S-181 AC4)
- **Kind:** verification · **Tool:** panel (browser, @llipe) and supabase (read) · **Touches state:** yes. It creates one `runs` row, and the runtime is called once and answers `not_applicable`.
- **Forward:** @llipe opens `/agents/bug-fix/invoke`: `issue_number` is the only required field. Submit `{issue_number: <a fixture issue>}`.
- **Verify:** the `runs` row for `bug-fix` reaches a terminal state, and the runtime replies `not_applicable` ("not yet implemented", the Wave A stub). Read with `select status, outcome, error_code from runs where agent_id = (select id from agents where slug='bug-fix') order by created_at desc limit 1;`
- **Revert:** none needed. The run row is the audit trail. Once it exists, the step 1 revert is blocked by `ON DELETE RESTRICT`, which is accepted.

### Step 3: records
- **Kind:** repo operation · **Tool:** git · **Touches state:** no
- **Forward:** `commands.sh`, `rollback.sh`, `result.md`; check tasks 5.6, 5.7 and 5.10; commit to PR #449.
