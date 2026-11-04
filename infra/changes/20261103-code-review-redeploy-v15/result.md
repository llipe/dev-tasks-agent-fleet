# Result — 20261103-code-review-redeploy-v15

| Step | Status | Backup id | Restore command | Verified at | Evidence |
| ---- | ------ | --------- | --------------- | ----------- | -------- |
| 1 — backup (read) | verified | `backup/runtime.before.json` (v4, image `3ad57df7…`) | n/a | 2026-11-04T01:40Z | READY v4; env (5 vars) and role as in `agentcore.json` |
| 2 — tests and diff (read) | verified | `backup/deploy-diff.json` | n/a | 2026-11-04T01:46Z | CDK 15/15; one resource changed, `ContainerBuildTrigger` image `3ad57df7…` → `e7559840…` |
| 3 — deploy app | verified | v4 / image `3ad57df7…` (in ECR) | `rollback.sh --from 3` | 2026-11-04T01:49:21Z | `agentcore deploy -y` success; `backup/runtime.after.json`: READY, v4 → v5, image `e7559840…`, env and role unchanged |

status: verified (a live `/review` on v5 runs as part of S-215)
