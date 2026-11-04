# Plan — 20261103-code-review-redeploy-v15

- **ChangeId:** `20261103-code-review-redeploy-v15`
- **Environment:** prod, AWS account `755641879575`, `us-east-1`; identity `arn:aws:iam::755641879575:root` (`aws sts get-caller-identity`).
- **Goal:** redeploy the code-review runtime (`codereview_code_review-g73KtjA3MT`, stack `AgentCore-codereview-default`) with `main` f4443bd: #477, PRD v1.5 FR-5 (D-67), full copies for code files only, before the spec.
- **Deploy source:** `main` f4443bd + `agents/code-review/agentcore/` and `infra/changes/20261024-code-review-runtime/` from PR #476's branch (the live config), per `docs/runbooks/code-review-deployment.md`.
- **Cost:** none new (same runtime; full code files can make prompts somewhat larger on review, within `max_context_tokens`).
- **Approval:** Llipe, 2026-11-03 ("Ok, redeploy"), after #477 merged.

| Step | Kind | Tool | Touches state | Backup | Forward | Verify | Revert |
| ---- | ---- | ---- | ------------- | ------ | ------- | ------ | ------ |
| 1 | backup (read) | aws | no | n/a | `get-agent-runtime` → `backup/runtime.before.json` | READY v4, image `3ad57df7…` | n/a |
| 2 | deploy check (read) | agentcore, npm | no | n/a | CDK tests; `agentcore deploy --diff --json` → `backup/deploy-diff.json` | 15/15; image hash only | n/a |
| 3 | deploy app | agentcore (CDK) | yes | step 1 (v4 image in ECR) | `agentcore deploy -y --json` | READY on a new version, new image, env and role unchanged | `rollback.sh --from 3` |
