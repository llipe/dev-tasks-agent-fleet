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

# Step 1c — deploy fix-round-2 image (ALLOW_PROBE=1 kept) — applied 2026-10-24T15:09:17Z (runtime v3 -> v4); from story/S-182-sandbox-spike @ ac37b63; preview: image f3c16965 -> 150553e8 only
(cd agents/bug-fix && agentcore deploy -y)
# Step 2c — re-probe on v4 — 2026-10-24T15:09:30Z..15:09:56Z; run_id 9c65573e-7469-455f-909d-75df8151ab9e; session s182-probe3-20261024T150930-402f306bf88e43d6; raw backup/probe-run-3.sse (leak scan 0)

# Step 1d — deploy fix-round-3 image (ALLOW_PROBE=1 kept) — applied 2026-10-24T15:40:03Z (runtime v4 -> v5); from story/S-182-sandbox-spike @ c71d98a; preview 15:37:13Z: image 150553e8 -> 5b24b169 only
(cd agents/bug-fix && agentcore deploy -y)
# Step 2d — re-probe on v5 — 2026-10-24T15:40:11Z..15:40:53Z; run_id 2fd1c9de-5a7c-415c-9a8c-0e4de9b2694c; session s182-probe4-20261024T154011-ef75557e7b04b207; raw backup/probe-run-4.sse (leak scan 0)

# Step 3 — remove ALLOW_PROBE and redeploy — applied 2026-10-24T15:53:10Z (runtime v5 -> v6); preview 15:51:44Z: Runtime EnvironmentVariables "Removed: .ALLOW_PROBE" only, image unchanged
sed -i '' '/{ "name": "ALLOW_PROBE", "value": "1" },/d' agents/bug-fix/agentcore/agentcore.json
(cd agents/bug-fix && agentcore deploy -y)
# Verify: probe payload refused — 2026-10-24T15:53:18Z; run_id f027af3f-cf91-4350-bc99-b8f37796b36a; session s182-refuse-20261024T155318-6b391a6d8d7fbcdf; PROBE_REFUSED; raw backup/probe-refused-v6.sse (leak scan 0)
