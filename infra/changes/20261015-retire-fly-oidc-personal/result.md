# Result — 20261015-retire-fly-oidc-personal

| Step | Status | Backup id | Restore command | Verified at | Evidence |
| --- | --- | --- | --- | --- | --- |
| 1 — delete IAM OIDC provider `oidc.fly.io/personal` | verified | `backup/oidc-provider-personal.before.json` | `rollback.sh` | 2026-10-15T18:16-03:00 | `list-open-id-connect-providers` now lists only `oidc.fly.io/felipe-mallea` and `token.actions.githubusercontent.com`. Live check from Machine `845de5f2e502e8` as uid 1001: Fly OIDC → `AssumeRoleWithWebIdentity` → HTTP 200 `assumed-role/panel-agentcore-invoke/probe-280` (credentials discarded) |

status: verified
