#!/usr/bin/env bash
# 20261103-code-review-redeploy-v14 — reverse order; regenerated after each applied step.
# Usage: rollback.sh --from N
set -euo pipefail
FROM="${2:-3}"
if [ "$FROM" -ge 3 ]; then
  # Step 3: redeploy the previous code (Wave B tip 7894c1a = live image 7881c60e…, version 3).
  git worktree add /tmp/cr-rollback 7894c1a
  echo '[{ "name": "default", "account": "755641879575", "region": "us-east-1" }]' \
    > /tmp/cr-rollback/agents/code-review/agentcore/aws-targets.json
  (cd /tmp/cr-rollback/agents/code-review && agentcore deploy --diff --json && agentcore deploy -y --json)
fi
# Steps 1–2 are read-only: nothing to revert.
