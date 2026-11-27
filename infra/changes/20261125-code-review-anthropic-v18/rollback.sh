#!/usr/bin/env bash
# 20261125-code-review-anthropic-v18 — reverse order. Usage: rollback.sh --from N
# Regenerated after each applied step. Applied: steps 2, 5.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
D=infra/changes/20261125-code-review-anthropic-v18/backup
FROM="${2:-5}"
if [ "$FROM" -ge 5 ]; then
  # Step 5: restore the role policy captured in step 1 (ReadTwoSecrets + InvokeDeepSeekV32).
  aws iam put-role-policy --role-name agent-fleet-code-review-runtime --policy-name code-review-runtime \
    --policy-document "file://$D/role-policy.before.json"
fi
if [ "$FROM" -ge 2 ]; then
  # Step 2: revoke the key in the Anthropic Console first, then schedule the secret's deletion.
  aws secretsmanager delete-secret --region us-east-1 \
    --secret-id agent-fleet/prod/CODE_REVIEW_ANTHROPIC_API_KEY --recovery-window-in-days 7
fi
