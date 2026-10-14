#!/usr/bin/env bash
# Rollback for ChangeId 20261014-fly-oidc-issuer-trust. Reverse order; supports --from N.
set -euo pipefail
FROM="${2:-1}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# --- revert step 3b+3 --- (invoke-runtime inline policy; restores the pre-step-3 policy)
if [ "$FROM" -le 3 ]; then
  aws iam put-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime \
    --policy-document "file://$HERE/backup/runtime-invoke-policy.before.json"
fi
# --- revert step 2 --- (trust policy)
if [ "$FROM" -le 2 ]; then
  aws iam update-assume-role-policy --role-name panel-agentcore-invoke \
    --policy-document "file://$HERE/backup/trust-policy.before.json"
fi
# --- revert step 1 --- (OIDC provider)
if [ "$FROM" -le 1 ]; then
  aws iam delete-open-id-connect-provider \
    --open-id-connect-provider-arn arn:aws:iam::755641879575:oidc-provider/oidc.fly.io/felipe-mallea
fi
