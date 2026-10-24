# Result: 20261024-bug-fix-agent-seed

| Step | Status | Backup id | Restore command | Verified at | Evidence |
| ---- | ------ | --------- | --------------- | ----------- | -------- |
| 1 — apply seed migration | verified | `backup/agents.before.json`, `backup/schema_migrations.before.json` | `rollback.sh --from 1` | 2026-10-24T18:17:44Z | First attempt (18:14:41Z) refused by the CLI with no change: the live project had `20261022120000_seed_code_review_agent.sql` (code-review line, applied by another session after discovery), which this branch didn't have. Copied byte-identical from `origin/main`; re-dry-run listed only ours. Applied. `backup/agents.after-step1.json`: `bug-fix`, `requires_repository=t`, required `["issue_number"]`, ARN `…runtime/bugfix_bug_fix-BiuPsdGSPK`, 3600/120/300, enabled. `schema_migrations` head: `20261024130000`, `20261022120000`. Live `agents`: bug-fix, code-review, dependency-update, security-analyst |
| 2 — panel check and live invoke | verified | n/a | n/a | 2026-10-24T18:30:51Z | @llipe: `/agents/bug-fix/invoke` form shows `issue_number` as the only required field; run `436458f2-efa1-4f19-9e24-6b479853756e` (manual, `issue_number: 119`), `succeeded` / `not_applicable`, result `not yet implemented` (the runtime stub's reply, so the panel reached the seeded ARN), 496 ms, `backup/run-step2.json`. Defaults filled by the panel (budgets, caps, status names). `runtime_invocation_id`/`session_id` empty, as for every run fleet-wide (0/40), so not this story. Rollback by row delete is now blocked by `ON DELETE RESTRICT` (accepted in the plan) |
| 3 — records | verified | n/a | n/a | 2026-10-24T18:35Z | this file, `commands.sh`, `rollback.sh`; tasks 5.6, 5.7, 5.10 checked |

status: verified (bug-fix seed row live; panel invoke reaches runtime v6)
