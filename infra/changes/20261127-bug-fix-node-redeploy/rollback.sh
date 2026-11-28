#!/usr/bin/env bash
# Regenerated after each applied step; reverts in reverse order. Usage: rollback.sh [--from N]
set -euo pipefail
FROM=99; [ "${1:-}" = "--from" ] && FROM="${2:?step number}"
# Step 1 — redeploy the v7 source (db7b4ec, image dac1d525), then restore the working tree.
if [ "$FROM" -ge 1 ]; then
  git checkout db7b4ec -- agents/bug-fix
  (cd agents/bug-fix && agentcore deploy -y)
  git checkout HEAD -- agents/bug-fix
fi
