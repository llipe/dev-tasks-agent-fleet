#!/usr/bin/env bash
# rollback.sh: 20261024-code-review-runtime. Regenerated after each applied step.
# Reverts applied steps in reverse order. Usage: rollback.sh [--from N]
# (start at step N and continue down to step 1).
set -euo pipefail
FROM=1
[[ "${1:-}" == "--from" ]] && FROM="${2:?--from needs a step number}"
REPO_ROOT="$(git rev-parse --show-toplevel)"

revert_step_6() {
  aws iam put-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime \
    --policy-document "file://$REPO_ROOT/infra/changes/20261024-code-review-runtime/backup/panel-invoke-policy.before.json"
}

revert_step_5() {
  aws iam put-role-policy --role-name agent-fleet-code-review-runtime --policy-name code-review-runtime \
    --policy-document "file://$REPO_ROOT/infra/changes/20261024-code-review-runtime/backup/role-policy.step2.json"
}

revert_step_4() {
  aws cloudformation delete-stack --region us-east-1 --stack-name AgentCore-codereview-default
  aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name AgentCore-codereview-default
  aws ecr delete-repository --region us-east-1 --repository-name codereview/code_review --force || true
}

revert_step_2() {
  aws iam delete-role-policy --role-name agent-fleet-code-review-runtime --policy-name code-review-runtime
  aws iam delete-role --role-name agent-fleet-code-review-runtime
}

revert_step_1() {
  # Repo only: the AgentCore project, role files, and D-58.
  git -C "$REPO_ROOT" revert --no-edit 676799b
}

for n in 6 5 4 2 1; do
  (( n <= FROM )) && "revert_step_${n}"
done
