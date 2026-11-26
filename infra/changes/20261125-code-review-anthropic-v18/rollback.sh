#!/usr/bin/env bash
# 20261125-code-review-anthropic-v18 — reverse order. Usage: rollback.sh --from N
# Regenerated after each applied step. Applied: step 2.
set -euo pipefail
FROM="${2:-2}"
if [ "$FROM" -ge 2 ]; then
  # Step 2: revoke the key in the Anthropic Console first, then schedule the secret's deletion.
  aws secretsmanager delete-secret --region us-east-1 \
    --secret-id agent-fleet/prod/CODE_REVIEW_ANTHROPIC_API_KEY --recovery-window-in-days 7
fi
