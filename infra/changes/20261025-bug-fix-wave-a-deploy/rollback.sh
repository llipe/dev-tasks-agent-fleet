#!/usr/bin/env bash
# Regenerated after each applied step; reverts in reverse order. Usage: rollback.sh [--from N]
set -euo pipefail
FROM=99; [ "${1:-}" = "--from" ] && FROM="${2:?step number}"
# Step 1 — redeploy the v6 source (S-182 tree, image 5b24b169), then restore the working tree.
if [ "$FROM" -ge 1 ]; then
  git checkout 8e4083c -- agents/bug-fix
  (cd agents/bug-fix && agentcore deploy -y)
  git checkout HEAD -- agents/bug-fix
fi
