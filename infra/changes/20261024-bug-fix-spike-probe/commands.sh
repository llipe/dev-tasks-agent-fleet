#!/usr/bin/env bash
# Append-only command log for ChangeId 20261024-bug-fix-spike-probe. No secret values are recorded.
set -euo pipefail

# Step 1 — deploy the #443 image with ALLOW_PROBE=1 — applied 2026-10-24T13:49:00Z (runtime v1 -> v2)
aws bedrock-agentcore-control get-agent-runtime --region us-east-1 --agent-runtime-id bugfix_bug_fix-BiuPsdGSPK > infra/changes/20261024-bug-fix-spike-probe/backup/runtime.before.json   # (query-filtered)
#   agents/bug-fix/agentcore/agentcore.json: envVars += { "name": "ALLOW_PROBE", "value": "1" }
(cd agents/bug-fix && agentcore deploy --diff -y)   # preview: image f89566aa -> 5574194c, env + ALLOW_PROBE; no IAM changes
(cd agents/bug-fix && agentcore deploy -y)

# Step 2 — probe run on the deployed runtime (v2) — 2026-10-24T13:56:01Z..13:56:20Z; run_id 267aba2c-cdad-4b04-ba6d-27d0d530c98b
aws bedrock-agentcore invoke-agent-runtime --region us-east-1 --cli-read-timeout 900 \
  --agent-runtime-arn arn:aws:bedrock-agentcore:us-east-1:755641879575:runtime/bugfix_bug_fix-BiuPsdGSPK \
  --runtime-session-id s182-probe-20261024T135601-3eb6b723befe4ab0 \
  --payload "$(printf '{"run_id":"267aba2c-cdad-4b04-ba6d-27d0d530c98b","repository_org":"llipe","repository_name":"bug-fix-smoke","base_branch":"main","params":{},"__probe":true}' | base64)" out.json
#   raw response kept as backup/probe-run-1.sse (leak scan: 0 hits)

# Step 1b — deploy the D-110 image (root wrapper + setpriv), ALLOW_PROBE=1 kept — applied 2026-10-24T14:26:33Z (runtime v2 -> v3)
#   from story/S-182-sandbox-spike @ aea27fa; preview: image 5574194c -> f3c16965 only (no IAM/env changes)
(cd agents/bug-fix && agentcore deploy -y)

# Step 2b — re-probe on runtime v3 — 2026-10-24T14:43:38Z..14:45:28Z; run_id 99eb0cc5-3055-4d2d-8e93-39a426c88cc4
#   session s182-probe2-20261024T144338-2bede17028fb4cd8; payload as step 2 with the new run_id; raw: backup/probe-run-2.sse (leak scan 0)
