#!/usr/bin/env bash
# Append-only record for 20261025-bug-fix-wave-a-deploy. No secrets.
set -euo pipefail
# Discovery — 2026-10-25T22:13:21Z (read-only)
aws sts get-caller-identity --query Account --output text   # 755641879575
aws bedrock-agentcore-control get-agent-runtime --region us-east-1 --agent-runtime-id bugfix_bug_fix-BiuPsdGSPK > backup/runtime.before.json
(cd agents/bug-fix && agentcore deploy --diff -y)   # image 5b24b169 -> dac1d525; env +FIX_LOOP_ENABLED +PANEL_BASE_URL
# Step 1 — redeploy — 2026-10-25T22:32:49Z..22:35:30Z (runtime v6 -> v7), from integration/bug-fix-agent-wave-a @ db7b4ec
(cd agents/bug-fix && agentcore deploy -y)
aws bedrock-agentcore-control get-agent-runtime --region us-east-1 --agent-runtime-id bugfix_bug_fix-BiuPsdGSPK   # v7 READY, image dac1d525, env +FIX_LOOP_ENABLED=0 +PANEL_BASE_URL
