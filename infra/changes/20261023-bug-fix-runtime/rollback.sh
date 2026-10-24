#!/usr/bin/env bash
# Regenerated after each applied step; reverts in reverse order. Usage: rollback.sh [--from N]
set -euo pipefail
FROM=99; [ "${1:-}" = "--from" ] && FROM="${2:?step number}"

# Step 9 — restore the panel invoke policy (also git-revert infra/agentcore-invoke-policy.json)
if [ "$FROM" -ge 9 ]; then
  aws iam put-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime --policy-document file://infra/changes/20261023-bug-fix-runtime/backup/panel-invoke-policy.before.json
fi
# Step 8b — restore EcrImageDecrypt to key/* (policy as after step 5b)
if [ "$FROM" -ge 8 ]; then
  aws iam put-role-policy --role-name agent-fleet-bug-fix-runtime --policy-name bug-fix-runtime --policy-document file://infra/changes/20261023-bug-fix-runtime/backup/role-policy.step7.json
fi
# Step 7 — destroy stack AgentCore-bugfix-default (runtime, ECR repo, KMS key scheduled for deletion, CodeBuild, Lambda)
if [ "$FROM" -ge 7 ]; then
  aws cloudformation delete-stack --region us-east-1 --stack-name AgentCore-bugfix-default
  aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name AgentCore-bugfix-default
  aws ecr delete-repository --region us-east-1 --repository-name bugfix/bug_fix --force 2>/dev/null || true   # only if retained
fi
# Step 5b — restore the role policy as it was after step 5 (before EcrImageDecrypt)
if [ "$FROM" -ge 6 ]; then
  aws iam put-role-policy --role-name agent-fleet-bug-fix-runtime --policy-name bug-fix-runtime --policy-document file://infra/changes/20261023-bug-fix-runtime/backup/role-policy.step5.json
fi
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
