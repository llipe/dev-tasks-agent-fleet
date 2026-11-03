#!/usr/bin/env bash
# 20261103-code-review-redeploy-v14 — append-only. No secret values.
set -euo pipefail
# Step 1 (read): backup
aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id codereview_code_review-g73KtjA3MT \
  --region us-east-1 --output json > infra/changes/20261103-code-review-redeploy-v14/backup/runtime.before.json
# Step 2 (read): tests and diff, from the deploy checkout (main d20d73a + Wave B agentcore/)
git checkout origin/integration/code-review-agent-wave-b -- agents/code-review/agentcore infra/changes/20261024-code-review-runtime
(cd agents/code-review/agentcore/cdk && npm ci && npm test)
(cd agents/code-review && agentcore deploy --diff --json)
# Step 3 (apply)
(cd agents/code-review && agentcore deploy -y --json)
