# Result: 20261127-bug-fix-node-redeploy

| Step | Status | Backup id | Restore command | Verified at | Evidence |
| ---- | ------ | --------- | --------------- | ----------- | -------- |
| 1 — redeploy | verified | `backup/runtime.before.json` (v7, image `dac1d525…`) | `rollback.sh --from 1` | 2026-11-27T14:47:40Z | runtime **v8 READY**, image `…:2d0f0a947154…`; roleArn, env (8 vars, `FIX_LOOP_ENABLED=0`) and all other fields identical to the backup (`backup/runtime.after.json`); the diff preview matched (image only) |
| 2 — regression invoke (smoke, default Node) | skipped(panel invoke never reached the server: two submits by @llipe at ~14:48Z and ~14:50Z produced no `/api/agents/bug-fix/invoke` request in the Fly logs and no `runs` row; the dialog's client-side checks blocked it. @llipe chose to go to Step 3 via `/bugfix`. Tracked as a separate panel finding) | n/a | n/a | n/a | `flyctl logs` 14:47Z..15:00Z: only webhook deliveries and code-review invokes |
| 3 — the failed case, on riel (Node 24) | verified | n/a | n/a | 2026-11-27T18:50:11Z | run `e7b70ade-7f9d-4be0-807c-dea6bd6b8583` (webhook `/bugfix` by @llipe on `llipe/riel#1349`, 18:47:57Z..18:50:07Z, 129.6 s): `succeeded`/`needs_review`, `result={summary:"fix loop not yet enabled", reason:"fix_loop_disabled"}`. Steps `preflight`→`refuse`→`checkout`→`claim`, all `succeeded`. Checkout: clone of `caf58feb`, link protection 1/1, **`repo gate passed (js, pnpm, node 24.22.2)`, `node_source=.nvmrc`**, then **`installed with pnpm install --frozen-lockfile`**: the `ERR_PNPM_UNSUPPORTED_ENGINE` of `fb717a51` is gone. Issue #1349: exactly 2 new bot comments (claim, disposition), still open, labels and assignees unchanged. Leak scan over `backup/`: 0. `backup/run-step3*.json`, `backup/issue-1349-comments.json` |
| 4 — records | verified | n/a | n/a | 2026-11-27T19:05Z | this file, `commands.sh`, `rollback.sh`; committed on `chore/471-bug-fix-node-redeploy`, draft PR into `main` |

## Observations (Step 3)

1. **`node_source` is `.nvmrc`, not `engines.node` as the plan expected.** This is correct per spec v2.9 §8.7: `engines.node` (`>=24.21.0 <25`) narrows the candidates to 24.22.2, and riel's `.nvmrc` (`24.21.0`, major 24) then picks among them. `node_source` names whatever made the final pick. The plan's expectation was wrong; the code is right.
2. **All five base gates fail on riel.** These are recorded in `metrics.gates_base` and don't stop a Wave A run. None of them comes from the Node selection or this deploy:
   - `test`, `lint`, `format:check` and `typecheck` all fail only in `@riel/creators`. That workspace member is a Python package whose scripts are `uv run …`. A root `package.json` makes the repo JS, so the sandbox sets up no Python toolchain or `.venv` for it.
   - `audit` fails with `EAI_AGAIN registry.npmjs.org`: the gate sandbox has no network, and `pnpm audit` needs the registry.

   Both will matter in Wave B, when base gates decide red-to-green. They are follow-ups, not part of this change.
3. **No 👀 or 😕 reaction on the `/bugfix` comment** ("reaction skipped"). The run's `params` carry no `trigger_comment_id`, and `fb717a51` had none either, so the webhook rule doesn't forward it. This predates the deploy.
4. **Panel invoke (Step 2)** never reached `/api/agents/bug-fix/invoke`. The cause wasn't diagnosed; it is a separate panel issue.

status: verified (runtime v8 live; per-repo Node selection verified on AgentCore against the `fb717a51` failure: riel installs on Node 24.22.2)
