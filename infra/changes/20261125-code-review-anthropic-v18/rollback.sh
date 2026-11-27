#!/usr/bin/env bash
# 20261125-code-review-anthropic-v18 — reverse order. Usage: rollback.sh --from N
# Regenerated after each applied step. Applied: steps 2, 5, 7.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
ROOT="$PWD"
D=infra/changes/20261125-code-review-anthropic-v18/backup
FROM="${2:-7}"
if [ "$FROM" -ge 7 ]; then
  # Step 7: redeploy runtime version 5's sources (plan "Rollback source"): app code f4443bd,
  # agents/code-review/agentcore from f4c66c2 (MODEL_ID=deepseek.v3.2, no ANTHROPIC_API_KEY_SECRET_ID).
  # Needs the interim policy (step 5) still in place, so bedrock:InvokeModel is allowed.
  W="$(mktemp -d)/cr-v5"
  git worktree add --detach "$W" f4443bd
  git -C "$W" checkout f4c66c2 -- agents/code-review/agentcore
  cp agents/code-review/agentcore/aws-targets.json "$W/agents/code-review/agentcore/"
  cp agents/code-review/agentcore/.cli/deployed-state.json "$W/agents/code-review/agentcore/.cli/"
  (cd "$W/agents/code-review/agentcore/cdk" && npm ci)
  (cd "$W/agents/code-review" && agentcore deploy -y --json)
  aws bedrock-agentcore-control get-agent-runtime --region us-east-1 \
    --agent-runtime-id codereview_code_review-g73KtjA3MT --output json > "$ROOT/$D/runtime.rolled-back.json"
  git worktree remove --force "$W"
fi
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
