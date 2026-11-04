# Plan — 20261103-code-review-params-v14

- **ChangeId:** `20261103-code-review-params-v14`
- **Environment:** prod, Supabase project `hegxeycmbmjfgzqpdiik` (dev-tasks-agent-fleet)
- **Identity:** `supabase projects list` shows `hegxeycmbmjfgzqpdiik` (linked) after `supabase login`
- **Goal:** apply `supabase/migrations/20261103120000_seed_code_review_agent.sql` (PRD v1.4 params `context_folders`, `context_selection`; spec §5.1, §5.4).
- **Order precondition:** the runtime that reads the new params is live (ChangeId `20261103-code-review-redeploy-v14`, runtime version 4). An older runtime would reject the new defaults as unknown params.
- **Cost:** none (data only).
- **Approval:** Llipe, 2026-11-03 ("apply the migration"; "deploy as proposed").

| Step | Kind | Tool | Touches state | Backup | Forward | Verify | Revert |
| ---- | ---- | ---- | ------------- | ------ | ------- | ------ | ------ |
| 1 | backup (read) | supabase | no | n/a | row and migration history → `backup/*.before.json` | row enabled, live ARN, v1.0 defaults; history head `20261024130000` | n/a |
| 2 | dry run (read) | supabase | no | n/a | `supabase db push --dry-run --linked` | lists only `20261103120000` | n/a |
| 3 | database migration | supabase | yes | step 1 | `supabase db push --linked --yes` | row still enabled on the live ARN; schema and defaults carry both new params | `rollback.sh --from 3` |
