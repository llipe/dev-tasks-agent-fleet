#!/usr/bin/env bash
# Append-only command log for ChangeId 20261014-fly-oidc-issuer-trust. No secret values.
set -euo pipefail

# --- discover (read-only, 2026-10-14) ---
# flyctl machine exec 845de5f2e502e8 '<decode OIDC claims as uid 1001; payload only>' -a dt-agent-fleet-panel
# aws iam list-open-id-connect-providers
# aws iam get-role --role-name panel-agentcore-invoke --query Role.AssumeRolePolicyDocument   > backup/trust-policy.before.json
# aws iam get-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime     > backup/runtime-invoke-policy.before.json

# --- step 1: create OIDC provider (approved by @llipe 2026-10-14T15:32-03:00) ---
aws iam create-open-id-connect-provider --url https://oidc.fly.io/felipe-mallea --client-id-list sts.amazonaws.com \
  --tags Key=environment,Value=prod Key=owner,Value=llipe Key=ChangeId,Value=20261014-fly-oidc-issuer-trust

# --- step 2: update role trust policy (approved by @llipe 2026-10-14T15:35-03:00) ---
aws iam update-assume-role-policy --role-name panel-agentcore-invoke --policy-document file://infra/trust-policy.json
# step 2 verify: as uid 1001 on the Machine, POST /v1/tokens/oidc → STS AssumeRoleWithWebIdentity (prints only AssumedRoleUser.Arn or the error code)

# --- step 3: invoke-runtime policy (+ security-analyst runtime) (approved by @llipe 2026-10-14T16:07-03:00) ---
aws iam put-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime --policy-document file://infra/agentcore-invoke-policy.json

# --- step 3b: invoke-runtime policy += runtime-endpoint/DEFAULT ARNs (approved by @llipe 2026-10-14T16:22-03:00) ---
aws iam get-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime > backup/runtime-invoke-policy.step3.json
aws iam put-role-policy --role-name panel-agentcore-invoke --policy-name invoke-runtime --policy-document file://infra/agentcore-invoke-policy.json
