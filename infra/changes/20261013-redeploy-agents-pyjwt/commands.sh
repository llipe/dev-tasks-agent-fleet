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
