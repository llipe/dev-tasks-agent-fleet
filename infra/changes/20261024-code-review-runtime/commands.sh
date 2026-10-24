#!/usr/bin/env bash
# commands.sh: 20261024-code-review-runtime (S-214, #416). Append-only.
# Each block is the exact forward command of an applied step. Secrets are
# referenced by name or ARN only; no value is ever written here.
# AWS calls ran through the AWS MCP server (boto3); each block gives the
# equivalent AWS CLI command.
set -euo pipefail

# Step 2: create IAM role agent-fleet-code-review-runtime (2026-10-24T15:24:22Z)
aws iam create-role --role-name agent-fleet-code-review-runtime \
  --assume-role-policy-document file://infra/changes/20261024-code-review-runtime/role-trust.json \
  --description "code-review AgentCore runtime (S-214, ChangeId 20261024-code-review-runtime): GPT-6.1 Sol InvokeModel, two secrets, no other Bedrock." \
  --tags Key=environment,Value=prod Key=owner,Value=llipe Key=ChangeId,Value=20261024-code-review-runtime Key=agent,Value=code-review
aws iam put-role-policy --role-name agent-fleet-code-review-runtime --policy-name code-review-runtime \
  --policy-document file://infra/changes/20261024-code-review-runtime/role-policy.json

# Step 3: simulate the role (read-only; 11 cases, see backup/simulation-step3.json)
aws iam simulate-principal-policy --policy-source-arn arn:aws:iam::755641879575:role/agent-fleet-code-review-runtime \
  --action-names bedrock:InvokeModel \
  --resource-arns arn:aws:bedrock:us-east-1:755641879575:inference-profile/us.openai.gpt-6.1-sol

# Step 4: deploy the runtime (2026-10-24T15:55Z; app code == main@5a056b8)
# local, gitignored agents/code-review/agentcore/aws-targets.json: target default -> 755641879575/us-east-1
(cd agents/code-review && agentcore deploy -y --json)
