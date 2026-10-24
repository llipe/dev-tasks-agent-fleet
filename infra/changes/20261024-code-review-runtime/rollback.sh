#!/usr/bin/env bash
# rollback.sh: 20261024-code-review-runtime. Regenerated after each applied step.
# Reverts applied steps in reverse order. Usage: rollback.sh [--from N]
# (start at step N and continue down to step 1).
set -euo pipefail
FROM=1
[[ "${1:-}" == "--from" ]] && FROM="${2:?--from needs a step number}"
REPO_ROOT="$(git rev-parse --show-toplevel)"

revert_step_10() {
  aws bedrock delete-foundation-model-agreement --region us-east-1 --model-id openai.gpt-6.1-sol
}

revert_step_8() {
  supabase db query --linked "update agents set is_enabled = false, runtime_arn = 'pending-deploy:code-review' where slug = 'code-review'"
}

revert_step_7() {
  # Only while no runs reference the agent; otherwise disable it instead (step 8's revert).
  supabase db query --linked "delete from agents where slug = 'code-review'"
  supabase db query --linked "delete from supabase_migrations.schema_migrations where version = '20261022120000'"
}

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

for n in 10 8 7 6 5 4 2 1; do
  (( n <= FROM )) && "revert_step_${n}"
done
