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
