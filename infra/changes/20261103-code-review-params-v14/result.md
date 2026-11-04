# Result — 20261103-code-review-params-v14

| Step | Status | Backup id | Restore command | Verified at | Evidence |
| ---- | ------ | --------- | --------------- | ----------- | -------- |
| 1 — backup (read) | verified | `backup/agents-code-review.before.json`, `backup/schema_migrations.before.json` | n/a | 2026-11-03T20:53Z | enabled, ARN `…/codereview_code_review-g73KtjA3MT`, v1.0 defaults, `has_context_folders: false`; history head `20261024130000` |
| 2 — dry run (read) | verified | `backup/dry-run.txt` | n/a | 2026-11-03T20:54Z | would push only `20261103120000_seed_code_review_agent.sql` |
| 3 — migration | verified | step 1 | `rollback.sh --from 3` | 2026-11-03T20:54:59Z | `backup/push.txt`: applied. `backup/agents-code-review.after.json`: enabled, same ARN; `context_folders` default `docs,workstream`; `context_selection` enum `llm`/`rules`, default `llm`; defaults carry both |

status: verified
