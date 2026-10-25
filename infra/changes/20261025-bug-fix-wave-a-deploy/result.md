# Result: 20261025-bug-fix-wave-a-deploy

| Step | Status | Backup id | Restore command | Verified at | Evidence |
| ---- | ------ | --------- | --------------- | ----------- | -------- |
| 1 — redeploy | verified | `backup/runtime.before.json` (v6, image `5b24b169…`) | `rollback.sh --from 1` | 2026-10-25T22:35:30Z | runtime **v7 READY**, image `…:dac1d52558028a04…`, roleArn `agent-fleet-bug-fix-runtime` unchanged, env = the 6 existing + `FIX_LOOP_ENABLED=0` + `PANEL_BASE_URL=https://dt-agent-fleet-panel.fly.dev`; diff preview matched (image + those 2 env vars only) |
| 2 — live invoke (11.7) | verified | n/a | n/a | 2026-10-25T22:46:24Z | run `a76a6c8c-4720-4580-8c65-520460e647f8` (manual, `llipe/bug-fix-smoke#1`): `succeeded`/`needs_review`, `result={summary:"fix loop not yet enabled", reason:"fix_loop_disabled"}`, 14.7 s. Steps `preflight`→`refuse`→`checkout`→`claim` (no `fix`), all `succeeded`. `metrics`: `issue_number=1`, `step_timings_ms` (1372/1144/6824/2303), `gates_base` 5/5 pass (`pnpm install --frozen-lockfile`). Events: **`fs.protected_hardlinks=1 fs.protected_symlinks=1` on AgentCore** (#446), clone of `27feaa1`, 10 entries materialized as fixer, repo gate passed (js, pnpm). Issue #1: exactly 2 comments by `devtasks-agent-fleet[bot]` (claim marker with panel link; disposition "fix loop not yet enabled"), 0 reactions, no labels/assignees, still open. Leak scan 0. `backup/run-step2*.json`, `backup/issue-1-comments.txt` |
| 3 — records | verified | n/a | n/a | 2026-10-25T22:55Z | this file; tasks 11.6, 11.7 checked |

status: verified (runtime v7 live; Wave A AC5 verified on AgentCore)
