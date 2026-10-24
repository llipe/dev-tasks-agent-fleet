# Result — 20261024-code-review-runtime

| Step                                                        | Status  | Backup id                                  | Restore command                                                   | Verified at | Evidence |
| ----------------------------------------------------------- | ------- | ------------------------------------------ | ----------------------------------------------------------------- | ----------- | -------- |
| 1 — confirm Sol profile ID, foundation-model ID, Regions    | planned | n/a                                        | revert the ID commit                                              | —           | —        |
| 2 — deploy the runtime + IAM check                          | planned | n/a (new stack)                            | delete stack `AgentCore-codereview-default`                       | —           | —        |
| 3 — panel invoke policy                                     | planned | `backup/runtime-invoke-policy.before.json` | `put-role-policy` with the backup                                 | —           | —        |
| 4 — GitHub App Issues read                                  | planned | `backup/app-permissions.before.json`       | remove the permission (only if added here)                        | —           | —        |
| 5 — prod migration preview (list confirmed by user)         | planned | `backup/migration-list.before.txt`         | n/a (read-only)                                                   | —           | —        |
| 6 — prod seed migration apply (confirmed list)              | planned | `backup/agents-row.before.json`            | `delete from agents where slug = 'code-review'` (no runs yet)     | —           | —        |
| 7 — enable row (D-39, one update)                           | planned | row from step 6                            | `update agents set is_enabled = false where slug = 'code-review'` | —           | —        |
| 8 — access-denied check before model access (TC-214-12)     | planned | n/a                                        | n/a                                                               | —           | —        |
| 9 — Bedrock model access (admin; Marketplace if applicable) | planned | pre-change access state                    | remove access / cancel subscription                               | —           | —        |
| 10 — panel invoke verification (TC-214-11)                  | planned | n/a                                        | n/a                                                               | —           | —        |
| 11 — record and close                                       | planned | n/a                                        | n/a                                                               | —           | —        |

status: planned
