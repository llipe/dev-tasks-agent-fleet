# Change plan: 20261024-bug-fix-spike-probe

- **ChangeId:** `infra/changes/20261024-bug-fix-spike-probe/`
- **Story / issue:** S-182 (#364), phase 2 (tasks 3.5, 3.6–3.8, 3.15, 3.10). Branch `story/S-182-sandbox-spike`, Draft PR #443 → `integration/bug-fix-agent-wave-a`.
- **Environment:** `prod`. AWS account `755641879575`, `us-east-1`. Runtime `bugfix_bug_fix-BiuPsdGSPK` (currently v1, the S-180 stub).
- **Identity:** AWS root, accepted by @llipe (same as `20261023-bug-fix-runtime`).
- **Approval status:** plan **approved by @llipe on 2026-10-24**. Each step still needs its own approval.

## Cost

| Item | Estimate | Source | Status |
| ---- | -------- | ------ | ------ |
| 2 CodeBuild ARM builds (steps 1, 3) | a few cents | https://aws.amazon.com/codebuild/pricing/ | Covered by the 2026-10-23 approval (CodeBuild per deploy) |
| One probe invocation (runtime CPU and memory seconds, CloudWatch logs) | under $0.01 | https://aws.amazon.com/bedrock/agentcore/pricing/ | Covered (usage-based) |
| Anthropic API for the `claude -p` deny checks | a few cents, within the $30/month cap | console.anthropic.com | Covered |

No new recurring cost.

## Steps

### Step 1: deploy the #443 image with `ALLOW_PROBE=1`
- **Kind:** deploy app · **Tool:** agentcore (CDK) · **Touches state:** yes (runtime v1 → v2)
- **Backup:** record the current runtime version and image digest (`get-agent-runtime` → `backup/runtime.before.json`).
- **Forward:** on `story/S-182-sandbox-spike`, add `{ "name": "ALLOW_PROBE", "value": "1" }` to `envVars` of runtime `bug_fix` in `agents/bug-fix/agentcore/agentcore.json`, then `cd agents/bug-fix && agentcore deploy --diff -y` (preview), then `agentcore deploy -y`.
- **Verify:** READY; the version increased; the image digest changed; the env includes `ALLOW_PROBE=1`; `roleArn` is unchanged.
- **Revert:** remove `ALLOW_PROBE`, then `agentcore deploy -y` from the S-181 state (the `integration/bug-fix-agent-wave-a` tree at `242032d`).

### Step 2: run the probe on the deployed runtime (IC: tasks 3.6–3.8, 3.15)
- **Kind:** verification invocation · **Tool:** aws (`bedrock-agentcore invoke-agent-runtime`) · **Touches state:**
  - GitHub: one `[probe] bug-fix board probe` issue in `llipe/dev-tasks` and a temporary card on board #5, both removed or closed by the probe;
  - Anthropic: a few tokens.
- **Forward:** invoke with payload `{"run_id":"<uuid>","repository_org":"llipe","repository_name":"bug-fix-smoke","base_branch":"main","params":{},"__probe":true}`.
- **Verify:** every check in the returned summary is recorded as PASS or FAIL. Confirm afterwards that the probe issue is closed and that its card is gone from board #5.
- **Revert:** n/a. If cleanup failed, delete the card or close the issue by hand (recorded).

### Step 3: remove `ALLOW_PROBE` and redeploy (task 3.10)
- **Kind:** deploy app · **Tool:** agentcore · **Touches state:** yes (v2 → v3)
- **Forward:** remove `ALLOW_PROBE` from `agentcore.json`, then `agentcore deploy -y`.
- **Verify:** READY; the env has no `ALLOW_PROBE`; a probe invoke is refused (`PROBE_REFUSED`).
- **Revert:** n/a (this *is* the safe state).

### Step 4: records, spike verdict, commit
- **Kind:** repo operation · **Tool:** git · **Touches state:** no
- **Forward:** `commands.sh`, `rollback.sh`, `result.md`; fill in the deployed-run rows and the PASS/FAIL verdict in `workstream/spike-bug-fix-sandbox.md` (task 3.9); commit and push to #443.

## Plan change (approved by @llipe on 2026-10-24, after probe run 1)

Probe run 1 found `no_new_privs` set on AgentCore, so the `sudo` switch (D-109) can't work. D-110 replaces it: a root wrapper that drops to `fixer` with `setpriv`. The new order is:

- **Step 1b:** deploy the D-110 image (keeping `ALLOW_PROBE=1`).
- **Step 2b:** re-probe.
- **Step 3:** remove `ALLOW_PROBE` and redeploy.
- **Step 4:** records and verdict.

Each step still needs its own approval. Runtime v2 keeps `ALLOW_PROBE=1` until step 3.

## Exit rule (spec §12, D-105)

- **Any sandbox or isolation check fails:** the verdict is FAIL. Wave B (#373–#377) stays blocked, and the finding goes to `product-engineer` drift reconciliation.
- **Only the board checks fail:** set `BOARD_UPDATES_ENABLED=0` and route the finding to drift. Wave B is not blocked.
