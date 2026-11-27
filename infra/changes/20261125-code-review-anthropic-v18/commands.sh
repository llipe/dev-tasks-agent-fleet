#!/usr/bin/env bash
# 20261125-code-review-anthropic-v18 — append-only. No secret values; secrets by name or ARN only.
set -euo pipefail
D=infra/changes/20261125-code-review-anthropic-v18/backup
# Step 2 (2026-11-26T15:44Z): the planned name agent-fleet/prod/ANTHROPIC_API_KEY is the bug-fix agent's key (-Oo8jsf);
# operator chose a dedicated secret. Placeholder value only; the operator puts the real key (put-secret-value).
aws secretsmanager create-secret --region us-east-1 --name agent-fleet/prod/CODE_REVIEW_ANTHROPIC_API_KEY \
  --description "code-review agent: dedicated Anthropic API key (D-88; S-218 #482, ChangeId 20261125-code-review-anthropic-v18). Value set by the operator." \
  --secret-string "PLACEHOLDER-not-a-key" \
  --tags Key=environment,Value=prod Key=owner,Value=llipe Key=ChangeId,Value=20261125-code-review-anthropic-v18
# -> arn:aws:secretsmanager:us-east-1:755641879575:secret:agent-fleet/prod/CODE_REVIEW_ANTHROPIC_API_KEY-K0guwA (KmsKeyId null)
# Step 1 (2026-11-26T16:0xZ): backups (read).
aws bedrock-agentcore-control get-agent-runtime --region us-east-1 --agent-runtime-id codereview_code_review-g73KtjA3MT --output json > $D/runtime.before.json
aws iam get-role-policy --role-name agent-fleet-code-review-runtime --policy-name code-review-runtime --query PolicyDocument --output json > $D/role-policy.before.json
supabase db query --linked "select slug, is_enabled, runtime_arn, version, default_params, params_schema->'properties'->'max_context_tokens' as mct, params_schema->'properties'->'max_diff_lines' as mdl from agents where slug = 'code-review';" -o json > $D/agents-code-review.before.json
supabase db query --linked "select version, name from supabase_migrations.schema_migrations order by version desc limit 5;" -o json > $D/schema_migrations.before.json
# No rule is named '/review'; the only code-review rule is "Auto Code Review" (Riel endpoint).
supabase db query --linked "select r.* from webhook_rules r join agents a on a.id = r.agent_id where a.slug = 'code-review';" -o json > $D/webhook-rule-review.before.json
# Step 3 (2026-11-26): repo only, test first. CDK test pinned to CODE_REVIEW_ANTHROPIC_API_KEY-K0guwA (5 failed), then
# agentcore.json ANTHROPIC_API_KEY_SECRET_ID and iam/runtime-role-policy.json updated (23/23 pass).
(cd agents/code-review/agentcore/cdk && npm test)
# Step 4 (2026-11-26T23:17Z): live probe, scratchpad script (not in repo); key read via get_secret_value into the client, never printed.
# First attempt failed before any API call: botocore needs the [crt] extra for `aws login` credentials (installed into the scratchpad venv).
(cd agents/code-review/app/codeReview && "$SCRATCH/probe-venv/bin/python" -I "$SCRATCH/probe_v18.py")
# -> G-A pass (ITPM 5000000); G-B Q9 FAIL: "output_config.format.schema: For 'array' type, property 'maxItems' is not supported"; Q12 not reached.
# Step 4 attempt 2 (2026-11-27T13:15Z), after PR #504 merged (main 256e9ef, merged into this branch at a3ac432). AWS re-login (`aws login --remote`).
(cd agents/code-review/app/codeReview && "$SCRATCH/probe-venv/bin/python" -I "$SCRATCH/probe_v18.py")
# -> G-A pass (ITPM 5000000); Q9 pass (accepted, valid full schema); Q12 pass ("prompt is too long: 3300772 tokens > 1000000 maximum", is_context_length=true).
