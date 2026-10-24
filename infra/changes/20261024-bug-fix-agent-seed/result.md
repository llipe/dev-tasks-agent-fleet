# Result: 20261024-bug-fix-agent-seed

| Step | Status | Backup id | Restore command | Verified at | Evidence |
| ---- | ------ | --------- | --------------- | ----------- | -------- |
| 1 — apply seed migration | verified | `backup/agents.before.json`, `backup/schema_migrations.before.json` | `rollback.sh --from 1` | 2026-10-24T18:17:44Z | First attempt (18:14:41Z) refused by the CLI with no change: the live project had `20261022120000_seed_code_review_agent.sql` (code-review line, applied by another session after discovery), which this branch didn't have. Copied byte-identical from `origin/main`; re-dry-run listed only ours. Applied. `backup/agents.after-step1.json`: `bug-fix`, `requires_repository=t`, required `["issue_number"]`, ARN `…runtime/bugfix_bug_fix-BiuPsdGSPK`, 3600/120/300, enabled. `schema_migrations` head: `20261024130000`, `20261022120000`. Live `agents`: bug-fix, code-review, dependency-update, security-analyst |
| 2 — panel check and live invoke | pending | n/a | n/a | | |
| 3 — records | pending | n/a | n/a | | |

status: in-progress (step 1 verified; step 2 needs @llipe in the panel)
