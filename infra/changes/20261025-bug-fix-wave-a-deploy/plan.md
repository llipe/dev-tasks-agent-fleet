# Plan: 20261025-bug-fix-wave-a-deploy

- **ChangeId:** `infra/changes/20261025-bug-fix-wave-a-deploy/`
- **Story:** S-190 (#372), tasks 11.6 (redeploy) and 11.7 (manual/IC invoke), which close Wave A AC5.
- **Environment:** production. AWS account `755641879575` (personal), `us-east-1`. Runtime `bugfix_bug_fix-BiuPsdGSPK`, stack `AgentCore-bugfix-default`. Panel `dt-agent-fleet-panel.fly.dev`. Supabase `hegxeycmbmjfgzqpdiik`.
- **Identity:** AWS root by explicit user acceptance (as in S-181 and S-182). `aws sts get-caller-identity` returned 755641879575 at 2026-10-25T22:13Z.
- **Source:** `integration/bug-fix-agent-wave-a` @ `db7b4ec`, which includes S-184..S-190.
- **Approval:** each step is approved by @llipe.

## Cost

About $0 beyond current usage: one CodeBuild image build and one short run on the existing runtime. The run makes no Anthropic call (the fix loop is off).

## Discovery (read-only, 2026-10-25T22:13:21Z)

- Runtime v6 READY. Image `…:5b24b169…`. Role `agent-fleet-bug-fix-runtime`. Six env vars, with no `ALLOW_PROBE`. Saved to `backup/runtime.before.json`.
- `agentcore deploy --diff`:
  - the image changes `5b24b169` → `dac1d525`;
  - Runtime `EnvironmentVariables` gains `FIX_LOOP_ENABLED` (S-190) and `PANEL_BASE_URL` (S-188).
  - Nothing else changes: no IAM, role, KMS or secret.
- Fixture: `llipe/bug-fix-smoke` (private), installed on the App and synced into `repositories` (enabled, `main`). Test issue `llipe/bug-fix-smoke#1`.

## Steps

### Step 1: redeploy (11.6)
- **Kind:** deploy app. **Tool:** agentcore CLI 0.28.0 (CDK). **Touches state:** yes (production).
- **Backup:** `backup/runtime.before.json` (v6, image `5b24b169…`).
- **Forward:** `cd agents/bug-fix && agentcore deploy -y`.
- **Verify:** `get-agent-runtime` shows v7 READY, the new image `…dac1d525…`, the same roleArn, and env = the six existing vars plus `FIX_LOOP_ENABLED=0` and `PANEL_BASE_URL`.
- **Revert:** redeploy the v6 source, i.e. the S-182 tree that built image `5b24b169…`: `git checkout 8e4083c -- agents/bug-fix && (cd agents/bug-fix && agentcore deploy -y)`, then `git checkout HEAD -- agents/bug-fix`. Verify v8 READY on image `…5b24b169…` with no `FIX_LOOP_ENABLED` or `PANEL_BASE_URL`.

### Step 2: live invoke (11.7)
- **Kind:** verification. **Tool:** panel (browser, @llipe) plus supabase/gh (read). **Touches state:** yes. It creates one `runs` row and posts two comments on the fixture issue.
- **Forward:** @llipe opens `/agents/bug-fix/invoke`, picks `llipe/bug-fix-smoke`, sets `issue_number = 1`, and submits.
- **Verify** (per the runbook's "Wave A run" section):
  - steps `preflight`, `refuse`, `checkout`, `claim`, with no `fix`;
  - exactly two new comments on #1: the claim marker with the panel link, then the disposition "Why it stopped: fix loop not yet enabled";
  - no reaction (manual invoke has no trigger comment); no label, assignee or board change;
  - the run ends `succeeded`/`needs_review` with `result = {summary: "fix loop not yet enabled", reason: "fix_loop_disabled"}`;
  - `runs.metrics` has `issue_number` and `step_timings_ms`;
  - there is a `run_event` for link protection (`fs.protected_hardlinks`/`protected_symlinks`, needed for #446).
- **Revert:** none needed. The comments and run row are the audit trail. A later `/bug-fix` on #1 is unaffected, because this run's claim is closed by its disposition.

### Step 3: records
- Write `commands.sh`, `rollback.sh` and `result.md`; check 11.6 and 11.7; commit; open a draft PR into the integration branch.
