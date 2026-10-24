#!/usr/bin/env bash
# Append-only command log for ChangeId 20261023-bug-fix-runtime.
# Secrets are referenced by name/ARN only; no values are ever recorded here.
set -euo pipefail

# Step 1 — create secret agent-fleet/prod/ANTHROPIC_API_KEY (no value) — applied 2026-10-23T21:54:28Z
aws secretsmanager describe-secret --region us-east-1 --secret-id agent-fleet/prod/ANTHROPIC_API_KEY   # pre-check: ResourceNotFoundException
aws secretsmanager create-secret --region us-east-1 --name agent-fleet/prod/ANTHROPIC_API_KEY \
  --description "bug-fix agent: dedicated, spend-capped Anthropic API key (D-50, D-58). Value set by the operator." \
  --tags Key=environment,Value=prod Key=owner,Value=llipe Key=ChangeId,Value=20261023-bug-fix-runtime Key=agent,Value=bug-fix

# Step 2 — operator (@llipe) put the Anthropic key value as a plaintext SecretString (outside this session); spend limit $30 USD/month.

# Step 3 — create secret agent-fleet/prod/GITHUB_PROJECTS_TOKEN (no value) — applied 2026-10-23T23:09:41Z
aws secretsmanager describe-secret --region us-east-1 --secret-id agent-fleet/prod/GITHUB_PROJECTS_TOKEN   # pre-check: ResourceNotFoundException
aws secretsmanager create-secret --region us-east-1 --name agent-fleet/prod/GITHUB_PROJECTS_TOKEN \
  --description "bug-fix agent: classic PAT, project scope only, Projects v2 board updates (D-99). Value set by the operator." \
  --tags Key=environment,Value=prod Key=owner,Value=llipe Key=ChangeId,Value=20261023-bug-fix-runtime Key=agent,Value=bug-fix

# Step 4 — operator (@llipe) put the classic PAT (project scope only, no expiry) as a plaintext SecretString (outside this session).

# Step 5 — create IAM role agent-fleet-bug-fix-runtime (no Bedrock; task 2.13 / DF-180-04) — applied 2026-10-23T23:15:17Z
aws iam get-role --role-name agent-fleet-bug-fix-runtime   # pre-check: NoSuchEntity
aws iam create-role --role-name agent-fleet-bug-fix-runtime \
  --assume-role-policy-document file://infra/changes/20261023-bug-fix-runtime/role-trust.json \
  --description "bug-fix AgentCore runtime execution role; no Bedrock (D-50, DF-180-04)" \
  --tags Key=environment,Value=prod Key=owner,Value=llipe Key=ChangeId,Value=20261023-bug-fix-runtime Key=agent,Value=bug-fix
aws iam put-role-policy --role-name agent-fleet-bug-fix-runtime --policy-name bug-fix-runtime \
  --policy-document file://infra/changes/20261023-bug-fix-runtime/role-policy.json

# Step 6 — point the agent at the role (repo + local target) — 2026-10-23
#   agents/bug-fix/agentcore/agentcore.json: runtime bug_fix gains "executionRoleArn": "arn:aws:iam::755641879575:role/agent-fleet-bug-fix-runtime"
#   agents/bug-fix/agentcore/aws-targets.json (local, gitignored): [{"name":"default","account":"755641879575","region":"us-east-1"}]

# Step 5b — add EcrImageDecrypt (kms:Decrypt via ECR only) to role agent-fleet-bug-fix-runtime — applied 2026-10-23T23:21:28Z
#   Approved by @llipe with the extra KMS cost (~$1.00/month) found in the step-7 diff preview.
aws iam get-role-policy --role-name agent-fleet-bug-fix-runtime --policy-name bug-fix-runtime --query PolicyDocument --output json > infra/changes/20261023-bug-fix-runtime/backup/role-policy.step5.json
aws iam put-role-policy --role-name agent-fleet-bug-fix-runtime --policy-name bug-fix-runtime \
  --policy-document file://infra/changes/20261023-bug-fix-runtime/role-policy.json

# Step 7 — deploy the bug-fix runtime (CDK, stack AgentCore-bugfix-default) — started 2026-10-23T23:21Z
#   preview: (cd agents/bug-fix && agentcore deploy --diff -y)
(cd agents/bug-fix && agentcore deploy -y)
#   applied 2026-10-23T23:25:06Z — stack AgentCore-bugfix-default; runtime bugfix_bug_fix-BiuPsdGSPK (READY, v1);
#   ECR bugfix/bug_fix (KMS key 429d9891-d1d3-4b6c-abe3-f8e8b5b6a2b8); image sha256:e810914db1788e4ffe35b756d980e2550c9f19cb9f36eb041bf4acffd404665a.
#   Side effect reported by the CLI: X-Ray transaction search enabled (account trace destination CloudWatchLogs, ACTIVE).

# Step 8a — permission simulation (read-only) — 2026-10-24; evidence backup/simulation-8a.json
#   aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::755641879575:role/agent-fleet-bug-fix-runtime --action-names <...> --resource-arns <...>
# Step 8b — narrow EcrImageDecrypt to the repository key — applied 2026-10-24T00:35:46Z
aws iam get-role-policy --role-name agent-fleet-bug-fix-runtime --policy-name bug-fix-runtime --query PolicyDocument --output json > infra/changes/20261023-bug-fix-runtime/backup/role-policy.step7.json
aws iam put-role-policy --role-name agent-fleet-bug-fix-runtime --policy-name bug-fix-runtime \
  --policy-document file://infra/changes/20261023-bug-fix-runtime/role-policy.json   # Resource: key/429d9891-d1d3-4b6c-abe3-f8e8b5b6a2b8 (kms:ViaService ecr)

# Step 9 — panel invoke policy: add the bug-fix runtime + DEFAULT endpoint — applied 2026-10-24T00:37:02Z
aws iam get-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime --query PolicyDocument --output json > infra/changes/20261023-bug-fix-runtime/backup/invoke-runtime.before.json
aws iam put-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime --policy-document file://infra/agentcore-invoke-policy.json

# Step 10 — operator (@llipe): GitHub App permission Issues = Read and write; accepted on the single installation (1 of 1).

# Step 10b — token-mint probe (in-memory; prints only permissions) — 2026-10-24T00:46:31Z
#   Local process using the bug-fix venv (boto3 + PyJWT) with temporary CLI credentials (aws configure export-credentials, subshell only):
#   reads github_installations (Supabase, service key from Secrets Manager), the App PEM (Secrets Manager), mints one installation token,
#   prints app_id, installation_id and the permissions object. No key or token is printed, written, or logged.

# Step 11 — smoke invoke (no AWS state change; runtime logs only) — 2026-10-24T00:48:21Z
aws bedrock-agentcore invoke-agent-runtime --region us-east-1 \
  --agent-runtime-arn arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/bugfix_bug_fix-BiuPsdGSPK \
  --runtime-session-id s181-smoke-20261024T004818-913f16c5d61e4b76 \
  --payload "$(printf '{"run_id":"2403210b-102b-4ea4-975c-5ac63b0aea42","repository_org":"llipe","repository_name":"bug-fix-smoke","base_branch":"main","params":{}}' | base64)" out.json

# Step 12 — environments.yaml (bug-fix runtime), runbook stub docs/runbooks/bug-fix-agent.md (+ README row),
#   agents/bug-fix/agentcore/.cli/deployed-state.json, final records; draft PR into integration/bug-fix-agent-wave-a — 2026-10-24
# (step 9 backup renamed to backup/panel-invoke-policy.before.json: the .gitignore pattern invoke-*.json would have excluded it)
