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

# Step 5: narrow kms:Decrypt to the ECR repository's key (backup: backup/role-policy.step2.json)
aws iam put-role-policy --role-name agent-fleet-code-review-runtime --policy-name code-review-runtime \
  --policy-document file://infra/changes/20261024-code-review-runtime/role-policy.json

# Step 6: panel invoke policy 6 -> 8 resources (backup: backup/panel-invoke-policy.before.json)
aws iam get-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime \
  > infra/changes/20261024-code-review-runtime/backup/panel-invoke-policy.before.json
aws iam put-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime \
  --policy-document file://infra/agentcore-invoke-policy.json

# Step 7: apply the code-review seed migration to prod (explicit confirmation by @llipe, 2026-10-24)
supabase link --project-ref hegxeycmbmjfgzqpdiik
supabase migration list --linked            # pending: exactly 20261022120000
supabase db query --linked --output json "select * from agents where slug = 'code-review'" \
  > infra/changes/20261024-code-review-runtime/backup/agents-code-review.before.json   # rows: []
supabase db push --linked --dry-run         # would push: 20261022120000_seed_code_review_agent.sql only
supabase db push --linked --yes

# Step 8: set runtime_arn and enable the row in one update (D-39)
supabase db query --linked "update agents set runtime_arn = 'arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/codereview_code_review-g73KtjA3MT', is_enabled = true where slug = 'code-review' and runtime_arn = 'pending-deploy:code-review' returning slug, is_enabled, runtime_arn"

# Step 9: negative panel invoke (operator, panel UI): code-review on llipe/security-analyst-fixture PR #5
#   scratch PR: https://github.com/llipe/security-analyst-fixture/pull/5 (draft, do not merge)
#   run: https://dt-agent-fleet-panel.fly.dev/runs/bf95f3c6-3ba4-495e-b0c7-a8ff46b7929b

# Step 10: accept the Bedrock Marketplace offer for GPT-6.1 Sol (backup: backup/model-availability.before.json)
OFFER_TOKEN="$(aws bedrock list-foundation-model-agreement-offers --region us-east-1 --model-id openai.gpt-6.1-sol --query 'offers[0].offerToken' --output text)"
aws bedrock create-foundation-model-agreement --region us-east-1 --model-id openai.gpt-6.1-sol --offer-token "$OFFER_TOKEN"
aws bedrock get-foundation-model-availability --region us-east-1 --model-id openai.gpt-6.1-sol   # PENDING -> AVAILABLE in ~40 s

# Step 11: positive panel invoke (operator): run 40e7d207-d5a2-4311-ad18-e319ef3d892e -> failed BEDROCK_ACCESS_DENIED
# Diagnosis (read-only + one 8-token Converse as the account principal, not the runtime role):
aws bedrock get-foundation-model-availability --region {us-east-1,us-east-2,us-west-2} --model-id openai.gpt-6.1-sol   # AVAILABLE in all three
aws bedrock-runtime converse --region us-east-1 --model-id us.openai.gpt-6.1-sol \
  --messages '[{"role":"user","content":[{"text":"Reply with the word ok."}]}]' --inference-config maxTokens=16
#   -> AccessDeniedException: openai.gpt-6.1-sol is not available for this account ... contact AWS Sales

# Step 11a: model probe (approved by @llipe): one forced-tool Converse per candidate, as the account principal
#   toolConfig: one tool submit_review {verdict: clear|blocking}, toolChoice {tool: submit_review}
aws bedrock-runtime converse --region us-east-1 --model-id deepseek.v3.2 ...            # maxTokens 64 -> max_tokens; 1024 -> tool_use {"verdict":"clear"}
aws bedrock-runtime converse --region us-east-1 --model-id us.moonshotai.kimi-k3 ...    # maxTokens 64 -> max_tokens; 1024 -> tool_use {"verdict":"clear"}
aws bedrock-runtime converse --region us-east-1 --model-id mistral.devstral-2-123b ...  # maxTokens 64 -> tool_use {"verdict":"clear"}
