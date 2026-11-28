# Plan: 20261127-bug-fix-node-redeploy

- **ChangeId:** `infra/changes/20261127-bug-fix-node-redeploy/`
- **Issue:** #471 (PR #472, merged): the image ships Node 22, 24 and 26 and picks one per repo.
- **Environment:** production. AWS account `755641879575` (personal), `us-east-1`. Runtime `bugfix_bug_fix-BiuPsdGSPK`, stack `AgentCore-bugfix-default`. Panel `dt-agent-fleet-panel.fly.dev`. Supabase `hegxeycmbmjfgzqpdiik`.
- **Identity:** AWS root by explicit user acceptance (as in 20261025-bug-fix-wave-a-deploy). `aws sts get-caller-identity` returned `755641879575` / `root` at 2026-11-27T14:37Z.
- **Source:** `main` @ `256e9ef`. Since the v7 source (`db7b4ec`), the only `agents/bug-fix` commits are #471's: `4ebfe69`, `b824346`, `0fbe74e`.
- **Approval:** @llipe approved the plan and the ~$0.01/month ECR cost on 2026-11-27. Each step is approved separately.
- **Runbook (FR-49a):** `docs/runbooks/bug-fix-agent.md` already covers this redeploy and the Node selection (shipped with #472). No new change kind.

## Cost

- **One-off:** one CodeBuild ARM64 image build, a few cents.
- **Recurring:** about **$0.01/month** more ECR storage. Today's image is about 342 MB compressed, and the two extra Node tarballs add about 100 MB. The ECR price is $0.10/GB-month, and the lifecycle policy keeps the last 10 images. **APPROVAL REQUIRED** (threshold $0).
- **The run:** no Anthropic call (`FIX_LOOP_ENABLED=0`).

## Discovery (read-only, 2026-11-27T14:37Z)

- **Runtime:** v7 READY, image `…:dac1d525…`, role `agent-fleet-bug-fix-runtime`. Eight env vars: `FIX_LOOP_ENABLED=0`, `BOARD_UPDATES_ENABLED=1`, `MODEL_ID`, `PANEL_BASE_URL` and the secret-ID/URL vars. Saved to `backup/runtime.before.json`.
- **`agentcore deploy --diff`:** the only change is the image, `dac1d525` → `2d0f0a94`. There are no IAM, role, env, KMS or secret changes.
- **Failed run `fb717a51-1df2-47a3-8d58-84d3966a433e`:**
  - Webhook `/bugfix` on `llipe/riel#719`, 2026-10-30.
  - Ended `failed`/`INSTALL_FAILED`: `ERR_PNPM_UNSUPPORTED_ENGINE`, expected `>=24.21.0 <25`, got `v26.12.1`.
  - riel declares `engines.node: ">=24.21.0 <25"` and `.npmrc` sets `engine-strict=true`.
  - **#719 is now CLOSED.** It was fixed through riel PR #732, so a re-run on it ends `not_applicable`/`closed` before the repo gate. The re-run therefore targets an open riel issue instead (Step 3).

## Steps

### Step 1: redeploy
- **Kind:** deploy app. **Tool:** agentcore CLI 0.28.0 (CDK; the Container build runs in CodeBuild). **Touches state:** yes (production).
- **Backup:** `backup/runtime.before.json` (v7, image `dac1d525…`).
- **Forward:** `cd agents/bug-fix && agentcore deploy -y`, from `main` @ `256e9ef`.
- **Verify:** `get-agent-runtime` shows:
  - v8 READY on image `…2d0f0a94…`;
  - the same roleArn;
  - env identical to the backup.
- **Revert:** redeploy the v7 source: `git checkout db7b4ec -- agents/bug-fix && (cd agents/bug-fix && agentcore deploy -y)`, then `git checkout HEAD -- agents/bug-fix`. Verify v9 READY on image `…dac1d525…`.

### Step 2: regression invoke on the default Node
- **Kind:** verification. **Tool:** panel (browser, @llipe), plus supabase and gh reads. **Touches state:** yes: one `runs` row and two comments on the fixture issue.
- **Forward:** @llipe invokes `llipe/bug-fix-smoke`, `issue_number = 1`, from `/agents/bug-fix/invoke`. The repo has no `engines`, so it takes the default Node.
- **Verify:**
  - the run ends `succeeded`/`needs_review`, reason `fix_loop_disabled`;
  - the `checkout` event says `repo gate passed (js, pnpm, node 26.12.1)` with `node_source=default`;
  - install passes;
  - exactly two new bot comments on #1.
- **Revert:** none needed. The comments and the run row are the audit trail, as in 20261025.

### Step 3: the failed case, on riel (Node 24)
- **Kind:** verification. **Tool:** GitHub `/bugfix` comment (webhook path, like `fb717a51`) or a panel invoke, by @llipe. **Touches state:** yes: one `runs` row, a claim comment (plus 👀 on a webhook trigger) and a disposition comment on `llipe/riel#1349` (chosen by @llipe).
- **Forward:** @llipe comments `/bugfix` on `llipe/riel#1349`. It must have no open linked PR.
- **Verify:**
  - the run ends `succeeded`/`needs_review`, reason `fix_loop_disabled`, not `INSTALL_FAILED`;
  - the `checkout` event says `node 24.22.2` with `node_source=engines.node`;
  - `pnpm install --frozen-lockfile` passes in the sandbox;
  - `gates_base` is recorded;
  - no label, assignee or issue edit.
- **Revert:** none needed (the audit trail). The disposition closes the run's claim, so a later `/bugfix` is unaffected.

### Step 4: records
- Write `commands.sh`, `rollback.sh` and `result.md`, commit on `chore/471-bug-fix-node-redeploy`, and open a draft PR.
