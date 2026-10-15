#!/usr/bin/env bash
# Append-only command log for ChangeId 20261015-retire-fly-oidc-personal. No secrets.
set -euo pipefail
# discover: aws iam list-roles + get-role (trust scan); aws cloudtrail lookup-events AssumeRoleWithWebIdentity since 2026-10-08
# backup:   aws iam get-open-id-connect-provider --open-id-connect-provider-arn arn:aws:iam::755641879575:oidc-provider/oidc.fly.io/personal > backup/oidc-provider-personal.before.json
# --- step 1 (approved by @llipe 2026-10-15T18:11-03:00) ---
aws iam delete-open-id-connect-provider --open-id-connect-provider-arn arn:aws:iam::755641879575:oidc-provider/oidc.fly.io/personal
