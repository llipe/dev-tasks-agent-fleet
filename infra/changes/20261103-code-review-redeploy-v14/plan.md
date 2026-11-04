# Plan — 20261103-code-review-redeploy-v14

- **ChangeId:** `20261103-code-review-redeploy-v14`
- **Environment:** prod (`production: true`), AWS account `755641879575`, `us-east-1`
- **Identity:** `aws sts get-caller-identity` → `arn:aws:iam::755641879575:root` (matches `infra/environments.yaml`; root is broader than a deploy needs — noted)
- **Goal:** redeploy the code-review AgentCore runtime (`codereview_code_review-g73KtjA3MT`, stack `AgentCore-codereview-default`) with `main` at d20d73a: #473 (`Refs #N` linked issues, D-58) and #474 (PRD v1.4 context selection).
- **Deploy source:** `main` d20d73a + `agents/code-review/agentcore/` and `infra/changes/20261024-code-review-runtime/` from `integration/code-review-agent-wave-b` (7894c1a), byte-identical to the live config (runbook: never deploy an `agentcore.json` that differs from live). Only the app code changes.
- **Out of scope:** the params migration `20261103120000_seed_code_review_agent.sql` (separate later step). Safe without it: the runtime applies the new params' defaults itself.
- **Cost:** no new resources. One extra selection Converse call per review on `deepseek.v3.2` (a few thousand tokens); estimate < $1/month at current volume, unverified pricing (source: token size of the request, PRD FR-32). **APPROVAL REQUIRED** — approved by Llipe on 2026-11-03 ("Ok with the cost, deploy").
- **Approval:** plan and apply approved by Llipe on 2026-11-03.

| Step | Kind | Tool | Touches state | Backup | Forward | Verify | Revert |
| ---- | ---- | ---- | ------------- | ------ | ------- | ------ | ------ |
| 1 | backup (read) | aws | no | n/a | `get-agent-runtime` → `backup/runtime.before.json` | status READY, env and role equal `agentcore.json` | n/a |
| 2 | deploy check (read) | agentcore, npm | no | n/a | CDK tests; `agentcore deploy --diff --json` → `backup/deploy-diff.json` | 15/15 tests; diff = container image source hash only | n/a |
| 3 | deploy app | agentcore (CDK) | yes | step 1 (version 3, image `7881c60e…`, still in ECR) | `agentcore deploy -y --json` | runtime READY on a new version with the new image; env and role unchanged | `rollback.sh --from 3`: redeploy from Wave B 7894c1a |
| 4 | verify | aws, panel | no | n/a | a `/review` run on a PR | run `succeeded`, metrics carry `selection_status` | n/a |
