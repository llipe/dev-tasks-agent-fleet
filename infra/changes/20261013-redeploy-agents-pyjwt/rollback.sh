#!/usr/bin/env bash
# Rollback for ChangeId 20261013-redeploy-agents-pyjwt. Reverse order; supports --from N.
# Redeploys the pre-#257 tree (feae3f8, PyJWT 2.13.0 / semgrep 1.177.0).
set -euo pipefail
FROM="${2:-1}"
WT=/tmp/revert-feae3f8
[ -d "$WT" ] || git worktree add "$WT" feae3f8

# --- revert step 3 --- (security-analyst → runtime v9 / image 760f3a2c…)
if [ "$FROM" -le 3 ]; then
  cp agents/security-analyst/agentcore/aws-targets.json "$WT/agents/security-analyst/agentcore/"
  ( cd "$WT/agents/security-analyst" && agentcore deploy -y )
fi

# --- revert step 1 --- (dependency-update → runtime v7 / image 0cc70f3b…)
if [ "$FROM" -le 1 ]; then
  cp agents/dependency-update/agentcore/aws-targets.json "$WT/agents/dependency-update/agentcore/"
  ( cd "$WT/agents/dependency-update" && agentcore deploy -y )
fi
