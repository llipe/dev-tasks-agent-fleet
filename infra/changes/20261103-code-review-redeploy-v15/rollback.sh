#!/usr/bin/env bash
# 20261103-code-review-redeploy-v15 — reverse order. Usage: rollback.sh --from N
set -euo pipefail
FROM="${2:-3}"
if [ "$FROM" -ge 3 ]; then
  # Step 3: redeploy runtime v4's code (main d20d73a = image 3ad57df7…) with the same AgentCore config.
  git worktree add /tmp/cr-rollback d20d73a
  (cd /tmp/cr-rollback && git checkout origin/chore/code-review-wave-b-to-main -- agents/code-review/agentcore infra/changes/20261024-code-review-runtime)
  echo '[{ "name": "default", "account": "755641879575", "region": "us-east-1" }]' \
    > /tmp/cr-rollback/agents/code-review/agentcore/aws-targets.json
  (cd /tmp/cr-rollback/agents/code-review && agentcore deploy --diff --json && agentcore deploy -y --json)
fi
