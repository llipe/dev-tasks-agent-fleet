#!/usr/bin/env bash
# rollback.sh: 20261024-code-review-runtime. Regenerated after each applied step.
# Reverts applied steps in reverse order. Usage: rollback.sh [--from N]
# (start at step N and continue down to step 1; default: all applied steps).
set -euo pipefail
FROM=""
[[ "${1:-}" == "--from" ]] && FROM="${2:?--from needs a step number}"
REPO_ROOT="$(git rev-parse --show-toplevel)"

revert_step_11f() {
  git -C "$REPO_ROOT" revert --no-edit f4c66c2
  echo "then: (cd agents/code-review && agentcore deploy -y)"
}

revert_step_11d() {
  # Redeploys the GPT-6.1 Sol config: run after revert_step_11b has restored agentcore.json.
  echo "after revert_step_11b: (cd agents/code-review && agentcore deploy -y)"
}

revert_step_11c() {
  aws iam put-role-policy --role-name agent-fleet-code-review-runtime --policy-name code-review-runtime \
    --policy-document "file://$REPO_ROOT/infra/changes/20261024-code-review-runtime/backup/role-policy.step5.json"
}

revert_step_11b() {
  git -C "$REPO_ROOT" revert --no-edit a1e9c32
}

revert_step_10() {
  aws bedrock delete-foundation-model-agreement --region us-east-1 --model-id openai.gpt-6.1-sol
}

revert_step_8() {
  supabase db query --linked "update agents set is_enabled = false, runtime_arn = 'pending-deploy:code-review' where slug = 'code-review'"
}

revert_step_7() {
  # runs.agent_id is ON DELETE RESTRICT: once any run exists the row can't be
  # deleted (and must not be: it would also cascade-delete webhook rules and
  # schedules). Then keep it disabled (step 8's revert) and leave the migration
  # recorded as applied.
  local n
  n="$(supabase db query --linked --output json "select count(*) as n from runs r join agents a on a.id = r.agent_id where a.slug = 'code-review'" | jq -r '.rows[0].n')"
  if [[ "$n" != "0" ]]; then
    echo "step 7: $n runs reference code-review; keeping the row disabled instead of deleting it"
    return 0
  fi
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

# Applied steps, newest first. --from N starts at step N (e.g. 7 or 11b).
STEPS=(11f 11d 11c 11b 10 8 7 6 5 4 2 1)
started=0
[[ "$FROM" == "${STEPS[0]}" || "${1:-}" != "--from" ]] && started=1
for n in "${STEPS[@]}"; do
  [[ "$n" == "$FROM" ]] && started=1
  (( started )) && "revert_step_${n}"
done
