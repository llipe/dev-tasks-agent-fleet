# Result — 20261024-code-review-runtime

| Step                                                  | Status  | Backup id                                  | Restore command                                                   | Verified at | Evidence |
| ----------------------------------------------------- | ------- | ------------------------------------------ | ----------------------------------------------------------------- | ----------- | -------- |
| 1 — deploy the runtime                                | planned | n/a (new stack)                            | delete stack `AgentCore-codereview-default`                       | —           | —        |
| 2 — Bedrock model access, `MODEL_ID` confirmed        | planned | n/a                                        | disable model access                                              | —           | —        |
| 3 — panel invoke policy                               | planned | `backup/runtime-invoke-policy.before.json` | `put-role-policy` with the backup                                 | —           | —        |
| 4 — GitHub App Issues read                            | planned | `backup/app-permissions.before.json`       | remove the permission (only if added here)                        | —           | —        |
| 5 — prod seed migration apply (explicit confirmation) | planned | `backup/agents-row.before.json`            | `delete from agents where slug = 'code-review'` (no runs yet)     | —           | —        |
| 6 — enable row (D-39, one update)                     | planned | row from step 5                            | `update agents set is_enabled = false where slug = 'code-review'` | —           | —        |
| 7 — panel invoke verification                         | planned | n/a                                        | n/a                                                               | —           | —        |
| 8 — record and close                                  | planned | n/a                                        | n/a                                                               | —           | —        |

status: planned
