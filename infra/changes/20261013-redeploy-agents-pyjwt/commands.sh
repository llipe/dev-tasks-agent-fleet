#!/usr/bin/env bash
# Append-only command log for ChangeId 20261013-redeploy-agents-pyjwt.
# No secret values; resources are referenced by id/name.
set -euo pipefail

# --- discover (read-only, 2026-10-13) ---
# aws sts get-caller-identity
# aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id dependencyupdate_dependency_update-UsQc5U5Yz0 --region us-east-1
# aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id securityanalyst_security_analyst-w6CpbYHRE0 --region us-east-1
# aws ecr describe-images --repository-name dependencyupdate/dependency_update --image-ids imageTag=0cc70f3b18f7af8890f4f393cbd9a5225eb4b095489933a0e0e2f6cf29d2e00f
# aws ecr describe-images --repository-name securityanalyst/security_analyst --image-ids imageTag=760f3a2cc31e54a506fff569e6bca55062e19747c87bb94879d25298ace296a4

# --- step 1: redeploy dependency-update (approved by @llipe 2026-10-13T14:53-03:00) ---
cd agents/dependency-update && agentcore deploy -y

# step 1 verify (read-only):
# aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id dependencyupdate_dependency_update-UsQc5U5Yz0 --region us-east-1
# docker run --rm --platform linux/arm64 --entrypoint python <ecr>/dependencyupdate/dependency_update:12421822… -c "import jwt; print(jwt.__version__)"  # → 2.15.1

# --- step 2: verify dependency-update live (approved 2026-10-13T15:01-03:00) ---
# operator invoked via `pnpm --filter panel dev` (local credential chain) → run 15f3b1f2-1157-498d-83c6-3969e3da719b
# read-only verify: GET $SUPABASE_URL/rest/v1/v_runs?id=eq.<run>, /run_steps?run_id=eq.<run>, /run_events?run_id=eq.<run>

# --- step 3: redeploy security-analyst (approved by @llipe 2026-10-13T16:17-03:00) ---
cd agents/security-analyst && agentcore deploy -y

# --- step 4: verify security-analyst live (approved 2026-10-13T16:31-03:00) ---
# operator invoked via local panel → runs 7cb97c44-b731-4c20-bcfe-341e6b8892db (memo-cli) and bf1eabc2-fbbd-47f0-9f30-b3ed8a7cedb0 (fixture), audit_only
# read-only verify via PostgREST: v_runs, run_steps, run_events, run_artifacts(type=audit_report)
