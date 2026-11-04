#!/usr/bin/env bash
# 20261103-code-review-redeploy-v15 — append-only. No secret values.
set -euo pipefail
# Deploy checkout: main f4443bd plus the live AgentCore config from PR #476's branch.
git checkout origin/chore/code-review-wave-b-to-main -- agents/code-review/agentcore infra/changes/20261024-code-review-runtime
aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id codereview_code_review-g73KtjA3MT \
  --region us-east-1 --output json > infra/changes/20261103-code-review-redeploy-v15/backup/runtime.before.json
(cd agents/code-review/agentcore/cdk && npm ci && npm test)
(cd agents/code-review && agentcore deploy --diff --json)
(cd agents/code-review && agentcore deploy -y --json)   # 2026-11-04T01:49Z success
