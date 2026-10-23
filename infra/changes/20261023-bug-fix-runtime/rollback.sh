#!/usr/bin/env bash
# Regenerated after each applied step; reverts in reverse order. Usage: rollback.sh [--from N]
set -euo pipefail
FROM=99; [ "${1:-}" = "--from" ] && FROM="${2:?step number}"

# Step 5 — delete IAM role agent-fleet-bug-fix-runtime (inline policy first)
if [ "$FROM" -ge 5 ]; then
  aws iam delete-role-policy --role-name agent-fleet-bug-fix-runtime --policy-name bug-fix-runtime
  aws iam delete-role --role-name agent-fleet-bug-fix-runtime
fi
# Step 3 — delete secret agent-fleet/prod/GITHUB_PROJECTS_TOKEN (step 4 operator value goes with it; also revoke the PAT on GitHub)
if [ "$FROM" -ge 3 ]; then
  aws secretsmanager delete-secret --region us-east-1 --secret-id agent-fleet/prod/GITHUB_PROJECTS_TOKEN --force-delete-without-recovery
fi
# Step 1 — delete secret agent-fleet/prod/ANTHROPIC_API_KEY (step 2 operator value goes with it; also revoke the key in the Anthropic console)
if [ "$FROM" -ge 1 ]; then
  aws secretsmanager delete-secret --region us-east-1 --secret-id agent-fleet/prod/ANTHROPIC_API_KEY --force-delete-without-recovery
fi
