#!/usr/bin/env bash
# Append-only record for 20261127-bug-fix-node-redeploy. No secrets.
set -euo pipefail
# Discovery — 2026-11-27T14:37:06Z (read-only), from main @ 256e9ef
aws sts get-caller-identity --query '[Account,Arn]' --output text   # 755641879575 root
aws bedrock-agentcore-control get-agent-runtime --region us-east-1 --agent-runtime-id bugfix_bug_fix-BiuPsdGSPK --output json > backup/runtime.before.json   # v7 READY, image dac1d525
supabase db query --linked "select * from runs where id='fb717a51-1df2-47a3-8d58-84d3966a433e';"   # failed/INSTALL_FAILED, llipe/riel#719
gh issue view 719 -R llipe/riel --json state   # CLOSED
(cd agents/bug-fix/agentcore/cdk && npm ci)
(cd agents/bug-fix && agentcore deploy --diff -y)   # image dac1d525 -> 2d0f0a94 only
aws ecr describe-images --region us-east-1 --repository-name bugfix/bug_fix   # latest 341872469 bytes; lifecycle keeps 10
# Step 1 — redeploy — 2026-11-27T14:45:03Z..14:47:27Z (runtime v7 -> v8), from main @ 256e9ef
(cd agents/bug-fix && agentcore deploy -y)
aws bedrock-agentcore-control get-agent-runtime --region us-east-1 --agent-runtime-id bugfix_bug_fix-BiuPsdGSPK --output json > backup/runtime.after.json   # v8 READY, image 2d0f0a94, role and env unchanged
# Step 2 — skipped: panel invoke never reached the server (flyctl logs 14:47Z..15:00Z)
flyctl logs -a dt-agent-fleet-panel --no-tail   # no /api/agents/bug-fix/invoke request
# Step 3 — @llipe `/bugfix` on llipe/riel#1349 (18:47:51Z) — run e7b70ade-7f9d-4be0-807c-dea6bd6b8583, 18:47:57Z..18:50:07Z
supabase db query --linked "select … from runs where id='e7b70ade-…';" > backup/run-step3.json
supabase db query --linked "select * from run_steps where run_id='e7b70ade-…' order by 1;" > backup/run-step3-steps.json
supabase db query --linked "select * from run_events where run_id='e7b70ade-…' order by 1;" > backup/run-step3-events.json
gh api repos/llipe/riel/issues/1349/comments > backup/issue-1349-comments.json   # leak scan over backup/: 0
